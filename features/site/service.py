"""site 의 규칙 층 - 무엇이 올바른 작품·설정인지, 무엇을 방문으로 세는지, 밖에 무엇을 보여주는지.

HTTP 도 디스크도 모른다. 값을 받아 검사하고, 고친 값이나 이유를 돌려줄 뿐이다
(그래서 시험하기 쉽고, 주소를 바꿔도 이 파일은 그대로다).
"""
import io
import os
import re
import zipfile
from urllib.parse import quote, urlsplit

from . import config as C

# ---- 처음 한 번 깔리는 값 (관리 화면에서 전부 고칠 수 있다) ----
DEFAULT_SETTINGS = {
    "name": "NasusFullstack",
    "headline": "게임을 만들고, 서버에 올리고, 이것저것 만듭니다.",
    "about": "기획부터 개발, 서버 운영까지 혼자 하는 개인 작업실입니다. 만든 것들을 여기에 모아 둡니다.",
    "roles": ["GAME", "APP", "SERVER", "TOOL", "WEB"],
    "email": "radiant9312@gmail.com",
    "github": "https://github.com/NasusFullstack",
}

DEFAULT_WORKS = [
    {"slug": "danmak", "title": "탄막게임", "kind": "게임", "status": "베타", "version": "Beta v1.0", "year": "2026",
     "tagline": "브라우저에서 바로 하는 2D 횡스크롤 탄막 슈팅",
     "desc": "설치 없이 브라우저에서 바로 플레이하는 횡스크롤 탄막 슈팅입니다. 1~2인 플레이를 지원합니다.",
     "tags": ["웹", "탄막 슈팅", "2인"], "accent": "#ff5c8a", "play_url": "/game/", "source": "", "order": 1},
    {"slug": "chupchat", "title": "춥채팅", "kind": "앱", "status": "운영 중", "version": "", "year": "2026",
     "tagline": "친구들끼리 쓰는 데스크톱·모바일 채팅",
     "desc": "IRC 와 자체 서버를 함께 쓰는 채팅 프로그램입니다. 파일·사진 보내기, 채팅 기록, 프로필 아이콘을 이 서버가 맡고 있습니다.",
     "tags": ["데스크톱", "모바일", "채팅"], "accent": "#5eead4", "play_url": "",
     "source": "https://github.com/NasusFullstack/chat", "release": "NasusFullstack/chat", "order": 2},
]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,80}$")


class Invalid(ValueError):
    """값이 규칙에 안 맞을 때. 메시지는 관리 화면에 그대로 보여준다."""


# ---- 작은 검사 도구 ----
def _text(data, key, limit, required=False):
    v = data.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise Invalid("%s 는 글자여야 합니다" % key)
    v = v.strip()
    if required and not v:
        raise Invalid("%s 를 적어 주세요" % key)
    if len(v) > limit:
        raise Invalid("%s 는 %d자까지입니다" % (key, limit))
    return v


def _url(data, key, allow_path=False):
    v = _text(data, key, 300)
    if not v:
        return ""
    if allow_path and v.startswith("/") and not v.startswith("//"):
        return v
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise Invalid("%s 는 http(s):// 주소%s여야 합니다" % (key, " 또는 / 로 시작하는 경로" if allow_path else ""))
    return v


def _list(data, key, count, each):
    v = data.get(key) or []
    if not isinstance(v, list):
        raise Invalid("%s 는 목록이어야 합니다" % key)
    out = []
    for item in v:
        if not isinstance(item, str):
            raise Invalid("%s 에 글자가 아닌 것이 있습니다" % key)
        item = item.strip()
        if item:
            if len(item) > each:
                raise Invalid("%s 하나는 %d자까지입니다" % (key, each))
            out.append(item)
    if len(out) > count:
        raise Invalid("%s 는 %d개까지입니다" % (key, count))
    return out


# ---- 작품 ----
def check_slug(slug):
    if not SLUG_RE.match(slug or ""):
        raise Invalid("주소 이름은 영어 소문자·숫자·- 로 1~32자입니다 (예: my-game)")
    return slug


