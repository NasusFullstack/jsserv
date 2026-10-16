"""화분키우기 서버 - 꾸러미가 서버 규칙으로만 늘고 줄며, 뽑기·보상이 두 번 되지 않고, 이벤트·차단이 맞게 되는가.

이 기능의 값은 넷이다: **잔액은 서버만 바꾼다**(처음 지급·보상·이벤트·관리), **같은 요청·같은 씨앗은 한 번만**,
**이벤트는 고른 대상에게 한 번씩**, **차단된 설치본·컴퓨터는 아무것도 못 한다.** 열쇠 없이는 관리 기능을 못 쓴다.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
import time

WORK = tempfile.mkdtemp(prefix="jsserv_dotpot_")
TOKEN = "test-token-123"
os.environ["JSSERV_SITE_DIR"] = os.path.join(WORK, "site")
os.environ["JSSERV_GAME_DIR"] = os.path.join(WORK, "game")
os.environ["JSSERV_DOTPOT_DIR"] = os.path.join(WORK, "dotpot")
os.environ["JSSERV_GAME_TOKEN_SHA256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
os.environ.pop("JSSERV_ADMIN_TOKEN_SHA256", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features.dotpot import config as DC  # noqa: E402
from features.dotpot import routes as DR  # noqa: E402
from features.dotpot import rules  # noqa: E402

client = TestClient(app)
checks = []
KEY = {"X-Admin-Key": TOKEN}
DEV_A = "a" * 64
DEV_B = "b" * 64
_n = [0]


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def req():
    _n[0] += 1
    return "req%06d" % _n[0]


def reg(body=None, device=DEV_A, ip="10.0.0.1"):
    h = {"X-Forwarded-For": ip}
    if device:
        h["X-Dotpot-Device"] = device
    return client.post("/dotpot/api/register", json=body or {"ver": "1.2.0"}, headers=h)


def H(acc, device=DEV_A):
    h = {"X-Dotpot-Id": acc["id"], "X-Dotpot-Secret": acc["secret"]}
    if device:
        h["X-Dotpot-Device"] = device
    return h


def db():
    con = sqlite3.connect(DC.DB)
    con.row_factory = sqlite3.Row
    return con


def give(acc, b=0, t=0):
    return client.post("/dotpot/api/admin/installs/%s/adjust" % acc["id"], json={"bundles": b, "tickets": t, "reason": "시험"}, headers=KEY)


# ---------- 등록 ----------
r = reg()
A = r.json()
check("새 설치본 등록 → 꾸러미 5·뽑기권 1", r.status_code == 200 and A["bundles"] == 5 and A["tickets"] == 1, r.text[:200])
r = reg({"ver": "1.2.0", "migrate": True, "bundles": 50, "tickets": 3, "legacy": [{"id": "1700000000_123", "kind": "flower"}, {"id": "../x", "kind": "flower"}]}, device=DEV_B, ip="10.0.0.2")
B = r.json()
check("예전 판에서 옮기기: 꾸러미 상한 20", B["bundles"] == 20 and B["tickets"] == 3, r.text[:200])
con = db()
check("예전 식물은 보상 자격으로 (이상한 번호는 버림)", [x["sid"] for x in con.execute("SELECT sid FROM seeds WHERE install=?", (B["id"],))] == ["1700000000_123"])
r = reg({"migrate": True, "bundles": 1, "tickets": 0, "legacy": [{"id": "1700000000_123", "kind": "tree"}]}, ip="10.0.0.3")
check("다른 사람의 예전 씨앗 번호가 같아도 각자 자격", con.execute("SELECT kind FROM seeds WHERE install=? AND sid='1700000000_123'", (r.json()["id"],)).fetchone()[0] == "tree")
check("비밀값은 지문만 저장", con.execute("SELECT secret_sha FROM installs WHERE id=?", (A["id"],)).fetchone()[0] == hashlib.sha256(A["secret"].encode()).hexdigest())
con.close()

# ---------- 인증 ----------
check("설치본 정보 없이 → 401", client.post("/dotpot/api/sync", json={}).status_code == 401)
check("비밀값 틀림 → 401", client.post("/dotpot/api/sync", json={}, headers={"X-Dotpot-Id": A["id"], "X-Dotpot-Secret": "nope"}).status_code == 401)
r = client.post("/dotpot/api/sync", json={"ver": "1.2.0"}, headers=H(A))
check("sync → 지금 개수", r.status_code == 200 and r.json()["bundles"] == 5 and r.json()["gifts"] == [], r.text[:200])

# ---------- 뽑기 ----------
q = req()
r1 = client.post("/dotpot/api/draw", json={"req": q}, headers=H(A))
r2 = client.post("/dotpot/api/draw", json={"req": q}, headers=H(A))
check("뽑기 → 씨앗·꾸러미 하나 줄음", r1.status_code == 200 and r1.json()["bundles"] == 4 and r1.json()["seed"]["kind"] in ("flower", "tree", "premium"), r1.text[:200])
check("같은 요청 번호 다시 → 같은 결과, 두 번 안 깎임", r2.json()["seed"] == r1.json()["seed"] and r2.json()["bundles"] == 4)
for i in range(4):
    client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A))
r = client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A))
check("꾸러미 0 → 409 (음수 안 됨)", r.status_code == 409 and r.json()["bundles"] == 0, r.text[:200])
con = db()
check("거절 기록 남음", con.execute("SELECT COUNT(*) FROM rejects WHERE install=? AND reason='no_bundle'", (A["id"],)).fetchone()[0] == 1)
con.close()

# 동시에 여러 번 눌러도 개수만큼만
give(A, b=10)
results = []


def hammer():
    rr = client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A))
    results.append(rr.status_code)


ths = [threading.Thread(target=hammer) for _ in range(20)]
[t.start() for t in ths]
[t.join() for t in ths]
r = client.post("/dotpot/api/sync", json={}, headers=H(A))
check("동시에 20번 → 10개만 성공, 남은 꾸러미 0", results.count(200) == 10 and r.json()["bundles"] == 0, str(sorted(results)))

# 확률 (규칙만, 많이)
N = 20000
kinds = {"premium": 0, "tree": 0, "flower": 0}
rare = 0
for i in range(N):
    s = rules.roll_seed({"premium": 0.10, "tree": 0.35, "rare": 0.05, "lux": 0.2}, 10)
    kinds[s["kind"]] += 1
    rare += 1 if s["rare"] else 0
pool10 = rules.premium_pool(10)
check("10월 고급 나무: 소나무·고무·은행·단풍", sorted(pool10) == ["ginkgo", "maple", "pine", "rubber"], str(pool10))
check("12월엔 크리스마스트리, 1월엔 없음", "xmas" in rules.premium_pool(12) and "xmas" not in rules.premium_pool(1))
check("고급 약 10%", abs(kinds["premium"] / N - 0.10) < 0.01, str(kinds))
check("나무 약 31.5% · 꽃 약 58.5%", abs(kinds["tree"] / N - 0.315) < 0.015 and abs(kinds["flower"] / N - 0.585) < 0.015, str(kinds))
check("신비한 씨앗 약 4.5%", abs(rare / N - 0.045) < 0.008, str(rare))

# ---------- 확률 바꾸기 (관리) ----------
r = client.get("/dotpot/api/admin/rates", headers=KEY)
check("확률: 기본 고급 나무 5%", r.status_code == 200 and r.json()["rates"]["premium"] == 0.05 and r.json()["names"]["lux"], r.text[:200])
check("확률: 열쇠 없으면 403", client.get("/dotpot/api/admin/rates").status_code == 403)
r = client.post("/dotpot/api/admin/rates", json={"rates": {"premium": 0.9}}, headers=KEY)
check("확률: 범위 밖(고급 90%)은 거절", r.status_code == 400, r.text[:200])
r = client.post("/dotpot/api/admin/rates", json={"rates": {"premium": 0.07, "lux": 0.2}, "note": "시험"}, headers=KEY)
check("확률: 고급 7% 로 (고급 화분은 그대로라 기록 안 함)", r.status_code == 200 and r.json()["changed"] == ["premium"] and r.json()["rates"]["premium"] == 0.07, r.text[:200])
rs = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()
check("확률: 게임은 켤 때 새 확률을 받음", rs.get("rates", {}).get("premium") == 0.07, str(rs)[:200])
lg = client.get("/dotpot/api/admin/rates", headers=KEY).json()["log"]
check("확률: 바뀐 기록 (5% → 7%, 메모)", lg and lg[0]["key"] == "premium" and lg[0]["old"] == 0.05 and lg[0]["new"] == 0.07 and lg[0]["note"] == "시험", str(lg)[:200])
client.post("/dotpot/api/admin/rates", json={"rates": {"premium": 0.05}}, headers=KEY)

# ---------- 화분 뽑기 ----------
r = client.post("/dotpot/api/potdraw", json={"req": req(), "size": "big"}, headers=H(A))
check("화분 뽑기 → 뽑기권 하나 줄음", r.status_code == 200 and r.json()["tickets"] == 0 and r.json()["pot"]["size"] == "big", r.text[:200])
check("이상한 크기 → 400", client.post("/dotpot/api/potdraw", json={"req": req(), "size": "giant"}, headers=H(A)).status_code == 400)
check("뽑기권 0 → 409", client.post("/dotpot/api/potdraw", json={"req": req(), "size": "small"}, headers=H(A)).status_code == 409)

# ---------- 보상 ----------
sid = r1.json()["seed"]["sid"]
kind = r1.json()["seed"]["kind"]
r = client.post("/dotpot/api/reward", json={"sid": sid, "outcome": "grown"}, headers=H(A))
check("뽑자마자 「다 키웠어요」 → 409 너무 이름", r.status_code == 409, r.text[:200])
con = db()
con.execute("UPDATE seeds SET drawn=? WHERE sid=?", (time.time() - rules.min_hours(kind) * 3600 - 10, sid))
con.commit()
con.close()
b0 = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()
r = client.post("/dotpot/api/reward", json={"sid": sid, "outcome": "grown"}, headers=H(A))
check("충분히 지난 뒤 다 키움 → 꾸러미+1·뽑기권+1", r.status_code == 200 and r.json()["bundles"] == b0["bundles"] + 1 and r.json()["tickets"] == b0["tickets"] + 1, r.text[:200])
r = client.post("/dotpot/api/reward", json={"sid": sid, "outcome": "grown"}, headers=H(A))
check("같은 씨앗 두 번 → 안 줌 (dup)", r.status_code == 200 and r.json().get("dup") and r.json()["bundles"] == b0["bundles"] + 1)
check("남의 씨앗 → 404", client.post("/dotpot/api/reward", json={"sid": sid, "outcome": "dead"}, headers=H(B, DEV_B)).status_code == 404)
r = client.post("/dotpot/api/reward", json={"sid": "1700000000_123", "outcome": "dead"}, headers=H(B, DEV_B))
check("예전 식물 시듦 → 꾸러미만 +1", r.status_code == 200 and r.json()["bundles"] == 21 and r.json()["tickets"] == 3, r.text[:200])

# 보상을 묶어 보내기 (sync·draw 본문의 rewards)
rr = client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A))
sid2 = rr.json().get("seed", {}).get("sid") if rr.status_code == 200 else None
if not sid2:
    give(A, b=1)
    sid2 = client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A)).json()["seed"]["sid"]
b1 = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()["bundles"]
r = client.post("/dotpot/api/sync", json={"rewards": [{"sid": sid2, "outcome": "dead"}, {"sid": sid2, "outcome": "dead"}]}, headers=H(A))
res = r.json()["rewarded"]
check("sync 에 묶은 보상: 첫 번째만 받고 두 번째는 dup", [x["result"] for x in res] == ["ok", "dup"] and r.json()["bundles"] == b1 + 1, str(res))
give(A, b=1)
r = client.post("/dotpot/api/draw", json={"req": req(), "rewards": [{"sid": sid2, "outcome": "dead"}]}, headers=H(A))
check("draw 에 묶은 보상도 처리 (이미 받은 건 dup)", r.status_code == 200 and r.json()["rewarded"][0]["result"] == "dup", r.text[:200])

# ---------- 이벤트 ----------
r = client.post("/dotpot/api/admin/events", json={"bundles": 3, "tickets": 1, "msg": "추석 선물"}, headers=KEY)
check("모두에게 이벤트 만들기", r.status_code == 200, r.text[:200])
ev_all = r.json()["id"]
ra = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()
ra2 = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()
check("켜면 선물 한 번 (꾸러미+3·뽑기권+1)", len(ra["gifts"]) == 1 and ra["gifts"][0]["msg"] == "추석 선물" and ra2["gifts"] == [] and ra2["bundles"] == ra["bundles"])
r = client.post("/dotpot/api/admin/events", json={"bundles": 2, "msg": "B만", "targets": [B["id"]]}, headers=KEY)
ga = client.post("/dotpot/api/sync", json={}, headers=H(A)).json()["gifts"]
gb = client.post("/dotpot/api/sync", json={}, headers=H(B, DEV_B)).json()["gifts"]
check("고른 설치본에게만", ga == [] and any(g["msg"] == "B만" for g in gb), str(ga) + str(gb))
r = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "앞자리로", "targets": [B["id"][:8].upper() + " "]}, headers=KEY)
gb = client.post("/dotpot/api/sync", json={}, headers=H(B, DEV_B)).json()["gifts"]
check("유저 아이디 앞 6자리 이상으로도 보냄", r.status_code == 200 and any(g["msg"] == "앞자리로" for g in gb), r.text[:200])
r = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "없는 번호", "targets": [B["id"], "ffffff00"]}, headers=KEY)
check("없는 아이디가 섞이면 보내지 않고 알려 줌", r.status_code == 400 and "ffffff00" in r.json().get("error", r.text), r.text[:200])
r = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "짧은 번호", "targets": ["abc"]}, headers=KEY)
check("너무 짧은 아이디는 거절", r.status_code == 400, r.text[:200])
r = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "예약", "start_at": time.time() + 3600}, headers=KEY)
check("시작 전 이벤트는 아직", client.post("/dotpot/api/sync", json={}, headers=H(A)).json()["gifts"] == [])
r = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "옛 사람만", "include_new": False}, headers=KEY)
C_ = reg(device="c" * 64, ip="10.0.0.3").json()
gc = client.post("/dotpot/api/sync", json={}, headers=H(C_, "c" * 64)).json()["gifts"]
check("「새로 온 사람 제외」 이벤트는 나중 등록자에게 안 감", not any(g["msg"] == "옛 사람만" for g in gc) and any(g["msg"] == "추석 선물" for g in gc), str(gc))
eid = client.post("/dotpot/api/admin/events", json={"bundles": 5, "msg": "취소될 것"}, headers=KEY).json()["id"]
client.post("/dotpot/api/admin/events/%d/cancel" % eid, headers=KEY)
check("취소한 이벤트는 안 감", not any(g["msg"] == "취소될 것" for g in client.post("/dotpot/api/sync", json={}, headers=H(B, DEV_B)).json()["gifts"]))
check("개수 0 이벤트는 거절", client.post("/dotpot/api/admin/events", json={"bundles": 0, "tickets": 0}, headers=KEY).status_code == 400)

# ---------- 우편함 (1.5.0~: sync 에 mail=1 → 바로 지급하지 않고 우편으로, 「받기」로 지급) ----------
M = reg(device="m" * 64, ip="10.0.0.7").json()
HM = H(M, "m" * 64)
e1 = client.post("/dotpot/api/admin/events", json={"bundles": 2, "tickets": 1, "msg": "우편 선물"}, headers=KEY).json()["id"]
e2 = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "우편 둘째"}, headers=KEY).json()["id"]
rm = client.post("/dotpot/api/sync", json={"mail": 1}, headers=HM).json()
due = [m for m in rm.get("mail", []) if not m["got"]]
check("우편함 게임: sync 는 지급 없이 우편 목록", rm["gifts"] == [] and {e1, e2} <= {m["event"] for m in due} and rm["bundles"] == 5, str(rm)[:300])
check("우편에 기간(끝 시각)", all(m["end"] > time.time() for m in due), str(due)[:200])
b0 = rm["bundles"]
rc = client.post("/dotpot/api/mail/claim", json={"event": e1}, headers=HM).json()
check("우편 받기 → 꾸러미+2·뽑기권+1, 받은 우편은 「받음」으로 남음", rc["result"] == "ok" and rc["bundles"] == b0 + 2 and len(rc["gifts"]) == 1
      and any(m["event"] == e1 and m["got"] for m in rc["mail"]) and any(m["event"] == e2 and not m["got"] for m in rc["mail"]), str(rc)[:300])
rc2 = client.post("/dotpot/api/mail/claim", json={"event": e1}, headers=HM).json()
check("같은 우편 두 번 → 안 줌 (got)", rc2["result"] == "got" and rc2["bundles"] == rc["bundles"] and rc2["gifts"] == [], str(rc2)[:200])
ra3 = client.post("/dotpot/api/sync", json={}, headers=HM).json()
check("예전 게임 sync 는 남은 우편을 바로 지급 (받은 건 다시 안 줌)", [g["event"] for g in ra3["gifts"] if g["event"] in (e1, e2)] == [e2], str(ra3["gifts"])[:200])
e3 = client.post("/dotpot/api/admin/events", json={"tickets": 2, "msg": "우편 셋째"}, headers=KEY).json()["id"]
e4 = client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "우편 넷째"}, headers=KEY).json()["id"]
rn = client.post("/dotpot/api/mail", json={}, headers=HM).json()
check("새로 고침(/mail) → 새 우편이 보임", {e3, e4} <= {m["event"] for m in rn["mail"] if not m["got"]}, str(rn)[:200])
ral = client.post("/dotpot/api/mail/claim", json={"event": "all"}, headers=HM).json()
check("모두 받기", ral["result"] == "ok" and {e3, e4} <= {g["event"] for g in ral["gifts"]} and not any(not m["got"] for m in ral["mail"]), str(ral)[:300])
e5 = client.post("/dotpot/api/admin/events", json={"bundles": 9, "msg": "취소될 우편"}, headers=KEY).json()["id"]
client.post("/dotpot/api/admin/events/%d/cancel" % e5, headers=KEY)
rx = client.post("/dotpot/api/mail/claim", json={"event": e5}, headers=HM).json()
check("취소된 우편은 못 받음 (gone)", rx["result"] == "gone" and rx["gifts"] == [] and not any(m["event"] == e5 for m in rx["mail"]), str(rx)[:200])
check("우편 번호가 이상하면 400", client.post("/dotpot/api/mail/claim", json={"event": "x"}, headers=HM).status_code == 400)
check("남의 우편: 고른 사람에게만 간 이벤트는 못 받음",
      client.post("/dotpot/api/mail/claim", json={"event": client.post("/dotpot/api/admin/events", json={"bundles": 1, "msg": "B 전용", "targets": [B["id"]]}, headers=KEY).json()["id"]}, headers=HM).json()["result"] == "gone")

# ---------- 의문의 상인 · 공방 · 도전과제 ----------
CR = reg({"ver": "1.3.0"}, device="d" * 64, ip="10.0.0.9").json()
con = db()
now = time.time()
for i, (k, rare) in enumerate([("flower", 0), ("tree", 0), ("flower", 0), ("flower", 1), ("premium", 0)]):
    con.execute("INSERT INTO seeds (sid, install, kind, ptype, rare, n, drawn) VALUES (?,?,?,?,?,?,?)",
                ("cs%d" % i, CR["id"], k, "pine" if k == "premium" else "", rare, 1, now))
for i in range(5):
    con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn) VALUES (?,?,?,?,?,?)", ("cp%d" % i, CR["id"], "small", 0, 1, now))
con.commit()
con.close()
fr = req()
r = client.post("/dotpot/api/fuse", json={"req": fr, "sids": ["cs0", "cs1", "cs2"], "pick": "tree"}, headers=H(CR, "d" * 64))
fs = r.json().get("seed", {})
check("상인: 일반 씨앗 3개 → 고른 묘목(또는 고급) 하나", r.status_code == 200 and fs.get("kind") in ("tree", "premium"), r.text[:200])
r2 = client.post("/dotpot/api/fuse", json={"req": fr, "sids": ["cs0", "cs1", "cs2"], "pick": "tree"}, headers=H(CR, "d" * 64))
check("상인: 같은 요청 번호면 같은 결과", r2.json().get("seed", {}).get("sid") == fs.get("sid"), r2.text[:200])
r = client.post("/dotpot/api/fuse", json={"req": req(), "sids": ["cs0", "cs1", "cs2"], "pick": "flower"}, headers=H(CR, "d" * 64))
check("상인: 이미 맡긴 씨앗은 다시 못 씀 → 409", r.status_code == 409, r.text[:200])
r = client.post("/dotpot/api/fuse", json={"req": req(), "sids": ["cs3", "cs4", fs.get("sid", "x")], "pick": "flower"}, headers=H(CR, "d" * 64))
check("상인: 신비한·고급 씨앗은 안 됨 → 409", r.status_code == 409, r.text[:200])
r = client.post("/dotpot/api/fuse", json={"req": req(), "sids": ["cs3", "cs3", "cs4"], "pick": "flower"}, headers=H(CR, "d" * 64))
check("상인: 같은 씨앗 두 번·개수 틀림 → 400", r.status_code == 400, r.text[:200])
rr = client.post("/dotpot/api/sync", json={"rewards": [{"sid": "cs0", "outcome": "grown"}]}, headers=H(CR, "d" * 64)).json()
check("상인에게 맡긴 씨앗으로는 보상 없음", rr["rewarded"] and rr["rewarded"][0]["result"] == "used", str(rr.get("rewarded")))
N = 4000
cnt = {"premium": 0, "tree": 0, "flower": 0}
for i in range(N):
    cnt[rules.roll_fuse({"fuse": 0.05}, "flower", 10)["kind"]] += 1
check("상인 고급 확률 약 5%% (%d/%d)" % (cnt["premium"], N), abs(cnt["premium"] / N - 0.05) < 0.012 and cnt["tree"] == 0, str(cnt))
kr = req()
r = client.post("/dotpot/api/kiln", json={"req": kr, "pots": [{"pid": "cp0"}, {"pid": "cp1"}, {"pid": "cp2"}]}, headers=H(CR, "d" * 64))
kp = r.json().get("pot", {})
check("공방: 화분 3개 → 다시 구운 화분 하나", r.status_code == 200 and kp.get("size") in DC.POT_SIZES, r.text[:200])
r = client.post("/dotpot/api/kiln", json={"req": req(), "pots": [{"pid": "cp0"}, {"pid": "cp3"}, {"pid": "cp4"}]}, headers=H(CR, "d" * 64))
check("공방: 이미 맡긴 화분은 다시 못 씀 → 409", r.status_code == 409, r.text[:200])
r = client.post("/dotpot/api/kiln", json={"req": req(), "pots": [{"pid": "st1", "sid": "cs3"}, {"pid": "st2", "sid": "cs4"}, {"pid": "cp3"}]}, headers=H(CR, "d" * 64))
check("공방: 씨앗의 기본 화분은 그 자리에서 등록해 맡김", r.status_code == 200, r.text[:200])
r = client.post("/dotpot/api/kiln", json={"req": req(), "pots": [{"pid": "st3", "sid": "cs3"}, {"pid": "cp4"}, {"pid": "x9"}]}, headers=H(CR, "d" * 64))
check("공방: 같은 씨앗의 기본 화분 두 번 · 지어낸 화분은 안 됨 → 409", r.status_code == 409, r.text[:200])
r = client.post("/dotpot/api/kiln", json={"req": req(), "pots": [{"pid": "lg1", "size": "big", "lux": True}, {"pid": "lg2", "size": "small"}, {"pid": "cp4"}]}, headers=H(CR, "d" * 64))
check("공방: 새로 시작한 유저는 예전 판 화분이 없음 → 409", r.status_code == 409, r.text[:200])
r = client.post("/dotpot/api/kiln", json={"req": req(), "pots": [{"pid": "lg1", "size": "big", "lux": True}, {"pid": "lg2", "size": "small"}, {"pid": "lg3", "size": "huge"}]}, headers=H(B, DEV_B))
check("공방: 옮겨 온 유저는 예전 판 화분을 맡길 수 있음", r.status_code == 200, r.text[:200])
sizes = {s: 0 for s in DC.POT_SIZES}
lux = 0
for i in range(N):
    p = rules.roll_kiln({"kiln": 0.05})
    sizes[p["size"]] += 1
    lux += 1 if p["lux"] else 0
check("공방: 크기는 고루 · 고급 약 5%%", all(abs(v / N - 1 / 3) < 0.04 for v in sizes.values()) and abs(lux / N - 0.05) < 0.012, str(sizes) + " lux %d" % lux)
sizes = {s: 0 for s in DC.POT_SIZES}
for i in range(600):
    sizes[rules.roll_kiln({"kiln": 0.05, "kiln_small": 0.0, "kiln_big": 0.25, "kiln_huge": 0.75})["size"]] += 1
check("공방: 크기 비율대로 (작은 0 · 큰 25 · 아주 큰 75)", sizes["small"] == 0 and abs(sizes["huge"] / 600 - 0.75) < 0.07, str(sizes))
check("공방: 크기 비율이 모두 0 이면 고루", {rules.roll_kiln({"kiln": 0, "kiln_small": 0, "kiln_big": 0, "kiln_huge": 0})["size"] for _ in range(200)} == set(DC.POT_SIZES))
r = client.post("/dotpot/api/admin/rates", json={"rates": {"kiln_small": 0, "kiln_big": 0, "kiln_huge": 0}}, headers=KEY)
check("확률: 공방 크기 비율 모두 0 은 거절", r.status_code == 400, r.text[:200])
r = client.get("/dotpot/api/admin/rates", headers=KEY).json()
check("확률: 관리 화면 묶음 — 재조합(상인·공방)", any(g[0].startswith("재조합") and "fuse" in g[1] and "kiln_big" in g[1] for g in r.get("groups", [])), str(r.get("groups"))[:200])
r = client.post("/dotpot/api/achieve", json={"key": "pots30"}, headers=H(CR, "d" * 64))
check("도전과제: 화분 30개 전엔 안 됨", r.json().get("result") == "not_yet", r.text[:200])
con = db()
for i in range(30):
    con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn) VALUES (?,?,?,?,?,?)", ("cq%d" % i, CR["id"], "small", 0, 1, now))
con.commit()
con.close()
t0 = client.post("/dotpot/api/sync", json={}, headers=H(CR, "d" * 64)).json()
r = client.post("/dotpot/api/achieve", json={"key": "pots30"}, headers=H(CR, "d" * 64)).json()
check("도전과제: 화분 수집가 → 뽑기권 +5", r.get("result") == "ok" and r["tickets"] == t0["tickets"] + 5 and "pots30" in r.get("ach", []), str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "pots30"}, headers=H(CR, "d" * 64)).json()
check("도전과제: 한 번만", r.get("result") == "dup" and r["tickets"] == t0["tickets"] + 5, str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "stage5"}, headers=H(CR, "d" * 64)).json()
check("도전과제: 막 시작한 유저의 5단계는 아직 (시간 확인)", r.get("result") == "not_yet", str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "stage3"}, headers=H(B, DEV_B)).json()
check("도전과제: 옮겨 온 유저의 3단계 → 꾸러미 +1", r.get("result") == "ok", str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "nope"}, headers=H(CR, "d" * 64)).json()
check("도전과제: 없는 이름", r.get("result") == "unknown", str(r)[:200])
s = client.post("/dotpot/api/sync", json={}, headers=H(CR, "d" * 64)).json()
check("켤 때 도전과제 진행·받은 것", s.get("stats", {}).get("pots", 0) >= 30 and "pots30" in s.get("ach", []), str(s)[:200])

# 옛 꼴 DB(화분 열쇠가 번호 하나) → 새 꼴로 옮김
import importlib  # noqa: E402
from features.dotpot import store as DS  # noqa: E402
old_db = os.path.join(WORK, "old.sqlite3")
oc = sqlite3.connect(old_db)
oc.executescript("""CREATE TABLE installs (id TEXT PRIMARY KEY, secret_sha TEXT NOT NULL, created REAL NOT NULL, last_seen REAL NOT NULL,
    ver TEXT NOT NULL DEFAULT '', bundles INTEGER NOT NULL, tickets INTEGER NOT NULL, migrated_bundles INTEGER NOT NULL DEFAULT 0,
    migrated_tickets INTEGER NOT NULL DEFAULT 0, device TEXT NOT NULL DEFAULT '');
