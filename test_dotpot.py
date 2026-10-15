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
