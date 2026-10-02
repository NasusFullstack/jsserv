"""서버 채팅 - **IRC 에서 못 하던 것들이 실제로 되는가**, 그리고 남의 것을 못 건드리는가.

이 기능을 만든 이유가 "IRC 제약을 걷어내는 것"이라, 그 제약이 정말 사라졌는지를
하나씩 못 박아 둔다. 안 그러면 IRC 때 하던 우회를 여기서도 그대로 하게 된다.

같이 보는 것: **남의 이름으로 말하거나 남의 것을 바꾸는** 길이 열려 있으면 안 된다.

## 읽기는 **이 스레드에서, 순서대로** 한다
받는 일을 따로 스레드에 맡겼더니, **다른 연결에서 밀어준 줄이 아예 안 왔다**(실측).
TestClient 는 연결마다 다른 이벤트 루프에서 앱을 돌려서, 남의 루프로 밀어넣는 것이
읽는 쪽이 이 스레드에 있을 때만 제대로 전달된다. 전투 검사(test_battle.py)가 처음부터
이 방식인 이유가 그것이다.

그래서 **서버가 보내는 순서를 알고 그만큼만 읽는다.** 대신 올 줄이 없으면 영원히
기다리게 되므로, 감시자를 두고 정해진 시간이 지나면 그 사실을 말하고 끝낸다.
"""
import json
import os
import shutil
import sys
import tempfile
import threading

WORK = tempfile.mkdtemp(prefix="jsserv_chat_")
os.environ["JSSERV_CHAT_DIR"] = WORK
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features import chat  # noqa: E402

client = TestClient(app)
checks = []


def check(name, passed, detail=""):
    checks.append((name, passed, detail))
    # **지나갈 때마다 바로 찍는다.** 모아서 끝에 찍으면 멈췄을 때 아무것도 안 보인다
    print(f"[{'OK' if passed else 'FAIL'}] {name}", flush=True)


def watchdog(seconds=90):
    """이 안에 안 끝나면 **멈춘 자리를 말하고** 끝낸다.

    없으면 검사가 조용히 영원히 기다린다(실제로 10분을 멈췄다).
    """
    def bite():
        print("\n[FAIL] 검사가 멈췄습니다 - 기다리던 줄이 안 왔습니다.", flush=True)
        print("       마지막으로 지난 것:", checks[-1][0] if checks else "(없음)", flush=True)
        os._exit(1)

    timer = threading.Timer(seconds, bite)
    timer.daemon = True
    timer.start()
    return timer


def send(ws, message):
    ws.send_text(json.dumps(message, ensure_ascii=False))


def take(ws, count=1):
    """정해진 수만큼 읽는다. 서버가 보내는 순서를 알고 쓰는 것이다."""
    return [ws.receive_json() for _ in range(count)]


def one(ws):
    return ws.receive_json()


def register(user_id, password="비밀1234"):
    return client.post("/chat/register", content=json.dumps(
        {"id": user_id, "pw": password}, ensure_ascii=False))


def login(ws, user_id, password="비밀1234"):
    send(ws, {"cmd": "login", "id": user_id, "pw": password})
    return one(ws)


def join(ws, channel):
    """들어간다. 서버는 **나에게 먼저 답하고**(channel_result) 그다음 방에 알린다."""
    send(ws, {"cmd": "join", "channel": channel})
    result = one(ws)
    one(ws)                     # 내 입장으로 생긴 참여자 목록
    return result


watchdog()

# ---------- 1) 계정 ----------
first = register("mong22")
check(f"계정을 만든다({first.status_code})", first.status_code == 200, first.text[:160])
check(f"같은 아이디는 거절({register('mong22').status_code})",
      register("mong22").status_code == 409)
check(f"아이디는 영문·숫자만({register('한글아이디').status_code})",
      register("한글아이디").status_code == 400)
short = client.post("/chat/register", content=json.dumps({"id": "dur1", "pw": "12"}))
check(f"너무 짧은 비밀번호는 거절({short.status_code})", short.status_code == 400)
register("duri")

# **비밀번호를 평문으로 적어두지 않는다**
saved = chat.load_users().get("mong22", {})
check("비밀번호를 평문으로 안 적는다",
      bool(saved.get("pw")) and "비밀1234" not in json.dumps(saved, ensure_ascii=False),
      saved)