CREATE TABLE seeds (sid TEXT NOT NULL, install TEXT NOT NULL, kind TEXT NOT NULL, ptype TEXT NOT NULL DEFAULT '', rare INTEGER NOT NULL DEFAULT 0,
    n INTEGER NOT NULL DEFAULT 0, drawn REAL NOT NULL, legacy INTEGER NOT NULL DEFAULT 0, rewarded TEXT, rewarded_at REAL, PRIMARY KEY (install, sid));
CREATE TABLE pots (pid TEXT PRIMARY KEY, install TEXT NOT NULL, size TEXT NOT NULL, lux INTEGER NOT NULL, n INTEGER NOT NULL, drawn REAL NOT NULL);
INSERT INTO pots VALUES ('pold', 'u1', 'big', 1, 5, 1.0);""")
oc.close()
_old = (DC.DB, DS._ready)
DC.DB = old_db
DS._ready = False
con = DS.connect()
pk = [r["name"] for r in sorted(con.execute("PRAGMA table_info(pots)"), key=lambda r: r["pk"]) if r["pk"]]
rowp = con.execute("SELECT * FROM pots").fetchone()
icol = {r["name"] for r in con.execute("PRAGMA table_info(installs)")}
scol = {r["name"] for r in con.execute("PRAGMA table_info(seeds)")}
con.close()
check("옛 DB 옮김: 화분 열쇠 (유저, 번호) · 자료 그대로 · 새 칸", pk == ["install", "pid"] and rowp["pid"] == "pold" and rowp["lux"] == 1 and rowp["used"] == 0
      and "legacy_pots" in icol and "used" in scol, str(pk) + str(dict(rowp)))
DC.DB, DS._ready = _old[0], True

# ---------- 차단 ----------
r = client.post("/dotpot/api/admin/bans", json={"kind": "install", "value": A["id"], "reason": "중복 보상 버그 사용"}, headers=KEY)
bid = r.json()["id"]
r = client.post("/dotpot/api/draw", json={"req": req()}, headers=H(A))
check("차단된 설치본 → 403 + 사유", r.status_code == 403 and r.json()["banned"] and r.json()["reason"] == "중복 보상 버그 사용", r.text[:200])
lst = client.get("/dotpot/api/admin/bans", headers=KEY).json()["bans"]
check("관리 화면 차단 목록에 사유", any(b["reason"] == "중복 보상 버그 사용" for b in lst))
client.post("/dotpot/api/admin/bans/%d/lift" % bid, json={"note": "오해"}, headers=KEY)
check("차단 풀면 다시 됨", client.post("/dotpot/api/sync", json={}, headers=H(A)).status_code == 200)
r = client.post("/dotpot/api/admin/bans", json={"kind": "device", "value": B["id"], "reason": "조작"}, headers=KEY)
check("설치 번호로 컴퓨터 차단 (그 컴퓨터 지문으로)", r.status_code == 200, r.text[:200])
D_ = reg(device=DEV_B, ip="10.0.0.4")
check("차단된 컴퓨터에서 새로 깔아 등록 → 403", D_.status_code == 403 and D_.json()["banned"], D_.text[:200])
check("차단된 컴퓨터의 다른 설치본도 → 403", client.post("/dotpot/api/sync", json={}, headers=H(B, DEV_B)).status_code == 403)
check("다른 지문을 보내도 처음 지문으로 차단 유지", client.post("/dotpot/api/sync", json={}, headers=H(B, "e" * 64)).status_code == 403)

# ---------- 관리 ----------
check("열쇠 없이 관리 → 403", client.get("/dotpot/api/admin/installs").status_code == 403)
# ---------- 일일 퀘스트 · 수집 목표 ----------
DQ = reg({"ver": "1.4.0"}, device="e" * 64, ip="10.0.0.21").json()
HD = H(DQ, "e" * 64)
s0 = client.post("/dotpot/api/sync", json={}, headers=HD).json()
check("일일: sync 가 서버 날짜·오늘 받은 것 알려 줌", s0.get("day") and s0.get("daily") == [] and s0.get("drew_today") is False, str(s0)[:200])
r = client.post("/dotpot/api/daily", json={"key": "care1", "water": 1, "food": 0}, headers=HD).json()
check("일일: 영양제를 안 줬으면 아직", r.get("result") == "not_yet", str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "care1", "water": 1, "food": 1}, headers=HD).json()
check("일일: 물·영양 1번씩 → 꾸러미 +1", r.get("result") == "ok" and r["bundles"] == s0["bundles"] + 1 and r.get("daily") == ["care1"], str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "care1", "water": 5, "food": 5}, headers=HD).json()
check("일일: 같은 날엔 한 번만", r.get("result") == "dup" and r["bundles"] == s0["bundles"] + 1, str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "care3", "water": 3, "food": 2}, headers=HD).json()
check("일일: 3번씩은 물·영양 둘 다 3번", r.get("result") == "not_yet", str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "care3", "water": 3, "food": 3}, headers=HD).json()
check("일일: 물·영양 3번씩 → 꾸러미 +1", r.get("result") == "ok" and r["bundles"] == s0["bundles"] + 2, str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "draw1"}, headers=HD).json()
check("일일: 꾸러미를 안 열었으면 아직", r.get("result") == "not_yet", str(r)[:200])
client.post("/dotpot/api/draw", json={"req": req()}, headers=HD)
r = client.post("/dotpot/api/daily", json={"key": "draw1"}, headers=HD).json()
check("일일: 꾸러미 1번 열기 → 화분 뽑기권 +2", r.get("result") == "ok" and r["tickets"] == s0["tickets"] + 2 and r.get("drew_today") is True, str(r)[:200])
r = client.post("/dotpot/api/daily", json={"key": "nope"}, headers=HD).json()
check("일일: 모르는 이름", r.get("result") == "unknown", str(r)[:200])
con = db()
con.execute("UPDATE daily SET day='2000-01-01' WHERE install=?", (DQ["id"],))
con.commit()
con.close()
r = client.post("/dotpot/api/daily", json={"key": "care1", "water": 1, "food": 1}, headers=HD).json()
check("일일: 날짜가 바뀌면 다시", r.get("result") == "ok", str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "col_spring"}, headers=HD).json()
check("수집: 다 키운 식물이 모자라면 아직", r.get("result") == "not_yet", str(r)[:200])
con = db()
for i in range(3):
    con.execute("INSERT INTO seeds (sid, install, kind, drawn, rewarded) VALUES (?,?,?,?,?)", ("gq%d" % i, DQ["id"], "flower", 0, "grown"))
con.commit()
con.close()
r = client.post("/dotpot/api/achieve", json={"key": "col_spring"}, headers=HD).json()
check("수집: 봄 화단(3그루) → 꾸러미 +1", r.get("result") == "ok" and r["stats"]["grown"] == 3, str(r)[:200])
r = client.post("/dotpot/api/achieve", json={"key": "col_premium"}, headers=HD).json()
check("수집: 고급 나무를 다 키운 적 없으면 아직", r.get("result") == "not_yet", str(r)[:200])
r = client.get("/dotpot/api/admin/installs/" + DQ["id"], headers=KEY).json()
check("관리: 유저 기록에 일일 퀘스트", len(r.get("daily", [])) == 4, str(r.get("daily"))[:200])
check("관리: 일일 퀘스트 CSV", client.get("/dotpot/api/admin/export/daily", headers=KEY).status_code == 200)

r = client.get("/dotpot/api/admin/installs", headers=KEY)
check("설치본 목록", r.status_code == 200 and r.json()["total"] >= 3, r.text[:200])
r = client.get("/dotpot/api/admin/installs/" + A["id"], headers=KEY)
d = r.json()
check("설치본 하나의 기록(장부·뽑기·씨앗·거절)", r.status_code == 200 and d["ledger"] and d["draws"] and d["seeds"] and "secret_sha" not in d["install"])
r = client.get("/dotpot/api/admin/export/installs", headers=KEY)
check("CSV 내려받기 (비밀값 지문 없음)", r.status_code == 200 and "secret_sha" not in r.text and A["id"] in r.text)
check("모르는 표 → 404", client.get("/dotpot/api/admin/export/sqlite_master", headers=KEY).status_code == 404)
r = client.get("/dotpot/api/admin/summary", headers=KEY)
check("요약", r.status_code == 200 and r.json()["installs"] >= 3, r.text[:200])

# ---------- 등록 횟수 제한 ----------
codes = [reg(device=None, ip="10.9.9.9").status_code for _ in range(DC.REGISTER_PER_HOUR + 2)]
check("한 주소에서 등록 너무 많이 → 429", codes[-1] == 429 and codes[0] == 200, str(codes[-3:]))

ok = sum(1 for c in checks if c[1])
for name, passed, detail in checks:
    print(("통과 " if passed else "실패 ") + name + ("" if passed else "  " + detail))
print("화분키우기 서버 시험: %d/%d" % (ok, len(checks)))
sys.exit(0 if ok == len(checks) else 1)
