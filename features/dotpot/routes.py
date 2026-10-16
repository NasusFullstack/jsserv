"""화분키우기 서버의 주소 층.

게임 (설치본 번호·비밀값은 헤더 X-Dotpot-Id · X-Dotpot-Secret, 컴퓨터 지문은 X-Dotpot-Device):
    POST /dotpot/api/register     처음 켤 때 등록 → 번호·비밀값·꾸러미·뽑기권
    POST /dotpot/api/sync         켤 때·창을 열 때: 이벤트 선물 받기 + 지금 개수
    POST /dotpot/api/draw         씨앗 꾸러미 하나 뽑기 (서버가 결과를 정함, 같은 req 면 같은 결과)
    POST /dotpot/api/potdraw      화분 뽑기권 하나로 화분 뽑기
    POST /dotpot/api/reward       씨앗 하나 다 키움(꾸러미+뽑기권)·시듦(꾸러미) — 씨앗마다 한 번
    (게임은 보상을 따로 보내지 않고 sync·draw·potdraw 본문의 rewards 목록에 묶어 보냄 → 요청 수를 줄임)
관리 (열쇠 X-Admin-Key, 사이트 관리 열쇠와 같음):
    GET  /dotpot/api/admin/summary · installs · installs/{id} · events · bans · export/{표}
    POST /dotpot/api/admin/events (모두에게 또는 고른 설치본에게 재화) · events/{id}/cancel
    POST /dotpot/api/admin/bans (설치본·컴퓨터 차단, 사유) · bans/{id}/lift (풀기) · installs/{id}/adjust (개수 고치기)
차단된 설치본·컴퓨터는 게임 주소에서 403 {banned, reason}.
"""
import csv
import datetime
import hashlib
import hmac
import io
import json
import re
import secrets
import threading
import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from ..site import auth as site_auth
from ..site import service as site_service
from . import config as C
from . import rules
from . import store

router = APIRouter(prefix="/dotpot/api")

ID_RE = re.compile(r"^[0-9a-f]{32}$")
DEVICE_RE = re.compile(r"^[0-9a-f]{64}$")
REQ_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")


def _err(msg, code=400, **extra):
    return JSONResponse({"error": msg, **extra}, status_code=code, headers={"Cache-Control": "no-store"})


def _ok(data):
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _ip(request):
    peer = request.client.host if request.client else None
    return site_service.client_ip(request.headers, peer)[0]


class _Limit:
    """한 시간 창에서 열쇠(주소·설치본)마다 횟수"""

    def __init__(self, per_hour):
        self.per_hour = per_hour
        self.hits = {}
        self.lock = threading.Lock()

    def over(self, key):
        now = time.time()
        with self.lock:
            rec = self.hits.get(key)
            if not rec or now - rec[1] > 3600:
                rec = [0, now]
            rec[0] += 1
            self.hits[key] = rec
            if len(self.hits) > 50000:
                for k in [k for k, v in self.hits.items() if now - v[1] > 3600]:
                    self.hits.pop(k, None)
            return rec[0] > self.per_hour


_reg_limit = _Limit(C.REGISTER_PER_HOUR)
_call_limit = _Limit(C.CALLS_PER_HOUR)


async def _body(request):
    raw = await request.body()
    if len(raw) > C.MAX_BODY:
        return None
    try:
        d = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _device(request):
    d = request.headers.get("x-dotpot-device", "").strip().lower()
    return d if DEVICE_RE.match(d) else ""


def _banned_resp(b):
    return _err("이용이 제한된 유저입니다", 403, banned=True, reason=b["reason"], since=b["at"])


async def _auth(request):
    """(설치본 dict, None) 또는 (None, 거절 응답)"""
    iid = request.headers.get("x-dotpot-id", "").strip().lower()
    secret = request.headers.get("x-dotpot-secret", "")
    if not ID_RE.match(iid) or not secret:
        return None, _err("유저 정보가 없습니다", 401)
    inst = await run_in_threadpool(store.install, iid)
    if not inst or not hmac.compare_digest(inst["secret_sha"], hashlib.sha256(secret.encode()).hexdigest()):
        return None, _err("유저 정보가 맞지 않습니다", 401)
    if _call_limit.over(iid):
        return None, _err("너무 자주 불렀습니다. 잠시 뒤에 다시 해 주세요", 429)
    dev = _device(request)
    b = await run_in_threadpool(store.ban_of, iid, dev)
    if b:
        return None, _banned_resp(b)
    return inst, None


