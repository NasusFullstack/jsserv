"""웹 게임 올려두기 - jsserv에 얹힌 기능 하나.

브라우저에서 바로 하는 웹 게임(HTML·스크립트·그림)을 주소 하나로 내려준다.
**게임 파일은 이 저장소에 없다.** 저장소는 공개라서, 게임은 따로 만들어 두고 열쇠(토큰)를 가진
사람만 서버에 직접 올린다. 그래서 게임을 고칠 때마다 이 코드를 고치거나 재배포할 필요가 없다.

    GET  /game           →  /game/ 로 보냄(게임 안의 상대 경로가 맞게)
    GET  /game/          게임 첫 화면(index.html)
    GET  /game/...       게임이 읽는 스크립트·그림
    POST /game/upload    게임 통째로 바꾸기. 본문 = zip, 헤더 X-Game-Token = 열쇠
    GET  /game/originals/index   (열쇠) 보관 중인 원본 목록 {경로: sha1}
    POST /game/originals         (열쇠) 원본 보관. 본문 = 바뀐 파일만 담은 zip. 공개되지 않는다

## 저장 위치
서버의 **영구 보존 폴더 `/data`** 아래 `/data/jsserv/game`(게임)과 `/data/jsserv/game_originals`(원본).
`/app`(저장소)은 배포할 때마다 새로 받아지므로 거기 두면 지워진다(chat 1.3.0 때 계정이 날아간 것과 같은 일).
`/data` 가 없는 곳(내 PC 등)에서는 집 폴더 `~/.jsserv/` 아래. 환경 변수 `JSSERV_GAME_DIR`·`JSSERV_GAME_ORIG_DIR`가 이긴다.
옛 자리(`~/.jsserv/game`)에 올려 둔 게임이 있으면 처음 한 번 새 자리로 옮겨 온다.

## 원본 보관
게임에는 용량을 줄인 그림을 올리고, 줄이기 전 원본(그림 도구가 그린 원본 시트 등)은 따로 쌓아 둔다.
누적 보관이라 같은 경로를 다시 올리면 예전 것은 `_history/` 에 날짜를 붙여 남긴다(지우지 않는다).

## 열쇠
코드에는 열쇠의 SHA-256 지문만 있다(공개돼도 열쇠를 거꾸로 알아낼 수 없다). 열쇠 자체는 게임을
만드는 사람 PC에만 있다. 바꾸려면 환경 변수 `JSSERV_GAME_TOKEN_SHA256`에 새 지문을 넣는다.

## 지키는 것
- 내려줄 때: `~/.jsserv/game` **밖의 파일은 절대 안 내려준다**(`..` 경로로 서버 파일을 빼 가지 못하게).
  정해 둔 종류(HTML·스크립트·그림·소리·글꼴)만 내려준다
- 올릴 때: 열쇠가 틀리면 거절. zip 크기·파일 수·풀린 크기에 상한. 경로가 이상하거나(`..`, 절대 경로)
  정해 둔 종류가 아닌 파일이 하나라도 있으면 **통째로 거절**한다. 다 풀린 뒤에 한 번에 바꿔 끼워서,
  올리는 도중에 게임이 반쯤 바뀐 상태로 보이지 않는다
- 게임을 고친 뒤 바로 보이게 HTML·스크립트는 캐시하지 않는다. 그림은 주소에 `?v=`(내용 지문)가 붙어 오면
  7일 캐시(내용이 바뀌면 주소가 바뀜), 없으면 10분만 캐시한다
- 원본은 열쇠 없이는 목록도 못 보고, 게임 주소로는 절대 안 내려준다(게임 폴더 밖)
"""
import hashlib
import hmac
import io
import os
import secrets
import shutil
import tempfile
import time
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

NAME = "game"
PREFIX = "/game"
VERSION = "0.2.0"
ABOUT = "웹 게임 올려두기"

def _base_dir():
    """쌓이는 데이터의 자리: 서버의 영구 보존 폴더 /data, 없으면 집 폴더."""
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return os.path.join("/data", "jsserv")
    return os.path.join(os.path.expanduser("~"), ".jsserv")


