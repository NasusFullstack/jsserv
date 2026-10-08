"""포트폴리오 사이트 - 열쇠 없이는 못 고치는가, 방문을 제대로 세는가, 서버 파일 밖으로 못 나가는가.

이 기능의 값은 넷이다: **주인(열쇠)만 고칠 수 있는가**, **방문·플레이·다운로드를 하루 한 번씩 세고
IP 는 남기지 않는가**, **올린 그림·파일·웹 빌드가 주소 하나로 그대로 나오는가**, 그리고
**경로를 꾸며도 서버의 다른 파일을 빼 가거나 덮어쓸 수 없는가.**
GitHub 는 부르지 않는다(가짜 릴리스를 끼운다).
"""
import hashlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile

WORK = tempfile.mkdtemp(prefix="jsserv_site_")
TOKEN = "test-token-123"
os.environ["JSSERV_SITE_DIR"] = os.path.join(WORK, "site")
os.environ["JSSERV_GAME_DIR"] = os.path.join(WORK, "game")
os.environ["JSSERV_GAME_TOKEN_SHA256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
os.environ.pop("JSSERV_ADMIN_TOKEN_SHA256", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features.site import releases  # noqa: E402

client = TestClient(app)
checks = []
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130", "Accept": "text/html,application/xhtml+xml"}
KEY = {"X-Admin-Key": TOKEN}


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def png(w=64, h=40):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 50, 90)).save(buf, "PNG")
    return buf.getvalue()


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def visit(path="/", ip="1.1.1.1", ua=None, **extra):
    headers = dict(BROWSER, **{"X-Forwarded-For": ip})
    if ua:
        headers["User-Agent"] = ua
    headers.update(extra)
    return client.get(path, headers=headers, follow_redirects=False)


def today():
    return client.get("/api/overview").json()["stats"]["today"]


r = visit("/w/chupchat", ip="1.0.0.1")
check("처음 받은 요청이 작품 주소여도 열린다(기본 작품을 먼저 깐다)", r.status_code == 200, r.status_code)

# 가짜 GitHub 릴리스
releases.fetch = lambda repo: {
    "tag": "v2.7.1", "name": "", "url": "https://github.com/%s/releases/tag/v2.7.1" % repo, "published": "2026-10-01T00:00:00Z",
    "assets": [{"name": "ChupChat.apk", "size": 1234, "url": "https://github.com/%s/releases/download/v2.7.1/ChupChat.apk" % repo}],
}

# ---- 첫 화면 ----
r = client.get("/")
check("프로그램에게는 / 가 그대로 JSON", r.headers["content-type"].startswith("application/json") and "features" in r.json(), r.text[:80])
check("기능 목록에 site 가 있다", any(f["name"] == "site" for f in r.json()["features"]), r.json())
r = visit("/")
check("브라우저에게는 / 가 첫 화면", r.status_code == 200 and "text/html" in r.headers["content-type"], r.status_code)
check("첫 화면 빈칸({{…}})이 다 채워진다", "{{" not in r.text and "NasusFullstack" in r.text, r.text[:200])
check("첫 화면에 보안 헤더", "default-src 'self'" in r.headers.get("content-security-policy", ""), r.headers)
check("주소 목록(openapi.json)은 안 보인다", client.get("/openapi.json").status_code == 404)
check("robots.txt 가 관리 화면을 막는다", "Disallow: /admin" in client.get("/robots.txt").text)
check("관리 화면 페이지는 열리고 검색엔진엔 안 뜬다", client.get("/admin").status_code == 200 and client.get("/admin").headers.get("x-robots-tag") == "noindex")

o = client.get("/api/overview").json()
slugs = [w["slug"] for w in o["works"]]
check("처음엔 기본 작품 둘이 깔린다", slugs == ["danmak", "chupchat"], slugs)
chup = next(w for w in o["works"] if w["slug"] == "chupchat")
check("GitHub 릴리스가 버전·다운로드로 나온다",
      chup["version"] == "v2.7.1" and chup["release"]["assets"][0]["url"] == "/dl/chupchat/a/ChupChat.apk", chup.get("release"))