def clean_work(data):
    """관리 화면이 보낸 작품 정보 → 저장할 값. 파일 정보(cover·download·build)는 여기서 안 받는다."""
    if not isinstance(data, dict):
        raise Invalid("작품 정보가 아닙니다")
    order = data.get("order", 0)
    if isinstance(order, bool) or not isinstance(order, (int, float)):
        raise Invalid("순서는 숫자여야 합니다")
    accent = _text(data, "accent", 7)
    if accent and not COLOR_RE.match(accent):
        raise Invalid("강조 색은 #rrggbb 꼴입니다")
    release = _text(data, "release", 140)
    if release.startswith("https://github.com/"):        # 주소를 통째로 붙여 넣어도 받아 준다
        release = "/".join(release[len("https://github.com/"):].split("/")[:2])
    if release and not REPO_RE.match(release):
        raise Invalid("GitHub 릴리스는 주인/저장소 꼴입니다 (예: NasusFullstack/chat)")
    return {
        "title": _text(data, "title", 60, required=True),
        "kind": _text(data, "kind", 12) or "기타",
        "status": _text(data, "status", 12),
        "version": _text(data, "version", 30),
        "year": _text(data, "year", 10),
        "tagline": _text(data, "tagline", 140),
        "desc": _text(data, "desc", 3000),
        "tags": _list(data, "tags", 10, 20),
        "accent": accent.lower(),
        "play_url": _url(data, "play_url", allow_path=True),
        "source": _url(data, "source"),
        "release": release,
        "order": int(order),
        "hidden": bool(data.get("hidden", False)),
    }


def clean_settings(data):
    if not isinstance(data, dict):
        raise Invalid("설정이 아닙니다")
    email = _text(data, "email", 120)
    if email and not EMAIL_RE.match(email):
        raise Invalid("메일 주소 꼴이 아닙니다")
    return {
        "name": _text(data, "name", 40, required=True),
        "headline": _text(data, "headline", 100),
        "about": _text(data, "about", 800),
        "roles": _list(data, "roles", 8, 16),
        "email": email,
        "github": _url(data, "github"),
    }


def sort_works(items):
    return sorted(items, key=lambda w: (w.get("order", 0), w.get("created", "")))


def media_url(slug, name):
    return "/media/%s/%s" % (slug, name) if name else None


def play_url(w):
    """웹 빌드를 올렸으면 /p/<작품>/, 아니면 적어 둔 플레이 주소."""
    if w.get("build"):
        return "/p/%s/" % w["slug"]
    return w.get("play_url") or None


def public_release(slug, info):
    """GitHub 최신 릴리스 → 밖에 보일 꼴. 파일 주소는 우리 /dl/ 을 거치게 바꾼다(받은 사람을 세려고)."""
    if not info:
        return None
    return {
        "tag": info["tag"],
        "url": info["url"],
        "published": info["published"],
        "assets": [{"name": a["name"], "bytes": a["size"], "url": "/dl/%s/a/%s" % (slug, quote(a["name"]))}
                   for a in info["assets"]],
    }


def public_work(w, counts, release=None):
    slug = w["slug"]
    dl = w.get("download")
    c = counts.get(slug, {})
    rel = public_release(slug, release)
    return {
        "slug": slug,
        "title": w.get("title", slug),
        "kind": w.get("kind", ""),
        "status": w.get("status", ""),
        "version": w.get("version", "") or (rel["tag"] if rel else ""),
        "year": w.get("year", ""),
        "tagline": w.get("tagline", ""),
        "desc": w.get("desc", ""),
        "tags": w.get("tags", []),
        "accent": w.get("accent", ""),
        "cover": media_url(slug, w.get("cover")),
        "shots": [media_url(slug, s) for s in w.get("shots", [])],
        "play": play_url(w),
        "download": {"url": "/dl/" + slug, "name": dl["name"], "bytes": dl["bytes"], "updated": dl["updated"]} if dl else None,
        "release": rel,
        "source": w.get("source", ""),
        "updated": w.get("updated", ""),
        "plays": c.get("plays", 0),
        "downloads": c.get("downloads", 0),
    }


def admin_work(w, counts, release=None):
    out = public_work(w, counts, release)
    out.update({"hidden": bool(w.get("hidden")), "order": w.get("order", 0), "play_url": w.get("play_url", ""),
                "version_own": w.get("version", ""), "release_repo": w.get("release", ""),
                "build": w.get("build"), "created": w.get("created", "")})
    return out


# ---- 무엇을 방문으로 세는가 ----
BOT_RE = re.compile(r"bot|crawl|spider|slurp|curl|wget|python|httpx|aiohttp|go-http|java/|okhttp|headless|"
                    r"lighthouse|preview|scrap|facebookexternalhit|yeti|daumoa|monitor|uptime|fetch", re.I)


def is_bot(agent):
    return not agent or bool(BOT_RE.search(agent))


def client_ip(headers, peer):
    """(주소, 어디서 알았는지). nginx 뒤라서 X-Forwarded-For 첫 칸이 진짜 손님이다."""
    xff = headers.get("x-forwarded-for", "")
    if xff.strip():
        return xff.split(",")[0].strip(), "x-forwarded-for"
    real = headers.get("x-real-ip", "").strip()
    if real:
        return real, "x-real-ip"
    return peer or "-", "peer"


