"""춥채팅 '배틀크루저 소환' 전투 중계 - jsserv에 얹힌 기능 하나.

평소에는 아무도 접속하지 않는다. 치트를 친 순간에만 붙었다가 전투가 끝나면 끊는다.

## 서버가 하는 일은 넘겨주기뿐이다
누가 어디 있는지, 누가 이겼는지 **서버는 모른다.** 조작(누른 키)을 같은 방 사람들에게
그대로 넘겨줄 뿐이고, 배의 움직임은 각자 계산한다. 그래야 서버가 가벼우면서 60fps로
움직인다(오가는 건 키를 누르고 뗄 때뿐이다).

## 지키는 것
- 방 번호를 알아야 들어온다. 채팅으로만 돌아다니므로 채널 밖 사람은 모른다
- 한 방에 4명. 5번째는 거절한다
- **자리 번호는 서버가 붙인다.** 보낸 쪽이 적어 보낸 건 아예 안 받는다
  (그래서 남의 배를 움직이거나 남이 죽었다고 대신 신고할 수 없다)
- 한 줄 길이·초당 줄 수·전체 바이트에 상한. 넘으면 끊는다
- 방이 비면 즉시 지운다. 오래된 방도 지운다(잊힌 방이 쌓이지 않게)
- 방 개수에도 상한(누가 방만 잔뜩 만드는 것 방지)
"""
import asyncio
import datetime
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from features import battle_protocol as bp

NAME = "battle"
PREFIX = "/battle"
VERSION = "1.0.0"
ABOUT = "춥채팅 배틀크루저 전투 중계"

MAX_ROOMS = 200             # 이보다 많아지면 새 방을 안 만든다
ROOM_IDLE_SEC = 30 * 60     # 아무 말 없는 방은 이만큼 뒤에 치운다

router = APIRouter(prefix=PREFIX, tags=[NAME])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Room:
    """한 판. **자리 번호와 색은 여기서만 준다**(보낸 쪽 말을 믿지 않는다)."""

    def __init__(self, room_id: str, cap: int):
        self.id = room_id
        self.cap = max(bp.MIN_PLAYERS, min(int(cap), bp.MAX_PLAYERS))
        self.seats: dict[int, dict] = {}     # 자리번호 -> {"nick":.., "color":.., "ws":..}
        self.started = False
        self.touched = time.monotonic()

    def free_seat(self) -> int:
        """비어 있는 가장 작은 자리. 없으면 -1(정원 찼음)."""
        for seat in range(self.cap):
            if seat not in self.seats:
                return seat
        return -1

    def pick_color(self, wanted: int) -> int:
        """원하는 색이 이미 쓰이고 있으면 남은 색 중 하나를 준다.

        서버가 정해주지 않으면 두 사람이 동시에 같은 색을 골랐을 때 화면에서
        누가 누군지 구분이 안 된다(대기방에서 막아도 동시에 고르면 새어 나간다).
        """
        taken = {who["color"] for who in self.seats.values()}
        if wanted not in taken:
            return wanted
        for candidate in range(bp.COLOR_COUNT):
            if candidate not in taken:
                return candidate
        return wanted

    def roster(self) -> list[dict]:
        return [{"slot": seat, "nick": who["nick"], "color": who["color"]}
                for seat, who in sorted(self.seats.items())]

    async def send_others(self, sender_seat: int, message: dict):
        """보낸 사람 빼고 모두에게. 끊긴 연결은 조용히 넘어간다(여기서 터지면 판이 멈춘다)."""
        payload = bp.encode(message)
        if not payload:
            return
        text = payload.decode("utf-8").rstrip("\n")
        for seat, who in list(self.seats.items()):
            if seat == sender_seat:
                continue
            try:
                await who["ws"].send_text(text)
            except Exception:
                pass


_rooms: dict[str, Room] = {}


def _sweep():
    """오래 조용한 방을 치운다. 방을 만들 때마다 한 번씩 훑으면 따로 돌 필요가 없다."""
    now = time.monotonic()
    for room_id, room in list(_rooms.items()):
        if not room.seats or now - room.touched > ROOM_IDLE_SEC:
            _rooms.pop(room_id, None)


