"""채팅 기록 하루치 - 놓친 이야기를 따라잡을 수 있는가.

이 기능의 값은 하나다: **앱을 꺼둔 사이에 오간 말을 다시 켰을 때 볼 수 있는가.**
그래서 여기서 보는 것도 그 줄기다 - 여럿이 같은 걸 올려도 한 번만 남는가,
내가 마지막으로 본 뒤엣것만 골라 오는가, 하루가 지나면 사라지는가.
"""
import json
import os
import shutil
import sys
import tempfile
import time

WORK = tempfile.mkdtemp(prefix="jsserv_logs_")
os.environ["JSSERV_LOG_DIR"] = WORK
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features import logs  # noqa: E402

client = TestClient(app)
checks = []

ROOM = "a" * 24
OTHER = "b" * 24


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def post(room, lines):
    return client.post(f"/logs/{room}", content=json.dumps({"lines": lines}))


def line(text, sender="몽키", ago=0.0):
    return {"ts": time.time() - ago, "sender": sender, "text": text}


# ---------- 1) 올리고 받아오기 ----------
first = post(ROOM, [line("안녕", ago=60), line("밥 먹었어?", ago=50)])
check(f"올라간다({first.status_code})", first.status_code == 200, first.text[:200])
check(f"몇 줄이 새로 남았는지 알려준다({first.json().get('added')})",
      first.json().get("added") == 2, first.json())

got = client.get(f"/logs/{ROOM}").json()
check(f"올린 그대로 돌아온다({len(got['lines'])}줄)", len(got["lines"]) == 2, got)
check("내용이 안 깨진다(한글)", got["lines"][0]["text"] == "안녕", got["lines"][0])
check("시간 순서대로 온다", got["lines"][0]["ts"] <= got["lines"][1]["ts"], got)

# ---------- 2) 여럿이 같은 대화를 올린다 ----------
# 이게 이 기능의 핵심 - 채팅을 받아본 사람이 전부 올리므로 안 거르면 사람 수만큼 겹친다
same = [line("안녕", ago=60), line("밥 먹었어?", ago=50), line("아직", ago=40)]
second = post(ROOM, same)
check(f"이미 있는 줄은 안 쌓인다(새로 {second.json().get('added')}줄만)",
      second.json().get("added") == 1, second.json())
after = client.get(f"/logs/{ROOM}").json()["lines"]
check(f"결국 세 줄만 남는다({len(after)}줄)", len(after) == 3, after)

texts = [entry["text"] for entry in after]
check("같은 말이 두 번 안 보인다", len(texts) == len(set(texts)), texts)

# 시각이 밀리초쯤 어긋나도 같은 줄로 본다(받은 시각은 사람마다 다르다)
drifted = dict(after[0])
drifted["ts"] += 0.4
check("받은 시각이 조금 달라도 같은 줄로 본다",
      post(ROOM, [drifted]).json().get("added") == 0, post(ROOM, [drifted]).json())

# **초 경계**에서 갈리면 안 된다. 37.93초와 38.12초는 0.19초 차이인데 초로 뭉개면
# 다른 줄이 된다 - 실제로 이렇게 겹쳐 보였다
edge = "f" * 24
base = float(int(time.time()) - 30)
check("초 경계를 사이에 둔 같은 줄도 하나로 본다",
      post(edge, [{"ts": base + 0.93, "sender": "몽키", "text": "경계"}]).json()["added"] == 1
      and post(edge, [{"ts": base + 1.12, "sender": "몽키", "text": "경계"}]).json()["added"] == 0,
      client.get(f"/logs/{edge}").json())

# 같은 말을 연달아 두 번 한 것은 두 줄로 남아야 한다(올리는 쪽이 seq로 구분한다)
twice = "0" * 24
post(twice, [{"ts": base, "sender": "몽키", "text": "ㅋㅋ", "seq": 0},
             {"ts": base + 1.5, "sender": "몽키", "text": "ㅋㅋ", "seq": 1}])
check("연달아 한 같은 말은 두 줄로 남는다",
      len(client.get(f"/logs/{twice}").json()["lines"]) == 2,
      client.get(f"/logs/{twice}").json())
# 다른 사람이 같은 대화를 올려도 그대로 두 줄
post(twice, [{"ts": base + 0.2, "sender": "몽키", "text": "ㅋㅋ", "seq": 0},
             {"ts": base + 1.7, "sender": "몽키", "text": "ㅋㅋ", "seq": 1}])
check("남이 같은 대화를 올려도 여전히 두 줄",
      len(client.get(f"/logs/{twice}").json()["lines"]) == 2,
      client.get(f"/logs/{twice}").json())

# ---------- 3) 내가 마지막으로 본 뒤엣것만 ----------
newest = max(entry["ts"] for entry in after)
post(ROOM, [line("나 왔어", ago=0)])
missed = client.get(f"/logs/{ROOM}", params={"since": newest}).json()["lines"]
check(f"마지막으로 본 뒤엣것만 준다({[m['text'] for m in missed]})",
      [m["text"] for m in missed] == ["나 왔어"], missed)
check("아무것도 안 놓쳤으면 빈 손으로 온다",
      client.get(f"/logs/{ROOM}", params={"since": time.time()}).json()["lines"] == [])

# ---------- 4) 방이 섞이지 않는다 ----------
post(OTHER, [line("다른 방 이야기")])
check("다른 방 기록이 섞이지 않는다",
      all("다른 방" not in e["text"] for e in client.get(f"/logs/{ROOM}").json()["lines"]))
