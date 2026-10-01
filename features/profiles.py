"""참여자 프로필(아이콘) - jsserv에 얹힌 기능 하나.

## 무엇을 푸는가
지금까지 아이콘은 **채팅 통로로** 오갔다. IRC는 한 줄이 512바이트를 못 넘어서 아이콘
하나를 300자씩 쪼개 여러 줄로 보내야 했고, 조각이 하나라도 빠지면 아무것도 안 떴다.
게다가 상대가 접속해 있지 않으면 받을 방법이 아예 없다 - 방금 들어온 사람에게는
모두가 자기 아이콘을 다시 보내야 했다.

여기 두면 조각낼 일이 없고, 상대가 없어도 얼굴을 볼 수 있다.

**채팅으로 주고받는 길은 그대로 둔다.** 이 서버를 못 쓰는 상황(중계가 내려갔거나 다른
사람이 옛 버전)에서도 지금처럼 동작해야 하고, 나중에 다시 쓸 수도 있다.

## 누구 것인지 - 먼저 잡은 사람이 임자
중계 서버에는 계정이 없다. 그냥 두면 **아무나 남의 얼굴을 바꿀 수 있다** - 채팅 통로로
주고받을 때는 IRC 서버가 닉네임을 지켜주므로 없던 문제라, 여기로 옮기면서 잃으면 안 된다.

그래서 처음 올린 사람이 표를 하나 받고(token), 그 뒤로는 그 표를 가진 사람만 고칠 수
있다. 다만 표를 영원히 붙들지는 않는다 - 컴퓨터를 바꾸면 표가 없어지므로, 한동안
아무도 안 고친 자리는 다시 잡을 수 있게 풀어준다(claim_days).

## 무슨 프로그램을 쓰는지도 여기 둔다
"저 사람은 춥채팅인가 WeeChat인가"를 알아내려고 지금까지는 IRC 로 CTCP VERSION 을
물어봤다. 그런데 서버마다 그걸 폭주로 보고 거절하고(UnrealIRCd: "Multi-target
messaging is not allowed"), 상대 화면에 요청이 찍히고, 다리 봇은 엉뚱한 답을 한다.

프로필을 올릴 때 **자기가 무엇인지 같이 적으면** 그 셋이 전부 사라진다. 아무에게도
묻지 않고, 참여자 목록을 받을 때 이미 하는 lookup 한 번으로 같이 온다.
IRC 로 묻는 길은 코드에 그대로 남겨두고 꺼둔다 - 우리 서버를 못 쓸 때 쓸 수 있다.

## 자리 이름은 서버에 안 알린다
who는 클라이언트가 (프로토콜, 호스트, 포트, 닉네임)을 해시해서 만든 24자다. 빌려 쓰는
서버에 누가 어느 채팅방을 쓰는지 적히지 않고, 서버가 달라도 같은 닉네임이 안 섞인다.
"""
import hashlib
import json
import os
import re
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

NAME = "profiles"
PREFIX = "/profiles"
# 1.1.0: 무슨 프로그램을 쓰는지(client)를 같이 보관한다. 클라이언트가 이 번호를 보고
# "이 서버가 그걸 알려주는가"를 판단할 수 있게 올린다
VERSION = "1.1.0"
ABOUT = "춥채팅 참여자 프로필(아이콘)"

# ---- 한도 (나중에 여기 숫자만 고치면 된다) ---------------------------------
LIMITS = {
    # 아이콘은 base64 글자로 들어온다. 지금 앱이 2000자까지 만들므로 여유를 둔 값
    "avatar_chars": 6000,
    "nick_chars": 64,
    "claim_days": 45,       # 이만큼 아무도 안 고친 자리는 다시 잡을 수 있다
    "keep_days": 90,        # 이만큼 손 안 댄 프로필은 지운다(다시 켜면 저절로 올라온다)
    "max_profiles": 20000,
    "daily_writes": 200,    # 한 사람이 하루에 고칠 수 있는 횟수
    "batch_size": 60,       # 한 번에 물어볼 수 있는 사람 수
    "app_chars": 32,        # 프로그램 이름 길이
    "version_chars": 24,
}

# 어느 자리에서 쓰는 것인지. 아는 것만 받는다 - 모르는 글자를 그대로 쥐고 있다가
# 화면에 뿌리면 남이 적어 보낸 글이 남의 화면에 뜨는 길이 된다
PLATFORMS = ("pc", "mobile", "web", "cli")

