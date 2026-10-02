"""춥채팅 서버 채팅 - **우리가 직접 돌리는 채팅방.**

## 왜 IRC 말고 이것도 두나
IRC 는 남의 규약이라 못 하는 것이 많았다. 전부 우회해서 겨우 되게 만들어 뒀는데,
우회 하나하나가 사고의 원인이기도 했다:

| IRC 에서 | 여기서 |
|---|---|
| 한 줄 512바이트 - 아이콘을 300자씩 쪼개 보냄(조각이 빠지면 안 뜸) | 그냥 보낸다 |
| 한글 닉네임을 서버가 거절 | 된다 |
| 아이콘·표시이름을 CTCP 로 몰래 주고받음(해석 실패하면 채팅에 쓰레기가 샘) | 서버가 들고 있다 |
| "무슨 앱 쓰나"를 물어보면 폭주로 보고 끊음 | 서버가 안다 |
| 지난 기록이 없어 **각자** 올리고 서버가 중복 제거 | 서버에 원본이 있다 |
| 귓속말은 기록도 알림도 안 됨 | 된다 |

**IRC 를 없애지는 않는다.** 둘을 따로 쓸 수 있게 두고, 사람이 고른다.

## 자리 이름(room)은 서버가 안다
IRC 모드에서는 기록·프로필이 (프로토콜, 호스트, 포트) 해시로 갈렸는데, 여기서는
이 서버가 곧 채팅 서버라 그럴 필요가 없다. 채널 이름이 곧 자리다.

## 받은 것은 전부 검사한다
다른 기능과 같은 규칙이다. 들어오는 줄은 전부 남이 정한 값이고, 그중 일부는 **남의
화면에 그대로 뜬다**(이름, 글). 모르는 명령은 조용히 버린다.
"""
import hashlib
import json
import os
import re
import secrets
import time

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse

NAME = "chat"
PREFIX = "/chat"
# 1.3.0 - 계정이 **저장소 밖에** 쌓인다. 안에 두면 배포할 때 지워진다(실측
#         2026-10-02: 버전 두 번 올리는 동안 그 전 계정이 전부 날아갔다).
#       - 아이디의 **대소문자를 안 가린다**. IRC 버릇대로 쳤다가 "있는 아이디인데
#         로그인이 안 된다"가 됐다
# 1.2.0 - ping 에 pong 으로 답한다. 조용한 연결이 살아 있는지 **클라이언트가 물어볼
#         수 있어야** 한다 - 없으면 조용하다는 이유로 스스로 끊고 다시 붙는다
#         (실측 2026-10-02: PC 가 170초마다 그랬다. 소켓은 멀쩡했다).
#       - channels 로 **방 목록**을 준다. 서버에 어떤 방이 있는지 보고 고를 수 있게
# 1.1.0 - WebSocket 으로도 가입할 수 있다(연결 하나로 가입+로그인).
#         올릴 때마다 손대야 하는 이유: 클라이언트가 "이 서버가 그걸 할 수
#         있나"를 **물어볼 수 있어야** 한다. 모르는 명령은 조용히 버리도록
#         되어 있어서(구버전이 죽지 않게), 안 올리면 새 클라이언트가 옛 서버에
#         붙었을 때 아무 답도 없이 멎는다 - 실제로 그렇게 겪었다
VERSION = "1.3.0"
ABOUT = "춥채팅 서버 채팅(IRC 없이)"

# ---- 한도 -------------------------------------------------------------------
LIMITS = {
    # IRC 는 한 줄 512바이트였다. 여기서는 사람이 쓸 만한 길이로 넉넉히 둔다
    "text_chars": 4000,
    "nick_chars": 24,          # 한글도 된다
    "id_chars": 24,
    "password_chars": 128,
    "channel_chars": 32,
    "avatar_chars": 6000,      # 쪼개 보내지 않는다
    "history_lines": 200,      # 들어갈 때 돌려주는 지난 줄
    "keep_hours": 24,          # 이보다 오래된 줄은 지운다(파일 기능과 같은 기준)
    "max_channels": 200,
    "members_per_channel": 100,
    "lines_per_sec": 10,       # 한 연결이 초당 보낼 수 있는 줄
}

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEGACY_DIR = os.path.join(_HERE, "chat")