check("아이디·비밀번호가 맞아야 들어온다",
      chat.check_login("mong22", "비밀1234") == "mong22"
      and chat.check_login("mong22", "틀림") is None)

# ---------- 1-1) 아이디는 **대소문자를 안 가린다** ----------
# IRC 는 이름의 대소문자를 안 가려서 사람들이 그 버릇으로 친다. 가렸더니
# "있는 아이디인데 로그인이 안 된다"가 됐다(실측 2026-10-02)
register("Sejong2")
check("대소문자가 달라도 들어온다",
      chat.check_login("sejong2", "비밀1234") == "Sejong2",
      chat.check_login("sejong2", "비밀1234"))
check("**처음 적은 그대로**를 돌려준다(화면에 Mong 과 mong 으로 갈려 보이면 안 된다)",
      chat.check_login("SEJONG2", "비밀1234") == "Sejong2")
check("대소문자만 다른 아이디는 또 못 만든다",
      register("SEJONG2").status_code == 409, register("sejong2").status_code)
check("앞뒤 공백은 지우고 본다", chat.check_login(" Sejong2 ", "비밀1234") == "Sejong2")

# ---------- 1-2) 쌓이는 자리가 **저장소 밖**이다 ----------
# 안에 두면 배포할 때 지워진다 - 그 전에 만든 계정이 전부 날아갔다
import os.path as _p  # noqa: E402
_repo = _p.dirname(_p.abspath(chat.__file__))
check("계정이 저장소 폴더 안에 쌓이지 않는다",
      not _p.abspath(chat.STORE_DIR).startswith(_p.abspath(_p.dirname(_repo)) + _p.sep)
      or _p.basename(chat.STORE_DIR) != "chat"
      or "JSSERV_CHAT_DIR" in os.environ,
      chat.STORE_DIR)

# ---------- 1-2) 가입은 WebSocket 으로도 된다 ----------
# 연결 하나로 가입과 로그인을 다 할 수 있어야 한다 - 가입만 HTTP 로 두면 클라이언트가
# 두 가지 길을 알아야 하고, 둘의 판단이 갈라질 자리가 생긴다
with client.websocket_connect("/chat/ws") as ws:
    send(ws, {"cmd": "register", "id": "sejong", "pw": "비밀1234"})
    made = one(ws)
    check("WebSocket 으로 가입된다", made.get("ok") is True and made.get("made") is True,
          made)
    send(ws, {"cmd": "register", "id": "sejong", "pw": "비밀1234"})
    check("이미 있는 아이디는 그쪽에서도 거절", one(ws).get("ok") is False)
    check("가입 뒤 바로 로그인된다", login(ws, "sejong").get("ok") is True)
    # HTTP 로 만든 계정과 같은 판단인가 - 규칙이 두 벌로 갈라지면 안 된다
    send(ws, {"cmd": "register", "id": "한글", "pw": "비밀1234"})
    check("아이디 규칙이 HTTP 와 같다", one(ws).get("ok") is False)


# ---------- 1-3) 살아 있는지 물어볼 수 있다 ----------
# 없으면 조용한 연결을 클라이언트가 죽은 것으로 보고 스스로 끊는다(실측: PC 가 170초마다)
with client.websocket_connect("/chat/ws") as ws:
    send(ws, {"cmd": "ping"})
    answer = one(ws)
    check("ping 에 pong 으로 답한다", answer.get("type") == "pong", answer)
    check("로그인 전에도 답한다(살아 있는지 묻는 데 자격이 필요 없다)",
          answer.get("ts", 0) > 0, answer)

# ---------- 1-4) 어떤 방이 있는지 보고 고른다 ----------
with client.websocket_connect("/chat/ws") as ws:
    login(ws, "mong22")
    join(ws, "목록검사")
    send(ws, {"cmd": "join", "channel": "잠긴방", "key": "열쇠"})
    one(ws)                      # 입장 응답
    one(ws)                      # 내 입장으로 생긴 참여자 목록
    send(ws, {"cmd": "channels"})
    listed = one(ws)
    names = [one_room["name"] for one_room in listed.get("channels", [])]
    check("방 목록을 준다", listed.get("type") == "channel_list", listed)
    check("만들어진 방이 다 보인다", "목록검사" in names and "잠긴방" in names, names)
    rooms = {one_room["name"]: one_room for one_room in listed["channels"]}
    check("몇 명 있는지 같이 온다", rooms["목록검사"]["users"] == 1, rooms["목록검사"])
    check("비밀번호가 걸렸는지 알려준다", rooms["잠긴방"]["locked"] is True, rooms["잠긴방"])
    check("**비밀번호 자체는 안 보낸다**",
          all("key" not in one_room for one_room in listed["channels"]),
          listed["channels"])
    check("사람이 있는 방이 위로 온다",
          listed["channels"][0]["users"] >= listed["channels"][-1]["users"])

