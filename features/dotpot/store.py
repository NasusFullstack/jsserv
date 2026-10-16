"""화분키우기 서버의 저장 층 - SQLite 하나. 설치본마다 꾸러미·뽑기권 수와 뽑기·보상·이벤트·거절 기록.

설치본은 게임이 처음 켤 때 만든 무작위 번호다(이름·계정·PC 정보 없음). 비밀값은 지문(SHA-256)만 둔다.
잔액이 바뀌는 일은 모두 ledger 에 한 줄씩 남긴다 → 관리 화면에서 그대로(로우 데이터) 볼 수 있다.
쓰기는 BEGIN IMMEDIATE 로 하나씩 (동시에 와도 꾸러미가 두 번 깎이거나 늘지 않게).
"""
import json
import os
import sqlite3
import threading
import time

from . import config as C

_init_lock = threading.Lock()
_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS installs (
    id TEXT PRIMARY KEY, secret_sha TEXT NOT NULL, created REAL NOT NULL, last_seen REAL NOT NULL,
    ver TEXT NOT NULL DEFAULT '', bundles INTEGER NOT NULL, tickets INTEGER NOT NULL,
    migrated_bundles INTEGER NOT NULL DEFAULT 0, migrated_tickets INTEGER NOT NULL DEFAULT 0,
    device TEXT NOT NULL DEFAULT '', legacy_pots INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS installs_device ON installs(device);
CREATE TABLE IF NOT EXISTS bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, value TEXT NOT NULL, reason TEXT NOT NULL,
    at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, lifted_at REAL, lift_note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS bans_value ON bans(value);
CREATE TABLE IF NOT EXISTS seeds (
    sid TEXT NOT NULL, install TEXT NOT NULL, kind TEXT NOT NULL, ptype TEXT NOT NULL DEFAULT '',
    rare INTEGER NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, drawn REAL NOT NULL,
    legacy INTEGER NOT NULL DEFAULT 0, rewarded TEXT, rewarded_at REAL,
    used INTEGER NOT NULL DEFAULT 0, src TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (install, sid));
CREATE INDEX IF NOT EXISTS seeds_install ON seeds(install);
CREATE TABLE IF NOT EXISTS pots (
    pid TEXT NOT NULL, install TEXT NOT NULL, size TEXT NOT NULL, lux INTEGER NOT NULL, n INTEGER NOT NULL, drawn REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0, legacy INTEGER NOT NULL DEFAULT 0, src TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (install, pid));
CREATE TABLE IF NOT EXISTS achievements (install TEXT NOT NULL, key TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (install, key));
CREATE INDEX IF NOT EXISTS pots_install ON pots(install);
CREATE TABLE IF NOT EXISTS draws (
    install TEXT NOT NULL, req TEXT NOT NULL, at REAL NOT NULL, what TEXT NOT NULL, result TEXT NOT NULL,
    PRIMARY KEY (install, req));
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, start_at REAL NOT NULL, end_at REAL NOT NULL,
    bundles INTEGER NOT NULL, tickets INTEGER NOT NULL, msg TEXT NOT NULL, include_new INTEGER NOT NULL,
    cancelled INTEGER NOT NULL DEFAULT 0, target_all INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS event_targets (event INTEGER NOT NULL, install TEXT NOT NULL, PRIMARY KEY (event, install));
CREATE TABLE IF NOT EXISTS grants (
    install TEXT NOT NULL, event INTEGER NOT NULL, at REAL NOT NULL, PRIMARY KEY (install, event));
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT, install TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL,
    d_bundles INTEGER NOT NULL, d_tickets INTEGER NOT NULL, ref TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ledger_install ON ledger(install);
CREATE TABLE IF NOT EXISTS rates (key TEXT PRIMARY KEY, value REAL NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rate_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, key TEXT NOT NULL, old REAL NOT NULL, new REAL NOT NULL, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS rejects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, install TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS rejects_install ON rejects(install);
"""


def connect():
    global _ready
    os.makedirs(C.DATA, exist_ok=True)
    con = sqlite3.connect(C.DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    if not _ready:
        with _init_lock:
            if not _ready:
                con.executescript(SCHEMA)
                _migrate(con)
                _ready = True
    return con


def _migrate(con):
    """예전 판 DB 를 새 꼴로 (칸 더하기 · 화분 열쇠를 (유저, 번호)로)"""
    cols = lambda t: {r["name"] for r in con.execute("PRAGMA table_info(%s)" % t)}
    if "legacy_pots" not in cols("installs"):
        con.execute("ALTER TABLE installs ADD COLUMN legacy_pots INTEGER NOT NULL DEFAULT 0")
    for c, d in (("used", "INTEGER NOT NULL DEFAULT 0"), ("src", "TEXT NOT NULL DEFAULT ''")):
        if c not in cols("seeds"):
            con.execute("ALTER TABLE seeds ADD COLUMN %s %s" % (c, d))
    pk = [r["name"] for r in sorted(con.execute("PRAGMA table_info(pots)"), key=lambda r: r["pk"]) if r["pk"]]
    if pk != ["install", "pid"]:
        con.executescript("""
BEGIN;
CREATE TABLE pots_new (
    pid TEXT NOT NULL, install TEXT NOT NULL, size TEXT NOT NULL, lux INTEGER NOT NULL, n INTEGER NOT NULL, drawn REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0, legacy INTEGER NOT NULL DEFAULT 0, src TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (install, pid));
INSERT INTO pots_new (pid, install, size, lux, n, drawn) SELECT pid, install, size, lux, n, drawn FROM pots;
DROP TABLE pots;
ALTER TABLE pots_new RENAME TO pots;
CREATE INDEX IF NOT EXISTS pots_install ON pots(install);
COMMIT;
""")


class Tx:
    """with Tx() as con: — BEGIN IMMEDIATE … COMMIT (예외면 ROLLBACK)"""

    def __enter__(self):
        self.con = connect()
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, et, ev, tb):
        self.con.execute("ROLLBACK" if et else "COMMIT")
        self.con.close()
        return False


def _ledger(con, install, reason, db, dt, ref="", at=None):
    con.execute("INSERT INTO ledger (install, at, reason, d_bundles, d_tickets, ref) VALUES (?,?,?,?,?,?)",
                (install, at or time.time(), reason, db, dt, ref))


def reject(install, reason, detail=""):
    with Tx() as con:
        con.execute("INSERT INTO rejects (install, at, reason, detail) VALUES (?,?,?,?)", (install, time.time(), reason, detail[:300]))


# ---- 설치본 ----

def register(iid, secret_sha, ver, bundles, tickets, legacy, migrated, device=""):
    now = time.time()
    with Tx() as con:
        con.execute("INSERT INTO installs (id, secret_sha, created, last_seen, ver, bundles, tickets, migrated_bundles, migrated_tickets, device) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", (iid, secret_sha, now, now, ver, bundles, tickets,
                                                     bundles if migrated else 0, tickets if migrated else 0, device))
        _ledger(con, iid, "migrate" if migrated else "start", bundles, tickets, "", now)
        for sid, kind in legacy:
            con.execute("INSERT OR IGNORE INTO seeds (sid, install, kind, drawn, legacy) VALUES (?,?,?,?,1)", (sid, iid, kind, now))


def install(iid):
    con = connect()
    try:
        r = con.execute("SELECT * FROM installs WHERE id=?", (iid,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def touch(iid, ver, device=""):
    """처음 받은 컴퓨터 지문은 고정 (나중에 다른 지문을 보내도 바꾸지 않음 — 차단을 피하지 못하게)"""
    with Tx() as con:
        con.execute("UPDATE installs SET last_seen=?, ver=?, device=CASE WHEN device='' THEN ? ELSE device END WHERE id=?",
                    (time.time(), ver[:20], device, iid))


# ---- 차단: 설치본 또는 컴퓨터(기기 지문) ----

def ban_of(iid, device=""):
    """차단돼 있으면 {id, kind, reason, at}, 아니면 None. 저장된 지문과 이번에 보낸 지문을 둘 다 봄"""
    con = connect()
    try:
        r = con.execute("SELECT device FROM installs WHERE id=?", (iid,)).fetchone()
        stored = r["device"] if r else ""
        r = con.execute("SELECT id, kind, reason, at FROM bans WHERE active=1 AND ((kind='install' AND value=?) OR "
                        "(kind='device' AND value<>'' AND (value=? OR value=?))) ORDER BY id DESC LIMIT 1", (iid, device, stored)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def ban(kind, value, reason):
    with Tx() as con:
        cur = con.execute("INSERT INTO bans (kind, value, reason, at) VALUES (?,?,?,?)", (kind, value, reason[:300], time.time()))
        return cur.lastrowid


def unban(bid, note=""):
    with Tx() as con:
        return con.execute("UPDATE bans SET active=0, lifted_at=?, lift_note=? WHERE id=? AND active=1",
                           (time.time(), note[:200], bid)).rowcount > 0


def balance(con, iid):
    r = con.execute("SELECT bundles, tickets FROM installs WHERE id=?", (iid,)).fetchone()
    return {"bundles": r["bundles"], "tickets": r["tickets"]}


# ---- 이벤트: 받을 차례인 이벤트를 이 설치본에 지급 (켤 때·창을 열 때·뽑을 때 부름) ----

def apply_events(iid, now=None):
    now = now or time.time()
    gifts = []
    with Tx() as con:
        inst = con.execute("SELECT created FROM installs WHERE id=?", (iid,)).fetchone()
        rows = con.execute("SELECT * FROM events WHERE cancelled=0 AND start_at<=? AND end_at>=? AND id NOT IN "
                           "(SELECT event FROM grants WHERE install=?)", (now, now, iid)).fetchall()
        for e in rows:
            if e["target_all"]:
                if not e["include_new"] and inst["created"] > e["start_at"]:
                    continue
            elif not con.execute("SELECT 1 FROM event_targets WHERE event=? AND install=?", (e["id"], iid)).fetchone():
                continue
            con.execute("INSERT INTO grants (install, event, at) VALUES (?,?,?)", (iid, e["id"], now))
            con.execute("UPDATE installs SET bundles=MIN(?, bundles+?), tickets=MIN(?, tickets+?) WHERE id=?",
                        (C.BALANCE_MAX, e["bundles"], C.BALANCE_MAX, e["tickets"], iid))
            _ledger(con, iid, "event", e["bundles"], e["tickets"], str(e["id"]), now)
            gifts.append({"event": e["id"], "msg": e["msg"], "bundles": e["bundles"], "tickets": e["tickets"]})
        bal = balance(con, iid)
    return gifts, bal


# ---- 뽑기: 같은 요청 번호면 앞 결과 그대로 (네트워크 재시도에 두 번 깎이지 않게) ----

def draw(iid, req, what, cost_col, make):
    """cost_col = 'bundles' | 'tickets'. make() → (결과 dict, 기록할 행 함수). 돌려줌: (결과, 잔액, 오류)"""
    now = time.time()
    with Tx() as con:
        old = con.execute("SELECT result FROM draws WHERE install=? AND req=?", (iid, req)).fetchone()
        if old:
            return json.loads(old["result"]), balance(con, iid), None
        bal = balance(con, iid)
        if bal[cost_col] <= 0:
            return None, bal, "none"
        result, save_row = make()
        con.execute("UPDATE installs SET %s=%s-1 WHERE id=?" % (cost_col, cost_col), (iid,))
        save_row(con, now)
        con.execute("INSERT INTO draws (install, req, at, what, result) VALUES (?,?,?,?,?)", (iid, req, now, what, json.dumps(result)))
        _ledger(con, iid, "draw_" + what, -1 if cost_col == "bundles" else 0, -1 if cost_col == "tickets" else 0,
                result.get("sid") or result.get("pid") or "", now)
        return result, balance(con, iid), None


# ---- 보상: 씨앗 하나당 한 번 (다 키움 = 꾸러미+뽑기권, 시듦 = 꾸러미) ----

def reward(iid, sid, outcome, min_hours):
    now = time.time()
    with Tx() as con:
        s = con.execute("SELECT * FROM seeds WHERE sid=? AND install=?", (sid, iid)).fetchone()
        if not s:
            return balance(con, iid), "unknown"
        if s["rewarded"]:
            return balance(con, iid), "dup"
        if s["used"]:   # 의문의 상인에게 맡긴 씨앗 → 보상 없음
            return balance(con, iid), "used"
        if outcome == "grown" and not s["legacy"] and now - s["drawn"] < min_hours(s["kind"]) * 3600.0:
            return balance(con, iid), "early"
        db, dt = (1, 1) if outcome == "grown" else (1, 0)
        con.execute("UPDATE seeds SET rewarded=?, rewarded_at=? WHERE install=? AND sid=?", (outcome, now, iid, sid))
        con.execute("UPDATE installs SET bundles=MIN(?, bundles+?), tickets=MIN(?, tickets+?) WHERE id=?",
                    (C.BALANCE_MAX, db, C.BALANCE_MAX, dt, iid))
        _ledger(con, iid, "reward_" + outcome, db, dt, sid, now)
        return balance(con, iid), None


# ---- 의문의 상인 · 공방 · 도전과제 ----

def progress(con, iid):
    """도전과제 진행 (서버 기준): 모은 화분 수 · 연 꾸러미 수 · 받은 도전과제"""
    pots = con.execute("SELECT COUNT(*) n FROM pots WHERE install=?", (iid,)).fetchone()["n"]
    seeds = con.execute("SELECT COUNT(*) n FROM draws WHERE install=? AND what='seed'", (iid,)).fetchone()["n"]
    ach = [r["key"] for r in con.execute("SELECT key FROM achievements WHERE install=? ORDER BY at", (iid,))]
    return {"stats": {"pots": pots, "seeds": seeds}, "ach": ach}


def _craft(iid, req, what, table, col, ids, check, make):
    """맡긴 것 3개(ids)를 쓰고 새것 하나: 같은 요청 번호면 같은 결과. 돌려줌 (결과, 잔액, 오류)"""
    now = time.time()
    with Tx() as con:
        old = con.execute("SELECT result FROM draws WHERE install=? AND req=?", (iid, req)).fetchone()
        if old:
            return json.loads(old["result"]), balance(con, iid), None
        rows = [con.execute("SELECT * FROM %s WHERE install=? AND %s=?" % (table, col), (iid, x)).fetchone() for x in ids]
        if any(r is None for r in rows):
            return None, balance(con, iid), "unknown"
        if any(r["used"] for r in rows) or not all(check(r) for r in rows):
            return None, balance(con, iid), "bad"
        result, save_row = make()
        con.executemany("UPDATE %s SET used=1 WHERE install=? AND %s=?" % (table, col), [(iid, x) for x in ids])
        save_row(con, now)
        con.execute("INSERT INTO draws (install, req, at, what, result) VALUES (?,?,?,?,?)", (iid, req, now, what, json.dumps(result)))
        _ledger(con, iid, what, 0, 0, "%s ← %s" % (result.get("sid") or result.get("pid"), ",".join(ids)), now)
        return result, balance(con, iid), None


def fuse(iid, req, sids, make):
    return _craft(iid, req, "fuse", "seeds", "sid", sids,
                  lambda r: r["kind"] in ("flower", "tree") and not r["rare"] and not r["rewarded"], make)


def _register_pots(con, iid, pots, now):
    """공방에 맡기는 화분 중 서버가 모르는 것을 등록 (기본 화분 · 예전 판 화분). 등록 못 하면 False"""
    inst = con.execute("SELECT * FROM installs WHERE id=?", (iid,)).fetchone()
    moved = inst["migrated_bundles"] or inst["migrated_tickets"] or con.execute(
        "SELECT 1 FROM seeds WHERE install=? AND legacy=1 LIMIT 1", (iid,)).fetchone()
    for p in pots:
        if con.execute("SELECT 1 FROM pots WHERE install=? AND pid=?", (iid, p["pid"])).fetchone():
            continue
        if p.get("sid"):
            if not con.execute("SELECT 1 FROM seeds WHERE install=? AND sid=?", (iid, p["sid"])).fetchone():
                return False
            if con.execute("SELECT 1 FROM pots WHERE install=? AND src=?", (iid, "seed:" + p["sid"])).fetchone():
                return False   # 그 씨앗의 기본 화분은 이미 있음
            con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn, src) VALUES (?,?,'small',0,0,?,?)", (p["pid"], iid, now, "seed:" + p["sid"]))
        else:
            n = con.execute("SELECT COUNT(*) n FROM pots WHERE install=? AND legacy=1", (iid,)).fetchone()["n"]
            if not moved or n >= C.LEGACY_POTS_MAX or p.get("size") not in C.POT_SIZES:
                return False
            con.execute("INSERT INTO pots (pid, install, size, lux, n, drawn, legacy, src) VALUES (?,?,?,?,0,?,1,'legacy')",
                        (p["pid"], iid, p["size"], 1 if p.get("lux") else 0, now))
    return True


class _NoReg(Exception):
    pass


def kiln(iid, req, pots, make):
    now = time.time()
    try:
        with Tx() as con:   # 먼저 모르는 화분 등록 (하나라도 안 되면 모두 되돌림)
            old = con.execute("SELECT 1 FROM draws WHERE install=? AND req=?", (iid, req)).fetchone()
            if not old and not _register_pots(con, iid, pots, now):
                raise _NoReg()
    except _NoReg:
        con = connect()
        try:
            return None, balance(con, iid), "unknown"
        finally:
            con.close()
    return _craft(iid, req, "kiln", "pots", "pid", [p["pid"] for p in pots], lambda r: True, make)


def achieve(iid, key):
    """도전과제 보상: 조건을 서버가 확인하고 한 번만. 돌려줌 (잔액, 결과 ok·dup·not_yet·unknown)"""
    now = time.time()
    if key not in C.ACHIEVEMENTS:
        with Tx() as con:
            return balance(con, iid), "unknown"
    with Tx() as con:
        if con.execute("SELECT 1 FROM achievements WHERE install=? AND key=?", (iid, key)).fetchone():
            return balance(con, iid), "dup"
        pr = progress(con, iid)["stats"]
        inst = con.execute("SELECT * FROM installs WHERE id=?", (iid,)).fetchone()
        ok = False
        if key == "pots30":
            ok = pr["pots"] >= C.ACH_POTS
        elif key == "seeds30":
            ok = pr["seeds"] >= C.ACH_SEEDS
        elif key.startswith("stage"):
            st = int(key[5:])
            moved = inst["migrated_bundles"] or inst["migrated_tickets"] or con.execute(
                "SELECT 1 FROM seeds WHERE install=? AND legacy=1 LIMIT 1", (iid,)).fetchone()
            ok = bool(moved) or now - inst["created"] >= (st - 1) * C.STAGE_HOURS * 3600.0
        if not ok:
            return balance(con, iid), "not_yet"
        db, dt = C.ACHIEVEMENTS[key]
        con.execute("INSERT INTO achievements (install, key, at) VALUES (?,?,?)", (iid, key, now))
        con.execute("UPDATE installs SET bundles=MIN(?, bundles+?), tickets=MIN(?, tickets+?) WHERE id=?",
                    (C.BALANCE_MAX, db, C.BALANCE_MAX, dt, iid))
        _ledger(con, iid, "ach_" + key, db, dt, key, now)
        return balance(con, iid), "ok"


def progress_of(iid):
    con = connect()
    try:
        return progress(con, iid)
    finally:
        con.close()


# ---- 관리 ----

def add_event(start_at, end_at, bundles, tickets, msg, include_new, targets=None):
    """targets = None 이면 모두에게, 설치 번호 목록이면 그 설치본에게만"""
    with Tx() as con:
        cur = con.execute("INSERT INTO events (created, start_at, end_at, bundles, tickets, msg, include_new, target_all) VALUES (?,?,?,?,?,?,?,?)",
                          (time.time(), start_at, end_at, bundles, tickets, msg, 1 if include_new else 0, 0 if targets is not None else 1))
        eid = cur.lastrowid
        for t in targets or []:
            con.execute("INSERT OR IGNORE INTO event_targets (event, install) VALUES (?,?)", (eid, t))
        return eid


def cancel_event(eid):
    with Tx() as con:
        return con.execute("UPDATE events SET cancelled=1 WHERE id=?", (eid,)).rowcount > 0


def adjust(iid, db, dt, reason):
    with Tx() as con:
        if not con.execute("SELECT 1 FROM installs WHERE id=?", (iid,)).fetchone():
            return None
        con.execute("UPDATE installs SET bundles=MAX(0, MIN(?, bundles+?)), tickets=MAX(0, MIN(?, tickets+?)) WHERE id=?",
                    (C.BALANCE_MAX, db, C.BALANCE_MAX, dt, iid))
        _ledger(con, iid, "admin", db, dt, reason[:100])
        return balance(con, iid)


def rows(sql, args=()):
    con = connect()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


TABLES = ("installs", "seeds", "pots", "draws", "events", "event_targets", "grants", "ledger", "rejects", "bans", "rate_log", "achievements")


# ---- 뽑기 확률 (기본값 + 관리 화면에서 바꾼 값) ----

def get_rates():
    out = dict(C.RATE_DEFAULTS)
    for r in rows("SELECT key, value FROM rates"):
        if r["key"] in out:
            out[r["key"]] = float(r["value"])
    return out


def set_rates(new, note=""):
    """바뀐 것만 저장하고 기록 (예전 값 → 새 값). 바뀐 이름들을 돌려줌"""
    now = time.time()
    changed = []
    with Tx() as con:
        cur = dict(C.RATE_DEFAULTS)
        for r in con.execute("SELECT key, value FROM rates"):
            if r["key"] in cur:
                cur[r["key"]] = float(r["value"])
        for k, v in new.items():
            if abs(cur[k] - v) < 1e-9:
                continue
            con.execute("INSERT INTO rates (key, value, at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, at=excluded.at", (k, v, now))
            con.execute("INSERT INTO rate_log (at, key, old, new, note) VALUES (?,?,?,?,?)", (now, k, cur[k], v, note[:200]))
            changed.append(k)
    return changed