STORE_DIR = os.environ.get("JSSERV_PROFILE_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__))), "profiles"))

_WHO_OK = re.compile(r"^[0-9a-f]{24}$")
_B64_OK = re.compile(r"^[A-Za-z0-9+/=\s]*$")

router = APIRouter(prefix=PREFIX, tags=[NAME])


# ------------------------------------------------------------------ 도구
def _path(who: str) -> str:
    return os.path.join(STORE_DIR, f"{who}.json")


def _today() -> str:
    return time.strftime("%Y%m%d", time.gmtime())


def _quota_path(key: str) -> str:
    return os.path.join(STORE_DIR, f"quota-{key}-{_today()}.txt")


def _writer_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")
    return hashlib.sha256(client.encode("utf-8")).hexdigest()[:16]


def _used_today(key: str) -> int:
    try:
        with open(_quota_path(key), encoding="utf-8") as fp:
            return int(fp.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def _add_used(key: str, count: int):
    total = _used_today(key) + count      # **열기 전에** 읽는다("w"는 열자마자 비운다)
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(_quota_path(key), "w", encoding="utf-8") as fp:
        fp.write(str(total))


def read_profile(who: str) -> dict | None:
    try:
        with open(_path(who), encoding="utf-8") as fp:
            saved = json.load(fp)
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) else None


def _write_profile(who: str, saved: dict):
    os.makedirs(STORE_DIR, exist_ok=True)
    temp = f"{_path(who)}.tmp"
    with open(temp, "w", encoding="utf-8") as fp:
        json.dump(saved, fp, ensure_ascii=False)
    os.replace(temp, _path(who))


def can_write(saved: dict | None, token: str, now: float | None = None) -> bool:
    """이 표로 이 자리를 고칠 수 있는가.

    - 빈 자리면 누구나 잡을 수 있다(처음 올린 사람이 임자)
    - 표가 맞으면 당연히 된다
    - 한동안 아무도 안 고쳤으면 풀어준다(컴퓨터를 바꾸면 표가 없어지므로)
    """
    if saved is None:
        return True
    if not saved.get("token"):
        return True
    if token and secrets.compare_digest(str(saved["token"]), token):
        return True
    stale = time.time() if now is None else now
    return stale - float(saved.get("updated", 0)) > LIMITS["claim_days"] * 86400


def _public(saved: dict) -> dict:
    """밖으로 내보낼 부분만. **표(token)는 절대 안 내보낸다.**"""
    return {"nick": saved.get("nick", ""), "avatar": saved.get("avatar", ""),
            "client": saved.get("client", {}),
            "updated": saved.get("updated", 0)}


def _sweep():
    """오래 손 안 댄 프로필을 지운다. 너무 많으면 오래된 것부터."""
    if not os.path.isdir(STORE_DIR):
        return
    cutoff = time.time() - LIMITS["keep_days"] * 86400
    alive = []
    today = _today()
    for name in os.listdir(STORE_DIR):
        if name.startswith("quota-"):
            if not name.endswith(f"-{today}.txt"):
                try:
                    os.remove(os.path.join(STORE_DIR, name))
                except OSError:
                    pass
            continue
        if not name.endswith(".json"):
            continue
        who = name[:-len(".json")]
        saved = read_profile(who)
        if saved is None or float(saved.get("updated", 0)) < cutoff:
            try:
                os.remove(os.path.join(STORE_DIR, name))
            except OSError:
                pass
            continue
        alive.append((float(saved.get("updated", 0)), who))

    if len(alive) > LIMITS["max_profiles"]:
        alive.sort()
        for _, who in alive[:len(alive) - LIMITS["max_profiles"]]:
            try:
                os.remove(_path(who))
            except OSError:
                pass


def clean_avatar(avatar) -> str | None:
    """올라온 아이콘 글자를 믿을 수 있는 모양으로. 아니면 None."""
    if avatar is None:
        return ""
    if not isinstance(avatar, str):
        return None
    avatar = avatar.strip()
    if len(avatar) > LIMITS["avatar_chars"]:
        return None
    # base64가 아닌 것이 들어오면 안 받는다 - 그림이 아닌 것을 쥐고 있을 이유가 없다
    if avatar and not _B64_OK.match(avatar):
        return None
    return avatar


def clean_client(raw):
    """'나는 무슨 프로그램인가'를 믿을 수 있는 모양으로. 아니면 None.

    글자를 그대로 믿지 않는다. 이 값은 남의 화면에 배지로 뜨므로, 아무나 아무 글자를
    적어 보낼 수 있으면 그게 곧 남의 화면에 글을 쓰는 길이 된다.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    app = str(raw.get("app", ""))[:LIMITS["app_chars"]]
    version = str(raw.get("version", ""))[:LIMITS["version_chars"]]
    platform = str(raw.get("platform", ""))
    if app and not re.fullmatch(r"[A-Za-z0-9 ._-]+", app):
        return None
    if version and not re.fullmatch(r"[0-9A-Za-z.+-]+", version):
        return None
    if platform and platform not in PLATFORMS:
        return None
    if not app:
        return {}
    return {"app": app, "version": version, "platform": platform}


# ------------------------------------------------------------------ 창구
@router.get("")
def status():
    count = 0
    if os.path.isdir(STORE_DIR):
        count = len([n for n in os.listdir(STORE_DIR) if n.endswith(".json")])
    return {"feature": NAME, "version": VERSION, "limits": dict(LIMITS), "profiles": count}


@router.put("/{who}")
async def put_profile(who: str, request: Request):
    """내 프로필을 올린다. 처음이면 표를 하나 만들어 돌려준다(다음에 고칠 때 쓴다)."""
    if not _WHO_OK.match(who):
        return JSONResponse({"error": "자리 id가 올바르지 않습니다"}, status_code=400)
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)

    avatar = clean_avatar(body.get("avatar"))
    if avatar is None:
        return JSONResponse({"error": "아이콘이 너무 크거나 그림이 아닙니다"}, status_code=413)
    client = clean_client(body.get("client"))
    if client is None:
        return JSONResponse({"error": "프로그램 정보가 올바르지 않습니다"}, status_code=400)

    key = _writer_key(request)
    if _used_today(key) >= LIMITS["daily_writes"]:
        return JSONResponse({"error": "오늘 고칠 수 있는 횟수를 넘었습니다"}, status_code=429)

    _sweep()
    saved = read_profile(who)
    token = str(body.get("token", ""))[:64]
    if not can_write(saved, token):
        # 남의 얼굴은 못 바꾼다
        return JSONResponse({"error": "이 자리는 다른 사람이 쓰고 있습니다"}, status_code=403)

    keep_token = (saved or {}).get("token") if (saved and token
                                                and saved.get("token") == token) else None
    new_token = keep_token or token or secrets.token_hex(16)

    # **안 보낸 칸은 건드리지 않는다.** 모바일은 아이콘 편집기가 없어서 "나는 춥채팅
    # 모바일"만 올리는데, 빈 아이콘으로 덮어쓰면 그 사람이 PC에서 정해둔 얼굴이
    # 서버에서 지워진다(같은 닉네임이면 같은 자리다)
    before = saved or {}
    nick = (str(body["nick"])[:LIMITS["nick_chars"]] if "nick" in body
            else before.get("nick", ""))
    if "avatar" not in body:
        avatar = before.get("avatar", "")
    if "client" not in body:
        client = before.get("client", {})

    _write_profile(who, {"nick": nick, "avatar": avatar, "client": client,
                         "token": new_token, "updated": time.time()})
    _add_used(key, 1)
    return {"ok": True, "token": new_token}


@router.get("/{who}")
def get_profile(who: str):
    if not _WHO_OK.match(who):
        return JSONResponse({"error": "자리 id가 올바르지 않습니다"}, status_code=400)
    saved = read_profile(who)
    if saved is None:
        return JSONResponse({"error": "없습니다"}, status_code=404)
    return _public(saved)


@router.post("/lookup")
async def lookup(request: Request):
    """여러 사람을 한 번에 묻는다.

    참여자가 여섯이면 요청도 여섯 번이 된다 - 채팅방에 들어갈 때마다 그러면 서버에도
    무리고 화면도 늦다. 한 번에 묻고 한 번에 받는다.
    """
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)
    wanted = body.get("who") if isinstance(body, dict) else None
    if not isinstance(wanted, list):
        return JSONResponse({"error": "물어볼 사람이 없습니다"}, status_code=400)
    if len(wanted) > LIMITS["batch_size"]:
        return JSONResponse({"error": "한 번에 물어볼 수 있는 수를 넘었습니다"},
                            status_code=413)
    found = {}
    for who in wanted:
        if not isinstance(who, str) or not _WHO_OK.match(who):
            continue
        saved = read_profile(who)
        if saved is not None:
            found[who] = _public(saved)
    return {"profiles": found}
