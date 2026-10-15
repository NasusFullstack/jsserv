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
    device TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS installs_device ON installs(device);
CREATE TABLE IF NOT EXISTS bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, value TEXT NOT NULL, reason TEXT NOT NULL,
    at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, lifted_at REAL, lift_note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS bans_value ON bans(value);
CREATE TABLE IF NOT EXISTS seeds (
    sid TEXT NOT NULL, install TEXT NOT NULL, kind TEXT NOT NULL, ptype TEXT NOT NULL DEFAULT '',
    rare INTEGER NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, drawn REAL NOT NULL,
    legacy INTEGER NOT NULL DEFAULT 0, rewarded TEXT, rewarded_at REAL,
    PRIMARY KEY (install, sid));
CREATE INDEX IF NOT EXISTS seeds_install ON seeds(install);
CREATE TABLE IF NOT EXISTS pots (
    pid TEXT PRIMARY KEY, install TEXT NOT NULL, size TEXT NOT NULL, lux INTEGER NOT NULL, n INTEGER NOT NULL, drawn REAL NOT NULL);
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
                _ready = True
    return con


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
        if outcome == "grown" and not s["legacy"] and now - s["drawn"] < min_hours(s["kind"]) * 3600.0:
            return balance(con, iid), "early"
        db, dt = (1, 1) if outcome == "grown" else (1, 0)
        con.execute("UPDATE seeds SET rewarded=?, rewarded_at=? WHERE install=? AND sid=?", (outcome, now, iid, sid))
        con.execute("UPDATE installs SET bundles=MIN(?, bundles+?), tickets=MIN(?, tickets+?) WHERE id=?",
                    (C.BALANCE_MAX, db, C.BALANCE_MAX, dt, iid))
        _ledger(con, iid, "reward_" + outcome, db, dt, sid, now)
        return balance(con, iid), None


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


TABLES = ("installs", "seeds", "pots", "draws", "events", "event_targets", "grants", "ledger", "rejects", "bans", "rate_log")


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
