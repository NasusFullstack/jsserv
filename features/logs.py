"""채팅 기록 하루치 - jsserv에 얹힌 기능 하나.

## 무엇을 푸는가
춥채팅은 지금까지 대화를 **자기 컴퓨터에만** 적어뒀다(history.json). 그래서 앱을 꺼둔
동안 오간 이야기는 아무 데도 남지 않는다 - 다시 켜면 그 사이가 통째로 비어 있다.
여기 하루치를 모아두고, 앱이 켜질 때 "내가 마지막으로 본 뒤로 뭐가 있었나"를 받아간다.

## 누가 적는가 - 받은 사람이 적는다
채팅을 받아본 클라이언트가 자기가 본 줄을 올린다. 서버가 채팅방에 직접 붙지 않는
방식이라 **남의 서버에 붙박이 접속을 만들지 않아도 되고**, 채팅방에 정체불명의 참여자가
하나 늘지도 않는다. 프로토콜(IRC/커스텀)이 무엇이든 똑같이 동작하는 것도 이 방식뿐이다.

대신 분명한 한계가 있다: **춥채팅을 켜둔 사람이 하나도 없는 동안** 다른 프로그램
(HexChat, 디스코드 다리)으로 오간 말은 아무도 안 올리므로 안 남는다.

여러 사람이 같은 줄을 올리므로 **같은 줄은 한 번만 남긴다**(내용 지문으로 거른다).

## 믿을 수 있는 기록이 아니다
중계 서버에는 계정이 없어서 누가 올렸는지 확인할 방법이 없다. 즉 마음먹으면 없던 말을
넣을 수 있다. 이건 **놓친 이야기를 따라잡는 편의**지 증거가 아니다 - 화면에도 "밀린
기록"이라고 따로 표시해서 지금 오가는 말과 섞이지 않게 한다.

## 방 이름은 서버에 안 알린다
방 id는 클라이언트가 (프로토콜, 호스트, 포트, 채널)을 해시해서 만든 24자다. 그래서
빌려 쓰는 서버에 우리가 어느 채널에 있는지 적히지 않고, 서버가 달라도 같은 이름의
채널(#general)이 섞이지 않는다.
"""
import hashlib
import json
import os
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

NAME = "logs"
PREFIX = "/logs"
VERSION = "1.0.0"
ABOUT = "춥채팅 채팅 기록 하루치"

# ---- 한도 (나중에 여기 숫자만 고치면 된다) ---------------------------------
LIMITS = {
    "keep_hours": 24,        # 이보다 오래된 줄은 지운다
    # 여러 사람이 올린 같은 줄로 보는 시간 차이. IRC는 각자 자기 시계로
    # 찍으므로 딱 맞을 수가 없다 - 너무 좁으면 겹쳐 보이고, 너무 넓으면
    # 연달아 한 같은 말이 하나로 뭉친다(그건 seq가 막는다)
    "same_line_seconds": 5.0,
    "room_lines": 3000,      # 한 방에 남길 수 있는 줄 수(넘으면 오래된 것부터)
    "line_bytes": 2000,      # 한 줄 최대 길이
    "post_lines": 200,       # 한 번에 올릴 수 있는 줄 수
    "daily_lines": 20000,    # 한 사람이 하루에 올릴 수 있는 줄 수
    "total_bytes": 256 * 1024 * 1024,   # 기록 전체 사용량 상한
}

