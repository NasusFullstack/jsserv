"""포트폴리오 사이트 - jsserv에 얹힌 기능 하나.

만든 작품(게임·앱·도구…)을 모아 보여주고, 방문 수를 세고, 주인이 열쇠로 관리하는 사이트.
**다른 기능을 모른다.** 서버에 무엇이 올라와 있는지는 app.py 가 configure 로 알려 준다.

## 층
    config.py    자리·한도·열쇠 지문 (숫자는 여기만)
    store.py     저장 - 작품 목록·설정 JSON, 그림·다운로드·웹 빌드 파일
    stats.py     통계 - 방문·플레이·다운로드 (SQLite, IP 는 저장 안 함)
    auth.py      열쇠 - 관리 기능 잠금
    releases.py  바깥 연결 - GitHub 최신 릴리스 (작품에 저장소를 적어 두면 버전·다운로드가 따라 바뀜)
    service.py   규칙 - 올바른 값인지, 무엇을 방문으로 세는지, 밖에 무엇을 보이는지 (HTTP·디스크 모름)
    routes.py    주소 - HTTP 를 받아 위 층에 넘김 (주소 목록은 그 파일 맨 위)
    ../../web/   화면 - HTML·CSS·JS (공개 저장소에 있어도 되는 것만)

아래 층은 위 층을 모른다: routes → service·store·stats·auth·releases → config.

## 데이터 자리
서버의 영구 보존 폴더 `/data/jsserv/site` (없으면 `~/.jsserv/site`, 환경 변수 `JSSERV_SITE_DIR` 이 이김).
배포해도 지워지지 않는다.
"""
from .routes import TrackMiddleware, configure, home_page, router, wants_page  # noqa: F401

NAME = "site"
PREFIX = ""
VERSION = "1.0.0"
ABOUT = "포트폴리오 사이트 (작품·방문 통계·관리)"