# ---- 방문 세기 ----
before = today()
visit("/", ip="2.2.2.2")
visit("/", ip="2.2.2.2")
visit("/", ip="3.3.3.3")
after = today()
check("같은 사람은 하루 한 번, 페이지뷰는 매번", after["visitors"] - before["visitors"] == 2 and after["views"] - before["views"] == 3, (before, after))
visit("/", ip="4.4.4.4", ua="Googlebot/2.1")
visit("/", ip="5.5.5.5", ua="curl/8.0")
check("검색 로봇·curl 은 안 센다", today()["visitors"] == after["visitors"], today())
client.get("/", headers={"X-Forwarded-For": "6.6.6.6", "User-Agent": "Mozilla/5.0"})   # JSON 요청
check("JSON 으로 물어본 것은 방문이 아니다", today()["visitors"] == after["visitors"], today())
db = sqlite3.connect(os.path.join(WORK, "site", "stats.sqlite3"))
dump = "\n".join(str(row) for t in ("daily", "seen", "refs", "meta") for row in db.execute("SELECT * FROM %s" % t))
check("통계에 IP 가 남지 않는다", "2.2.2.2" not in dump and "3.3.3.3" not in dump, dump[:200])
visit("/", ip="7.7.7.7", Referer="https://www.google.com/search?q=x")
check("타고 온 사이트가 남는다(www 뗌)", ("google.com", 1) in list(db.execute("SELECT host, n FROM refs")))

# ---- 열쇠 ----
r = client.put("/api/admin/works/new-one", json={"title": "x"})
check("열쇠 없이는 작품을 못 만든다", r.status_code == 403, r.status_code)
r = client.put("/api/admin/works/new-one", json={"title": "x"}, headers={"X-Admin-Key": "wrong"})
check("틀린 열쇠로도 못 만든다", r.status_code == 403, r.status_code)
check("열쇠 없이는 관리 통계도 못 본다", client.get("/api/admin/overview").status_code == 403)
for _ in range(20):
    client.get("/api/admin/overview", headers={"X-Admin-Key": "nope", "X-Forwarded-For": "9.9.9.9"})
r = client.get("/api/admin/overview", headers={"X-Admin-Key": TOKEN, "X-Forwarded-For": "9.9.9.9"})
check("20번 틀린 주소는 맞는 열쇠도 잠시 막힌다", r.status_code == 429, r.status_code)
r = client.get("/api/admin/overview", headers=KEY)
check("다른 주소의 맞는 열쇠는 된다", r.status_code == 200 and "stats" in r.json(), r.status_code)

# ---- 작품 고치기 ----
bad = [
    ("Bad_Slug", {"title": "x"}, "주소 이름에 대문자"),
    ("ok-slug", {"title": ""}, "제목 없음"),
    ("ok-slug", {"title": "x", "source": "javascript:alert(1)"}, "javascript: 주소"),
    ("ok-slug", {"title": "x", "play_url": "//evil.com/x"}, "// 로 시작하는 주소"),
    ("ok-slug", {"title": "x", "accent": "red"}, "색 꼴이 아님"),
    ("ok-slug", {"title": "x", "release": "not a repo"}, "릴리스 꼴이 아님"),
    ("ok-slug", {"title": "x" * 61}, "제목 61자"),
]
for slug, body, why in bad:
    r = client.put("/api/admin/works/" + slug, json=body, headers=KEY)
    check("잘못된 값은 거절: " + why, r.status_code == 400, (r.status_code, r.text))
r = client.put("/api/admin/works/my-game", headers=KEY, json={
    "title": "내 게임", "kind": "게임", "tagline": "시험", "tags": ["a", "b"], "order": 5,
    "release": "https://github.com/NasusFullstack/chat/releases"})
check("작품을 만든다", r.status_code == 200 and r.json()["work"]["title"] == "내 게임", r.text)
check("GitHub 주소를 통째로 넣어도 주인/저장소로 줄인다", r.json()["work"]["release_repo"] == "NasusFullstack/chat", r.json()["work"])
check("만든 작품이 첫 화면에 나온다", "my-game" in [w["slug"] for w in client.get("/api/overview").json()["works"]])
client.put("/api/admin/works/my-game", headers=KEY, json={"title": "내 게임", "hidden": True})
check("숨긴 작품은 첫 화면에 안 나온다", "my-game" not in [w["slug"] for w in client.get("/api/overview").json()["works"]])
check("숨긴 작품도 관리 화면엔 나온다", "my-game" in [w["slug"] for w in client.get("/api/admin/overview", headers=KEY).json()["works"]])
check("숨긴 작품 주소(/w/)는 첫 화면으로 돌려보낸다", visit("/w/my-game").status_code == 307)
client.put("/api/admin/works/my-game", headers=KEY, json={"title": "내 게임", "tagline": "링크 미리보기", "hidden": False})
r = visit("/w/my-game")
check("작품 주소(/w/)는 그 작품 제목이 미리보기로", r.status_code == 200 and "내 게임 · NasusFullstack" in r.text and "링크 미리보기" in r.text, r.text[:300])

