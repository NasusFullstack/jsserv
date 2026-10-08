"""site 의 통계 층 - 방문·플레이·다운로드 수를 SQLite 하나에 쌓는다.

## IP 는 저장하지 않는다
방문자를 가리는 데는 `sha256(비밀 소금 + 날짜 + IP + 브라우저)` 앞 16자리만 쓴다. 날짜가 섞여 있어서
**오늘의 지문으로 어제의 같은 사람을 알아낼 수 없고**, 그 지문도 이틀 지나면 지운다.
남는 것은 날짜별 숫자뿐이다.

## 세는 것
    views       페이지를 연 횟수(새로고침 포함)
    visitors    그날 처음 온 사람 수
    plays       그날 그 작품을 처음 연 사람 수(같은 사람이 열 번 열어도 1)
    downloads   그날 그 작품을 처음 받은 사람 수
작품별 숫자는 `plays:<작품>`·`downloads:<작품>` 으로 따로 쌓는다.

여러 프로세스가 동시에 써도 되게 SQLite(WAL)를 쓴다. 쓰는 일은 요청마다 짧은 거래 한 번.
"""
import datetime
import hashlib
import os
import secrets
import sqlite3
import threading

from . import config as C

_init_lock = threading.Lock()
_ready = set()


def _connect():
    os.makedirs(os.path.dirname(C.STATS_DB), exist_ok=True)
    con = sqlite3.connect(C.STATS_DB, timeout=5)
    if C.STATS_DB not in _ready:
        with _init_lock:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS daily (day TEXT, metric TEXT, n INTEGER NOT NULL DEFAULT 0,
                                                  PRIMARY KEY (day, metric));
                CREATE TABLE IF NOT EXISTS seen  (day TEXT, scope TEXT, vid TEXT, PRIMARY KEY (day, scope, vid));
                CREATE TABLE IF NOT EXISTS refs  (day TEXT, host TEXT, n INTEGER NOT NULL DEFAULT 0,
                                                  PRIMARY KEY (day, host));
                CREATE TABLE IF NOT EXISTS meta  (k TEXT PRIMARY KEY, v TEXT);
            """)
            _ready.add(C.STATS_DB)
    return con


def today(now=None):
    return (now or datetime.datetime.now(C.KST)).astimezone(C.KST).strftime("%Y-%m-%d")


def _salt(con):
    row = con.execute("SELECT v FROM meta WHERE k='salt'").fetchone()
    if row:
        return row[0]
    salt = secrets.token_hex(32)
    con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('salt', ?)", (salt,))
    return con.execute("SELECT v FROM meta WHERE k='salt'").fetchone()[0]


def _bump(con, day, metric, n=1):
    con.execute("INSERT INTO daily (day, metric, n) VALUES (?, ?, ?) "
                "ON CONFLICT(day, metric) DO UPDATE SET n = n + excluded.n", (day, metric, n))


def _first(con, day, scope, vid):
    """그날 그 범위에서 처음 보는 사람이면 True (그리고 기억해 둔다)."""
    cur = con.execute("INSERT OR IGNORE INTO seen (day, scope, vid) VALUES (?, ?, ?)", (day, scope, vid))
    return cur.rowcount == 1


def record(kind, ip, agent, slug=None, ref_host=None, day=None):
    """kind: 'view' | 'play' | 'download'. 페이지를 연 것(view·play)은 방문으로도 센다."""
    day = day or today()
    con = _connect()
    try:
        with con:
            vid = hashlib.sha256(("%s|%s|%s|%s" % (_salt(con), day, ip, agent)).encode()).hexdigest()[:16]
            if kind in ("view", "play"):
                _bump(con, day, "views")
                if _first(con, day, "site", vid):
                    _bump(con, day, "visitors")
                if ref_host:
                    con.execute("INSERT INTO refs (day, host, n) VALUES (?, ?, 1) "
                                "ON CONFLICT(day, host) DO UPDATE SET n = n + 1", (day, ref_host[:100]))
            if kind in ("play", "download") and slug:
                metric = "plays" if kind == "play" else "downloads"
                if _first(con, day, "%s:%s" % (metric, slug), vid):
                    _bump(con, day, metric)
                    _bump(con, day, "%s:%s" % (metric, slug))
            # 지문은 이틀만 둔다
            if _first(con, day, "_sweep", "-"):
                con.execute("DELETE FROM seen WHERE day < ?", (_day_before(day, 1),))
    finally:
        con.close()


def _day_before(day, n):
    d = datetime.date.fromisoformat(day) - datetime.timedelta(days=n)
    return d.isoformat()


def summary(days=14, refs_days=0):
    """오늘·누적·최근 days 일 흐름·작품별 누적. refs_days > 0 이면 들어온 곳 순위도."""
    day = today()
    first = _day_before(day, days - 1)
    con = _connect()
    try:
        rows = con.execute("SELECT day, metric, n FROM daily WHERE day >= ?", (first,)).fetchall()
        totals = dict(con.execute("SELECT metric, SUM(n) FROM daily GROUP BY metric").fetchall())
        refs = []
        if refs_days:
            refs = con.execute("SELECT host, SUM(n) AS c FROM refs WHERE day >= ? GROUP BY host ORDER BY c DESC LIMIT 15",
                               (_day_before(day, refs_days - 1),)).fetchall()
    finally:
        con.close()
    by_day = {}
    for d, metric, n in rows:
        by_day.setdefault(d, {})[metric] = n
    main = ("visitors", "views", "plays", "downloads")
    series = []
    for i in range(days):
        d = _day_before(day, days - 1 - i)
        series.append(dict({"day": d}, **{m: by_day.get(d, {}).get(m, 0) for m in main}))
    per_work = {}
    for metric, n in totals.items():
        if ":" in metric:
            what, slug = metric.split(":", 1)
            per_work.setdefault(slug, {"plays": 0, "downloads": 0})[what] = n
    return {
        "today": {m: by_day.get(day, {}).get(m, 0) for m in main},
        "total": {m: totals.get(m, 0) or 0 for m in main},
        "days": series,
        "works": per_work,
        "refs": [{"host": h, "n": n} for h, n in refs],
    }
