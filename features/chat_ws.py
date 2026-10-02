"""서버 채팅의 **오가는 줄 다루기** - chat.py 가 읽어 쓴다.

왜 파일을 둘로 나눴나: `chat.py` 는 "무엇을 저장하고 무엇을 받아주는가"(계정·기록·한도)를
맡고, 여기는 "들어온 줄에 무엇을 하는가"를 맡는다. 한쪽을 고칠 때 다른 쪽을 읽을 필요가
없게 하려는 것이고, 기능 파일 하나가 400줄을 넘어가면서 그 경계가 흐려지기 시작했다.

새 명령이 생기면 `HANDLERS` 에 한 줄만 추가한다 - if/elif 사슬을 만들지 않는다
(다른 기능과 같은 규칙). **표에 없는 명령은 조용히 버린다** - 구버전 클라이언트가
모르는 것을 보내도 죽지 않아야 한다.
"""
import json
import secrets
import time

from features import chat as c


def err(text: str) -> dict:
    return {"type": "error", "text": text}


class Session:
    """연결 하나. 누가 붙어 있고 어디에 들어가 있는가."""

    def __init__(self, socket):
        self.socket = socket
        self.user_id = ""
        self.stamps = []        # 너무 빨리 보내는지 보는 창

    @property
    def logged_in(self) -> bool:
        return bool(self.user_id)

    def too_fast(self, now: float) -> bool:
        """한 연결이 초당 보낼 수 있는 줄을 넘었는가.

        넉넉히 두면 의미가 없고 빡빡하면 잠깐 몰릴 때 억울하게 끊긴다.
        전투 중계(features/battle.py)와 같은 방식이다.
        """
        self.stamps = [t for t in self.stamps if now - t < 1.0]
        if len(self.stamps) >= c.LIMITS["lines_per_sec"]:
            return True
        self.stamps.append(now)
        return False

    async def send(self, message: dict) -> None:
        await self.socket.send_text(json.dumps(message, ensure_ascii=False))


def members_of(channel: str) -> list:
    """그 방에 지금 있는 사람들 - 이름과 아이콘까지 같이 준다.

    IRC 에서는 이것들을 CTCP 로 따로 주고받아야 했고(아이콘은 300자씩 쪼개서),
    조각이 하나라도 빠지면 아무것도 안 떴다. 여기서는 그냥 같이 보낸다.
    """
    users = c.load_users()
    out = []
    for user_id in sorted(c.hub.room(channel).members):
        saved = users.get(user_id, {})
        out.append({"id": user_id, "nick": saved.get("nick", user_id),
                    "avatar": saved.get("avatar", "")})
    return out


async def do_register(s: Session, body: dict) -> dict:
    """계정을 만든다. **연결 하나로 가입과 로그인을 다 할 수 있게** 여기도 둔다 -
    가입만 HTTP 로 두면 클라이언트가 두 가지 길을 알아야 한다.

    판단은 chat.make_account 하나가 한다(HTTP 창구와 같은 규칙).
    """
    code, answer = c.make_account(body.get("id"), body.get("pw"))
    if code != 200:
        return {"type": "auth_result", "ok": False, "text": answer.get("error", "실패"),
                "made": False}
    return {"type": "auth_result", "ok": True, "made": True, "id": answer["id"]}


async def do_login(s: Session, body: dict) -> dict:
    # **저장된 아이디로 바꿔 쓴다.** 대소문자를 안 가리므로 사람이 친 것과 다를 수
    # 있는데, 다른 사람 화면에는 처음 적은 그대로 보여야 한다
    user_id = c.check_login(body.get("id"), body.get("pw"))
    if user_id is None:
        return {"type": "auth_result", "ok": False, "text": "아이디나 비밀번호가 다릅니다"}
    # 한 아이디로 두 군데서 들어오면 **먼저 있던 쪽을 내보낸다.** 둘 다 두면 같은
    # 사람이 두 번 보이고, 귓속말을 누구에게 보낼지도 갈린다
    old = c.hub.online.get(user_id)
    if old is not None:
        try:
            await old.send_text(json.dumps(
                {"type": "system", "text": "다른 곳에서 접속해 연결을 끊습니다."},
                ensure_ascii=False))
            await old.close()
        except Exception:
            pass
    s.user_id = user_id
    c.hub.online[user_id] = s.socket
    saved = c.load_users().get(user_id, {})
    return {"type": "auth_result", "ok": True, "id": user_id,
            "nick": saved.get("nick", user_id), "avatar": saved.get("avatar", "")}