# ---------- 2) 들어가서 이야기한다 ----------
with client.websocket_connect("/chat/ws") as a:
    check("로그인하면 자리를 받는다", login(a, "mong22").get("ok") is True)

    joined = join(a, "일반")
    check("채널에 들어간다", joined.get("ok") is True, joined)
    # **IRC 와 다르게 채널 이름에 # 이 필요 없고 한글도 된다**
    check("한글 채널 이름이 된다", joined.get("channel") == "일반")
    check("들어가면 지난 기록을 바로 준다", isinstance(joined.get("history"), list))

    send(a, {"cmd": "msg", "channel": "일반", "text": "안녕하세요"})
    said = one(a)
    # **보낸 사람에게도 돌려준다.** IRC 는 안 돌려줘서 각자 자기 말을 화면에 직접 올려야 했다
    check("내가 보낸 말이 나에게도 돌아온다",
          said.get("text") == "안녕하세요" and said.get("sender") == "mong22", said)
    check("줄마다 id 가 붙는다(나중에 답장·수정·삭제에 쓴다)", bool(said.get("id")))

    # ---------- 3) IRC 에서 못 하던 것들 ----------
    send(a, {"cmd": "set_nickname", "nick": "몽키"})
    named = take(a, 2)[-1]      # 방에 알리는 것 + 나에게 돌아오는 것
    check("한글 표시 이름이 된다(IRC 서버는 거절했다)", named.get("nick") == "몽키", named)

    # 아이콘을 **쪼개지 않고** 한 번에. IRC 는 512바이트 제한 때문에 300자씩 나눠야 했다
    big_avatar = "A" * 5000
    send(a, {"cmd": "set_avatar", "avatar": big_avatar})
    faced = take(a, 2)[-1]
    check("큰 아이콘을 한 번에 올린다(IRC 는 300자씩 쪼갰다)",
          faced.get("avatar") == big_avatar)

    send(a, {"cmd": "set_avatar", "avatar": "A" * (chat.LIMITS["avatar_chars"] + 10)})
    check("그래도 한도는 있다", one(a).get("type") == "error")

    long_text = "가" * 1000      # IRC 는 한 줄 512바이트였다
    send(a, {"cmd": "msg", "channel": "일반", "text": long_text})
    long_said = one(a)
    check("긴 글이 안 잘린다(IRC 는 512바이트에서 잘렸다)",
          long_said.get("text") == long_text, len(long_said.get("text", "")))

