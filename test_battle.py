"""중계 서버가 제대로 넘겨주고, 이상한 건 막는가.

서버가 판단하는 건 딱 하나다 - **자리 번호는 서버가 붙인다.** 이게 무너지면 남의 배를
움직이거나 남이 죽었다고 대신 신고할 수 있다. 그래서 그걸 가장 먼저 확인한다.

    python test_battle.py
"""
import json
import sys

from fastapi.testclient import TestClient

import app as server
from features import battle, battle_protocol as bp

client = TestClient(server.app)
ok = True


def check(name, passed, detail=""):
    global ok
    ok = ok and passed
    extra = f"  <- {detail}" if detail and not passed else ""
    print(f"[{'OK' if passed else 'FAIL'}] {name}{extra}")


def send(ws, message):
    ws.send_text(json.dumps(message, separators=(",", ":"), ensure_ascii=False))


def drain(ws, count):
    return [ws.receive_json() for _ in range(count)]


battle._rooms.clear()
room = bp.new_room()

# ---------- 1) 들어가고 자리를 받는다 ----------
with client.websocket_connect("/battle/ws") as a:
    send(a, {"t": "join", "room": room, "nick": "Mong"})
    hello = a.receive_json()
    check(f"첫 사람은 0번 자리({hello})",
          hello["t"] == "welcome" and hello["slot"] == 0 and hello["players"] == [], hello)

    with client.websocket_connect("/battle/ws") as b:
        send(b, {"t": "join", "room": room, "nick": "Gil"})
        hello_b = b.receive_json()
        check(f"두 번째는 1번 자리({hello_b['slot']})", hello_b["slot"] == 1, hello_b)
        check(f"먼저 있던 사람이 목록에 보인다({hello_b['players']})",
              hello_b["players"] == [{"slot": 0, "nick": "Mong", "color": 0}], hello_b)

        joined = a.receive_json()
        check(f"먼저 있던 사람에게 '누가 들어왔다'가 간다({joined})",
              joined == {"t": "joined", "slot": 1, "nick": "Gil", "color": 1}, joined)

        # ---------- 2) 자리 번호는 서버가 붙인다(핵심) ----------
        send(b, {"t": "in", "tick": 7, "keys": bp.KEY_FIRE, "slot": 0})   # 0번인 척 해본다
        relayed = a.receive_json()
        check(f"남의 자리 번호를 적어 보내도 자기 번호로 바뀐다({relayed})",
              relayed == {"t": "peer", "slot": 1, "tick": 7, "keys": bp.KEY_FIRE}, relayed)

        send(b, {"t": "dead", "by": 0, "slot": 0})
        dead = a.receive_json()
        check(f"'죽었다'도 보낸 사람 자리로 기록된다({dead})",
              dead == {"t": "peerdead", "slot": 1, "by": 0}, dead)

        send(b, {"t": "hit", "by": 0})
        hit = a.receive_json()
        check(f"맞았다도 넘어간다({hit})", hit == {"t": "peerhit", "slot": 1, "by": 0}, hit)

        # ---------- 3) 손님이 서버 노릇을 할 수 없다 ----------
        send(b, {"t": "peer", "slot": 0, "tick": 1, "keys": 15})
        send(b, {"t": "welcome", "slot": 0, "tick": 0, "players": []})
        send(b, {"t": "in", "tick": 8, "keys": 0})        # 이건 정상 - 뒤에 와야 한다
        after = a.receive_json()
        check(f"서버가 만드는 종류를 손님이 보내면 버린다({after})",
              after == {"t": "peer", "slot": 1, "tick": 8, "keys": 0}, after)

        # ---------- 4) 이상한 값은 버리되 끊지는 않는다 ----------
        send(b, {"t": "in", "tick": -1, "keys": 1})
        send(b, {"t": "in", "tick": 1, "keys": 9999})
        b.send_text("{깨진 json")
        send(b, {"t": "in", "tick": 9, "keys": bp.KEY_UP})
        alive = a.receive_json()
        check(f"이상한 값 뒤에도 연결이 살아있다({alive})",
              alive == {"t": "peer", "slot": 1, "tick": 9, "keys": bp.KEY_UP}, alive)

        # ---------- 5) 정원 ----------
        with client.websocket_connect("/battle/ws") as c:
            send(c, {"t": "join", "room": room, "nick": "C"})
            check(f"세 번째는 2번({c.receive_json()['slot']})", True)
            a.receive_json(), b.receive_json()
            with client.websocket_connect("/battle/ws") as d:
                send(d, {"t": "join", "room": room, "nick": "D"})
                check("네 번째는 3번", d.receive_json()["slot"] == 3)
                a.receive_json(), b.receive_json(), c.receive_json()
                with client.websocket_connect("/battle/ws") as e:
                    send(e, {"t": "join", "room": room, "nick": "E"})
                    denied = e.receive_json()
                    check(f"다섯 번째는 거절({denied})",
                          denied["t"] == "deny" and "정원" in denied["why"], denied)

                # ---------- 5-1) 시작은 방장만 ----------
                send(d, {"t": "start"})                     # 손님이 눌러봄
                send(d, {"t": "in", "tick": 1, "keys": 0})  # 뒤따르는 정상 신호
                after_guest_start = a.receive_json()
                check(f"손님이 시작을 눌러도 안 시작된다({after_guest_start['t']})",
                      after_guest_start["t"] == "peer", after_guest_start)
                b.receive_json(), c.receive_json()

                send(a, {"t": "start"})                     # 방장이 누름
                # 방장에게도 간다 - 시작으로 넘어가는 길을 한 갈래로 두기 위함
                started = [a.receive_json(), b.receive_json(), c.receive_json(),
                           d.receive_json()]
                check(f"방장 포함 모두에게 시작이 간다({[s['t'] for s in started]})",
                      all(s == {"t": "started"} for s in started), started)

                with client.websocket_connect("/battle/ws") as late:
                    send(late, {"t": "join", "room": room, "nick": "늦은사람"})
                    denied_late = late.receive_json()
                    check(f"시작된 뒤에는 못 들어온다({denied_late})",
                          denied_late["t"] == "deny" and "시작" in denied_late["why"],
                          denied_late)

    # 안쪽에 있던 사람들이 차례로 나감(나간 순서는 뒤에서부터라 여러 건이 쌓인다)
    departures = []
    for _ in range(4):
        message = a.receive_json()
        if message.get("t") == "left":
            departures.append(message["slot"])
        if 1 in departures:
            break
    check(f"나가면 알려준다(나간 자리 {departures})", 1 in departures, departures)