# ---- 그림 ----
r = client.post("/api/admin/works/my-game/cover", content=b"not an image", headers=KEY)
check("그림이 아닌 것은 거절(확장자 말고 내용으로)", r.status_code == 400, r.status_code)
r = client.post("/api/admin/works/my-game/cover", content=png(3000, 1000), headers=KEY)
cover = r.json()["work"]["cover"]
check("대표 그림이 WebP 로 줄어 올라간다", r.status_code == 200 and cover.endswith(".webp"), r.text)
r = client.get(cover)
check("대표 그림이 열린다(오래 캐시)", r.status_code == 200 and r.headers["content-type"] == "image/webp" and "immutable" in r.headers["cache-control"], r.headers)
from PIL import Image  # noqa: E402
check("긴 변이 1920 으로 줄었다", max(Image.open(io.BytesIO(r.content)).size) == 1920, Image.open(io.BytesIO(r.content)).size)
r2 = client.post("/api/admin/works/my-game/cover", content=png(), headers=KEY)
check("새 그림을 올리면 옛 그림은 지운다", client.get(cover).status_code == 404 and r2.json()["work"]["cover"] != cover)
for _ in range(8):
    client.post("/api/admin/works/my-game/shots", content=png(), headers=KEY)
r = client.post("/api/admin/works/my-game/shots", content=png(), headers=KEY)
check("스크린샷은 8장까지", r.status_code == 400, r.status_code)
shots = client.get("/api/admin/overview", headers=KEY).json()["works"]
shots = next(w for w in shots if w["slug"] == "my-game")["shots"]
name = shots[0].split("/")[-1]
r = client.delete("/api/admin/works/my-game/shots/" + name, headers=KEY)
check("스크린샷 하나를 지운다", r.status_code == 200 and len(r.json()["work"]["shots"]) == 7, r.text[:100])

# ---- 다운로드 ----
r = client.post("/api/admin/works/my-game/download?name=evil.php", content=b"x", headers=KEY)
check("정해 둔 종류가 아닌 파일은 거절", r.status_code == 400, r.status_code)
r = client.post("/api/admin/works/my-game/download?name=" + "..%2F..%2Fworks.zip", content=b"PK-zip", headers=KEY)
check("파일 이름의 경로는 떼고 받는다", r.status_code == 200 and r.json()["work"]["download"]["name"] == "works.zip", r.text)
r = client.post("/api/admin/works/my-game/download?name=" + "내%20게임%20v1.zip", content=b"PK-zip-2", headers=KEY)
check("한글 파일 이름도 된다(새로 올리면 바뀜)", r.status_code == 200 and r.json()["work"]["download"]["name"] == "내 게임 v1.zip", r.text)
check("옛 다운로드 파일은 남지 않는다", os.listdir(os.path.join(WORK, "site", "downloads", "my-game")) == ["내 게임 v1.zip"],
      os.listdir(os.path.join(WORK, "site", "downloads", "my-game")))
before = today()["downloads"]
r = visit("/dl/my-game", ip="8.8.8.8")
check("다운로드가 받아진다(파일 이름 그대로)", r.content == b"PK-zip-2" and "filename*=utf-8''" in r.headers.get("content-disposition", ""), r.headers.get("content-disposition"))
visit("/dl/my-game", ip="8.8.8.8")
visit("/dl/my-game", ip="8.8.4.4")
check("다운로드는 하루 한 사람 한 번", today()["downloads"] - before == 2, (before, today()))
r = visit("/dl/chupchat/a/ChupChat.apk", ip="8.8.8.8")
check("GitHub 릴리스 파일은 세고 나서 넘겨준다", r.status_code == 302 and r.headers["location"].startswith("https://github.com/NasusFullstack/chat/releases/download/"), r.headers)
check("릴리스에 없는 파일 이름은 404", visit("/dl/chupchat/a/evil.exe").status_code == 404)

