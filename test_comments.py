"""작품 댓글 - 깊이 2로 늘어놓는가, 지우기는 비밀번호로만, 도배·로봇·남의 사이트에서 못 쓰는가.

이 기능의 값은 넷이다: **본댓 → 답글 두 단계로만, 답글에 단 답글은 @닉네임 으로 그 글 바로 밑에**,
**자기 글은 비밀번호로만 지우고 작성자 글은 주인만**, **도배·로봇·다른 사이트의 몰래 쓰기를 막는가**,
그리고 **비밀번호·IP 원문을 남기지 않는가.**
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile

WORK = tempfile.mkdtemp(prefix="jsserv_comments_")
TOKEN = "test-token-123"
os.environ["JSSERV_SITE_DIR"] = os.path.join(WORK, "site")
os.environ["JSSERV_GAME_DIR"] = os.path.join(WORK, "game")
os.environ["JSSERV_GAME_TOKEN_SHA256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
os.environ.pop("JSSERV_ADMIN_TOKEN_SHA256", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features.site import releases  # noqa: E402

releases.fetch = lambda repo: None     # GitHub 는 부르지 않는다
client = TestClient(app)
checks = []
KEY = {"X-Admin-Key": TOKEN}
URL = "/api/works/danmak/comments"


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def post(nick="손님", body="좋아요", pw="1234", parent=None, ip="1.1.1.1", slug="danmak", **extra):
    data = dict({"nick": nick, "body": body, "password": pw, "parent": parent}, **extra)
    return client.post("/api/works/%s/comments" % slug, json=data, headers={"X-Forwarded-For": ip})


def flat(threads):
    """[(본댓 닉네임, [답글 '(@멘션)닉네임' …])]"""
    return [(t.get("nick", "삭제"), [("@%s " % r["mention"] if r.get("mention") else "") + r.get("nick", "삭제") for r in t["replies"]])
            for t in threads]


client.get("/api/overview")   # 기본 작품 깔기

r = client.get(URL)
check("처음엔 댓글이 없다", r.status_code == 200 and r.json() == {"count": 0, "threads": []}, r.text)

# ---- 잘못된 글 ----
for body, why in [({"nick": "", "body": "x", "password": "1234"}, "닉네임 없음"),
                  ({"nick": "a", "body": "   ", "password": "1234"}, "내용 없음"),
                  ({"nick": "a", "body": "x", "password": "12"}, "비밀번호 짧음"),
                  ({"nick": "a" * 21, "body": "x", "password": "1234"}, "닉네임 21자"),
                  ({"nick": "a", "body": "x" * 1001, "password": "1234"}, "내용 1001자"),
                  ({"nick": "관리자", "body": "x", "password": "1234"}, "관리자 사칭"),
                  ({"nick": "NasusFullstack", "body": "x", "password": "1234"}, "사이트 이름 사칭")]:
    r = client.post(URL, json=body, headers={"X-Forwarded-For": "9.9.9.%d" % len(why)})
    check("거절: " + why, r.status_code == 400, (r.status_code, r.text))
r = client.post(URL, content='{"nick":"a","body":"x","password":"1234"}', headers={"Content-Type": "text/plain"})
check("JSON 이 아니면 거절 (다른 사이트의 몰래 쓰기 막기)", r.status_code == 400, r.status_code)
r = post(nick="로봇", website="http://spam.example")
check("함정 칸에 뭔가 적힌 글은 성공한 척하고 저장 안 함", r.status_code == 200 and r.json()["count"] == 0, r.text)
check("없는 작품에는 못 쓴다", post(slug="nope").status_code == 404)

# ---- 본댓·답글 순서 ----
a = post(nick="가", body="첫 댓글", ip="10.0.0.1").json()["id"]
b = post(nick="나", body="두 번째 댓글", ip="10.0.0.2").json()["id"]
ra = post(nick="다", body="가에게 답", parent=a, ip="10.0.0.3").json()["id"]
rb = post(nick="라", body="또 가에게 답", parent=a, ip="10.0.0.4").json()["id"]
rra = post(nick="마", body="다에게 답", parent=ra, ip="10.0.0.5").json()["id"]
rrra = post(nick="바", body="마에게 답", parent=rra, ip="10.0.0.6").json()["id"]
data = client.get(URL).json()
check("최신 본댓이 위", [t["nick"] for t in data["threads"]] == ["나", "가"], flat(data["threads"]))
got = flat(data["threads"])[1][1]
check("답글에 단 답글은 @닉네임 으로, 그 글 바로 밑에 (깊이는 2 그대로)", got == ["다", "@다 마", "@마 바", "라"], got)
check("본댓에 바로 단 답글에는 @ 가 없다", data["threads"][1]["replies"][0]["mention"] is None)
check("댓글 수는 본댓·답글을 다 센다", data["count"] == 6, data["count"])
check("비밀번호는 응답에 안 나온다", "password" not in str(data) and "pw" not in data["threads"][0], data["threads"][0])

r = post(nick="사", body="다른 작품 글에 답", parent=a, slug="chupchat", ip="10.0.0.7")
check("다른 작품의 글에는 답을 못 단다", r.status_code == 404, r.status_code)
check("없는 글 번호에도 못 단다", post(parent=99999, ip="10.0.0.8").status_code == 404)

# ---- 지우기 ----
r = client.request("DELETE", "/api/comments/%d" % ra, json={"password": "틀림"})
check("비밀번호가 틀리면 못 지운다", r.status_code == 403, r.status_code)
r = client.request("DELETE", "/api/comments/%d" % rb, json={"password": "1234"})
check("맞는 비밀번호로 지운다", r.status_code == 200, r.text)
check("답이 없는 글을 지우면 아예 안 보인다", "라" not in str(flat(r.json()["threads"])), flat(r.json()["threads"]))
r = client.request("DELETE", "/api/comments/%d" % a, json={"password": "1234"})
th = r.json()["threads"]
gone = next(t for t in th if t["id"] == a)
check("답이 달린 본댓을 지우면 「삭제된 댓글」 자리만 남고 답글은 그대로",
      gone["deleted"] and "body" not in gone and len(gone["replies"]) == 3, gone)
check("지운 글에는 답을 못 단다", post(parent=a, ip="10.0.0.9").status_code == 404)
check("이미 지운 글은 다시 못 지운다", client.request("DELETE", "/api/comments/%d" % a, json={"password": "1234"}).status_code == 404)
for cid in (rrra, rra, ra):
    client.request("DELETE", "/api/comments/%d" % cid, json={"password": "1234"})
check("밑에 산 글이 하나도 없으면 지운 본댓 자리도 사라진다", [t["id"] for t in client.get(URL).json()["threads"]] == [b], client.get(URL).json())

# ---- 도배 ----
codes = [post(nick="도배", body="글 %d" % i, ip="20.0.0.1").status_code for i in range(4)]
check("같은 사람은 1분에 3개까지", codes == [200, 200, 200, 429], codes)
check("다른 사람은 그대로 쓸 수 있다", post(nick="옆사람", ip="20.0.0.2").status_code == 200)

# ---- 글은 글자로만 ----
r = post(nick="<b>꾀</b>", body='<script>alert(1)</script>\n\n\n\n\n\n줄바꿈 도배', ip="30.0.0.1")
c = next(t for t in r.json()["threads"] if t["id"] == r.json()["id"])
check("태그는 그대로 글자로 보관한다 (화면이 글자로만 넣음)", c["body"].startswith("<script>") and c["nick"] == "<b>꾀</b>", c)
check("빈 줄 도배는 세 줄로 줄인다", "\n\n\n\n" not in c["body"], repr(c["body"]))

# ---- 주인 ----
check("열쇠 없이는 작성자로 못 쓴다", client.post("/api/admin/works/danmak/comments", json={"body": "x"}).status_code == 403)
r = client.post("/api/admin/works/danmak/comments", json={"body": "고마워요!", "parent": b}, headers=KEY)
owner_id = r.json().get("id")
t = next(t for t in client.get(URL).json()["threads"] if t["id"] == b)
check("작성자 답글은 작성자 표시·사이트 이름으로", r.status_code == 200 and t["replies"][-1]["owner"] and t["replies"][-1]["nick"] == "NasusFullstack", t)
check("방문자는 작성자 글을 못 지운다", client.request("DELETE", "/api/comments/%d" % owner_id, json={"password": ""}).status_code == 403)
r = client.get("/api/admin/comments", headers=KEY)
check("관리 화면 목록 (작품 이름·글쓴이 지문)", r.status_code == 200 and r.json()["comments"][0]["work"] == "탄막게임" and r.json()["comments"][1]["who"], r.json()["comments"][:2])
check("열쇠 없이는 관리 목록을 못 본다", client.get("/api/admin/comments").status_code == 403)
r = client.delete("/api/admin/comments/%d" % b, headers=KEY)
check("주인은 아무 글이나 지운다", r.status_code == 200, r.status_code)
counts = {w["slug"]: w["comments"] for w in client.get("/api/overview").json()["works"]}
check("첫 화면 작품 정보에 댓글 수", counts.get("danmak") == client.get(URL).json()["count"], counts)

# ---- 남기지 않는 것 ----
db = sqlite3.connect(os.path.join(WORK, "site", "comments.sqlite3"))
dump = "\n".join(str(row) for row in db.execute("SELECT * FROM comments"))
check("비밀번호 원문이 안 남는다", "'1234'" not in dump and "$" in dump, dump[:200])
check("IP 원문이 안 남는다", "10.0.0." not in dump and "20.0.0." not in dump, dump[:200])

# ---- 숨긴·지운 작품 ----
client.put("/api/admin/works/danmak", headers=KEY, json={"title": "탄막게임", "hidden": True})
check("숨긴 작품의 댓글은 안 보인다", client.get(URL).status_code == 404)
client.put("/api/admin/works/danmak", headers=KEY, json={"title": "탄막게임", "hidden": False})
client.delete("/api/admin/works/danmak", headers=KEY)
check("작품을 지우면 댓글도 지운다", db.execute("SELECT COUNT(*) FROM comments WHERE slug='danmak'").fetchone()[0] == 0)
db.close()

shutil.rmtree(WORK, ignore_errors=True)
bad = [c for c in checks if not c[1]]
for name, passed, detail in checks:
    print(("통과 " if passed else "실패 ") + name + ("" if passed else "  (%s)" % (detail,)))
print("%d개 중 %d개 통과" % (len(checks), len(checks) - len(bad)))
sys.exit(1 if bad else 0)
