"""site 의 댓글 규칙 층 - 올바른 댓글인지, 비밀번호, 그리고 화면에 늘어놓는 순서.

HTTP 도 디스크도 모른다. 값을 받아 검사하고 고친 값이나 이유(Invalid)를 돌려준다.

## 늘어놓는 순서 (깊이 2)
    본댓                          ← 최신 본댓이 위
      답글 A                      ← 답글은 오래된 것부터
        (A 에 단 답글은 깊이를 늘리지 않고 "@A닉네임" 을 붙여 A 바로 밑에)
      @A 답글 A-1
      @A-1 답글 A-1-1             ← 답에 답이 이어지면 그 글 바로 밑으로 계속
      답글 B
지운 글은 답이 달려 있으면 "삭제된 댓글" 자리로 남고, 없으면 아예 안 보인다.
"""
import hashlib
import hmac
import re
import secrets

from .service import Invalid

NICK_MAX = 20
BODY_MAX = 1000
PW_MIN, PW_MAX = 4, 40
RESERVED = {"관리자", "운영자", "작성자", "admin", "administrator", "owner"}

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


def _clean_text(v, limit, what):
    if not isinstance(v, str):
        raise Invalid("%s 이(가) 비었습니다" % what)
    v = _CTRL.sub("", v.replace("\r\n", "\n").replace("\r", "\n")).strip()
    v = re.sub(r"\n{4,}", "\n\n\n", v)              # 빈 줄 도배는 세 줄까지
    if not v:
        raise Invalid("%s 을(를) 적어 주세요" % what)
    if len(v) > limit:
        raise Invalid("%s 은(는) %d자까지입니다" % (what, limit))
    return v


def clean_comment(data, site_name=""):
    """방문자가 보낸 댓글 → (닉네임, 내용, 비밀번호)."""
    if not isinstance(data, dict):
        raise Invalid("댓글이 아닙니다")
    nick = _clean_text(data.get("nick"), NICK_MAX, "닉네임")
    if "\n" in nick:
        raise Invalid("닉네임은 한 줄로 적어 주세요")
    if nick.lower() in RESERVED or (site_name and nick.lower() == site_name.lower()):
        raise Invalid("그 닉네임은 쓸 수 없습니다")
    body = _clean_text(data.get("body"), BODY_MAX, "내용")
    pw = data.get("password")
    if not isinstance(pw, str) or not (PW_MIN <= len(pw) <= PW_MAX):
        raise Invalid("비밀번호는 %d~%d자입니다 (지울 때 씁니다)" % (PW_MIN, PW_MAX))
    return nick, body, pw


def clean_owner_comment(data):
    if not isinstance(data, dict):
        raise Invalid("댓글이 아닙니다")
    return _clean_text(data.get("body"), BODY_MAX, "내용")


# ---- 비밀번호: 원문은 안 남기고, 글마다 다른 소금을 친 느린 지문만 ----
def hash_pw(pw):
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return "%s$%s" % (salt, digest)


def check_pw(pw, stored):
    if not stored or not isinstance(pw, str) or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex(), digest)


# ---- 어디에 붙는가 ----
def place_reply(parent):
    """답할 글 → (본댓 번호, 답한 글 번호, @닉네임 또는 None). 본댓에 바로 단 답글은 @ 를 안 붙인다."""
    if parent["top"] is None:
        return parent["id"], parent["id"], None
    return parent["top"], parent["id"], parent["nick"]


# ---- 화면에 늘어놓기 ----
def _public(c):
    if c["deleted"]:
        return {"id": c["id"], "deleted": True, "created": c["created"]}
    return {"id": c["id"], "nick": c["nick"], "body": c["body"], "owner": bool(c["owner"]),
            "mention": c["mention"], "created": c["created"], "deleted": False}


def threads(rows):
    """한 작품의 글 전부 → [{본댓…, replies: [답글…]}] (위 순서대로). 보일 것만."""
    tops = [r for r in rows if r["top"] is None]
    by_target = {}
    for r in rows:
        if r["top"] is not None:
            by_target.setdefault(r["reply_to"], []).append(r)   # rows 는 오래된 것부터라 그대로 시간 순

    def live_under(cid):
        return any(not k["deleted"] or live_under(k["id"]) for k in by_target.get(cid, []))

    def walk(cid, out):
        for r in by_target.get(cid, []):
            if not r["deleted"] or live_under(r["id"]):      # 지운 글은 밑에 산 글이 있을 때만 자리로
                out.append(_public(r))
            walk(r["id"], out)
        return out

    result = []
    for t in reversed(tops):                                 # 최신 본댓이 위
        replies = walk(t["id"], [])
        if t["deleted"] and not replies:
            continue
        item = _public(t)
        item["replies"] = replies
        result.append(item)
    return result


def admin_view(c, titles):
    """관리 화면 목록 한 줄."""
    out = _public(c)
    out.update({"slug": c["slug"], "work": titles.get(c["slug"], c["slug"]), "who": c["who"], "is_reply": c["top"] is not None})
    return out