# ---------- 게임 ----------

async def _rewards(inst, d):
    """본문에 묶어 온 보상들 처리 → [{sid, ok|dup|early|unknown}] (최대 20개)"""
    out = []
    for x in (d.get("rewards") or [])[:20]:
        if not isinstance(x, dict):
            continue
        sid = str(x.get("sid", ""))
        outcome = str(x.get("outcome", ""))
        if not SID_RE.match(sid) or outcome not in ("grown", "dead"):
            continue
        _bal, err = await run_in_threadpool(store.reward, inst["id"], sid, outcome, rules.min_hours)
        if err:
            await run_in_threadpool(store.reject, inst["id"], "reward_" + err, sid)
        out.append({"sid": sid, "result": err or "ok", "outcome": outcome})
    return out


@router.post("/register")
async def register(request: Request):
    if _reg_limit.over(_ip(request)):
        return _err("등록을 너무 자주 했습니다. 잠시 뒤에 다시 해 주세요", 429)
    d = await _body(request)
    if d is None:
        return _err("요청이 이상합니다")
    dev = _device(request)
    if dev:
        b = await run_in_threadpool(store.ban_of, "", dev)
        if b:
            return _banned_resp(b)
    migrated = bool(d.get("migrate", False))
    if migrated:
        bundles, tickets = rules.migrate_counts(d.get("bundles"), d.get("tickets"))
    else:
        bundles, tickets = C.START_BUNDLES, C.START_TICKETS
    legacy = []
    for x in (d.get("legacy") or [])[:C.MIGRATE_MAX_LEGACY]:
        if isinstance(x, dict) and SID_RE.match(str(x.get("id", ""))) and x.get("kind") in ("flower", "tree", "premium"):
            legacy.append((str(x["id"]), x["kind"]))
    iid = secrets.token_hex(16)
    secret = secrets.token_urlsafe(32)
    ver = str(d.get("ver", ""))[:20]
    await run_in_threadpool(store.register, iid, hashlib.sha256(secret.encode()).hexdigest(), ver, bundles, tickets, legacy, migrated, dev)
    rates = await run_in_threadpool(store.get_rates)
    return _ok({"id": iid, "secret": secret, "bundles": bundles, "tickets": tickets, "rates": rates})


@router.post("/sync")
async def sync(request: Request):
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    await run_in_threadpool(store.touch, inst["id"], str(d.get("ver", "")), _device(request))
    rewarded = await _rewards(inst, d)
    if d.get("mail"):   # 우편함이 있는 게임(1.5.0~): 선물은 우편으로 — 「받기」를 눌러야 들어감
        mail, bal = await run_in_threadpool(store.mail_of, inst["id"])
        extra = {"gifts": [], "mail": mail}
    else:               # 예전 게임: 켤 때 바로 지급
        gifts, bal = await run_in_threadpool(store.apply_events, inst["id"])
        extra = {"gifts": gifts}
    rates = await run_in_threadpool(store.get_rates)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({**bal, **extra, "rewarded": rewarded, "rates": rates, **prog})


@router.post("/mail")
async def mail(request: Request):
    """우편함 새로 보기 (받을 이벤트 + 최근 받은 것)"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    mail_, bal = await run_in_threadpool(store.mail_of, inst["id"])
    return _ok({**bal, "mail": mail_})


@router.post("/mail/claim")
async def mail_claim(request: Request):
    """우편 「받기」 — event = 이벤트 번호 또는 "all" (모두 받기). 한 이벤트는 한 번만"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    ev = d.get("event")
    if ev != "all":
        try:
            ev = int(ev)
        except (TypeError, ValueError):
            return _err("우편 번호가 이상합니다")
    gifts, mail_, bal, res = await run_in_threadpool(store.claim_mail, inst["id"], ev)
    return _ok({**bal, "result": res, "gifts": gifts, "mail": mail_})


@router.post("/draw")
async def draw(request: Request):
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    req = str(d.get("req", ""))
    if not REQ_RE.match(req):
        return _err("요청 번호가 이상합니다")
    rewarded = await _rewards(inst, d)   # 묶어 온 보상 먼저 (받은 꾸러미로 바로 뽑을 수 있게)
    rates = await run_in_threadpool(store.get_rates)
    seed = rules.roll_seed(rates)

    def save_row(con, now):
        con.execute("INSERT INTO seeds (sid, install, kind, ptype, rare, n, drawn) VALUES (?,?,?,?,?,?,?)",
                    (seed["sid"], inst["id"], seed["kind"], seed["ptype"], 1 if seed["rare"] else 0, seed["n"], now))

    result, bal, err = await run_in_threadpool(store.draw, inst["id"], req, "seed", "bundles", lambda: (seed, save_row))
    if err:
        await run_in_threadpool(store.reject, inst["id"], "no_bundle", "req=" + req)
        return _err("꾸러미가 없어요", 409, rewarded=rewarded, **bal)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"seed": result, "rewarded": rewarded, "rates": rates, **bal, **prog})


