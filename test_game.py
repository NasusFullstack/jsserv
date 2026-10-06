"""웹 게임 올려두기 - 열쇠 있는 사람만 올리고, 올린 게임이 열리고, 게임 폴더 밖은 안 나가는가.

이 기능의 값은 셋이다: **열쇠 없이는 못 올리는가**, **올린 게임이 주소 하나로 그대로 열리는가**,
그리고 **경로를 꾸며도 서버의 다른 파일을 빼 가거나 덮어쓸 수 없는가.**
"""
import hashlib
import io
import os
import shutil
import sys
import tempfile
import zipfile

WORK = tempfile.mkdtemp(prefix="jsserv_game_")
TOKEN = "test-token-123"
os.environ["JSSERV_GAME_DIR"] = os.path.join(WORK, "game")
os.environ["JSSERV_GAME_TOKEN_SHA256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)
checks = []


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


GAME = {
    "index.html": '<title>탄막게임</title><script src="js/game.js"></script>',
    "js/game.js": "const G = {};",
    "assets/chars/idle.png": b"\x89PNG\r\n\x1a\n" + b"0" * 32,
}


def upload(data, token=TOKEN):
    return client.post("/game/upload", content=data, headers={"X-Game-Token": token} if token else {})


r = client.get("/game/")
check("올리기 전에는 404", r.status_code == 404, r.status_code)

r = upload(make_zip(GAME), token=None)
check("열쇠 없이는 못 올린다", r.status_code == 403, r.status_code)
r = upload(make_zip(GAME), token="wrong")
check("틀린 열쇠로는 못 올린다", r.status_code == 403, r.status_code)

r = upload(make_zip(dict(GAME, **{"../evil.js": "x"})))
check("../ 경로가 섞인 zip 은 통째로 거절", r.status_code == 400, r.status_code)
r = upload(make_zip(dict(GAME, **{"run.py": "print(1)"})))
check("정해 둔 종류가 아닌 파일이 섞이면 거절", r.status_code == 400, r.status_code)
r = upload(make_zip({"js/game.js": "x"}))
check("index.html 이 없으면 거절", r.status_code == 400, r.status_code)
r = upload(b"not a zip")
check("zip 이 아니면 거절", r.status_code == 400, r.status_code)
check("거절된 올리기는 아무것도 안 남긴다", not os.path.exists(os.environ["JSSERV_GAME_DIR"]), os.listdir(WORK))

r = upload(make_zip(GAME))
check("열쇠가 맞으면 올라간다", r.status_code == 200 and r.json().get("files") == 3, r.text)

r = client.get("/game", follow_redirects=False)
check("/game 은 /game/ 로 보낸다", r.status_code in (301, 302, 307, 308) and r.headers.get("location", "").endswith("/game/"), r.status_code)
r = client.get("/game/")
check("첫 화면이 열린다", r.status_code == 200 and "탄막게임" in r.text and r.headers["content-type"].startswith("text/html"), r.status_code)
check("HTML 은 캐시하지 않는다", r.headers.get("cache-control") == "no-cache", r.headers.get("cache-control"))
r = client.get("/game/js/game.js")
check("스크립트가 열린다", r.status_code == 200 and r.headers["content-type"].startswith("text/javascript"), r.status_code)
r = client.get("/game/assets/chars/idle.png")
check("그림이 열린다", r.status_code == 200 and r.headers["content-type"] == "image/png", r.status_code)

for bad in ("/game/../app.py", "/game/..%2Fapp.py", "/game/%2E%2E/%2E%2E/app.py", "/game/js/../../app.py"):
    r = client.get(bad)
    check("게임 폴더 밖으로 못 나간다: " + bad, r.status_code == 404 or "FastAPI" not in r.text, r.status_code)

r = upload(make_zip({"index.html": "<title>새 버전</title>"}))
r2 = client.get("/game/js/game.js")
check("다시 올리면 통째로 바뀐다(옛 파일은 사라짐)", client.get("/game/").text == "<title>새 버전</title>" and r2.status_code == 404, r2.status_code)
check("바꿔 끼우고 남은 임시 폴더가 없다", sorted(os.listdir(WORK)) == ["game"], os.listdir(WORK))

r = client.get("/")
check("루트에 game 기능이 보인다", "game" in [f["name"] for f in r.json()["features"]])

shutil.rmtree(WORK, ignore_errors=True)
bad = [c for c in checks if not c[1]]
for name, passed, detail in checks:
    print(("통과 " if passed else "실패 ") + name + ("" if passed else "  (%s)" % (detail,)))
print("%d개 중 %d개 통과" % (len(checks), len(checks) - len(bad)))
sys.exit(1 if bad else 0)