async def do_join(s: Session, body: dict):
    channel = body.get("channel")
    if not c.is_channel(channel):
        return err("채널 이름이 올바르지 않습니다")
    channels = c.load_channels()
    room = channels.get(channel)
    if room is None:
        if len(channels) >= c.LIMITS["max_channels"]:
            return err("채널이 너무 많습니다")
        # **없으면 만든다.** IRC 와 같은 느낌이다 - 들어가면 곧 생긴다
        channels[channel] = {"key": c.clean_text(body.get("key"), 64), "made": time.time()}
        c.save_channels(channels)
        room = channels[channel]
    if room.get("key") and room["key"] != c.clean_text(body.get("key"), 64):
        return err("채널 비밀번호가 다릅니다")
    if len(c.hub.room(channel).members) >= c.LIMITS["members_per_channel"]:
        return err("이 채널은 자리가 찼습니다")

    c.hub.room(channel).add(s.user_id, s.socket)

    # **들어온 사람에게 먼저 답한다.** 그래야 받는 쪽이 "내가 어느 방에 들어갔다"를
    # 알고 나서 그 방의 참여자 목록을 받는다. 순서가 뒤집히면 클라이언트가 모르는
    # 방의 목록을 먼저 받게 되고, 그걸 어떻게 다룰지가 또 하나의 규칙이 된다
    await s.send({"type": "channel_result", "ok": True, "channel": channel,
                  # **지난 기록을 서버가 바로 준다.** IRC 모드에서는 각자 올린 것을
                  # 모아 중복을 걸러 돌려줘야 했다(features/logs.py 의 _is_same)
                  "history": c.read_history(channel),
                  "users": members_of(channel)})
    await c.hub.tell(channel, {"type": "system", "channel": channel,
                               "text": f"{s.user_id}님이 들어왔습니다."}, skip=s.user_id)
    await c.hub.tell(channel, {"type": "userlist", "channel": channel,
                               "users": members_of(channel)})
    return None


async def do_leave(s: Session, body: dict) -> dict:
    channel = body.get("channel")
    if not c.is_channel(channel) or s.user_id not in c.hub.room(channel).members:
        return err("그 채널에 들어가 있지 않습니다")
    c.hub.room(channel).remove(s.user_id)
    await c.hub.tell(channel, {"type": "system", "channel": channel,
                               "text": f"{s.user_id}님이 나갔습니다."})
    await c.hub.tell(channel, {"type": "userlist", "channel": channel,
                               "users": members_of(channel)})
    return {"type": "leave_result", "ok": True, "channel": channel}


async def do_msg(s: Session, body: dict):
    channel = body.get("channel")
    text = c.clean_text(body.get("text"), c.LIMITS["text_chars"])
    if not text:
        return None                      # 빈 줄은 조용히 버린다
    if not c.is_channel(channel) or s.user_id not in c.hub.room(channel).members:
        return err("그 채널에 들어가 있지 않습니다")

    line = {"id": secrets.token_hex(8), "ts": time.time(),
            "sender": s.user_id, "text": text}
    c.add_history(channel, line)
    # **보낸 사람에게도 돌려준다.** IRC 는 안 돌려줘서 각 클라이언트가 자기 말을 직접
    # 화면에 올려야 했다(로컬 에코) - 그래서 "내 화면에만 있는 말"이 생길 여지가 있었다
    await c.hub.tell(channel, {"type": "chat", "channel": channel, **line})
    return None


async def do_whisper(s: Session, body: dict):
    """귓속말. **IRC 에서는 기록도 알림도 안 되던 것이다.**"""
    to = body.get("to")
    text = c.clean_text(body.get("text"), c.LIMITS["text_chars"])
    if not c.is_id(to) or not text:
        return err("보낼 사람과 내용이 필요합니다")
    line = {"id": secrets.token_hex(8), "ts": time.time(),
            "sender": s.user_id, "to": to, "text": text}
    sent = await c.hub.tell_one(to, {"type": "whisper", **line})
    await s.send({"type": "whisper", **line})      # 내 화면에도 남는다
    if not sent:
        return {"type": "system", "text": f"{to}님은 지금 접속해 있지 않습니다."}
    return None


async def do_set_nick(s: Session, body: dict) -> dict:
    """표시 이름을 바꾼다. **한글도 된다** - IRC 서버가 거절하던 것이다."""
    nick = c.clean_nick(body.get("nick"))
    if not nick:
        return err("이름이 비어 있습니다")
    users = c.load_users()
    if s.user_id not in users:
        return err("계정을 찾을 수 없습니다")
    users[s.user_id]["nick"] = nick
    c.save_users(users)
    for channel in c.hub.channels_of(s.user_id):
        await c.hub.tell(channel, {"type": "member_nickname", "channel": channel,
                                   "id": s.user_id, "nick": nick})
    return {"type": "member_nickname", "id": s.user_id, "nick": nick}


