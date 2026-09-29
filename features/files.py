"""파일·사진 올리기 - jsserv에 얹힌 기능 하나.

## 왜 주소를 돌려주는 방식인가
올린 뒤 **주소 한 줄**을 돌려주고, 그 주소를 채팅에 넣는다. 그러면 사진 미리보기도
이모티콘 등록도 **이미 있는 길**을 그대로 탄다(둘 다 주소로 동작한다). 새로 만들 게
적고, 나중에 저장하는 곳을 바꿔도 채팅 쪽은 안 건드린다.

## 한도는 전부 여기 한 곳에
서버 디스크가 남의 것이므로 처음부터 상한을 둔다. **숫자는 나중에 바꾸기 쉽게 모아뒀다** -
지금 값은 "일단 이 정도"지 확정이 아니다.

    LIMITS 표 한 곳만 고치면 된다.

## 지키는 것
- 파일 하나 크기 상한. 넘으면 **받다가 끊는다**(다 받아놓고 버리면 그 사이에 디스크가 찬다)
- 하루에 같은 사람이 올릴 수 있는 총량(지금은 IP 기준 - 중계 서버에는 계정이 없다)
- 서버 전체 사용량 상한과 보관 기간. 오래된 것부터 지운다
- 이름은 **절대 그대로 안 쓴다**(경로가 섞여 들어오면 엉뚱한 곳에 쓴다).
  저장 이름은 서버가 만든 난수고, 원래 이름은 내려줄 때만 쓴다
- HTML/스크립트로 열리지 않게 내려준다. 그림만 화면에 바로 뜨고 나머지는 내려받기다
  (남의 파일이 우리 주소에서 페이지로 실행되면 안 된다)
"""
import datetime
import hashlib
import mimetypes
import os
import re
import secrets
import urllib.parse
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

NAME = "files"
PREFIX = "/files"
VERSION = "1.0.0"
ABOUT = "춥채팅 파일·사진 올리기"

# ---- 한도 (나중에 여기 숫자만 고치면 된다) ---------------------------------
#
# **일반 파일과 이모티콘을 다르게 다룬다.** 이유가 분명하다:
# 일반 파일은 한 번 보고 마는 것이라 기한이 지나면 지워도 된다. 그런데 이모티콘은
# 보관함에 남아 **영원히 참조된다** - 같은 규칙으로 지우면 어느 날 갑자기 깨진다.
# 그렇다고 안 지우면 무한히 쌓여 서버가 찬다.
#
# 그래서 이모티콘은 (1) 올릴 때 작게 줄여 받고 (2) 기한으로 안 지우고
# (3) 개수·총량 상한을 두되 **차면 옛것을 지우는 대신 새로 올리는 걸 거절**한다.
# 옛 이모티콘이 소리 없이 사라지는 것이 더 나쁘기 때문이다.
LIMITS = {
    # 일반 파일
    "file_bytes": 100 * 1024 * 1024,        # 파일 하나 최대 100MB
    "daily_bytes": 500 * 1024 * 1024,       # 한 사람이 하루에 올릴 수 있는 총량
    "total_bytes": 8 * 1024 * 1024 * 1024,  # 일반 파일 전체 사용량 상한
    # 이만큼 지난 일반 파일은 지운다. **1일은 일부러 짧게 잡은 것이다** - 남의 서버를
    # 빌려 쓰므로 오래 쌓아두지 않는다. 그래서 어제 올린 사진은 오늘 안 열린다(채팅 기록을
    # 하루치만 남기는 것과 짝을 맞췄다). 나중에 늘릴 때는 total_bytes도 같이 볼 것
    "keep_days": 1,

    # 이모티콘(안 지운다)
    "emoji_bytes": 512 * 1024,              # 하나 최대 512KB(줄여서 올리므로 넉넉)
    "emoji_per_person": 300,                # 한 사람이 저장할 수 있는 개수
    "emoji_total_bytes": 2 * 1024 * 1024 * 1024,   # 이모티콘 전체 상한
}

KIND_FILE = "file"
KIND_EMOJI = "emoji"

# 화면에 바로 띄워도 되는 것들. 여기 없는 건 전부 내려받기로 준다 -
# 남이 올린 HTML이 우리 주소에서 페이지로 열리면 안 된다
INLINE_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}