_LEGACY_ROOT = os.path.realpath(os.path.join(os.path.expanduser("~"), ".jsserv", "game"))
ROOT = os.path.realpath(os.environ.get("JSSERV_GAME_DIR", os.path.join(_base_dir(), "game")))
ORIG = os.path.realpath(os.environ.get("JSSERV_GAME_ORIG_DIR", os.path.join(os.path.dirname(ROOT), "game_originals")))


def _carry_over_once():
    """옛 자리(집 폴더)에 올려 둔 게임이 있고 새 자리가 비었으면 한 번 옮겨 온다."""
    try:
        if ROOT != _LEGACY_ROOT and not os.path.exists(ROOT) and os.path.isfile(os.path.join(_LEGACY_ROOT, "index.html")):
            os.makedirs(os.path.dirname(ROOT), exist_ok=True)
            shutil.copytree(_LEGACY_ROOT, ROOT)
    except OSError:
        pass


_carry_over_once()
TOKEN_SHA256 = os.environ.get("JSSERV_GAME_TOKEN_SHA256", "22ab5feafcd3f8d0d9e6e3874ad7639a5e9204b483644e4d2761a5e0d634079d")

# ---- 한도 (나중에 여기 숫자만 고치면 된다) ----
MAX_ZIP = 80 * 1024 * 1024        # 올리는 zip 하나
MAX_FILES = 3000                   # zip 안 파일 수
MAX_UNPACKED = 250 * 1024 * 1024   # 풀었을 때 전체 크기
MAX_ORIG_ZIP = 300 * 1024 * 1024        # 원본 zip 하나 (나눠서 여러 번 올린다)
MAX_ORIG_FILES = 5000
MAX_ORIG_UNPACKED = 600 * 1024 * 1024
ORIG_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".md", ".txt", ".csv", ".mp3", ".ogg", ".wav"}

# 내려주는(그리고 올릴 수 있는) 파일 종류
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".woff2": "font/woff2",
}
CACHE = {".png": "public, max-age=600", ".jpg": "public, max-age=600", ".webp": "public, max-age=600"}
CACHE_VERSIONED = "public, max-age=604800, immutable"   # ?v=지문 이 붙은 그림

router = APIRouter(prefix=PREFIX)


def _err(msg, code):
    return JSONResponse({"error": msg}, status_code=code)


def _token_ok(request: Request) -> bool:
    token = request.headers.get("x-game-token", "")
    return bool(token) and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), TOKEN_SHA256)


def _serve(rel: str, versioned: bool = False):
    rel = rel or "index.html"
    path = os.path.realpath(os.path.join(ROOT, rel))
    if not path.startswith(ROOT + os.sep):   # 게임 폴더 밖으로 나가는 경로
        return _err("없는 파일", 404)
    ext = os.path.splitext(path)[1].lower()
    if ext not in TYPES or not os.path.isfile(path):
        return _err("없는 파일" if os.path.isdir(ROOT) else "아직 올린 게임이 없다", 404)
    cache = CACHE_VERSIONED if versioned and ext in CACHE else CACHE.get(ext, "no-cache")
    return FileResponse(path, media_type=TYPES[ext], headers={"Cache-Control": cache})


def _check_zip(zf):
    """zip 안 파일 목록을 검사한다. 하나라도 이상하면 (None, 이유)."""
    names, total = [], 0
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        return None, "파일이 너무 많다"
    for info in infos:
        name = info.filename.replace("\\", "/")
        if name.endswith("/"):
            continue
        parts = name.split("/")
        if name.startswith("/") or ":" in name or any(p in ("", ".", "..") for p in parts):
            return None, "경로가 이상한 파일: " + name
        if os.path.splitext(name)[1].lower() not in TYPES:
            return None, "올릴 수 없는 종류: " + name
        total += info.file_size
        if total > MAX_UNPACKED:
            return None, "풀었을 때 너무 크다"
        names.append((info, name))
    if not any(n == "index.html" for _, n in names):
        return None, "맨 위에 index.html 이 없다"
    return names, None


@router.get("")
def to_slash():
    return RedirectResponse(PREFIX + "/", status_code=307)


@router.get("/")
def index():
    return _serve("index.html")