@router.post("/potdraw")
async def potdraw(request: Request):
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    req = str(d.get("req", ""))
    size = str(d.get("size", ""))
    if not REQ_RE.match(req) or size not in C.POT_SIZES:
        return _err("요청이 이상합니다")
    rewarded = await _rewards(inst, d)
    rates = await run_in_threadpool(store.get_rates)
    pot = rules.roll_pot(size, rates)

    def save_row(con, now):
        con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn, src) VALUES (?,?,?,?,?,?,'draw')",
                    (pot["pid"], inst["id"], pot["size"], 1 if pot["lux"] else 0, pot["n"], now))

    result, bal, err = await run_in_threadpool(store.draw, inst["id"], req, "pot", "tickets", lambda: (pot, save_row))
    if err:
        await run_in_threadpool(store.reject, inst["id"], "no_ticket", "req=" + req)
        return _err("화분 뽑기권이 없어요", 409, rewarded=rewarded, **bal)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"pot": result, "rewarded": rewarded, "rates": rates, **bal, **prog})


def _ids(d, key, rx):
    """맡긴 것 번호 3개 (서로 다름)"""
    xs = d.get(key)
    if not isinstance(xs, list) or len(xs) != C.CRAFT_COUNT:
        return None
    xs = [str(x) for x in xs]
    if len(set(xs)) != C.CRAFT_COUNT or not all(rx.match(x) for x in xs):
        return None
    return xs


@router.post("/fuse")
async def fuse(request: Request):
    """의문의 상인: 일반 씨앗·묘목 3개 → 고른 것(씨앗 flower · 묘목 tree)의 씨앗 하나, 정해진 확률로 고급 묘목"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    req = str(d.get("req", ""))
    sids = _ids(d, "sids", SID_RE)
    pick = str(d.get("pick", ""))
    if not REQ_RE.match(req) or sids is None or pick not in ("flower", "tree"):
        return _err("요청이 이상합니다")
    rates = await run_in_threadpool(store.get_rates)
    seed = rules.roll_fuse(rates, pick)

    def make():
        def save_row(con, now):
            con.execute("INSERT INTO seeds (sid, install, kind, ptype, rare, n, drawn, src) VALUES (?,?,?,?,0,?,?,'fuse')",
                        (seed["sid"], inst["id"], seed["kind"], seed["ptype"], seed["n"], now))
        return seed, save_row

    result, bal, err = await run_in_threadpool(store.fuse, inst["id"], req, sids, make)
    if err:
        await run_in_threadpool(store.reject, inst["id"], "fuse_" + err, ",".join(sids))
        return _err("맡길 수 없는 씨앗이 있어요 (이미 쓴 씨앗·신비한·고급 씨앗은 안 돼요)", 409, **bal)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"seed": result, "rates": rates, **bal, **prog})


@router.post("/kiln")
async def kiln(request: Request):
    """공방: 화분 3개 → 다시 구운 화분 하나 (크기는 아무거나, 정해진 확률로 고급)"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    req = str(d.get("req", ""))
    raw = d.get("pots")
    pots = []
    if isinstance(raw, list) and len(raw) == C.CRAFT_COUNT:
        for x in raw:
            if isinstance(x, dict) and SID_RE.match(str(x.get("pid", ""))):
                sid = str(x.get("sid", ""))
                pots.append({"pid": str(x["pid"]), "sid": sid if SID_RE.match(sid) else "", "size": str(x.get("size", "")), "lux": x.get("lux") is True})
    if not REQ_RE.match(req) or len(pots) != C.CRAFT_COUNT or len({p["pid"] for p in pots}) != C.CRAFT_COUNT:
        return _err("요청이 이상합니다")
    pids = [p["pid"] for p in pots]
    rates = await run_in_threadpool(store.get_rates)
    pot = rules.roll_kiln(rates)

    def make():
        def save_row(con, now):
            con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn, src) VALUES (?,?,?,?,?,?,'kiln')",
                        (pot["pid"], inst["id"], pot["size"], 1 if pot["lux"] else 0, pot["n"], now))
        return pot, save_row

    result, bal, err = await run_in_threadpool(store.kiln, inst["id"], req, pots, make)
    if err:
        await run_in_threadpool(store.reject, inst["id"], "kiln_" + err, ",".join(pids))
        return _err("맡길 수 없는 화분이 있어요", 409, **bal)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"pot": result, "rates": rates, **bal, **prog})


