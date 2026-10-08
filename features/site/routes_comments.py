"""site 의 댓글 주소 층.

    GET    /api/works/<작품>/comments          댓글 목록 (늘어놓는 순서 그대로)
    POST   /api/works/<작품>/comments          쓰기 {nick, password, body, parent?}  parent = 답할 글 번호
    DELETE /api/comments/<번호>                지우기 {password}

    (열쇠 X-Admin-Key)
    GET    /api/admin/comments                 최근 댓글 (모든 작품)
    POST   /api/admin/works/<작품>/comments    작성자로 쓰기 {body, parent?}
    DELETE /api/admin/comments/<번호>          아무 글이나 지우기

## 도배·장난 막기
- 같은 사람(IP 지문)은 1분에 3개, 하루에 60개까지
- 사람 눈에 안 보이는 칸(website)에 뭔가 적혀 오면 로봇으로 보고 저장하지 않는다(성공한 척만)
- 다른 사이트가 몰래 글을 쓰게 못 하도록 JSON 으로 보낸 것만 받는다
"""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from . import comment_rules as R
from . import comments, store
from .routes import _admin, _err, _ip, _public, _settings, _works
from .service import Invalid

router = APIRouter()

PER_MINUTE = 3
PER_DAY = 60


async def _json(request):
    """JSON 본문. 다른 사이트의 폼 전송(text/plain 등)은 거절."""
    if "application/json" not in request.headers.get("content-type", ""):
        raise Invalid("JSON 으로 보내 주세요")
    if int(request.headers.get("content-length") or 0) > 16 * 1024:
        raise Invalid("너무 깁니다")
    try:
        data = await request.json()
    except ValueError:
        raise Invalid("JSON 이 아닙니다")
    if not isinstance(data, dict):
        raise Invalid("JSON 이 아닙니다")
    return data


def _parent(slug, data):
    """답할 글 (없으면 None = 본댓). 다른 작품의 글이나 지운 글에는 못 단다."""
    pid = data.get("parent")
    if pid in (None, ""):
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise Invalid("답할 글 번호가 이상합니다")
    p = comments.get(pid)
    if not p or p["slug"] != slug or p["deleted"]:
        raise LookupError
    return p


def _listing(slug):
    rows = comments.for_work(slug)
    return {"count": sum(1 for r in rows if not r["deleted"]), "threads": R.threads(rows)}


@router.get("/api/works/{slug}/comments")
def list_comments(slug: str):
    if not _public(slug):
        return _err("없는 작품", 404)
    return _listing(slug)


@router.post("/api/works/{slug}/comments")
async def post_comment(slug: str, request: Request):
    if not _public(slug):
        return _err("없는 작품", 404)
    try:
        data = await _json(request)
        if str(data.get("website") or "").strip():          # 로봇 함정 칸
            return {"ok": True, **_listing(slug)}
        nick, body, pw = R.clean_comment(data, _settings().get("name", ""))
        parent = _parent(slug, data)
    except Invalid as e:
        return _err(str(e), 400)
    except LookupError:
        return _err("답할 글이 없습니다 (지워졌을 수 있습니다)", 404)
    who = comments.who_of(_ip(request))
    if comments.recent_by(who, 60) >= PER_MINUTE:
        return _err("너무 빨리 쓰고 있습니다. 잠시 뒤에 다시 써 주세요", 429)
    if comments.recent_by(who, 86400) >= PER_DAY:
        return _err("오늘은 더 쓸 수 없습니다", 429)
    top, reply_to, mention = R.place_reply(parent) if parent else (None, None, None)
    pw_hash = await run_in_threadpool(R.hash_pw, pw)
    cid = comments.add(slug, nick, body, pw=pw_hash, top=top, reply_to=reply_to, mention=mention,
                       who=who, created=store.now_iso())
    return {"ok": True, "id": cid, **_listing(slug)}


@router.delete("/api/comments/{cid}")
async def delete_comment(cid: int, request: Request):
    try:
        data = await _json(request)
    except Invalid as e:
        return _err(str(e), 400)
    c = comments.get(cid)
    if not c or c["deleted"] or not _public(c["slug"]):
        return _err("없는 글", 404)
    if c["owner"]:
        return _err("작성자 글은 관리 화면에서만 지울 수 있습니다", 403)
    ok = await run_in_threadpool(R.check_pw, data.get("password"), c["pw"])
    if not ok:
        return _err("비밀번호가 맞지 않습니다", 403)
    comments.mark_deleted(cid)      # 내용은 바로 사라지고, 답이 달려 있으면 "삭제된 댓글" 자리만 남는다
    return {"ok": True, **_listing(c["slug"])}


# ---- 관리 ----
@router.get("/api/admin/comments")
def admin_list(request: Request):
    denied = _admin(request)
    if denied:
        return denied
    titles = {w["slug"]: w.get("title", w["slug"]) for w in _works()}
    return {"comments": [R.admin_view(c, titles) for c in comments.recent(200)], "counts": comments.counts()}


@router.post("/api/admin/works/{slug}/comments")
async def admin_post(slug: str, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    if not store.work(slug):
        return _err("없는 작품", 404)
    try:
        data = await _json(request)
        body = R.clean_owner_comment(data)
        parent = _parent(slug, data)
    except Invalid as e:
        return _err(str(e), 400)
    except LookupError:
        return _err("답할 글이 없습니다", 404)
    top, reply_to, mention = R.place_reply(parent) if parent else (None, None, None)
    cid = comments.add(slug, _settings().get("name") or "작성자", body, top=top, reply_to=reply_to,
                       mention=mention, owner=True, created=store.now_iso())
    return {"ok": True, "id": cid}


@router.delete("/api/admin/comments/{cid}")
def admin_delete(cid: int, request: Request):
    denied = _admin(request)
    if denied:
        return denied
    c = comments.get(cid)
    if not c or c["deleted"]:
        return _err("없는 글", 404)
    comments.mark_deleted(cid)
    return {"ok": True}
