"""site 의 주소 층 - HTTP 를 받아 규칙(service)·저장(store)·통계(stats)에 넘기고 응답을 만든다.

    GET  /                      첫 화면 (브라우저일 때. 프로그램이 물으면 app.py 가 JSON 을 준다)
    GET  /w/<작품>              작품 하나를 연 첫 화면 (링크를 보내면 그 작품의 제목·그림이 미리보기로 뜬다)
    GET  /admin                 관리 화면
    GET  /static/...            화면 파일 (web/static)
    GET  /api/overview          첫 화면이 그리는 모든 것: 사이트·작품·방문 수·서버 상태
    GET  /media/<작품>/<그림>   작품 그림
    GET  /dl/<작품>             다운로드 (올려 둔 파일)
    GET  /dl/<작품>/a/<파일>    GitHub 릴리스 파일로 넘겨줌 (받은 사람을 세고 나서)
    GET  /p/<작품>/...          올려 둔 웹 빌드 (브라우저에서 바로 플레이)
    GET  /robots.txt · /sitemap.xml · /site.webmanifest · /favicon.ico   검색엔진·브라우저용 (seo.py)
    GET  /og/site.jpg           간판 그림 (링크 미리보기, 관리 화면에서 바꿈)
    GET  /og/<작품>.jpg         작품 링크 미리보기 그림 (대표 그림에서 1200×630 JPEG 로 만들어 둠)

    (열쇠 X-Admin-Key)
    POST   /api/admin/site/og                  간판 그림 올리기 (본문 = 그림)   DELETE 기본 그림으로
    GET    /api/admin/overview                 관리 화면이 그리는 모든 것
    PUT    /api/admin/settings                 사이트 설정
    PUT    /api/admin/works/<작품>             작품 만들기·고치기
    DELETE /api/admin/works/<작품>
    POST   /api/admin/works/<작품>/cover       대표 그림 (본문 = 그림)
    POST   /api/admin/works/<작품>/shots       스크린샷 한 장 더
    DELETE /api/admin/works/<작품>/shots/<그림>
    POST   /api/admin/works/<작품>/download?name=파일이름   (본문 = 파일)
    POST   /api/admin/works/<작품>/build       웹 빌드 (본문 = zip, 맨 위에 index.html)
    DELETE /api/admin/works/<작품>/cover | download | build
"""
import html
import os
import platform
import shutil
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from . import auth, bots, comments, releases, seo, service, stats, store
from . import config as C
from .service import Invalid

router = APIRouter()
STARTED = time.time()
SITE_URL = os.environ.get("JSSERV_SITE_URL", "https://jsserv.pdlab.kr")

_server = {"name": "jsserv", "version": "?"}
_services = lambda: []      # noqa: E731 - app.py 가 configure 로 넣어 준다
_last_ip_source = {"value": None}   # 관리 화면 진단용: 손님 주소를 어느 헤더로 알았나

PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
                               "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
                               "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'self'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-cache",
}


def configure(server_name, server_version, services):
    """app.py 가 부른다: 서버 이름·버전, 그리고 올라와 있는 기능 목록을 돌려주는 함수."""
    global _services
    _server.update(name=server_name, version=server_version)
    _services = services


# ---- 공통 ----
def _err(msg, code):
    return JSONResponse({"error": msg}, status_code=code)


def _ip(request):
    peer = request.client.host if request.client else None
    return service.client_ip(request.headers, peer)[0]


def _admin(request):
    """열쇠가 맞으면 None, 아니면 거절 응답."""
    result = auth.check(request.headers.get("x-admin-key", ""), _ip(request))
    if result == "ok":
        return None
    if result == "locked":
        return _err("열쇠를 너무 많이 틀렸습니다. 10분 뒤에 다시 하세요", 429)
    return _err("열쇠가 맞지 않습니다", 403)


def _settings():
    s = store.settings()
    if s is None:
        s = dict(service.DEFAULT_SETTINGS)
        store.save_settings(s)
    return s


def _works():
    if not store.has_works_file():
        store.save_works([dict(w, created=store.now_iso(), updated=store.now_iso()) for w in service.DEFAULT_WORKS])
    return service.sort_works(store.works())