@router.post("/achieve")
async def achieve(request: Request):
    """도전과제 보상 받기 — 조건은 서버가 확인, 한 번만"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    key = str(d.get("key", ""))[:20]
    bal, res = await run_in_threadpool(store.achieve, inst["id"], key)
    if res == "not_yet":
        await run_in_threadpool(store.reject, inst["id"], "ach_not_yet", key)
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"result": res, "key": key, **bal, **prog})


@router.post("/daily")
async def daily(request: Request):
    """일일 퀘스트 보상 받기 — 서버 날짜로 하루에 한 번 (water·food = 오늘 물·영양제 준 횟수, 게임이 셈)"""
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    key = str(d.get("key", ""))[:20]
    try:
        water = max(0, min(999, int(d.get("water", 0))))
        food = max(0, min(999, int(d.get("food", 0))))
    except (TypeError, ValueError):
        water = food = 0
    bal, res = await run_in_threadpool(store.daily, inst["id"], key, water, food)
    if res == "not_yet":
        await run_in_threadpool(store.reject, inst["id"], "daily_not_yet", "%s w=%d f=%d" % (key, water, food))
    prog = await run_in_threadpool(store.progress_of, inst["id"])
    return _ok({"result": res, "key": key, **bal, **prog})


@router.post("/reward")
async def reward(request: Request):
    inst, bad = await _auth(request)
    if bad:
        return bad
    d = await _body(request) or {}
    sid = str(d.get("sid", ""))
    outcome = str(d.get("outcome", ""))
    if not SID_RE.match(sid) or outcome not in ("grown", "dead"):
        return _err("요청이 이상합니다")
    bal, err = await run_in_threadpool(store.reward, inst["id"], sid, outcome, rules.min_hours)
    if err == "dup":   # 이미 받은 보상: 다시 주지 않고 지금 개수만 (기록은 남김)
        await run_in_threadpool(store.reject, inst["id"], "reward_dup", sid)
        return _ok({**bal, "dup": True})
    if err == "early":
        await run_in_threadpool(store.reject, inst["id"], "reward_early", sid)
        return _err("아직 다 자랄 시간이 아니에요", 409, **bal)
    if err == "unknown":
        await run_in_threadpool(store.reject, inst["id"], "reward_unknown", sid)
        return _err("모르는 씨앗이에요", 404, **bal)
    return _ok(bal)


# ---------- 관리 ----------

def _admin(request):
    r = site_auth.check(request.headers.get("x-admin-key", ""), _ip(request))
    if r == "ok":
        return None
    if r == "locked":
        return _err("열쇠를 너무 많이 틀렸습니다. 10분 뒤에 다시 하세요", 429)
    return _err("열쇠가 맞지 않습니다", 403)


def _ts(v, default):
    """'2026-10-20T11:00' (한국 시간) 또는 숫자(유닉스 초) → 초"""
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        dt = datetime.datetime.fromisoformat(str(v))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=C.KST)
    return dt.timestamp()


@router.get("/admin/rates")
def admin_rates(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    return _ok({"rates": store.get_rates(), "defaults": C.RATE_DEFAULTS, "names": C.RATE_NAMES,
                "limits": {k: list(v) for k, v in C.RATE_LIMITS.items()}, "groups": C.RATE_GROUPS,
                "log": store.rows("SELECT * FROM rate_log ORDER BY id DESC LIMIT 50")})


@router.post("/admin/rates")
async def admin_set_rates(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    d = await _body(request) or {}
    try:
        new = rules.clean_rates(d.get("rates") or {})
    except ValueError as e:
        return _err(str(e))
    if not new:
        return _err("바꿀 확률이 없습니다")
    changed = await run_in_threadpool(store.set_rates, new, str(d.get("note", "")).strip())
    return _ok({"ok": True, "changed": changed, "rates": store.get_rates()})


@router.get("/admin/summary")
def admin_summary(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    now = time.time()
    day = now - 86400
    one = lambda sql, a=(): store.rows(sql, a)[0]
    return _ok({
        "installs": one("SELECT COUNT(*) n FROM installs")["n"],
        "active_7d": one("SELECT COUNT(*) n FROM installs WHERE last_seen>?", (now - 7 * 86400,))["n"],
        "active_1d": one("SELECT COUNT(*) n FROM installs WHERE last_seen>?", (day,))["n"],
        "bundles_total": one("SELECT COALESCE(SUM(bundles),0) n FROM installs")["n"],
        "tickets_total": one("SELECT COALESCE(SUM(tickets),0) n FROM installs")["n"],
        "draws_1d": one("SELECT COUNT(*) n FROM draws WHERE at>?", (day,))["n"],
        "rejects_1d": one("SELECT COUNT(*) n FROM rejects WHERE at>?", (day,))["n"],
        "bans_active": one("SELECT COUNT(*) n FROM bans WHERE active=1")["n"],
        "premium_1d": one("SELECT COUNT(*) n FROM seeds WHERE drawn>? AND kind='premium'", (day,))["n"],
        "now": now,
    })


@router.get("/admin/installs")
def admin_installs(request: Request, q: str = "", sort: str = "last_seen", limit: int = 100, offset: int = 0):
    bad = _admin(request)
    if bad:
        return bad
    order = {"last_seen": "last_seen DESC", "created": "created DESC", "bundles": "bundles DESC", "rejects": "rejects DESC"}.get(sort, "last_seen DESC")
    limit = max(1, min(500, limit))
    rows = store.rows(
        "SELECT i.id, i.created, i.last_seen, i.ver, i.bundles, i.tickets, i.device, i.migrated_bundles, "
        "(SELECT COUNT(*) FROM draws d WHERE d.install=i.id) draws, (SELECT COUNT(*) FROM rejects r WHERE r.install=i.id) rejects, "
        "(SELECT b.reason FROM bans b WHERE b.active=1 AND ((b.kind='install' AND b.value=i.id) OR (b.kind='device' AND b.value=i.device AND i.device<>'')) LIMIT 1) ban "
        "FROM installs i WHERE i.id LIKE ? OR i.device LIKE ? ORDER BY " + order + " LIMIT ? OFFSET ?",
        (q.lower() + "%", q.lower() + "%", limit, max(0, offset)))
    total = store.rows("SELECT COUNT(*) n FROM installs")[0]["n"]
    return _ok({"installs": rows, "total": total})


@router.get("/admin/installs/{iid}")
def admin_install(iid: str, request: Request):
    bad = _admin(request)
    if bad:
        return bad
    inst = store.install(iid)
    if not inst:
        return _err("없는 유저입니다", 404)
    inst.pop("secret_sha", None)
    q = lambda t, extra="": store.rows("SELECT * FROM %s WHERE install=? %s ORDER BY rowid DESC LIMIT 500" % (t, extra), (iid,))
    return _ok({
        "install": inst, "ban": store.ban_of(iid, inst["device"]),
        "ledger": q("ledger"), "draws": q("draws"), "seeds": q("seeds"), "pots": q("pots"), "grants": q("grants"), "rejects": q("rejects"),
        "achievements": q("achievements"), "daily": q("daily"),
        "same_device": store.rows("SELECT id, last_seen FROM installs WHERE device=? AND device<>'' AND id<>?", (inst["device"], iid)),
    })


@router.post("/admin/installs/{iid}/adjust")
async def admin_adjust(iid: str, request: Request):
    bad = _admin(request)
    if bad:
        return bad
    d = await _body(request) or {}
    try:
        db, dt = int(d.get("bundles", 0)), int(d.get("tickets", 0))
    except (TypeError, ValueError):
        return _err("숫자가 아닙니다")
    bal = await run_in_threadpool(store.adjust, iid, db, dt, str(d.get("reason", "관리")))
    return _ok(bal) if bal else _err("없는 유저입니다", 404)


@router.get("/admin/events")
def admin_events(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    ev = store.rows("SELECT e.*, (SELECT COUNT(*) FROM grants g WHERE g.event=e.id) granted, "
                    "(SELECT COUNT(*) FROM event_targets t WHERE t.event=e.id) targets FROM events e ORDER BY id DESC LIMIT 200")
    return _ok({"events": ev})


PREFIX_RE = re.compile(r"^[0-9a-f]{6,32}$")


def _resolve_ids(raw):
    """관리자가 적은 설치 번호들 → 전체 번호. 앞 6자리 이상이면 그 번호로 시작하는 설치본 하나를 찾음.
    (전체 번호들, 못 찾은 것 설명들) — 없거나 여러 개와 맞으면 조용히 버리지 않고 알려 줌"""
    out, bad = [], []
    for x in raw:
        s = re.sub(r"[\s\-…\.]", "", str(x)).lower()
        if not s:
            continue
        if not PREFIX_RE.match(s):
            bad.append(f"{str(x)[:40]} (번호 꼴이 아님)")
            continue
        hit = store.rows("SELECT id FROM installs WHERE id LIKE ? LIMIT 2", (s + "%",))
        if len(hit) == 1:
            out.append(hit[0]["id"])
        elif not hit:
            bad.append(f"{s} (없음)")
        else:
            bad.append(f"{s} (여러 설치본과 맞음 — 더 길게)")
    return list(dict.fromkeys(out)), bad


@router.post("/admin/events")
async def admin_add_event(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    d = await _body(request) or {}
    try:
        b, t = int(d.get("bundles", 0)), int(d.get("tickets", 0))
    except (TypeError, ValueError):
        return _err("개수는 숫자여야 합니다")
    if b < 0 or t < 0 or b + t == 0 or b > 99 or t > 99:
        return _err("꾸러미·뽑기권 중 하나 이상, 0~99개")
    msg = str(d.get("msg", "")).strip()[:60] or "선물이 도착했어요"
    now = time.time()
    start = _ts(d.get("start_at"), now)
    if start is None:
        return _err("시작 시각 꼴이 이상합니다 (예: 2026-10-20T11:00)")
    end = _ts(d.get("end_at"), start + C.EVENT_DAYS * 86400)
    if end is None or end <= start:
        return _err("끝 시각이 이상합니다")
    targets = d.get("targets")
    if targets is not None:
        if not isinstance(targets, list) or not targets or len(targets) > 5000:
            return _err("받을 유저를 골라 주세요")
        targets, bad = await run_in_threadpool(_resolve_ids, targets)
        if bad:
            return _err("이 번호는 못 찾았습니다 — " + " · ".join(bad[:20]))
        if not targets:
            return _err("받을 유저 아이디가 이상합니다")
    eid = await run_in_threadpool(store.add_event, start, end, b, t, msg, bool(d.get("include_new", True)), targets)
    return _ok({"ok": True, "id": eid})


@router.post("/admin/events/{eid}/cancel")
def admin_cancel_event(eid: int, request: Request):
    bad = _admin(request)
    if bad:
        return bad
    return _ok({"ok": store.cancel_event(eid)})


@router.get("/admin/bans")
def admin_bans(request: Request, active: int = 1):
    bad = _admin(request)
    if bad:
        return bad
    rows = store.rows("SELECT * FROM bans %s ORDER BY id DESC LIMIT 500" % ("WHERE active=1" if active else ""))
    return _ok({"bans": rows})


@router.post("/admin/bans")
async def admin_ban(request: Request):
    bad = _admin(request)
    if bad:
        return bad
    d = await _body(request) or {}
    reason = str(d.get("reason", "")).strip()
    if not reason:
        return _err("차단 사유를 적어 주세요")
    kind = d.get("kind")
    value = str(d.get("value", "")).lower()
    if kind == "install":
        if not ID_RE.match(value) or not store.install(value):
            return _err("없는 유저입니다", 404)
    elif kind == "device":
        if not DEVICE_RE.match(value):   # 설치 번호를 주면 그 컴퓨터 지문으로
            inst = store.install(value) if ID_RE.match(value) else None
            if not inst or not inst["device"]:
                return _err("컴퓨터 지문을 모릅니다 (아직 지문을 보낸 적 없는 유저)")
            value = inst["device"]
    else:
        return _err("차단 종류는 install 또는 device")
    bid = await run_in_threadpool(store.ban, kind, value, reason)
    return _ok({"ok": True, "id": bid})


@router.post("/admin/bans/{bid}/lift")
async def admin_unban(bid: int, request: Request):
    bad = _admin(request)
    if bad:
        return bad
    d = await _body(request) or {}
    return _ok({"ok": await run_in_threadpool(store.unban, bid, str(d.get("note", "")))})


@router.get("/admin/export/{table}")
def admin_export(table: str, request: Request):
    bad = _admin(request)
    if bad:
        return bad
    if table not in store.TABLES:
        return _err("없는 표입니다", 404)
    rows = store.rows("SELECT * FROM %s ORDER BY rowid" % table)
    for r in rows:
        r.pop("secret_sha", None)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="dotpot_%s.csv"' % table, "Cache-Control": "no-store"})
