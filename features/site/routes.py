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

    (열쇠 X-Admin-Key)
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

from . import auth, releases, service, stats, store
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


def _page(name, title=None, desc=None, image=None, path="/"):
    try:
        with open(os.path.join(C.WEB, name), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return _err("화면 파일이 없습니다", 500)
    s = _settings()
    site = s.get("name") or "Portfolio"
    fill = {
        "{{TITLE}}": title or site,
        "{{DESC}}": desc or s.get("headline") or "",
        "{{IMAGE}}": SITE_URL + (image or "/static/og.png"),
        "{{URL}}": SITE_URL + path,
        "{{SITE}}": site,
    }
    for k, v in fill.items():
        text = text.replace(k, html.escape(v, quote=True))
    return HTMLResponse(text, headers=PAGE_HEADERS)


def home_page():
    return _page("index.html")


@router.get("/w/{slug}")
def work_page(slug: str):
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    if not w or w.get("hidden"):
        return RedirectResponse("/", status_code=307)
    site = _settings().get("name") or ""
    return _page("index.html", title="%s · %s" % (w.get("title", slug), site), desc=w.get("tagline"),
                 image=service.media_url(slug, w.get("cover")), path="/w/" + slug)


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
    return FileResponse(os.path.join(C.WEB, "static", "favicon.svg"), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/robots.txt")
def robots():
    lines = ["User-agent: *", "Allow: /"] + ["Disallow: " + p for p in
                                           ("/admin", "/api/", "/dl/", "/files/", "/logs/", "/profiles/", "/battle")]
    return Response("\n".join(lines) + "\n", media_type="text/plain")


# ---- 공개 API ----
def _services_public():
    return [s for s in _services() if s.get("name") != "site"]


def _release(w):
    return releases.latest(w.get("release")) if w.get("release") else None


@router.get("/api/overview")
def overview():
    summary = stats.summary(days=14)
    works = [service.public_work(w, summary["works"], _release(w)) for w in _works() if not w.get("hidden")]
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
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    dl = (w or {}).get("download")
    path = store.download_path(slug, dl["name"]) if dl else None
    if not path or w.get("hidden"):
        return _err("받을 파일이 없습니다", 404)
    return FileResponse(path, filename=dl["name"], media_type="application/octet-stream",
                        headers={"Cache-Control": "no-cache"})


@router.get("/dl/{slug}/a/{name}")
def download_release(slug: str, name: str):
    w = store.work(slug) if service.SLUG_RE.match(slug) else None
    url = releases.asset_url(w.get("release"), name) if w and not w.get("hidden") and w.get("release") else None
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
    sizes = {name: store.folder_bytes(path) for name, path in
             (("그림", C.MEDIA), ("다운로드", C.DOWNLOADS), ("웹 빌드", C.BUILDS))}
    try:
        sizes["통계"] = os.path.getsize(C.STATS_DB)
    except OSError:
        sizes["통계"] = 0
    return JSONResponse({
        "site": _settings(),
        "works": [service.admin_work(w, summary["works"], _release(w)) for w in _works()],
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
    store.save_settings(clean)
    return {"ok": True, "site": clean}


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
    store.remove_image(slug, w.get("cover"))
    w = store.put_work(slug, {"cover": name})
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
            hit = service.classify("GET", scope.get("path", ""), status.get("code"), headers, store.works())
            if hit:
                peer = (scope.get("client") or (None,))[0]
                ip, source = service.client_ip(headers, peer)
                _last_ip_source["value"] = source
                await run_in_threadpool(stats.record, hit[0], ip, headers.get("user-agent", ""), hit[1],
                                        service.ref_host(headers))
        except Exception:     # noqa: BLE001 - 통계 때문에 사이트가 죽으면 안 된다
            pass
