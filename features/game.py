"""웹 게임 올려두기 - jsserv에 얹힌 기능 하나.

브라우저에서 바로 하는 웹 게임(HTML·스크립트·그림)을 주소 하나로 내려준다.
**게임 파일은 이 저장소에 없다.** 저장소는 공개라서, 게임은 따로 만들어 두고 열쇠(토큰)를 가진
사람만 서버에 직접 올린다. 그래서 게임을 고칠 때마다 이 코드를 고치거나 재배포할 필요가 없다.

    GET  /game           →  /game/ 로 보냄(게임 안의 상대 경로가 맞게)
    GET  /game/          게임 첫 화면(index.html)
    GET  /game/...       게임이 읽는 스크립트·그림
    POST /game/upload    게임 통째로 바꾸기. 본문 = zip, 헤더 X-Game-Token = 열쇠

## 저장 위치
서버 집 폴더의 `~/.jsserv/game` (환경 변수 `JSSERV_GAME_DIR`로 바꿀 수 있음).
저장소 폴더 안에 두면 **배포할 때마다 지워진다**(chat 1.3.0 때 계정이 날아간 것과 같은 일).

## 열쇠
코드에는 열쇠의 SHA-256 지문만 있다(공개돼도 열쇠를 거꾸로 알아낼 수 없다). 열쇠 자체는 게임을
만드는 사람 PC에만 있다. 바꾸려면 환경 변수 `JSSERV_GAME_TOKEN_SHA256`에 새 지문을 넣는다.

## 지키는 것
- 내려줄 때: `~/.jsserv/game` **밖의 파일은 절대 안 내려준다**(`..` 경로로 서버 파일을 빼 가지 못하게).
  정해 둔 종류(HTML·스크립트·그림·소리·글꼴)만 내려준다
- 올릴 때: 열쇠가 틀리면 거절. zip 크기·파일 수·풀린 크기에 상한. 경로가 이상하거나(`..`, 절대 경로)
  정해 둔 종류가 아닌 파일이 하나라도 있으면 **통째로 거절**한다. 다 풀린 뒤에 한 번에 바꿔 끼워서,
  올리는 도중에 게임이 반쯤 바뀐 상태로 보이지 않는다
- 게임을 고친 뒤 바로 보이게 HTML·스크립트는 캐시하지 않고, 그림만 잠깐 캐시한다
"""
import hashlib
import hmac
import io
import os
import secrets
import shutil
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

NAME = "game"
PREFIX = "/game"
VERSION = "0.1.0"
ABOUT = "웹 게임 올려두기"

ROOT = os.path.realpath(os.environ.get("JSSERV_GAME_DIR", os.path.join(os.path.expanduser("~"), ".jsserv", "game")))
TOKEN_SHA256 = os.environ.get("JSSERV_GAME_TOKEN_SHA256", "22ab5feafcd3f8d0d9e6e3874ad7639a5e9204b483644e4d2761a5e0d634079d")

# ---- 한도 (나중에 여기 숫자만 고치면 된다) ----
MAX_ZIP = 80 * 1024 * 1024        # 올리는 zip 하나
MAX_FILES = 3000                   # zip 안 파일 수
MAX_UNPACKED = 250 * 1024 * 1024   # 풀었을 때 전체 크기

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

router = APIRouter(prefix=PREFIX)


def _err(msg, code):
    return JSONResponse({"error": msg}, status_code=code)


def _serve(rel: str):
    rel = rel or "index.html"
    path = os.path.realpath(os.path.join(ROOT, rel))
    if not path.startswith(ROOT + os.sep):   # 게임 폴더 밖으로 나가는 경로
        return _err("없는 파일", 404)
    ext = os.path.splitext(path)[1].lower()
    if ext not in TYPES or not os.path.isfile(path):
        return _err("없는 파일" if os.path.isdir(ROOT) else "아직 올린 게임이 없다", 404)
    return FileResponse(path, media_type=TYPES[ext], headers={"Cache-Control": CACHE.get(ext, "no-cache")})


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
    token = request.headers.get("x-game-token", "")
    if not token or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), TOKEN_SHA256):
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


@router.get("/{rel:path}")
def asset(rel: str):
    return _serve(rel)