# ---------- 5-2) 정원은 방장이 정한다 ----------
battle._rooms.clear()
small = bp.new_room()
with client.websocket_connect("/battle/ws") as host:
    send(host, {"t": "join", "room": small, "nick": "방장", "cap": 2, "color": 3})
    hello = host.receive_json()
    check(f"방장이 정한 정원이 돌아온다({hello['cap']}명)", hello["cap"] == 2, hello)
    check(f"고른 색도 그대로({hello['color']})", hello["color"] == 3, hello)

    with client.websocket_connect("/battle/ws") as guest:
        # 손님이 정원을 4로 적어 보내도 방장이 정한 2가 유지돼야 한다
        send(guest, {"t": "join", "room": small, "nick": "손님", "cap": 4, "color": 3})
        hello_guest = guest.receive_json()
        check(f"손님이 정원을 못 바꾼다({hello_guest['cap']}명)", hello_guest["cap"] == 2,
              hello_guest)
        check(f"이미 쓰는 색이면 다른 색을 준다(원한 3 -> 받은 {hello_guest['color']})",
              hello_guest["color"] != 3, hello_guest)
        host.receive_json()

        with client.websocket_connect("/battle/ws") as third:
            send(third, {"t": "join", "room": small, "nick": "셋째"})
            denied = third.receive_json()
            check(f"2인 방에 세 번째는 거절({denied})",
                  denied["t"] == "deny" and "정원(2명)" in denied["why"], denied)

battle._rooms.clear()

# ---------- 5-3) 혼자서도 시작할 수 있다 ----------
# 서버가 '2명 이상'을 요구했더니 혼자서 연습 상대(AI)와 하려는 사람이 시작을 눌러도
# 아무 일도 안 일어났다(실제 신고). 연습 상대는 그 사람 화면에서만 돌아서 서버는
# 그 존재를 모른다 - 알 수도 없는 것을 조건으로 걸면 안 된다
battle._rooms.clear()
solo = bp.new_room()
with client.websocket_connect("/battle/ws") as lonely:
    send(lonely, {"t": "join", "room": solo, "nick": "혼자"})
    check(f"혼자 들어간다({lonely.receive_json()['slot']}번 자리)", True)
    send(lonely, {"t": "start"})
    started_alone = lonely.receive_json()
    check(f"혼자서도 시작된다({started_alone})", started_alone == {"t": "started"},
          started_alone)
battle._rooms.clear()

# ---------- 6) 방 번호를 모르면 못 들어온다 ----------
with client.websocket_connect("/battle/ws") as x:
    send(x, {"t": "in", "tick": 1, "keys": 1})        # 방부터 말해야 한다
    first = x.receive_json()
    check(f"방 번호 없이 조작부터 보내면 거절({first})", first["t"] == "deny", first)

with client.websocket_connect("/battle/ws") as x:
    send(x, {"t": "join", "room": "../../etc", "nick": "a"})
    check("이상한 방 번호는 거절", x.receive_json()["t"] == "deny")

# ---------- 7) 방이 비면 지워진다 ----------
check(f"판이 끝나면 방이 남지 않는다(지금 {len(battle._rooms)}개)",
      len(battle._rooms) == 0, list(battle._rooms))

# ---------- 8) 상태 페이지 ----------
status = client.get("/battle").json()
check(f"상태에 규약 번호가 있다({status.get('protocol')})",
      status.get("protocol") == bp.PROTOCOL_VERSION, status)
check(f"정원을 알려준다({status.get('max_players_per_room')})",
      status.get("max_players_per_room") == 4, status)

print("\n전체 통과:", ok)
sys.exit(0 if ok else 1)