def _public(slug):
    """밖에서 찾는 작품 하나 (숨긴 것은 없는 셈). 처음이면 기본 작품부터 깐다."""
    if not service.SLUG_RE.match(slug):
        return None
    w = next((w for w in _works() if w.get("slug") == slug), None)
    return None if not w or w.get("hidden") else w


async def _read_body(request, limit):
    """본문을 limit 까지만 받는다. 넘으면 None (다 받아 놓고 버리지 않게 받다가 끊는다)."""
    if int(request.headers.get("content-length") or 0) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return bytes(body)


async def _stream_to(request, path, limit):
    """본문을 파일로 바로 받는다(큰 파일을 메모리에 다 들지 않게). 넘으면 -1."""
    if int(request.headers.get("content-length") or 0) > limit:
        return -1
    size = 0
    with open(path, "wb") as out:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return -1
            out.write(chunk)
    return size


def _remove(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---- 화면 ----
def wants_page(request):
    return "text/html" in request.headers.get("accept", "")


def _brand_image(s):
    """간판 그림 주소: 관리 화면에서 올린 것이 있으면 그것, 없으면 기본 그림."""
    if s.get("og_image") and store.image_path("_site", s["og_image"]):
        return "/og/site.jpg?v=" + s["og_image"].split("-")[-1].split(".")[0]
    return "/static/og.png"


def _work_image(w, s):
    if w.get("cover"):
        return "/og/%s.jpg?v=%s" % (w["slug"], w["cover"].split("-")[-1].split(".")[0])
    return _brand_image(s)


def _page(name, title=None, desc=None, image=None, image_alt=None, path="/", og_type="website", jsonld="", works_html=""):
    try:
        with open(os.path.join(C.WEB, name), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return _err("화면 파일이 없습니다", 500)
    s = _settings()
    site = s.get("name") or "Portfolio"
    fill = {     # 글자로 넣는 것 (태그 문자는 글자로 바뀜)
        "{{TITLE}}": title or seo.site_title(s),
        "{{DESC}}": desc or s.get("headline") or seo.DEFAULT_DESC,
        "{{IMAGE}}": SITE_URL + (image or _brand_image(s)),
        "{{IMAGE_ALT}}": image_alt or "%s 간판" % site,
        "{{URL}}": SITE_URL + path,
        "{{SITE}}": site,
        "{{OG_TYPE}}": og_type,
    }
    raw = {      # 이미 안전하게 만든 HTML 조각 (seo.py 가 속을 다 escape 함)
        "{{VERIFY}}": seo.verify_tags(s),
        "{{JSONLD}}": jsonld,
        "{{WORKS_SSR}}": works_html,
    }
    for k, v in fill.items():
        text = text.replace(k, html.escape(v, quote=True))
    for k, v in raw.items():
        text = text.replace(k, v)
    return HTMLResponse(text, headers=PAGE_HEADERS)


def _public_works():
    return [w for w in _works() if not w.get("hidden")]


def home_page():
    s = _settings()
    works = _public_works()
    return _page("index.html", jsonld=seo.home_ld(s, SITE_URL, works), works_html=seo.works_html(works))


@router.get("/w/{slug}")
def work_page(slug: str):
    w = _public(slug)
    if not w:
        return RedirectResponse("/", status_code=307)
    s = _settings()
    image = _work_image(w, s)
    pub = dict(w, play=service.play_url(w))
    return _page("index.html", title=seo.work_title(w, s), desc=seo.work_desc(w), image=image,
                 image_alt="%s 대표 그림" % (w.get("title") or slug), path="/w/" + slug, og_type="article",
                 jsonld=seo.work_ld(pub, s, SITE_URL, SITE_URL + image), works_html=seo.works_html(_public_works()))


@router.get("/admin")
def admin_page():
    resp = _page("admin.html")
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@router.get("/static/{rel:path}")
def static(rel: str):
    path = store.inside(os.path.join(C.WEB, "static"), *rel.split("/"))
    ext = os.path.splitext(path or "")[1].lower()
    if not path or ext not in C.WEB_TYPES or not os.path.isfile(path):
        return _err("없는 파일", 404)
    return FileResponse(path, media_type=C.WEB_TYPES[ext], headers={"Cache-Control": "no-cache"})


@router.get("/favicon.ico")
def favicon():
    ico = os.path.join(C.WEB, "static", "icons", "favicon.ico")
    if os.path.isfile(ico):
        return FileResponse(ico, media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(os.path.join(C.WEB, "static", "favicon.svg"), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/robots.txt")
def robots():
    return Response(seo.robots_txt(SITE_URL), media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml")
def sitemap():
    return Response(seo.sitemap_xml(SITE_URL, _public_works()), media_type="application/xml; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/site.webmanifest")
def webmanifest():
    return JSONResponse(seo.manifest(_settings()), media_type="application/manifest+json",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/og/site.jpg")
def og_site():
    s = _settings()
    path = store.image_path("_site", s.get("og_image") or "") if s.get("og_image") else None
    if path:
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(os.path.join(C.WEB, "static", "og.png"), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/og/{slug}.jpg")
async def og_work(slug: str):
    """작품 링크 미리보기 그림. 처음 요청 때 대표 그림에서 만들어 두고 다음부터는 그대로 준다."""
    w = _public(slug)
    cover = store.image_path(slug, w.get("cover")) if w and w.get("cover") else None
    if not cover:
        return og_site()
    name = "og-%s.jpg" % os.path.splitext(w["cover"])[0]
    path = store.image_path(slug, name)
    if not path:
        try:
            data = await run_in_threadpool(service.og_from_file, cover)
        except Exception:      # noqa: BLE001 - 못 만들면 간판 그림으로
            return og_site()
        store.write_media(slug, name, data)
        path = store.image_path(slug, name)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


# ---- 공개 API ----
def _services_public():
    return [s for s in _services() if s.get("name") != "site"]


def _release(w):
    return releases.latest(w.get("release")) if w.get("release") else None


@router.get("/api/overview")
def overview():
    summary = stats.summary(days=14)
    talk = comments.counts()
    works = [dict(service.public_work(w, summary["works"], _release(w)), comments=talk.get(w["slug"], 0))
             for w in _works() if not w.get("hidden")]
    s = _settings()
    return JSONResponse({
        "site": s,
        "server": {"name": _server["name"], "version": _server["version"], "uptime": int(time.time() - STARTED),
                   "time": store.now_iso()},
        "services": _services_public(),
        "stats": {k: summary[k] for k in ("today", "total", "days")},
        "works": works,
    }, headers={"Cache-Control": "no-cache"})


@router.get("/media/{slug}/{name}")
def media(slug: str, name: str):
    path = store.image_path(slug, name) if service.SLUG_RE.match(slug) else None
    ext = os.path.splitext(name)[1].lower()
    if not path or ext not in C.IMAGE_MEDIA:
        return _err("없는 그림", 404)
    # 이름에 무작위 꼬리가 붙어 있어서(바뀌면 이름도 바뀜) 오래 캐시해도 된다
    return FileResponse(path, media_type=C.IMAGE_MEDIA[ext], headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/dl/{slug}")
def download(slug: str):
    w = _public(slug)
    dl = (w or {}).get("download")
    path = store.download_path(slug, dl["name"]) if dl else None
    if not path:
        return _err("받을 파일이 없습니다", 404)
    return FileResponse(path, filename=dl["name"], media_type="application/octet-stream",
                        headers={"Cache-Control": "no-cache"})


@router.get("/dl/{slug}/a/{name}")
def download_release(slug: str, name: str):
    w = _public(slug)
    url = releases.asset_url(w.get("release"), name) if w and w.get("release") else None
    if not url:
        return _err("받을 파일이 없습니다", 404)
    return RedirectResponse(url, status_code=302)


@router.get("/p/{slug}")
def play_slash(slug: str):
    return RedirectResponse("/p/%s/" % slug, status_code=307)


@router.get("/p/{slug}/{rel:path}")
def play(slug: str, rel: str, request: Request):
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    if not w or not w.get("build"):
        return _err("올린 웹 빌드가 없습니다", 404)
    rel = rel or "index.html"
    path = store.build_file(slug, rel)
    ext = os.path.splitext(rel)[1].lower()
    if not path or ext not in C.BUILD_TYPES:
        return _err("없는 파일", 404)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp3", ".ogg", ".wav", ".woff2", ".woff", ".ttf"):
        cache = "public, max-age=604800, immutable" if "v" in request.query_params else "public, max-age=600"
    else:
        cache = "no-cache"
    return FileResponse(path, media_type=C.BUILD_TYPES[ext], headers={"Cache-Control": cache})


# ---- 관리 API ----
def _disk():
    try:
        os.makedirs(C.DATA, exist_ok=True)
        u = shutil.disk_usage(C.DATA)
        return {"total": u.total, "used": u.used, "free": u.free}
    except OSError:
        return None


@router.get("/api/admin/overview")
def admin_overview(request: Request):
    denied = _admin(request)
    if denied:
        return denied
    summary = stats.summary(days=30, refs_days=30)
    talk = comments.counts()
    sizes = {name: store.folder_bytes(path) for name, path in
             (("그림", C.MEDIA), ("다운로드", C.DOWNLOADS), ("웹 빌드", C.BUILDS))}
    try:
        sizes["통계"] = os.path.getsize(C.STATS_DB)
    except OSError:
        sizes["통계"] = 0
    return JSONResponse({
        "site": _settings(),
        "works": [dict(service.admin_work(w, summary["works"], _release(w)), comments=talk.get(w["slug"], 0)) for w in _works()],
        "stats": summary,
        "server": {"name": _server["name"], "version": _server["version"], "uptime": int(time.time() - STARTED),
                   "python": platform.python_version(), "data_dir": C.DATA, "disk": _disk(), "sizes": sizes,
                   "ip_source": _last_ip_source["value"], "time": store.now_iso()},
        "services": _services(),
        "limits": {"image": C.MAX_IMAGE, "shots": C.MAX_SHOTS, "download": C.MAX_DOWNLOAD, "build": C.MAX_BUILD_ZIP},
    }, headers={"Cache-Control": "no-store"})


@router.put("/api/admin/settings")
async def admin_settings(request: Request):
    denied = _admin(request)
    if denied:
        return denied
    try:
        clean = service.clean_settings(await request.json())
    except ValueError as e:   # Invalid 와 JSON 깨짐 둘 다
        return _err(str(e) if isinstance(e, Invalid) else "JSON 이 아닙니다", 400)
    clean["og_image"] = _settings().get("og_image")     # 간판 그림은 따로 올리고 지운다
    store.save_settings(clean)
    return {"ok": True, "site": clean}


@router.post("/api/admin/site/og")
async def admin_site_og(request: Request):
    """간판 그림(링크 미리보기에 뜨는 그림) 올리기 → 1200×630 JPEG 로 맞춰 보관."""
    denied = _admin(request)
    if denied:
        return denied
    data = await _read_body(request, C.MAX_IMAGE)
    if data is None:
        return _err("그림이 너무 큽니다 (%d MB 까지)" % (C.MAX_IMAGE >> 20), 413)
    try:
        jpeg = await run_in_threadpool(service.prepare_og, data)
    except Invalid as e:
        return _err(str(e), 400)
    s = _settings()
    name = store.save_image("_site", "og", ".jpg", jpeg)
    store.remove_image("_site", s.get("og_image"))
    s["og_image"] = name
    store.save_settings(s)
    return {"ok": True, "site": s, "image": _brand_image(s)}


@router.delete("/api/admin/site/og")
def admin_site_og_delete(request: Request):
    denied = _admin(request)
    if denied:
        return denied
    s = _settings()
    store.remove_image("_site", s.get("og_image"))
    s["og_image"] = None
    store.save_settings(s)
    return {"ok": True, "site": s, "image": _brand_image(s)}


@router.put("/api/admin/works/{slug}")
async def admin_put_work(slug: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    try:
        service.check_slug(slug)
        clean = service.clean_work(await request.json())
    except ValueError as e:
        return _err(str(e) if isinstance(e, Invalid) else "JSON 이 아닙니다", 400)
    if not store.work(slug) and len(_works()) >= C.MAX_WORKS:
        return _err("작품이 너무 많습니다", 400)
    w = store.put_work(slug, clean)
    return {"ok": True, "work": service.admin_work(w, {})}


@router.delete("/api/admin/works/{slug}")
def admin_delete_work(slug: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    if not service.SLUG_RE.match(slug) or not store.delete_work(slug):
        return _err("없는 작품", 404)
    comments.remove_work(slug)
    return {"ok": True}


async def _image_upload(request, slug):
    """(작품, 확장자, 바이트) 또는 거절 응답."""
    denied = _admin(request)
    if denied:
        return denied
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    if not w:
        return _err("없는 작품", 404)
    data = await _read_body(request, C.MAX_IMAGE)
    if data is None:
        return _err("그림이 너무 큽니다 (%d MB 까지)" % (C.MAX_IMAGE >> 20), 413)
    try:
        ext, data = await run_in_threadpool(service.prepare_image, data)
    except Invalid as e:
        return _err(str(e), 400)
    return w, ext, data


@router.post("/api/admin/works/{slug}/cover")
async def admin_cover(slug: str, request: Request):
    got = await _image_upload(request, slug)
    if isinstance(got, Response):
        return got
    w, ext, data = got
    name = store.save_image(slug, "cover", ext, data)
    still_bytes = await run_in_threadpool(service.still_of, data)
    still = store.save_image(slug, "still", ".webp", still_bytes) if still_bytes else None
    store.remove_image(slug, w.get("cover"))
    store.remove_image(slug, w.get("cover_still"))
    store.remove_media_prefix(slug, "og-")       # 옛 링크 미리보기 그림 (새 그림으로 다시 만든다)
    w = store.put_work(slug, {"cover": name, "cover_still": still})
    return {"ok": True, "work": service.admin_work(w, {})}


@router.post("/api/admin/works/{slug}/shots")
async def admin_add_shot(slug: str, request: Request):
    got = await _image_upload(request, slug)
    if isinstance(got, Response):
        return got
    w, ext, data = got
    shots = w.get("shots", [])
    if len(shots) >= C.MAX_SHOTS:
        return _err("스크린샷은 %d장까지입니다" % C.MAX_SHOTS, 400)
    name = store.save_image(slug, "shot", ext, data)
    w = store.put_work(slug, {"shots": shots + [name]})
    return {"ok": True, "work": service.admin_work(w, {})}


@router.delete("/api/admin/works/{slug}/shots/{name}")
def admin_delete_shot(slug: str, name: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    if not w or name not in w.get("shots", []):
        return _err("없는 그림", 404)
    store.remove_image(slug, name)
    w = store.put_work(slug, {"shots": [s for s in w["shots"] if s != name]})
    return {"ok": True, "work": service.admin_work(w, {})}


@router.post("/api/admin/works/{slug}/download")
async def admin_download(slug: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    if not (service.SLUG_RE.match(slug) and store.work(slug)):
        return _err("없는 작품", 404)
    try:
        name = service.clean_filename(request.query_params.get("name", ""))
    except Invalid as e:
        return _err(str(e), 400)
    tmp = store.temp_path("dl")
    try:
        size = await _stream_to(request, tmp, C.MAX_DOWNLOAD)
        if size < 0:
            return _err("파일이 너무 큽니다 (%d MB 까지)" % (C.MAX_DOWNLOAD >> 20), 413)
        if size == 0:
            return _err("빈 파일입니다", 400)
        store.commit_download(slug, tmp, name)
    finally:
        _remove(tmp)
    w = store.put_work(slug, {"download": {"name": name, "bytes": size, "updated": store.now_iso()}})
    return {"ok": True, "work": service.admin_work(w, {})}


def _unpack_build(zip_path, dest):
    """zip 을 검사하고 dest 에 푼다. (파일 수, 바이트)."""
    with service.open_zip(zip_path) as zf:
        items = service.check_build_zip(zf)
        total = 0
        for info, name in items:
            target = os.path.join(dest, *name.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            total += info.file_size
    return len(items), total


@router.post("/api/admin/works/{slug}/build")
async def admin_build(slug: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    if not (service.SLUG_RE.match(slug) and store.work(slug)):
        return _err("없는 작품", 404)
    tmp_zip, tmp_dir = store.temp_path("build-zip"), store.temp_path("build-new")
    try:
        size = await _stream_to(request, tmp_zip, C.MAX_BUILD_ZIP)
        if size < 0:
            return _err("zip 이 너무 큽니다 (%d MB 까지)" % (C.MAX_BUILD_ZIP >> 20), 413)
        try:
            files, total = await run_in_threadpool(_unpack_build, tmp_zip, tmp_dir)
        except Invalid as e:
            return _err(str(e), 400)
        store.commit_build(slug, tmp_dir)   # 다 풀린 뒤 한 번에 바꿔 끼운다
    finally:
        _remove(tmp_zip)
        _remove(tmp_dir)
    w = store.put_work(slug, {"build": {"files": files, "bytes": total, "updated": store.now_iso()}})
    return {"ok": True, "work": service.admin_work(w, {})}


@router.delete("/api/admin/works/{slug}/{what}")
def admin_remove_file(slug: str, what: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    if not w or what not in ("cover", "download", "build"):
        return _err("없는 것", 404)
    if what == "cover":
        store.remove_image(slug, w.get("cover"))
        store.remove_image(slug, w.get("cover_still"))
        store.remove_media_prefix(slug, "og-")
        store.put_work(slug, {"cover_still": None})
    elif what == "download":
        store.remove_download(slug)
    else:
        store.remove_build(slug)
    w = store.put_work(slug, {what: None})
    return {"ok": True, "work": service.admin_work(w, {})}


# ---- 방문 세기 ----
class TrackMiddleware:
    """응답이 나간 **뒤에** 방문·플레이·다운로드를 센다. 세다가 무슨 일이 나도 응답에는 영향이 없다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        status = {}

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_and_note)
        try:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            hit = service.classify("GET", scope.get("path", ""), status.get("code"), headers, _works())
            if hit:
                peer = (scope.get("client") or (None,))[0]
                ip, source = service.client_ip(headers, peer)
                _last_ip_source["value"] = source
                await run_in_threadpool(stats.record, hit[0], ip, headers.get("user-agent", ""), hit[1],
                                        service.ref_host(headers))
        except Exception:     # noqa: BLE001 - 통계 때문에 사이트가 죽으면 안 된다
            pass


# ---- 로봇 막기 ----
# 앱·도구가 쓰는 주소는 검사하지 않는다 (춥채팅 앱의 파일·기록·프로필, 게임 올리기 도구, 살아 있는지 확인)
GUARD_SKIP = ("/files", "/logs", "/profiles", "/battle", "/chat", "/health", "/robots.txt",
              "/game/upload", "/game/originals")
# 한 주소에서 1분에 이보다 많이 열면 잠시 쉬게 한다 (검색엔진·링크 미리보기는 빼고)
_page_limit = bots.RateLimit(120)      # 페이지 (/, /w/…)
_misc_limit = bots.RateLimit(900)      # 그림·자료 (/media, /og, /api/…)


class BotGuard:
    """수집 로봇은 사이트 주소에서 403, 한 주소가 너무 자주 열면 429. 사람·앱은 그대로 지나간다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(GUARD_SKIP):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        agent = headers.get("user-agent", "")
        kind = bots.classify(agent)
        if kind in ("bad", "bot"):
            await _plain(send, 403, "로봇 접근은 받지 않습니다.\n")
            return
        if kind is None and scope.get("method") == "GET":
            ip = service.client_ip(headers, (scope.get("client") or (None,))[0])[0]
            if path == "/" or path.startswith("/w/"):
                over = _page_limit.over(ip)
            elif path.startswith(("/media/", "/og/", "/api/", "/sitemap.xml", "/dl/")):
                over = _misc_limit.over(ip)
            else:
                over = False
            if over:
                await _plain(send, 429, "너무 자주 열었습니다. 1분 뒤에 다시 와 주세요.\n", {"retry-after": "60"})
                return
        await self.app(scope, receive, send)


async def _plain(send, status, text, extra=None):
    body = text.encode("utf-8")
    head = [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode()),
            (b"x-robots-tag", b"noindex"), (b"cache-control", b"no-store")]
    head += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": head})
    await send({"type": "http.response.body", "body": body})
