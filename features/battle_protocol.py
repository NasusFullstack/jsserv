"""전투 규약 - **춥채팅 레포(chat/battle_protocol.py)의 사본이다.**

원본은 저쪽이다. 한쪽만 고치면 서로 말이 안 통하므로, 고칠 일이 있으면
저쪽을 먼저 고치고 이 파일을 맞춰 넣는다. 아래 `PROTOCOL_VERSION`이 서로 다르면
클라이언트가 접속을 거부하므로, 어긋난 채로 배포돼도 조용히 이상하게 도는 일은 없다.

내용 설명은 원본 파일에 있다. 여기서는 서버가 쓰는 것만 담는다.
"""
import json
import re
import secrets

PROTOCOL_VERSION = 2

MAX_PLAYERS = 4
MAX_LINE_BYTES = 512
MAX_LINES_PER_SEC = 30
MAX_SESSION_BYTES = 4 * 1024 * 1024
MAX_NICK_LEN = 24
MIN_PLAYERS = 2
COLOR_COUNT = 9        # 마지막은 숨겨진 무지개(계속 바뀌는 색). 서버에겐 그냥 색 하나다

KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN, KEY_FIRE = 1, 2, 4, 8, 16
KEY_MASK = KEY_LEFT | KEY_RIGHT | KEY_UP | KEY_DOWN | KEY_FIRE

MAX_TICK = 2_000_000
MAX_HP = 5000             # 보고에 실린 체력이 말이 되는지 보는 상한

_ROOM_OK = re.compile(r"^[0-9a-f]{8,64}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

JOIN, WELCOME, DENY, JOINED, LEFT = "join", "welcome", "deny", "joined", "left"
START, STARTED = "start", "started"
INPUT, PEER_INPUT = "in", "peer"
HIT, PEER_HIT = "hit", "peerhit"
DEAD, PEER_DEAD = "dead", "peerdead"
BYE = "bye"


def new_room() -> str:
    return secrets.token_hex(12)


def is_room_id(value) -> bool:
    return isinstance(value, str) and bool(_ROOM_OK.match(value.lower()))


def safe_nick(nick: str) -> str:
    cleaned = _CONTROL_CHARS.sub("", nick or "").strip()
    return cleaned[:MAX_NICK_LEN] or "손님"


def encode(message: dict) -> bytes:
    line = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"" if len(line) + 1 > MAX_LINE_BYTES else line + b"\n"


def _as_int(value, low: int, high: int):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def decode(line: bytes) -> dict | None:
    if not line or len(line) > MAX_LINE_BYTES:
        return None
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(message, dict):
        return None
    checker = _CHECKERS.get(message.get("t"))
    return checker(message) if checker is not None else None


def _check_join(message):
    room = message.get("room")
    if not is_room_id(room):
        return None
    color = _as_int(message.get("color"), 0, COLOR_COUNT - 1)
    cap = _as_int(message.get("cap"), MIN_PLAYERS, MAX_PLAYERS)
    return {
        "t": JOIN,
        "room": room.lower(),
        "nick": safe_nick(message.get("nick", "")),
        "color": 0 if color is None else color,
        "cap": MAX_PLAYERS if cap is None else cap,
    }


def _check_start(_message):
    return {"t": START}


def _check_input(message):
    tick = _as_int(message.get("tick"), 0, MAX_TICK)
    keys = _as_int(message.get("keys"), 0, KEY_MASK)
    if tick is None or keys is None:
        return None
    return {"t": INPUT, "tick": tick, "keys": keys}


def _own_report(kind):
    """'내 배가 당했다' - 남은 체력을 같이 받는다.

    "맞았다"만 보내면 받는 쪽이 얼마나 깎을지 몰라 최대치를 깎는다. 기를 모은 정도에
    따라 데미지가 달라지므로, 약하게 맞은 배가 남의 화면에서만 죽어 유령이 됐다.
    """
    def check(message):
        by = _as_int(message.get("by"), 0, MAX_PLAYERS - 1)
        hp = _as_int(message.get("hp"), 0, MAX_HP)
        return None if by is None or hp is None else {"t": kind, "by": by, "hp": hp}
    return check


def _check_bye(_message):
    return {"t": BYE}


# 서버는 **손님이 보낼 수 있는 것만** 받는다. peer/welcome 같은 '서버가 만드는 것'을
# 손님이 보내와도 표에 없으므로 통과하지 못한다
_CHECKERS = {
    JOIN: _check_join,
    START: _check_start,
    INPUT: _check_input,
    HIT: _own_report(HIT),
    DEAD: _own_report(DEAD),
    BYE: _check_bye,
}


class RateWindow:
    def __init__(self, limit_per_sec: int = MAX_LINES_PER_SEC):
        self.limit = max(1, int(limit_per_sec))
        self._stamps = []
        self.total_bytes = 0

    def allow(self, now: float, size: int = 0) -> bool:
        self.total_bytes += max(0, int(size))
        if self.total_bytes > MAX_SESSION_BYTES:
            return False
        self._stamps = [t for t in self._stamps if now - t < 1.0]
        if len(self._stamps) >= self.limit:
            return False
        self._stamps.append(now)
        return True