check("그 방에는 그 방 것만 있다",
      [e["text"] for e in client.get(f"/logs/{OTHER}").json()["lines"]] == ["다른 방 이야기"])

# ---------- 5) 이상한 것 ----------
check("방 id가 아니면 거절", client.get("/logs/../../etc/passwd").status_code in (400, 404))
check("방 id가 짧으면 거절", post("abc", [line("x")]).status_code == 400)
check("읽을 수 없는 내용은 거절",
      client.post(f"/logs/{ROOM}", content=b"\xff\xfe not json").status_code == 400)
check("올릴 줄이 없으면 거절", post(ROOM, []).status_code == 400)

check("보낸 사람이 없는 줄은 안 받는다",
      logs.clean_line({"ts": time.time(), "sender": "", "text": "x"}) is None)
check("내용이 없는 줄은 안 받는다",
      logs.clean_line({"ts": time.time(), "sender": "몽키", "text": ""}) is None)
check("너무 긴 줄은 안 받는다",
      logs.clean_line({"ts": time.time(), "sender": "몽키",
                       "text": "가" * 2000}) is None)
# 시계가 틀어진 컴퓨터가 기록 맨 끝에 영원히 붙박이지 않게
check("먼 미래의 줄은 안 받는다",
      logs.clean_line({"ts": time.time() + 99999, "sender": "몽키", "text": "x"}) is None)
check("아주 오래된 줄은 안 받는다",
      logs.clean_line({"ts": time.time() - 99999, "sender": "몽키", "text": "x"}) is None)

before = len(client.get(f"/logs/{ROOM}").json()["lines"])
mixed = post(ROOM, [line("멀쩡한 줄"), {"sender": "몽키"}, "줄이 아님", None])
check(f"섞여 들어온 쓰레기는 버리고 멀쩡한 것만 받는다({mixed.json().get('added')}줄)",
      mixed.json().get("added") == 1, mixed.json())
check("그래도 앞의 기록은 그대로다",
      len(client.get(f"/logs/{ROOM}").json()["lines"]) == before + 1)

too_many = post(ROOM, [line(f"줄 {i}") for i in range(logs.LIMITS["post_lines"] + 1)])
check(f"한 번에 너무 많이 올리면 거절({too_many.status_code})",
      too_many.status_code == 413, too_many.text[:120])

# ---------- 6) 하루가 지나면 사라진다 ----------
old_room = "c" * 24
post(old_room, [line("어제 이야기", ago=60)])
raw = logs._read(old_room)
raw[0]["ts"] -= logs.LIMITS["keep_hours"] * 3600 + 600   # 기한 밖으로 밀어둔다
logs._write(old_room, raw)
check("기한 지난 줄은 안 보인다", client.get(f"/logs/{old_room}").json()["lines"] == [],
      client.get(f"/logs/{old_room}").json())
logs._sweep()
check("기한 지난 방은 파일째 지운다", not os.path.exists(logs._room_path(old_room)),
      os.listdir(WORK))
check("멀쩡한 방은 안 지운다", os.path.exists(logs._room_path(ROOM)), os.listdir(WORK))

# 한 방에 무한히 쌓이지 않는다
real_cap = logs.LIMITS["room_lines"]
logs.LIMITS["room_lines"] = 5
try:
    packed = "d" * 24
    for i in range(12):
        post(packed, [line(f"줄 {i}", ago=100 - i)])
    kept = client.get(f"/logs/{packed}").json()["lines"]
    check(f"한 방에 쌓이는 줄에 상한이 있다({len(kept)}줄)", len(kept) == 5, len(kept))
    check("남는 것은 최근 것이다", kept[-1]["text"] == "줄 11", kept[-1])
finally:
    logs.LIMITS["room_lines"] = real_cap

# ---------- 7) 하루 총량 ----------
real_daily = logs.LIMITS["daily_lines"]
logs.LIMITS["daily_lines"] = 3
# 앞 검사들이 이미 쓴 몫을 비운다 - 안 그러면 첫 줄부터 한도에 걸린다
for name in os.listdir(WORK):
    if name.startswith("quota-"):
        os.remove(os.path.join(WORK, name))
try:
    room = "e" * 24
    check("한도 안에서는 올라간다", post(room, [line("하나"), line("둘")]).status_code == 200)
    flooded = post(room, [line("셋"), line("넷"), line("다섯")])
    check(f"하루 한도를 넘으면 거절({flooded.status_code})", flooded.status_code == 429,
          flooded.text[:120])
    check(f"이유를 알려준다({flooded.json().get('error')})",
          "줄 수" in flooded.json().get("error", ""), flooded.json())
finally:
    logs.LIMITS["daily_lines"] = real_daily

status = client.get("/logs").json()
check(f"한도를 밖에서 볼 수 있다({sorted(status['limits'])[:3]})",
      status["limits"]["keep_hours"] == 24, status)
check("서버가 이 기능을 알려준다",
      any(f["name"] == "logs" for f in client.get("/").json()["features"]),
      client.get("/").json()["features"])

shutil.rmtree(WORK, ignore_errors=True)

print("=== 검증 결과 (채팅 기록 하루치) ===")
all_ok = True
for name, passed, *detail in checks:
    extra = f"  <- {detail[0]}" if detail and detail[0] and not passed else ""
    print(f"[{'OK' if passed else 'FAIL'}] {name}{extra}")
    all_ok = all_ok and passed
print(f"\n검사 {len(checks)}개")
print("전체 통과:", all_ok)
sys.exit(0 if all_ok else 1)