# ---- 웹 빌드 ----
r = client.post("/api/admin/works/my-game/build", content=make_zip({"../evil.html": "x", "index.html": "x"}), headers=KEY)
check("../ 경로가 섞인 zip 은 통째로 거절", r.status_code == 400, r.status_code)
r = client.post("/api/admin/works/my-game/build", content=make_zip({"index.html": "x", "run.exe": "MZ"}), headers=KEY)
check("정해 둔 종류가 아닌 파일이 있으면 거절", r.status_code == 400, r.status_code)
r = client.post("/api/admin/works/my-game/build", content=make_zip({"a.html": "x"}), headers=KEY)
check("index.html 이 없으면 거절", r.status_code == 400, r.status_code)
check("zip 이 아니면 거절", client.post("/api/admin/works/my-game/build", content=b"nope", headers=KEY).status_code == 400)
r = client.post("/api/admin/works/my-game/build", headers=KEY, content=make_zip({
    "MyGame/index.html": "<title>my</title>PLAY", "MyGame/js/a.js": "1", "MyGame/README.md": "x", "MyGame/.DS_Store": "x"}))
check("폴더 하나에 싸인 zip 은 벗겨서 올린다(설명서·숨김 파일은 뺌)", r.status_code == 200 and r.json()["work"]["build"]["files"] == 2, r.text)
check("웹 빌드가 /p/<작품>/ 에서 열린다", "PLAY" in client.get("/p/my-game/").text and client.get("/p/my-game/js/a.js").status_code == 200)
check("/p/<작품> 은 / 를 붙여 보낸다", client.get("/p/my-game", follow_redirects=False).status_code == 307)
check("빌드를 올리면 플레이 버튼이 /p/ 로", next(w for w in client.get("/api/overview").json()["works"] if w["slug"] == "my-game")["play"] == "/p/my-game/")
before = today()["plays"]
visit("/p/my-game/", ip="10.0.0.1")
visit("/p/my-game/", ip="10.0.0.1")
visit("/p/my-game/js/a.js", ip="10.0.0.2")
check("플레이는 하루 한 사람 한 번, 스크립트 요청은 안 셈", today()["plays"] - before == 1, (before, today()))
os.makedirs(os.environ["JSSERV_GAME_DIR"], exist_ok=True)
open(os.path.join(os.environ["JSSERV_GAME_DIR"], "index.html"), "w").write("game")
before = today()["plays"]
visit("/game/", ip="10.0.0.3")
check("따로 적어 둔 플레이 주소(/game/)도 플레이로 센다", today()["plays"] - before == 1, (before, today()))

# ---- 밖으로 못 나간다 ----
for path in ("/media/my-game/..%2F..%2Fworks.json", "/media/my-game/../../works.json", "/static/../features/site/config.py",
             "/static/..%2F..%2Fapp.py", "/p/my-game/..%2F..%2Fworks.json", "/p/my-game/../../stats.sqlite3",
             "/dl/..%2Fworks.json", "/media/my-game/cover.part"):
    r = client.get(path)
    check("경로 꾸미기 막힘: " + path, r.status_code in (404, 307) and b'"works"' not in r.content and b"ADMIN_SHA256" not in r.content
          and b"SQLite" not in r.content, (r.status_code, r.content[:60]))

# ---- 설정 ----
r = client.put("/api/admin/settings", headers=KEY, json={"name": "", "email": "x"})
check("설정: 이름 없음은 거절", r.status_code == 400, r.status_code)
r = client.put("/api/admin/settings", headers=KEY, json={"name": "<b>내 작업실</b>", "headline": "만든 것들", "roles": ["GAME"], "email": "a@b.c", "github": ""})
check("설정을 바꾼다", r.status_code == 200, r.text)
page = visit("/", ip="11.0.0.1").text
check("바꾼 이름이 첫 화면에, 태그는 글자로만", "&lt;b&gt;내 작업실&lt;/b&gt;" in page and "<b>내 작업실</b>" not in page, page[:300])

# ---- 지우기 ----
r = client.delete("/api/admin/works/my-game", headers=KEY)
check("작품을 지운다", r.status_code == 200, r.status_code)
check("지우면 그림·다운로드·빌드도 같이 사라진다",
      not any(os.path.exists(os.path.join(WORK, "site", d, "my-game")) for d in ("media", "downloads", "builds")))
check("지운 작품의 다운로드는 404", client.get("/dl/my-game").status_code == 404)

shutil.rmtree(WORK, ignore_errors=True)
bad = [c for c in checks if not c[1]]
for name, passed, detail in checks:
    print(("통과 " if passed else "실패 ") + name + ("" if passed else "  (%s)" % (detail,)))
print("%d개 중 %d개 통과" % (len(checks), len(checks) - len(bad)))
sys.exit(1 if bad else 0)
