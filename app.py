"""jsserv - 여러 기능을 함께 얹는 서버.

**이 서버는 무엇 하나의 전용이 아니다.** 기능마다 자기 경로를 가지고 들어오고, 루트는
"여기 무엇이 올라와 있는가"만 알려준다. 그래서 기능을 하나 더 붙일 때 이 파일을 거의
안 건드린다 - `features/` 에 파일 하나 만들고 아래 표에 한 줄 추가하면 끝이다.

    /                브라우저면 포트폴리오 첫 화면, 프로그램이면 무엇이 올라와 있는지(JSON)
    /health          살아있는지
    /w/ /p/ /dl/ /admin /api/…   포트폴리오 사이트 (features/site/)
    /battle/...      춥채팅 배틀크루저 전투 중계 (features/battle.py)
    /chat/...        춥채팅 서버 채팅 - **지금은 꺼둠**(아래 FEATURES 참고)
    /files/...       춥채팅 파일·사진 올리기 (features/files.py)
    /logs/...        춥채팅 채팅 기록 하루치 (features/logs.py)
    /profiles/...    춥채팅 참여자 프로필 (features/profiles.py)
    /game/...        웹 게임 탄막게임 (features/game.py, 파일은 /data/jsserv/game)

실행 방법을 모르므로 두 가지를 다 받아둔다:
    uvicorn app:app --host 0.0.0.0 --port 8000
    python app.py
"""
import datetime
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# chat 은 지금 안 얹지만 **import 는 남겨둔다** - 되살릴 때 FEATURES 한 곳만
# 고치면 되게(두 군데를 고쳐야 하면 한쪽을 빠뜨린다)
from features import battle, chat, files, game, logs, profiles, site  # noqa: F401

SERVER_NAME = "jsserv"
SERVER_VERSION = "0.2.0"

# 무엇이 올라와 있는가 - 기능을 추가하면 여기 한 줄만 늘어난다.
#
# **서버 채팅(chat)은 지금 꺼져 있다**(2026-10-06, 사용자 요청 - 당분간 안 쓰므로
# 메모리를 비워둔다). 코드는 그대로 있고 얹지만 않는다.
#
#   되살리는 법: 아래 줄에 `chat,` 을 도로 넣고 올리면 끝이다. 계정과 방은
#   `~/.jsserv/chat` 에 그대로 있다(chat 1.3.0 부터 저장소 밖에 쌓는다).
#
#   끄면 같이 사라지는 것: /chat 과 /chat/ws. 춥채팅 앱의 "춥채팅 서버" 쪽이
#   안 붙는다 - IRC 쪽은 우리 서버를 안 거치므로 그대로 된다. 파일·프로필·기록·
#   전투는 따로 돌아가므로 영향 없다.
FEATURES = (battle, files, logs, profiles, game, site)

# 설명서 화면도 주소 목록(openapi.json)도 밖에 안 보인다 - 관리 주소를 굳이 알려줄 이유가 없다
app = FastAPI(title=SERVER_NAME, version=SERVER_VERSION, docs_url=None, redoc_url=None, openapi_url=None)

for feature in FEATURES:
    app.include_router(feature.router)

# 사이트가 방문·플레이·다운로드를 센다(응답이 나간 뒤에). 무엇이 올라와 있는지는 여기서 알려 준다.
app.add_middleware(site.TrackMiddleware)
site.configure(SERVER_NAME, SERVER_VERSION, lambda: _feature_list())


def _feature_list():
    return [{"name": f.NAME, "prefix": f.PREFIX, "about": f.ABOUT, "version": f.VERSION} for f in FEATURES]


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@app.get("/")
def index(request: Request):
    """브라우저(사람)에게는 포트폴리오 첫 화면, 프로그램에게는 여기 무엇이 올라와 있는지(JSON)."""
    if site.wants_page(request):
        return site.home_page()
    return JSONResponse({
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "time": now(),
        "features": _feature_list(),
    })


@app.get("/health")
def health():
    return {"ok": True, "time": now()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
