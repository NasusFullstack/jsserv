"""춥채팅 전투 중계 서버 - 우선 '되는지 확인'만 하는 첫 판.

지금 이 파일이 답해야 하는 질문은 두 개뿐이다.

1. 배포가 실제로 도는가          -> GET /        (상태를 JSON으로)
2. WebSocket이 nginx를 통과하는가 -> WS  /ws      (받은 걸 그대로 돌려줌)

2번이 핵심이다. nginx가 `proxy_pass`만 있고 Upgrade 헤더를 안 넘기면 WebSocket이
막히는데, 그러면 실시간 전투를 다른 방법으로 짜야 한다. 그래서 막혔는지 통과했는지
**한눈에 알 수 있게** /ws 가 받은 헤더를 그대로 되돌려준다.

실행 방법을 모르므로 두 가지를 다 받아둔다:
    uvicorn app:app --host 0.0.0.0 --port 8000
    python app.py
"""
import datetime
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

APP_NAME = "chupchat-battle-relay"
APP_VERSION = "0.1.0"          # 아직 중계는 없음 - 연결 확인용

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@app.get("/")
def root():
    """배포가 실제로 돌고 있는지 확인하는 자리."""
    return JSONResponse({
        "app": APP_NAME,
        "version": APP_VERSION,
        "time": _now(),
        "ws": "/ws",
        "note": "WebSocket이 되는지 확인하려면 /ws 로 접속해 보세요.",
    })


@app.get("/health")
def health():
    return {"ok": True, "time": _now()}


@app.websocket("/ws")
async def ws_echo(websocket: WebSocket):
    """받은 글을 그대로 돌려준다.

    붙는 순간 한 줄을 먼저 보내서, **연결만 되고 데이터가 안 오는 상태**와
    **애초에 연결이 안 된 상태**를 구분할 수 있게 한다(둘 다 '안 된다'로 보이지만
    원인이 전혀 다르다).
    """
    await websocket.accept()
    client = websocket.client
    await websocket.send_json({
        "t": "hello",
        "app": APP_NAME,
        "version": APP_VERSION,
        "time": _now(),
        # nginx를 거쳐 왔는지, 어떤 헤더가 살아서 왔는지 그대로 보여준다
        "seen_headers": {
            key: value for key, value in websocket.headers.items()
            if key.lower() in ("host", "upgrade", "connection", "origin",
                               "x-forwarded-for", "x-forwarded-proto",
                               "sec-websocket-version", "user-agent")
        },
        "peer": f"{client.host}:{client.port}" if client else "",
    })
    try:
        while True:
            text = await websocket.receive_text()
            await websocket.send_json({"t": "echo", "text": text[:512], "time": _now()})
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