STORE_DIR = os.environ.get("JSSERV_LOG_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__))), "chatlogs"))

_ROOM_OK = re.compile(r"^[0-9a-f]{24}$")

router = APIRouter(prefix=PREFIX, tags=[NAME])


# ------------------------------------------------------------------ 도구
def _room_path(room: str) -> str:
    return os.path.join(STORE_DIR, f"{room}.jsonl")


def _quota_path(key: str) -> str:
    return os.path.join(STORE_DIR, f"quota-{key}-{_today()}.txt")


def _today() -> str:
    return time.strftime("%Y%m%d", time.gmtime())


def _poster_key(request: Request) -> str:
    """누가 올렸는지 - 계정이 없으므로 주소로 센다(하루 줄 수를 세는 데만 쓴다)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")
    return hashlib.sha256(client.encode("utf-8")).hexdigest()[:16]


def _slot(line: dict) -> tuple:
    """같은 줄 후보를 모으는 칸. 실제로 같은지는 시각까지 봐야 안다(_is_same)."""
    return (line["sender"], line["text"], line.get("seq", 0))


def _is_same(one: dict, other: dict) -> bool:
    """여러 사람이 올린 이 두 줄이 **원래 같은 한 줄**인가.

    시각을 초 단위로 뭉개서 비교하면 안 된다. 받은 시각이 37.93초와 38.12초로 갈리면
    0.19초 차이인데도 다른 줄이 된다(실제로 그렇게 겹쳐 보였다). 그래서 뭉개지 않고
    **차이가 창 안에 드는가**로 본다.

    시각이 갈리는 이유는 프로토콜에 있다. 커스텀 서버는 보낸 시각을 실어 보내므로 모두
    같은 값을 받지만, IRC는 그런 게 없어서 **각자 자기 시계로 찍는다.**

    같은 사람이 같은 말을 연달아 두 번 하면("ㅋㅋ" "ㅋㅋ") 창 안에 들어 한 줄로 뭉칠 수
    있다. 그래서 올리는 쪽이 `seq`(창 안에서 몇 번째로 본 같은 말인가)를 붙인다 - 두 번
    본 사람은 0, 1을 붙이고, 한 번만 본 사람은 0을 붙이므로 서로 어긋나지 않는다.
    """
    return (_slot(one) == _slot(other)
            and abs(one["ts"] - other["ts"]) <= LIMITS["same_line_seconds"])


def fingerprint(line: dict) -> str:
    """같은 줄인지 가리는 지문(시각을 뺀 부분만). 창 비교는 _is_same이 한다."""
    raw = "|".join(str(part) for part in _slot(line))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _read(room: str) -> list[dict]:
    """한 방의 기록. 깨진 줄은 조용히 버린다(한 줄 때문에 전체를 잃지 않게)."""
    path = _room_path(room)
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                lines.append(json.loads(raw))
            except ValueError:
                continue
    return lines


def _write(room: str, lines: list[dict]):
    """통째로 다시 쓴다. 쓰다 만 파일이 남지 않게 옆에 쓰고 바꿔치기한다."""
    os.makedirs(STORE_DIR, exist_ok=True)
    path = _room_path(room)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as fp:
        for line in lines:
            fp.write(json.dumps(line, ensure_ascii=False) + "\n")
    os.replace(temp, path)


def _fresh(lines: list[dict]) -> list[dict]:
    """기한 안에 든 것만, 최근 것 위주로 상한까지."""
    cutoff = time.time() - LIMITS["keep_hours"] * 3600
    kept = [line for line in lines if line.get("ts", 0) >= cutoff]
    if len(kept) > LIMITS["room_lines"]:
        kept = kept[-LIMITS["room_lines"]:]
    return kept


def _sweep():
    """기한이 다 된 방 파일을 지운다. 전체 용량이 넘치면 오래된 방부터 통째로 비운다."""
    if not os.path.isdir(STORE_DIR):
        return
    rooms = []
    total = 0
    for name in os.listdir(STORE_DIR):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(STORE_DIR, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        room = name[:-len(".jsonl")]
        kept = _fresh(_read(room))
        if not kept:
            # 하루 넘게 아무 말도 없던 방은 파일째 지운다
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if len(kept) != len(_read(room)):
            _write(room, kept)
            try:
                stat = os.stat(path)
            except OSError:
                continue
        rooms.append((stat.st_mtime, path, stat.st_size))
        total += stat.st_size

    rooms.sort()
    while total > LIMITS["total_bytes"] and rooms:
        _, path, size = rooms.pop(0)
        try:
            os.remove(path)
            total -= size
        except OSError:
            break

    # 지난 날짜의 사용량 기록도 같이 치운다
    today = _today()
    for name in os.listdir(STORE_DIR):
        if name.startswith("quota-") and not name.endswith(f"-{today}.txt"):
            try:
                os.remove(os.path.join(STORE_DIR, name))
            except OSError:
                pass


def _used_today(key: str) -> int:
    try:
        with open(_quota_path(key), encoding="utf-8") as fp:
            return int(fp.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def _add_used(key: str, count: int):
    # **읽고 나서 연다.** "w"로 열면 그 순간 내용이 날아가므로, 열어둔 채로 읽으면
    # 항상 0이 나온다(파일 올리기 쪽에서 실제로 이 실수를 했다)
    total = _used_today(key) + count
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(_quota_path(key), "w", encoding="utf-8") as fp:
        fp.write(str(total))


def clean_line(raw) -> dict | None:
    """올라온 줄 하나를 믿을 수 있는 모양으로 다듬는다. 아니면 None."""
    if not isinstance(raw, dict):
        return None
    try:
        ts = float(raw.get("ts", 0))
    except (TypeError, ValueError):
        return None
    sender = str(raw.get("sender", ""))[:64]
    text = str(raw.get("text", ""))
    if not text or not sender:
        return None
    if len(text.encode("utf-8")) > LIMITS["line_bytes"]:
        return None
    now = time.time()
    # 미래나 아주 먼 과거는 안 받는다 - 시계가 틀어진 컴퓨터가 기록을 맨 끝이나
    # 맨 앞에 영원히 붙박아 둘 수 있다
    if ts > now + 300 or ts < now - LIMITS["keep_hours"] * 3600:
        return None
    try:
        seq = max(0, min(99, int(raw.get("seq", 0))))
    except (TypeError, ValueError):
        seq = 0
    return {"ts": ts, "sender": sender, "text": text, "seq": seq}


# ------------------------------------------------------------------ 창구
@router.get("")
def status():
    """무엇을 어디까지 받아주는지."""
    rooms = 0
    total = 0
    if os.path.isdir(STORE_DIR):
        for name in os.listdir(STORE_DIR):
            if name.endswith(".jsonl"):
                rooms += 1
                try:
                    total += os.path.getsize(os.path.join(STORE_DIR, name))
                except OSError:
                    pass
    return {"feature": NAME, "version": VERSION, "limits": dict(LIMITS),
            "rooms": rooms, "used_bytes": total}


@router.post("/{room}")
async def put_lines(room: str, request: Request):
    """받아본 줄을 올린다. 이미 있는 줄은 조용히 넘어간다."""
    if not _ROOM_OK.match(room):
        return JSONResponse({"error": "방 id가 올바르지 않습니다"}, status_code=400)
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "읽을 수 없는 내용입니다"}, status_code=400)
    raw_lines = body.get("lines") if isinstance(body, dict) else None
    if not isinstance(raw_lines, list) or not raw_lines:
        return JSONResponse({"error": "올릴 줄이 없습니다"}, status_code=400)
    if len(raw_lines) > LIMITS["post_lines"]:
        return JSONResponse({"error": "한 번에 올릴 수 있는 줄 수를 넘었습니다"},
                            status_code=413)

    key = _poster_key(request)
    if _used_today(key) + len(raw_lines) > LIMITS["daily_lines"]:
        return JSONResponse({"error": "오늘 올릴 수 있는 줄 수를 넘었습니다"},
                            status_code=429)

    _sweep()
    existing = _fresh(_read(room))
    # 같은 칸(보낸 사람·내용·몇 번째)끼리만 모아둔다 - 3000줄을 매번 훑지 않기 위해
    by_slot: dict[tuple, list[dict]] = {}
    for line in existing:
        by_slot.setdefault(_slot(line), []).append(line)

    added = 0
    for raw in raw_lines:
        line = clean_line(raw)
        if line is None:
            continue
        neighbours = by_slot.setdefault(_slot(line), [])
        if any(_is_same(line, seen) for seen in neighbours):
            continue
        neighbours.append(line)
        existing.append(line)
        added += 1

    if added:
        existing.sort(key=lambda line: line["ts"])
        _write(room, _fresh(existing))
        _add_used(key, added)
    return {"added": added, "kept": len(existing)}


@router.get("/{room}")
def get_lines(room: str, since: float = 0.0, limit: int = 0):
    """그 방의 기록. since를 주면 그보다 뒤엣것만 준다."""
    if not _ROOM_OK.match(room):
        return JSONResponse({"error": "방 id가 올바르지 않습니다"}, status_code=400)
    lines = _fresh(_read(room))
    if since:
        lines = [line for line in lines if line["ts"] > since]
    if limit and len(lines) > limit:
        lines = lines[-limit:]
    return {"lines": lines, "now": time.time()}