async def do_set_avatar(s: Session, body: dict) -> dict:
    """아이콘을 바꾼다. **쪼개 보내지 않는다** - IRC 는 300자씩 나눠야 했고, 조각이
    빠지면 아무것도 안 떴다."""
    avatar = body.get("avatar")
    if not isinstance(avatar, str) or len(avatar) > c.LIMITS["avatar_chars"]:
        return err("아이콘이 너무 큽니다")
    users = c.load_users()
    if s.user_id not in users:
        return err("계정을 찾을 수 없습니다")
    users[s.user_id]["avatar"] = avatar
    c.save_users(users)
    for channel in c.hub.channels_of(s.user_id):
        await c.hub.tell(channel, {"type": "member_avatar", "channel": channel,
                                   "id": s.user_id, "avatar": avatar})
    return {"type": "member_avatar", "id": s.user_id, "avatar": avatar}


async def do_ping(s: Session, body: dict) -> dict:
    """살아 있나. **답이 있어야 한다** - 없으면 클라이언트가 조용한 연결을 죽은 것으로
    보고 스스로 끊는다(실측 2026-10-02: PC 가 170초마다 그랬다).

    로그인 전에도 답한다 - 살아 있는지 묻는 데 자격이 필요할 이유가 없다.
    """
    return {"type": "pong", "ts": time.time()}


async def do_channels(s: Session, body: dict) -> dict:
    """서버에 있는 방을 전부 알려준다 - 들어갈 방을 **보고 고를 수 있게**.

    사람이 안 들어가 있는 방도 보여준다(방은 서버에 남아 있고 기록도 하루치 남는다).
    비밀번호가 걸린 방은 **그 사실만** 알려준다 - 비밀번호 자체는 절대 안 보낸다.
    """
    channels = c.load_channels()
    out = []
    for name, room in channels.items():
        out.append({
            "name": name,
            "users": len(c.hub.room(name).members),
            "made": room.get("made", 0),
            "locked": bool(room.get("key")),
        })
    # 사람이 있는 방부터, 그 다음은 이름순 - 들어갈 만한 곳이 위로 온다
    out.sort(key=lambda one: (-one["users"], one["name"]))
    return {"type": "channel_list", "channels": out}


# 로그인해야 쓸 수 있는 명령들
NEED_LOGIN = {"join", "leave", "msg", "whisper", "set_nickname", "set_avatar"}

HANDLERS = {
    "ping": do_ping,
    "channels": do_channels,
    "register": do_register,
    "login": do_login,
    "join": do_join,
    "leave": do_leave,
    "msg": do_msg,
    "whisper": do_whisper,
    "set_nickname": do_set_nick,
    "set_avatar": do_set_avatar,
}


async def serve(socket) -> None:
    """연결 하나를 끝까지 돌본다."""
    s = Session(socket)
    try:
        while True:
            raw = await socket.receive_text()
            if len(raw) > c.LIMITS["text_chars"] + c.LIMITS["avatar_chars"] + 1000:
                break                      # 터무니없이 긴 줄 - 끊는다
            if s.too_fast(time.time()):
                await s.send(err("너무 빠르게 보내고 있습니다"))
                break
            try:
                body = json.loads(raw)
            except ValueError:
                continue                   # 읽을 수 없는 줄은 조용히 버린다
            if not isinstance(body, dict):
                continue
            handler = HANDLERS.get(body.get("cmd"))
            if handler is None:
                continue                   # 모르는 명령은 조용히 버린다
            if body.get("cmd") in NEED_LOGIN and not s.logged_in:
                await s.send(err("먼저 로그인해야 합니다"))
                continue
            answer = await handler(s, body)
            if answer is not None:
                await s.send(answer)
    except Exception:
        # 끊김은 사고가 아니다. 어떤 이유로 끝나든 아래 뒷정리는 해야 한다
        pass
    finally:
        await _cleanup(s, socket)


async def _cleanup(s: Session, socket) -> None:
    """나간 것을 **그 방 사람들에게 알린다** - 안 알리면 참여자 목록에 유령이 남는다."""
    if not s.logged_in:
        return
    for channel in c.hub.channels_of(s.user_id):
        c.hub.room(channel).remove(s.user_id)
        await c.hub.tell(channel, {"type": "system", "channel": channel,
                                   "text": f"{s.user_id}님이 접속을 종료했습니다."})
        await c.hub.tell(channel, {"type": "userlist", "channel": channel,
                                   "users": members_of(channel)})
    if c.hub.online.get(s.user_id) is socket:
        c.hub.online.pop(s.user_id, None)