STORE_DIR = os.environ.get("JSSERV_FILE_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__))), "uploads"))

_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ID_OK = re.compile(r"^[0-9a-f]{24}$")

router = APIRouter(prefix=PREFIX, tags=[NAME])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def safe_name(name: str) -> str:
    """올린 사람이 정한 이름은 **그대로 쓰지 않는다.**

    경로가 섞여 있으면(`..\\..\\Windows\\system32\\...`) 엉뚱한 곳을 가리키게 된다.
    폴더 부분을 버리고 쓸 수 없는 글자도 지운다. 이 이름은 **내려줄 때만** 쓰고,
    실제로 저장하는 이름은 서버가 만든 난수다.
    """
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME.sub("_", name).strip(". ")
    return name[:120] or "파일"


def _uploader_key(request: Request) -> str:
    """누가 올렸는지 - 중계 서버에는 계정이 없으므로 주소로 센다.

    nginx 뒤에 있으므로 X-Forwarded-For를 본다. 그대로 적어두면 남의 주소를 파일로
    남기는 셈이라 **짧게 요약해서** 쓴다(하루 총량을 세는 데만 필요하다).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")
    return hashlib.sha256(client.encode("utf-8")).hexdigest()[:16]


def _paths(file_id: str):
    return (os.path.join(STORE_DIR, file_id + ".bin"),
            os.path.join(STORE_DIR, file_id + ".name"),
            os.path.join(STORE_DIR, file_id + ".kind"))


def _kind_of(file_id: str) -> str:
    """이 파일이 한 번 보고 마는 것인지, 보관함에 남는 이모티콘인지."""
    try:
        with open(_paths(file_id)[2], encoding="utf-8") as fp:
            return fp.read().strip() or KIND_FILE
    except OSError:
        return KIND_FILE


def _entries(kind=None):
    """저장된 것들 - (id, 크기, 만든 시각). kind를 주면 그 종류만."""
    if not os.path.isdir(STORE_DIR):
        return []
    found = []
    for entry in os.scandir(STORE_DIR):
        if not entry.name.endswith(".bin"):
            continue
        file_id = entry.name[:-4]
        if kind is not None and _kind_of(file_id) != kind:
            continue
        info = entry.stat()
        found.append((file_id, info.st_size, info.st_mtime))
    return found


def _sweep():
    """오래된 것과 넘치는 것을 치운다. 올릴 때마다 부른다(따로 돌 필요가 없다).

    **이모티콘은 건드리지 않는다.** 보관함에 남아 영원히 참조되므로, 기한이 지났다고
    지우면 어느 날 갑자기 깨진다. 이모티콘은 개수·총량으로 막는다(올릴 때 거절).
    """
    entries = _entries(KIND_FILE)
    now = time.time()
    keep_seconds = LIMITS["keep_days"] * 24 * 3600
    for file_id, _size, made in list(entries):
        if now - made > keep_seconds:
            _remove(file_id)
    entries = _entries(KIND_FILE)
    total = sum(size for _i, size, _m in entries)
    if total <= LIMITS["total_bytes"]:
        return
    # 넘치면 **오래된 것부터** 지운다
    for file_id, size, _made in sorted(entries, key=lambda row: row[2]):
        _remove(file_id)
        total -= size
        if total <= LIMITS["total_bytes"]:
            break


def _remove(file_id: str):
    for path in _paths(file_id):
        try:
            os.remove(path)
        except OSError:
            pass


def _used_today(key: str) -> int:
    """이 사람이 오늘 올린 총량."""
    marker = os.path.join(STORE_DIR, f"quota-{key}-{_today()}.txt")
    try:
        with open(marker, encoding="utf-8") as fp:
            return int(fp.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _add_used(key: str, size: int):
    marker = os.path.join(STORE_DIR, f"quota-{key}-{_today()}.txt")
    total = _used_today(key) + size
    try:
        with open(marker, "w", encoding="utf-8") as fp:
            fp.write(str(total))
    except OSError:
        pass


def _emoji_count(key: str) -> int:
    """이 사람이 저장해둔 이모티콘 개수."""
    marker = os.path.join(STORE_DIR, f"emoji-{key}.txt")
    try:
        with open(marker, encoding="utf-8") as fp:
            return int(fp.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _add_emoji(key: str):
    # **세는 것을 먼저 한다.** open(..., "w")가 파일을 비우고 시작하므로, 그 안에서
    # 읽으면 언제나 0이 나와 개수가 1에서 안 올라간다(실제로 그렇게 안 막혔다)
    total = _emoji_count(key) + 1
    marker = os.path.join(STORE_DIR, f"emoji-{key}.txt")
    try:
        with open(marker, "w", encoding="utf-8") as fp:
            fp.write(str(total))
    except OSError:
        pass


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


@router.get("")
def status():
    entries = _entries()
    return {
        "feature": NAME,
        "version": VERSION,
        "about": ABOUT,
        "time": _now(),
        "limits": dict(LIMITS),
        "stored": len(entries),
        "used_bytes": sum(size for _i, size, _m in entries),
    }


@router.post("")
async def upload(request: Request):
    """파일 하나를 받는다.

    본문을 그대로 받고 이름은 헤더(X-File-Name)로 받는다 - multipart보다 단순하고,
    **다 받기 전에 끊을 수 있다**(그게 상한을 지키는 유일한 방법이다).
    """
    os.makedirs(STORE_DIR, exist_ok=True)
    _sweep()

    key = _uploader_key(request)
    kind = KIND_EMOJI if request.headers.get("x-file-kind") == KIND_EMOJI else KIND_FILE
    cap = LIMITS["emoji_bytes"] if kind == KIND_EMOJI else LIMITS["file_bytes"]

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        return JSONResponse({"error": "파일이 너무 큽니다", "limit": cap}, status_code=413)

    if kind == KIND_EMOJI:
        # **이모티콘은 안 지우므로 들어올 때 막는다.** 꽉 차면 옛것을 지우는 대신
        # 새로 저장하는 걸 거절한다 - 남의 이모티콘이 소리 없이 사라지면 안 된다
        mine = _emoji_count(key)
        if mine >= LIMITS["emoji_per_person"]:
            return JSONResponse({"error": "이모티콘을 더 저장할 수 없습니다",
                                 "limit": LIMITS["emoji_per_person"]}, status_code=429)
        stored = sum(size for _i, size, _m in _entries(KIND_EMOJI))
        if stored >= LIMITS["emoji_total_bytes"]:
            return JSONResponse({"error": "이모티콘 보관 공간이 가득 찼습니다"},
                                status_code=507)
        used = 0
    else:
        used = _used_today(key)
        if used >= LIMITS["daily_bytes"]:
            return JSONResponse({"error": "오늘 올릴 수 있는 용량을 다 썼습니다",
                                 "limit": LIMITS["daily_bytes"]}, status_code=429)

    file_id = secrets.token_hex(12)
    data_path, name_path, kind_path = _paths(file_id)
    written = 0
    try:
        with open(data_path, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                # **받다가 끊는다.** 다 받아놓고 버리면 그 사이에 디스크가 찬다
                over_daily = (kind == KIND_FILE
                              and used + written > LIMITS["daily_bytes"])
                if written > cap or over_daily:
                    out.close()
                    _remove(file_id)
                    return JSONResponse(
                        {"error": "오늘 올릴 수 있는 용량을 넘었습니다" if over_daily
                                  else "파일이 너무 큽니다",
                         "limit": LIMITS["daily_bytes"] if over_daily else cap},
                        status_code=429 if over_daily else 413)
                out.write(chunk)
    except Exception:
        _remove(file_id)
        return JSONResponse({"error": "받는 중에 문제가 생겼습니다"}, status_code=500)

    if written == 0:
        _remove(file_id)
        return JSONResponse({"error": "빈 파일입니다"}, status_code=400)

    # **이름은 부호화해서 온다.** HTTP 헤더는 ASCII만 실을 수 있어서 한글 이름을
    # 그대로 넣으면 아예 안 올라간다(실제로 그렇게 막혔다)
    name = safe_name(urllib.parse.unquote(request.headers.get("x-file-name", "")))
    with open(name_path, "w", encoding="utf-8") as fp:
        fp.write(name)
    with open(kind_path, "w", encoding="utf-8") as fp:
        fp.write(kind)
    if kind == KIND_EMOJI:
        _add_emoji(key)
    else:
        _add_used(key, written)

    return {
        "id": file_id,
        "name": name,
        "size": written,
        "kind": kind,
        # **주소에도 부호화해서 넣는다.** 이 주소는 채팅 한 줄에 그대로 실려 가는데,
        # 채팅은 공백에서 토큰을 끊으므로 "우리집 사진.png"가 들어가면 링크가 두
        # 조각으로 갈라져 그림이 안 뜬다(실제로 그렇게 깨졌다)
        "url": f"{PREFIX}/{file_id}/{urllib.parse.quote(name)}",
    }


@router.get("/{file_id}/{name}")
def download(file_id: str, name: str):
    """올린 파일을 내려준다.

    그림만 화면에 바로 뜨고(INLINE_TYPES) 나머지는 내려받기로 준다 -
    **남이 올린 HTML이 우리 주소에서 페이지로 열리면 안 된다.**
    """
    if not _ID_OK.match(file_id or ""):
        return JSONResponse({"error": "없는 파일입니다"}, status_code=404)
    data_path, name_path, _kind_path = _paths(file_id)
    if not os.path.exists(data_path):
        return JSONResponse({"error": "없는 파일입니다"}, status_code=404)

    stored_name = "파일"
    try:
        with open(name_path, encoding="utf-8") as fp:
            stored_name = fp.read().strip() or "파일"
    except OSError:
        pass

    guessed = mimetypes.guess_type(stored_name)[0] or "application/octet-stream"
    inline = guessed in INLINE_TYPES
    return FileResponse(
        data_path,
        media_type=guessed if inline else "application/octet-stream",
        filename=None if inline else stored_name,
        headers={
            # 그림이라도 브라우저가 알아서 다른 걸로 해석하지 않게 못 박는다
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=86400",
        },
    )
