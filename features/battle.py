"""춥채팅 '배틀크루저 소환' 전투 중계 - jsserv에 얹힌 기능 하나.

평소에는 아무도 접속하지 않는다. 치트를 친 순간에만 붙었다가 전투가 끝나면 끊는다.

## 지금 단계
아직 중계는 없다. **WebSocket이 nginx를 통과하는지**부터 확인한다. 이게 막혀 있으면
실시간 전투를 다른 방법으로 짜야 하므로, 여기서 판가름이 나야 다음을 설계할 수 있다.

막혔다면 nginx에 두 줄이 필요하다:

    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

`/battle/ws`는 붙는 즉시 **어떤 헤더가 살아서 왔는지** 돌려준다. '연결이 아예 안 된
것'과 '연결은 됐는데 데이터가 안 오는 것'은 둘 다 "안 된다"로 보이지만 원인이 전혀
다르기 때문이다.
"""
import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

NAME = "battle"
PREFIX = "/battle"
VERSION = "0.1.0"
ABOUT = "춥채팅 배틀크루저 전투 중계 (지금은 연결 확인만)"

# 돌려줄 헤더 - 진단에 쓸 것만 고른다(남의 요청 내용을 통째로 되비추지 않는다)
_HEADERS_OF_INTEREST = (
    "host", "upgrade", "connection", "origin", "user-agent",
    "x-forwarded-for", "x-forwarded-proto", "sec-websocket-version",
)

router = APIRouter(prefix=PREFIX, tags=[NAME])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@router.get("")
def status():
    return {
        "feature": NAME,
        "version": VERSION,
        "about": ABOUT,
        "time": _now(),
        "ws": f"{PREFIX}/ws",
        "note": "WebSocket이 되는지 확인하려면 /battle/ws 로 접속해 보세요.",
    }


@router.websocket("/ws")
async def ws_echo(websocket: WebSocket):
    """받은 글을 그대로 돌려준다(연결 확인용)."""
    await websocket.accept()
    client = websocket.client
    await websocket.send_json({
        "t": "hello",
        "feature": NAME,
        "version": VERSION,
        "time": _now(),
        "seen_headers": {
            key: value for key, value in websocket.headers.items()
            if key.lower() in _HEADERS_OF_INTEREST
        },
        "peer": f"{client.host}:{client.port}" if client else "",
    })
    try:
        while True:
            text = await websocket.receive_text()
            await websocket.send_json({"t": "echo", "text": text[:512], "time": _now()})
    except WebSocketDisconnect:
        pass