def ref_host(headers):
    """다른 사이트에서 타고 왔으면 그 사이트 이름. 우리 사이트 안에서 옮겨 다닌 것은 None."""
    ref = headers.get("referer", "")
    if not ref:
        return None
    host = (urlsplit(ref).hostname or "").lower()
    own = (headers.get("host", "").split(":")[0]).lower()
    if not host or host == own:
        return None
    return host[4:] if host.startswith("www.") else host


def play_paths(items):
    """플레이로 셀 경로 → 작품. 웹 빌드(/p/<작품>/)와 따로 적어 둔 내부 주소(예: /game/)."""
    paths = {}
    for w in items:
        slug = w.get("slug")
        targets = ["/p/%s/" % slug]
        own = w.get("play_url") or ""
        if own.startswith("/") and not own.startswith("//"):
            targets.append(own.split("?")[0].split("#")[0])
        for t in targets:
            paths[t] = slug
            if t.endswith("/"):
                paths[t + "index.html"] = slug
    return paths


def classify(method, path, status, headers, items):
    """이 요청을 무엇으로 셀지: None | ('view', None) | ('play', 작품) | ('download', 작품)."""
    if method != "GET" or is_bot(headers.get("user-agent", "")):
        return None
    if path.startswith("/dl/") and status in (200, 206, 302):    # 302 = GitHub 릴리스로 넘겨줌
        rng = headers.get("range", "")
        if rng and not rng.replace(" ", "").startswith("bytes=0-"):
            return None      # 이어받기 조각은 한 번으로 친다
        return ("download", path[4:].split("/")[0])
    if status != 200 or "text/html" not in headers.get("accept", ""):
        return None
    slug = play_paths(items).get(path)
    if slug:
        return ("play", slug)
    if path == "/" or path.startswith("/w/"):
        return ("view", None)
    return None


# ---- 그림 ----
def sniff_image(data):
    """앞머리로 그림 종류를 가린다(확장자는 믿지 않는다)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def prepare_image(data):
    """올린 그림 → (확장자, 저장할 바이트). Pillow 가 있으면 긴 변 1920 의 WebP 로 줄인다(움직이는 그림은 그대로)."""
    ext = sniff_image(data)
    if not ext:
        raise Invalid("그림 파일(PNG·JPG·WebP·GIF)이 아닙니다")
    try:
        from PIL import Image
    except ImportError:
        return ext, data
    try:
        im = Image.open(io.BytesIO(data))
        if getattr(im, "n_frames", 1) > 1:
            return ext, data
        im.load()
    except Exception:
        raise Invalid("그림을 읽을 수 없습니다")
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    im.thumbnail((C.IMAGE_EDGE, C.IMAGE_EDGE))
    out = io.BytesIO()
    im.save(out, "WEBP", quality=86, method=4)
    return ".webp", out.getvalue()


# ---- 다운로드 파일 이름 ----
def clean_filename(name):
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name)
    if not name or name.startswith("."):
        raise Invalid("파일 이름이 없습니다")
    low = name.lower()
    if not any(low.endswith(ext) for ext in C.DOWNLOAD_TYPES):
        raise Invalid("올릴 수 있는 종류: " + " ".join(sorted(C.DOWNLOAD_TYPES)))
    return name[-120:]


# ---- 웹 빌드 zip ----
def check_build_zip(zf):
    """zip 안 목록 검사 → [(info, 놓을 경로)]. 맨 위 폴더 하나에 싸여 있으면 벗겨 낸다."""
    infos = [i for i in zf.infolist() if not i.filename.endswith("/")]
    if len(infos) > C.MAX_BUILD_FILES:
        raise Invalid("파일이 너무 많습니다")
    names = [i.filename.replace("\\", "/") for i in infos]
    strip = ""
    if "index.html" not in names:
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) == 1 and (next(iter(tops)) + "/index.html") in names:
            strip = next(iter(tops)) + "/"
        else:
            raise Invalid("맨 위(또는 폴더 하나 안)에 index.html 이 없습니다")
    out, total = [], 0
    for info, name in zip(infos, names):
        if strip:
            name = name[len(strip):]
        parts = name.split("/")
        if name.startswith("/") or ":" in name or any(p in ("", ".", "..") for p in parts):
            raise Invalid("경로가 이상한 파일: " + info.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in C.BUILD_TYPES:
            if parts[-1].startswith(".") or name.lower().endswith((".md", ".map")):
                continue          # 숨김 파일·설명서·소스맵은 조용히 뺀다
            raise Invalid("올릴 수 없는 종류: " + name)
        total += info.file_size
        if total > C.MAX_BUILD_UNPACKED:
            raise Invalid("풀었을 때 너무 큽니다")
        out.append((info, name))
    return out


def open_zip(path):
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise Invalid("zip 파일이 아닙니다")