def _store_dir() -> str:
    """계정과 방이 쌓이는 자리.

    **저장소 폴더 안에 두면 안 된다.** 배포하면 지워진다 - 실측(2026-10-02): 버전을
    두 번 올리는 동안 그 전에 만든 계정이 전부 사라졌다("있는 아이디인데 로그인이
    안 된다"는 신고로 드러났다). 다른 기능들은 환경 변수로 바깥을 가리키고 있는데
    (JSSERV_FILE_DIR 등) 채팅은 새로 생긴 거라 그 설정이 없었다.

    그래서 **설정이 없어도** 코드와 따로 사는 자리를 고른다 - 집 폴더 아래.
    환경 변수를 주면 그쪽이 이긴다(다른 기능들과 같은 자리에 모으고 싶을 때).
    """
    chosen = os.environ.get("JSSERV_CHAT_DIR")
    if chosen:
        return chosen
    home = os.path.expanduser("~")
    if home and os.path.isdir(home) and os.access(home, os.W_OK):
        return os.path.join(home, ".jsserv", "chat")
    # 집 폴더를 못 쓰는 환경이면 어쩔 수 없이 옛 자리(배포 때 지워질 수 있다)
    return _LEGACY_DIR


STORE_DIR = _store_dir()


def _carry_over_once() -> None:
    """옛 자리에 있던 것을 새 자리로 한 번 옮긴다.

    자리를 바꾸면서 그냥 두면, 이미 만들어 둔 계정이 **없는 것처럼** 보인다.
    새 자리에 이미 뭔가 있으면 건드리지 않는다.
    """
    if STORE_DIR == _LEGACY_DIR or not os.path.isdir(_LEGACY_DIR):
        return
    if os.path.exists(os.path.join(STORE_DIR, "users.json")):
        return
    import shutil
    try:
        os.makedirs(STORE_DIR, exist_ok=True)
        for entry in os.listdir(_LEGACY_DIR):
            source = os.path.join(_LEGACY_DIR, entry)
            target = os.path.join(STORE_DIR, entry)
            if os.path.exists(target):
                continue
            (shutil.copytree if os.path.isdir(source) else shutil.copy2)(
                source, target)
    except OSError:
        # 못 옮겨도 서버는 떠야 한다. 계정을 다시 만들면 된다
        pass


_carry_over_once()