@router.post("/upload")
async def upload(request: Request):
    if not _token_ok(request):
        return _err("열쇠가 맞지 않는다", 403)
    body = bytearray()
    async for chunk in request.stream():   # 다 받아놓고 버리지 않게, 넘으면 받다가 끊는다
        body += chunk
        if len(body) > MAX_ZIP:
            return _err("zip 이 너무 크다", 413)
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(body)))
    except zipfile.BadZipFile:
        return _err("zip 이 아니다", 400)
    names, why = _check_zip(zf)
    if names is None:
        return _err(why, 400)
    parent = os.path.dirname(ROOT)
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, ".game-new-" + secrets.token_hex(6))
    total = 0
    try:
        for info, name in names:
            dest = os.path.join(tmp, *name.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            total += info.file_size
        # 다 풀린 뒤 한 번에 바꿔 끼운다
        old = os.path.join(parent, ".game-old-" + secrets.token_hex(6))
        if os.path.isdir(ROOT):
            os.rename(ROOT, old)
        os.rename(tmp, ROOT)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": True, "files": len(names), "bytes": total}


# ---- 원본 보관 (공개 안 함) ----
def _safe_rel(name: str):
    name = name.replace("\\", "/")
    parts = name.split("/")
    if name.startswith("/") or ":" in name or any(p in ("", ".", "..") for p in parts) or parts[0] == "_history":
        return None
    return name


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@router.get("/originals/index")
def originals_index(request: Request):
    if not _token_ok(request):
        return _err("열쇠가 맞지 않는다", 403)
    files = {}
    if os.path.isdir(ORIG):
        for dp, dn, fn in os.walk(ORIG):
            dn[:] = [d for d in dn if not (dp == ORIG and d == "_history")]
            for f in fn:
                if f.startswith(".orig-"):
                    continue
                full = os.path.join(dp, f)
                files[os.path.relpath(full, ORIG).replace(os.sep, "/")] = _sha1(full)
    return {"files": files}


@router.post("/originals")
async def originals_upload(request: Request):
    """바뀐 원본만 담은 zip 을 받아 쌓는다. 같은 경로에 다른 내용이 오면 옛 것은 _history/ 로 옮긴다."""
    if not _token_ok(request):
        return _err("열쇠가 맞지 않는다", 403)
    os.makedirs(ORIG, exist_ok=True)
    fd, tmp_zip = tempfile.mkstemp(prefix=".orig-", suffix=".zip", dir=ORIG)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:   # 큰 zip 을 메모리에 다 들고 있지 않게 바로 디스크로
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ORIG_ZIP:
                    return _err("zip 이 너무 크다(나눠서 올릴 것)", 413)
                out.write(chunk)
        try:
            zf = zipfile.ZipFile(tmp_zip)
        except zipfile.BadZipFile:
            return _err("zip 이 아니다", 400)
        with zf:
            items, total = [], 0
            infos = [i for i in zf.infolist() if not i.filename.endswith("/")]
            if len(infos) > MAX_ORIG_FILES:
                return _err("파일이 너무 많다", 400)
            for info in infos:
                rel = _safe_rel(info.filename)
                if rel is None:
                    return _err("경로가 이상한 파일: " + info.filename, 400)
                if os.path.splitext(rel)[1].lower() not in ORIG_TYPES:
                    return _err("보관할 수 없는 종류: " + rel, 400)
                total += info.file_size
                if total > MAX_ORIG_UNPACKED:
                    return _err("풀었을 때 너무 크다", 400)
                items.append((info, rel))
            stamp = time.strftime("%Y%m%d-%H%M%S")
            added = replaced = same = 0
            for info, rel in items:
                dest = os.path.realpath(os.path.join(ORIG, *rel.split("/")))
                if not dest.startswith(ORIG + os.sep):
                    return _err("경로가 이상한 파일: " + rel, 400)
                data = zf.read(info)
                if os.path.isfile(dest):
                    if hashlib.sha1(data).hexdigest() == _sha1(dest):
                        same += 1
                        continue
                    hist = os.path.join(ORIG, "_history", *rel.split("/")) + "." + stamp
                    os.makedirs(os.path.dirname(hist), exist_ok=True)
                    os.replace(dest, hist)
                    replaced += 1
                else:
                    added += 1
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                part = dest + ".part"
                with open(part, "wb") as f:
                    f.write(data)
                os.replace(part, dest)
        return {"ok": True, "added": added, "replaced": replaced, "unchanged": same, "bytes": total}
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


@router.get("/{rel:path}")
def asset(rel: str, request: Request):
    return _serve(rel, versioned="v" in request.query_params)