@router.get("")
def status():
    return {
        "feature": NAME,
        "version": VERSION,
        "protocol": bp.PROTOCOL_VERSION,
        "about": ABOUT,
        "time": _now(),
        "ws": f"{PREFIX}/ws",
        "rooms": len(_rooms),
        "players": sum(len(r.seats) for r in _rooms.values()),
        "max_players_per_room": bp.MAX_PLAYERS,
    }


async def _deny(websocket: WebSocket, why: str):
    try:
        await websocket.send_text(bp.encode({"t": bp.DENY, "why": why}).decode().rstrip("\n"))
    except Exception:
        pass
    await websocket.close()


@router.websocket("/ws")
async def battle_ws(websocket: WebSocket):
    await websocket.accept()
    guard = bp.RateWindow()
    room: Room | None = None
    seat = -1

    try:
        # ---- 먼저 '어느 방에 들어갈지'부터 말해야 한다 ----
        first = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        message = bp.decode(first.encode("utf-8"))
        if not message or message["t"] != bp.JOIN:
            await _deny(websocket, "방 번호를 먼저 보내세요")
            return

        room_id = message["room"]
        room = _rooms.get(room_id)
        if room is None:
            _sweep()
            if len(_rooms) >= MAX_ROOMS:
                await _deny(websocket, "지금은 방을 더 만들 수 없습니다")
                return
            # **정원은 방을 처음 연 사람만 정한다.** 나중에 들어온 사람이 적어 보낸
            # 값으로 정원이 바뀌면, 먼저 온 사람이 튕겨나가거나 정원이 늘어난다
            room = _rooms[room_id] = Room(room_id, message["cap"])

        if room.started:
            await _deny(websocket, "이미 시작된 전투입니다")
            return

        seat = room.free_seat()
        if seat < 0:
            await _deny(websocket, f"정원({room.cap}명)이 찼습니다")
            return

        nick = message["nick"]
        color = room.pick_color(message["color"])
        # 자리에 앉히기 **전에** 지금 있는 사람 목록을 뜬다(자기 자신이 안 끼게)
        others = room.roster()
        room.seats[seat] = {"nick": nick, "color": color, "ws": websocket}
        room.touched = time.monotonic()

        await websocket.send_text(bp.encode({
            "t": bp.WELCOME, "slot": seat, "tick": 0, "cap": room.cap,
            "color": color, "players": others, "started": room.started,
        }).decode().rstrip("\n"))
        await room.send_others(
            seat, {"t": bp.JOINED, "slot": seat, "nick": nick, "color": color})

        # ---- 이제부터는 넘겨주기만 ----
        while True:
            raw = await websocket.receive_text()
            data = raw.encode("utf-8")
            if not guard.allow(time.monotonic(), len(data)):
                await _deny(websocket, "너무 빠르게 보내고 있습니다")
                return
            message = bp.decode(data)
            if message is None:
                continue                      # 모르는 값은 조용히 버린다(끊지는 않는다)

            kind = message["t"]
            room.touched = time.monotonic()
            if kind == bp.START:
                # 시작은 **방을 연 사람(0번 자리)만** 할 수 있다. 손님이 눌러도 무시한다 -
                # 아직 고르는 중인 사람을 남이 전투로 끌고 들어갈 수 없게
                if seat == 0 and not room.started and len(room.seats) >= bp.MIN_PLAYERS:
                    room.started = True
                    await room.send_others(-1, {"t": bp.STARTED})
            elif kind == bp.INPUT:
                # **자리 번호는 여기서 붙인다** - 보낸 쪽 말을 믿지 않는다
                await room.send_others(seat, {
                    "t": bp.PEER_INPUT, "slot": seat,
                    "tick": message["tick"], "keys": message["keys"],
                })
            elif kind == bp.HIT:
                await room.send_others(seat, {
                    "t": bp.PEER_HIT, "slot": seat, "by": message["by"]})
            elif kind == bp.DEAD:
                await room.send_others(seat, {
                    "t": bp.PEER_DEAD, "slot": seat, "by": message["by"]})
            elif kind == bp.BYE:
                return

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        if room is not None and seat >= 0 and room.seats.get(seat, {}).get("ws") is websocket:
            room.seats.pop(seat, None)
            await room.send_others(seat, {"t": bp.LEFT, "slot": seat})
            if not room.seats:
                _rooms.pop(room.id, None)