# 아이디는 로그인 식별자라 영문·숫자로 묶는다(헷갈리는 이름으로 남을 사칭하지 못하게).
# **표시 이름(nick)은 한글도 된다** - IRC 에서 못 하던 것이 이것이다
_ID_OK = re.compile(r"^[A-Za-z0-9_.-]{2,24}$")
_CHANNEL_OK = re.compile(r"^[^\s\x00-\x1f#&][^\s\x00-\x1f]{0,31}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

router = APIRouter(prefix=PREFIX, tags=[NAME])


# ------------------------------------------------------------------ 저장
def _path(name: str) -> str:
    return os.path.join(STORE_DIR, name)


def _read(name: str, fallback):
    try:
        with open(_path(name), encoding="utf-8") as fp:
            saved = json.load(fp)
    except (OSError, ValueError):
        return fallback
    return saved if isinstance(saved, type(fallback)) else fallback


def _write(name: str, data) -> None:
    os.makedirs(STORE_DIR, exist_ok=True)
    temp = _path(name + ".tmp")
    with open(temp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    os.replace(temp, _path(name))


def load_users() -> dict:
    return _read("users.json", {})


def save_users(users: dict) -> None:
    _write("users.json", users)


def load_channels() -> dict:
    return _read("channels.json", {})


def save_channels(channels: dict) -> None:
    _write("channels.json", channels)


def hash_password(password: str, salt: str = "") -> tuple:
    """비밀번호는 **절대 평문으로 두지 않는다.** salt 를 섞어 해시만 적어둔다."""
    if not salt:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return digest, salt


# ------------------------------------------------------------------ 다듬기
def clean_text(value, limit: int) -> str:
    """남이 보낸 글을 화면에 그려도 되는 모양으로.

    제어문자를 걷어내는 이유: IRC 색·굵게 문자가 그대로 들어오면 화면이 깨진다
    (실제로 겪었다). 줄바꿈(\\n)과 탭은 남겨둔다 - 여러 줄 글은 쓸 수 있어야 한다.
    """
    if not isinstance(value, str):
        return ""
    cleaned = _CONTROL.sub("", value).strip()
    return cleaned[:limit]


def clean_nick(value) -> str:
    """표시 이름. **한글도 된다** - IRC 에서 못 하던 것이다."""
    return clean_text(value, LIMITS["nick_chars"])


def is_id(value) -> bool:
    return isinstance(value, str) and bool(_ID_OK.match(value))


def is_channel(value) -> bool:
    """채널 이름. IRC 처럼 # 로 시작할 필요가 없고 한글도 된다."""
    return isinstance(value, str) and bool(_CHANNEL_OK.match(value))


# ------------------------------------------------------------------ 기록
def history_path(channel: str) -> str:
    """채널 이름을 그대로 파일 이름에 쓰지 않는다(경로를 벗어나는 이름이 올 수 있다)."""
    key = hashlib.sha256(channel.encode("utf-8")).hexdigest()[:24]
    return os.path.join(STORE_DIR, "rooms", f"{key}.json")


def read_history(channel: str) -> list:
    try:
        with open(history_path(channel), encoding="utf-8") as fp:
            lines = json.load(fp)
    except (OSError, ValueError):
        return []
    return lines if isinstance(lines, list) else []


def add_history(channel: str, line: dict) -> None:
    """한 줄을 적어둔다. **서버가 원본을 갖는다** - 각자 올리고 중복을 거를 필요가 없다."""
    lines = read_history(channel)
    lines.append(line)
    cutoff = time.time() - LIMITS["keep_hours"] * 3600
    lines = [one for one in lines if float(one.get("ts", 0)) >= cutoff]
    if len(lines) > LIMITS["history_lines"]:
        lines = lines[-LIMITS["history_lines"]:]
    os.makedirs(os.path.dirname(history_path(channel)), exist_ok=True)
    temp = history_path(channel) + ".tmp"
    with open(temp, "w", encoding="utf-8") as fp:
        json.dump(lines, fp, ensure_ascii=False)
    os.replace(temp, history_path(channel))


# ------------------------------------------------------------------ 지금 붙어 있는 사람들
class Room:
    """채널 하나에 지금 들어와 있는 연결들."""

    def __init__(self):
        self.members: dict = {}      # user_id -> WebSocket

    def add(self, user_id: str, socket) -> None:
        self.members[user_id] = socket

    def remove(self, user_id: str) -> None:
        self.members.pop(user_id, None)


class Hub:
    """지금 붙어 있는 사람과 방들. **서버가 켜져 있는 동안만** 산다."""

    def __init__(self):
        self.rooms: dict = {}        # channel -> Room
        self.online: dict = {}       # user_id -> WebSocket

    def room(self, channel: str) -> Room:
        return self.rooms.setdefault(channel, Room())

    def channels_of(self, user_id: str) -> list:
        return [name for name, room in self.rooms.items() if user_id in room.members]

    async def tell(self, channel: str, message: dict, skip: str = "") -> None:
        """그 방 사람들에게 한 줄 보낸다. 끊긴 연결은 조용히 넘어간다."""
        room = self.rooms.get(channel)
        if room is None:
            return
        for user_id, socket in list(room.members.items()):
            if user_id == skip:
                continue
            try:
                await socket.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                room.remove(user_id)

    async def tell_one(self, user_id: str, message: dict) -> bool:
        socket = self.online.get(user_id)
        if socket is None:
            return False
        try:
            await socket.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except Exception:
            return False


hub = Hub()


# ------------------------------------------------------------------ 창구
@router.get("")
def status():
    users = len(load_users())
    channels = len(load_channels())
    return {"feature": NAME, "version": VERSION, "limits": dict(LIMITS),
            "users": users, "channels": channels,
            "online": len(hub.online)}


@router.post("/register")
async def register(request: Request):
    """계정을 만든다. **비밀번호는 해시로만 적어둔다.**

    본문을 직접 읽는다 - 다른 기능과 같은 방식이다. FastAPI 가 알아서 읽게 두면
    Content-Type 이 없는 요청을 422 로 거절하는데, 우리 클라이언트는 그 머리말을
    늘 붙이지는 않는다.
    """
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)

    code, answer = make_account(payload.get("id"), payload.get("pw"))
    if code != 200:
        return JSONResponse(answer, status_code=code)
    return answer


def clean_id(value) -> str:
    """사람이 친 아이디를 다듬는다 - **앞뒤 공백을 지운다.**

    폰 자판은 글자 뒤에 공백을 잘 붙인다. 그대로 두면 눈에 안 보이는 한 칸 때문에
    "있는 아이디인데 로그인이 안 된다"가 된다.
    """
    return value.strip() if isinstance(value, str) else ""


def find_account(users: dict, user_id) -> tuple:
    """적힌 아이디를 찾는다. **대소문자를 안 가린다.**

    IRC 는 이름의 대소문자를 안 가려서 사람들이 그 버릇으로 친다. 가렸더니
    "있는 아이디인데 로그인이 안 된다"가 됐다(실측 2026-10-02: Case43F4DF 로
    만들고 case43f4df 로 들어가려다 거절).

    돌려주는 것은 (저장된 아이디, 그 내용). 없으면 (None, None).
    저장된 쪽을 돌려주는 이유: 화면에 보이는 이름을 **처음 적은 그대로** 두려고 -
    안 그러면 같은 사람이 Mong 과 mong 으로 갈려 보인다.
    """
    typed = clean_id(user_id)
    if not typed:
        return None, None
    saved = users.get(typed)
    if saved is not None:
        return typed, saved
    lowered = typed.lower()
    for key, value in users.items():
        if key.lower() == lowered:
            return key, value
    return None, None


def make_account(user_id, password):
    """계정을 만든다. (상태코드, 답) 을 돌려준다.

    HTTP 와 WebSocket 이 **같은 판단**을 쓰게 하려고 따로 뺐다 - 두 군데에 같은 규칙을
    적어두면 한쪽만 고치는 일이 반드시 생긴다.
    """
    user_id = clean_id(user_id)
    if not is_id(user_id):
        return 400, {"error": "아이디는 영문·숫자 2~24자입니다"}
    if not isinstance(password, str) or not 4 <= len(password) <= LIMITS["password_chars"]:
        return 400, {"error": "비밀번호는 4자 이상입니다"}

    users = load_users()
    # **대소문자만 다른 아이디도 같은 것으로 본다.** 안 그러면 Mong 과 mong 이
    # 따로 생겨서, 둘 중 누가 누군지 화면에서 구분할 수 없다
    if find_account(users, user_id)[0] is not None:
        return 409, {"error": "이미 쓰고 있는 아이디입니다"}
    digest, salt = hash_password(password)
    users[user_id] = {"pw": digest, "salt": salt, "nick": user_id,
                      "avatar": "", "made": time.time()}
    save_users(users)
    return 200, {"ok": True, "id": user_id}


def check_login(user_id, password):
    """맞으면 **저장된 아이디**를, 아니면 None 을 돌려준다.

    참/거짓이 아니라 아이디를 돌려주는 이유: 대소문자를 안 가리므로 사람이 친 것과
    저장된 것이 다를 수 있다. 다른 사람들 화면에는 **처음 적은 그대로** 보여야 한다.
    """
    if not is_id(clean_id(user_id)) or not isinstance(password, str):
        return None
    key, saved = find_account(load_users(), user_id)
    if saved is None:
        return None
    digest, _ = hash_password(password, saved.get("salt", ""))
    return key if secrets.compare_digest(digest, saved.get("pw", "")) else None


@router.websocket("/ws")
async def chat_ws(socket: WebSocket):
    """채팅 한 연결. 오가는 줄을 다루는 일은 chat_ws.py 가 한다."""
    from features import chat_ws       # 지연 import - 서로를 맨 위에서 부르면 순환참조

    await socket.accept()
    await chat_ws.serve(socket)