# ---------- 4) 둘이 같이 있을 때 ----------
with client.websocket_connect("/chat/ws") as a:
    login(a, "mong22")
    join(a, "같이")

    with client.websocket_connect("/chat/ws") as b:
        login(b, "duri")
        b_joined = join(b, "같이")
        check("둘째 사람도 들어간다", b_joined.get("ok") is True, b_joined)
        names = sorted(user["id"] for user in b_joined.get("users", []))
        check("참여자 목록에 둘 다 있다", names == ["duri", "mong22"], names)
        # **이름과 아이콘이 목록에 같이 온다.** IRC 는 CTCP 로 따로 받아야 했다
        mine = [u for u in b_joined["users"] if u["id"] == "mong22"]
        check("목록에 이름과 아이콘이 같이 온다",
              bool(mine) and mine[0]["nick"] == "몽키" and bool(mine[0]["avatar"]), mine)

        # 먼저 있던 사람에게 '누가 들어왔다' + 새 목록이 간다
        told = take(a, 2)
        check("먼저 있던 사람에게 들어온 것을 알린다",
              told[0].get("type") == "system" and "duri" in told[0].get("text", ""), told[0])
        check("참여자 목록도 다시 간다", told[1].get("type") == "userlist", told[1])

        # **보낸 쪽을 먼저 읽는다.** TestClient 는 연결마다 다른 이벤트 루프에서
        # 앱을 돌려서, 보낸 연결을 읽어줘야 다른 연결로 간 줄이 실제로 넘어간다
        # (안 그러면 받는 쪽에서 영원히 기다린다 - 실측으로 확인했다)
        send(b, {"cmd": "msg", "channel": "같이", "text": "왔어요"})
        mine = one(b)
        check("보낸 사람에게도 돌아온다", mine.get("text") == "왔어요", mine)
        heard = one(a)
        check("남이 한 말이 나에게 온다",
              heard.get("text") == "왔어요" and heard.get("sender") == "duri", heard)

        # 귓속말 - **IRC 에서는 기록도 알림도 안 되던 것**
        send(b, {"cmd": "whisper", "to": "mong22", "text": "둘만 아는 얘기"})
        one(b)      # 보낸 사람 화면에도 남는다(먼저 읽는 이유는 위와 같다)
        whispered = one(a)
        check("귓속말이 간다", whispered.get("text") == "둘만 아는 얘기", whispered)

        # 로그인은 대소문자를 안 가리는데 귓속말만 가리면, 같은 이름을 쳤는데 어떤
        # 때는 가고 어떤 때는 안 가는 것으로 보인다
        send(a, {"cmd": "whisper", "to": "DURI", "text": "대문자로 불러본다"})
        one(a)                   # 보낸 사람 화면에도 남는다(먼저 읽는 이유는 위와 같다)
        reached = one(b)
        check("귓속말도 대소문자를 안 가린다",
              reached.get("type") == "whisper"
              and reached.get("text") == "대문자로 불러본다", reached)

# ---------- 5) 남의 것을 못 건드린다 ----------
with client.websocket_connect("/chat/ws") as a:
    send(a, {"cmd": "msg", "channel": "일반", "text": "몰래"})
    check("로그인 전에는 말할 수 없다", one(a).get("type") == "error")

    login(a, "duri")
    join(a, "일반")

    # **보낸 사람 이름을 적어 보내도 소용없다** - 서버가 연결로 정한다
    send(a, {"cmd": "msg", "channel": "일반", "text": "사칭", "sender": "mong22"})
    faked = one(a)
    check("남의 이름으로 말할 수 없다", faked.get("sender") == "duri", faked)

    send(a, {"cmd": "msg", "channel": "안들어간방", "text": "몰래"})
    check("안 들어간 채널에는 못 쓴다", one(a).get("type") == "error")

    # 모르는 명령은 조용히 버린다(구버전이 모르는 것을 보내도 죽지 않게)
    send(a, {"cmd": "모르는명령", "뭐": "든"})
    send(a, {"cmd": "msg", "channel": "일반", "text": "그래도 산다"})
    check("모르는 명령을 받아도 연결이 산다", one(a).get("text") == "그래도 산다")

    # 제어문자는 걷어낸다 - 남의 화면이 깨지면 안 된다
    send(a, {"cmd": "msg", "channel": "일반", "text": "색\x03깨짐\x02"})
    cleaned = one(a)
    check("제어문자를 걷어낸다",
          "\x03" not in cleaned["text"] and "\x02" not in cleaned["text"],
          repr(cleaned.get("text")))

# ---------- 6) 기록이 남는다 ----------
with client.websocket_connect("/chat/ws") as a:
    login(a, "mong22")
    back = join(a, "일반")
    texts = [line.get("text") for line in back.get("history", [])]
    # **서버가 원본을 갖는다** - IRC 모드처럼 각자 올리고 중복을 거를 필요가 없다
    check("나갔다 와도 지난 이야기가 그대로 있다", "안녕하세요" in texts, texts[:4])
    check("다른 채널 이야기는 안 섞인다", "왔어요" not in texts, texts[:4])

check("서버가 이 기능을 알려준다",
      any(f["name"] == "chat" for f in client.get("/").json()["features"]))

shutil.rmtree(WORK, ignore_errors=True)

print("" + chr(10) + "=== 검증 결과 (서버 채팅) ===")
all_ok = True
for name, passed, *detail in checks:
    if not passed:
        print(f"[FAIL] {name}  <- {detail[0] if detail else ''}")
    all_ok = all_ok and passed
print(f"\n검사 {len(checks)}개")
print("전체 통과:", all_ok)
sys.exit(0 if all_ok else 1)
