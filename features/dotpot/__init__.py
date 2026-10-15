"""화분키우기(데스크톱 게임) 서버 - jsserv에 얹힌 기능 하나.

씨앗 꾸러미·화분 뽑기권 개수를 서버가 갖고, 뽑기 결과도 서버가 정한다(조작·중복 방지).
주인은 관리 화면에서 이벤트 재화를 모두에게 또는 고른 설치본에게 뿌리고, 버그·조작 의심 설치본이나
컴퓨터를 사유와 함께 차단·해제한다. 설치본은 무작위 번호(이름·계정 없음), 컴퓨터는 되돌릴 수 없는 지문.

## 층
    config.py   자리·한도·확률 (숫자는 여기만, 게임 data.gd 와 같게)
    store.py    저장 - SQLite (설치본·씨앗·화분·뽑기·이벤트·지급·장부·거절·차단)
    rules.py    규칙 - 뽑기 결과 정하기
    routes.py   주소 - 게임용·관리용
    ../../web/static/js/admin/dotpot.js  관리 화면

## 데이터 자리
`/data/jsserv/dotpot/dotpot.sqlite3` (없으면 `~/.jsserv/dotpot`, 환경 변수 `JSSERV_DOTPOT_DIR` 이 이김).
"""
from .routes import router  # noqa: F401

NAME = "dotpot"
PREFIX = "/dotpot"
VERSION = "1.0.0"
ABOUT = "화분키우기 게임 서버 (꾸러미·뽑기·이벤트·차단)"
