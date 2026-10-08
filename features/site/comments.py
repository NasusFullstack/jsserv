"""site 의 댓글 저장 층 - 작품마다 댓글·답글을 SQLite 하나에 쌓는다.

    top       본댓이면 NULL, 답글이면 그 본댓 번호 (깊이는 언제나 2: 본댓 → 답글)
    reply_to  답한 글 번호 (본댓에 바로 단 답글이면 본댓, 답글에 단 답글이면 그 답글)
    mention   답글에 단 답글이면 그 글쓴이 닉네임 (화면에 @닉네임 으로)
    owner     주인이 관리 화면에서 쓴 글 (작성자 표시)
    who       글쓴이 지문 sha256(비밀 소금 + IP) 앞 12자리 - 도배 막기·관리 화면 구분용, IP 자체는 안 남긴다
    deleted   지운 글 (답글이 달린 본댓은 "삭제된 댓글"로 자리만 남긴다)

**무엇이 올바른 댓글인지는 모른다**(service 가 검사). 여기는 쓰고 읽기만.
"""
import hashlib
import os
import secrets
import sqlite3
import threading
import time

from . import config as C

DB = os.path.join(C.DATA, "comments.sqlite3")
_ready = set()
_lock = threading.Lock()


def _connect():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    if DB not in _ready:
        with _lock:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL,
                    top INTEGER,
                    reply_to INTEGER,
                    mention TEXT,
                    nick TEXT NOT NULL,
                    body TEXT NOT NULL,
                    pw TEXT,
                    owner INTEGER NOT NULL DEFAULT 0,
                    who TEXT,
                    ts REAL NOT NULL,
                    created TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS comments_slug ON comments (slug, deleted);
                CREATE INDEX IF NOT EXISTS comments_who ON comments (who, ts);
                CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            """)
            _ready.add(DB)
    return con


def who_of(ip):
    """IP → 지문 (같은 사람인지만 알 수 있고 IP 는 거꾸로 못 알아낸다)."""
    con = _connect()
    try:
        with con:
            row = con.execute("SELECT v FROM meta WHERE k='salt'").fetchone()
            if not row:
                con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('salt', ?)", (secrets.token_hex(32),))
                row = con.execute("SELECT v FROM meta WHERE k='salt'").fetchone()
    finally:
        con.close()
    return hashlib.sha256(("%s|%s" % (row[0], ip)).encode()).hexdigest()[:12]


def add(slug, nick, body, pw=None, top=None, reply_to=None, mention=None, owner=False, who=None, created=""):
    con = _connect()
    try:
        with con:
            cur = con.execute(
                "INSERT INTO comments (slug, top, reply_to, mention, nick, body, pw, owner, who, ts, created) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, top, reply_to, mention, nick, body, pw, 1 if owner else 0, who, time.time(), created))
            return cur.lastrowid
    finally:
        con.close()


def get(cid):
    con = _connect()
    try:
        row = con.execute("SELECT * FROM comments WHERE id = ?", (cid,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def for_work(slug):
    """그 작품의 글 전부(지운 것 포함 - 자리 표시가 필요할 수 있어서). 오래된 것부터."""
    con = _connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM comments WHERE slug = ? ORDER BY id", (slug,))]
    finally:
        con.close()


def mark_deleted(cid):
    con = _connect()
    try:
        with con:
            con.execute("UPDATE comments SET deleted = 1, body = '', pw = NULL WHERE id = ?", (cid,))
    finally:
        con.close()


def counts():
    """작품별 살아 있는 댓글 수."""
    con = _connect()
    try:
        return dict(con.execute("SELECT slug, COUNT(*) FROM comments WHERE deleted = 0 GROUP BY slug").fetchall())
    finally:
        con.close()


def recent_by(who, seconds):
    """그 사람이 최근 몇 초 안에 쓴 글 수 (도배 막기)."""
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM comments WHERE who = ? AND ts > ?", (who, time.time() - seconds)).fetchone()[0]
    finally:
        con.close()


def recent(limit=100):
    """관리 화면: 최근 글 (지운 것 제외)."""
    con = _connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM comments WHERE deleted = 0 ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        con.close()


def remove_work(slug):
    """작품을 지우면 그 댓글도."""
    con = _connect()
    try:
        with con:
            con.execute("DELETE FROM comments WHERE slug = ?", (slug,))
    finally:
        con.close()
