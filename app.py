"""jsserv - 여러 기능을 함께 얹는 서버.

**이 서버는 무엇 하나의 전용이 아니다.** 기능마다 자기 경로를 가지고 들어오고, 루트는
"여기 무엇이 올라와 있는가"만 알려준다. 그래서 기능을 하나 더 붙일 때 이 파일을 거의
안 건드린다 - `features/` 에 파일 하나 만들고 아래 표에 한 줄 추가하면 끝이다.

    /                무엇이 올라와 있는지
    /health          살아있는지
    /battle/...      춥채팅 배틀크루저 전투 중계 (features/battle.py)
    /chat/...        춥채팅 서버 채팅 - IRC 없이 (features/chat.py)
    /files/...       춥채팅 파일·사진 올리기 (features/files.py)
    /logs/...        춥채팅 채팅 기록 하루치 (features/logs.py)
    /profiles/...    춥채팅 참여자 프로필 (features/profiles.py)

실행 방법을 모르므로 두 가지를 다 받아둔다:
    uvicorn app:app --host 0.0.0.0 --port 8000
    python app.py
"""
import datetime
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from features import battle, chat, files, logs, profiles

SERVER_NAME = "jsserv"
SERVER_VERSION = "0.1.0"

# 무엇이 올라와 있는가 - 기능을 추가하면 여기 한 줄만 늘어난다
FEATURES = (battle, chat, files, logs, profiles)

app = FastAPI(title=SERVER_NAME, version=SERVER_VERSION, docs_url=None, redoc_url=None)

for feature in FEATURES:
    app.include_router(feature.router)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@app.get("/")
def index():
    """여기 무엇이 올라와 있는지. 기능 목록은 각 기능이 스스로 알려준다."""
    return JSONResponse({
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "time": now(),
        "features": [
            {"name": f.NAME, "prefix": f.PREFIX, "about": f.ABOUT, "version": f.VERSION}
            for f in FEATURES
        ],
    })


@app.get("/health")
def health():
    return {"ok": True, "time": now()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
