"""참여자 프로필 - 상대가 접속 안 해 있어도 얼굴이 보이는가, 그리고 남이 못 바꾸는가.

채팅 통로로 주고받을 때는 IRC 서버가 닉네임을 지켜줬다. 서버에 두면 그 보호가
사라지므로, **먼저 잡은 사람만 고칠 수 있는가**를 특히 꼼꼼히 본다.
"""
import json
import os
import shutil
import sys
import tempfile
import time

WORK = tempfile.mkdtemp(prefix="jsserv_profiles_")
os.environ["JSSERV_PROFILE_DIR"] = WORK
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from features import profiles  # noqa: E402

client = TestClient(app)
checks = []

ME = "1" * 24
YOU = "2" * 24
FACE = "iVBORw0KGgo=" * 4


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def put(who, **body):
    return client.put(f"/profiles/{who}", content=json.dumps(body))


# ---------- 1) 올리고 보기 ----------
first = put(ME, nick="몽키", avatar=FACE)
check(f"올라간다({first.status_code})", first.status_code == 200, first.text[:200])
token = first.json().get("token", "")
check(f"표를 하나 준다({token[:8]}...)", len(token) >= 16, first.json())

seen = client.get(f"/profiles/{ME}")
check(f"다른 사람이 볼 수 있다({seen.status_code})", seen.status_code == 200, seen.text[:120])
check("아이콘이 그대로 온다", seen.json().get("avatar") == FACE, seen.json())
check("닉네임도 온다", seen.json().get("nick") == "몽키", seen.json())
check("**표는 안 나간다**(나가면 아무나 남의 얼굴을 바꿀 수 있다)",
      "token" not in seen.json(), seen.json())

check("없는 사람은 404", client.get(f"/profiles/{YOU}").status_code == 404)

# ---------- 2) 남이 못 바꾼다 ----------
stolen = put(ME, nick="가짜몽키", avatar="AAAA")
check(f"표 없이 고치려 하면 막는다({stolen.status_code})", stolen.status_code == 403,
      stolen.text[:120])
check("표가 틀려도 막는다", put(ME, nick="가짜", avatar="AAAA",
                          token="0" * 32).status_code == 403)
check("얼굴이 안 바뀌었다", client.get(f"/profiles/{ME}").json()["avatar"] == FACE)

mine = put(ME, nick="몽키2", avatar="BBBB", token=token)
check(f"표가 맞으면 고칠 수 있다({mine.status_code})", mine.status_code == 200, mine.text[:120])
check("바뀐 것이 보인다", client.get(f"/profiles/{ME}").json()["nick"] == "몽키2")
check("표는 그대로다(고칠 때마다 바뀌면 다음에 못 고친다)",
      mine.json().get("token") == token, mine.json())

# 컴퓨터를 바꾸면 표가 없어진다 - 한동안 아무도 안 고친 자리는 다시 잡게 풀어준다
fresh = {"token": "abc", "updated": time.time()}
old = {"token": "abc", "updated": time.time() - profiles.LIMITS["claim_days"] * 86400 - 60}
check("방금 쓴 자리는 남이 못 잡는다", not profiles.can_write(fresh, ""))
check("오래 손 안 댄 자리는 다시 잡을 수 있다", profiles.can_write(old, ""))
check("빈 자리는 누구나 잡는다", profiles.can_write(None, ""))

# ---------- 3) 여러 명을 한 번에 ----------
put(YOU, nick="두리", avatar="CCCC")
batch = client.post("/profiles/lookup", content=json.dumps({"who": [ME, YOU, "9" * 24]}))
found = batch.json()["profiles"]
check(f"한 번에 여러 명을 받아온다({len(found)}명)", len(found) == 2, found)
check("없는 사람은 그냥 빠진다(오류가 아니다)", "9" * 24 not in found, list(found))
check("각자 제 얼굴이다", found[YOU]["nick"] == "두리" and found[ME]["nick"] == "몽키2", found)
check("여기서도 표는 안 나간다", all("token" not in p for p in found.values()), found)

check("한 번에 너무 많이 물으면 거절",
      client.post("/profiles/lookup",
                  content=json.dumps({"who": [ME] * (profiles.LIMITS["batch_size"] + 1)})
                  ).status_code == 413)
check("이상한 id가 섞여 있어도 나머지는 준다",
      len(client.post("/profiles/lookup",
                      content=json.dumps({"who": [ME, "../../etc/passwd", None]})
                      ).json()["profiles"]) == 1)

# ---------- 4) 이상한 것 ----------
check("자리 id가 아니면 거절", put("abc", nick="x", avatar="AAAA").status_code == 400)
check("읽을 수 없는 내용은 거절",
      client.put(f"/profiles/{'3' * 24}", content=b"\xff not json").status_code == 400)
check("너무 큰 아이콘은 거절",
      put("4" * 24, nick="x", avatar="A" * (profiles.LIMITS["avatar_chars"] + 1)
          ).status_code == 413)
check("그림이 아닌 것은 거절", profiles.clean_avatar("<script>alert(1)</script>") is None)
check("빈 아이콘은 받아준다(아이콘을 지운 사람)", profiles.clean_avatar("") == "")
check("긴 닉네임은 잘라서 받는다",
      len(put("5" * 24, nick="가" * 500, avatar="AAAA").status_code * "x") > 0
      and len(client.get(f"/profiles/{'5' * 24}").json()["nick"])
      <= profiles.LIMITS["nick_chars"],
      client.get(f"/profiles/{'5' * 24}").json()["nick"])

# 자리를 찾아 돌아다닐 수 없어야 한다
check("경로가 섞인 id로 남의 파일을 못 읽는다",
      client.get("/profiles/..%2F..%2Fapp.py").status_code in (400, 404))

# ---------- 5) 오래된 것은 지운다 ----------
gone = "6" * 24
put(gone, nick="옛사람", avatar="AAAA")
saved = profiles.read_profile(gone)
saved["updated"] = time.time() - profiles.LIMITS["keep_days"] * 86400 - 600
profiles._write_profile(gone, saved)
profiles._sweep()
check("오래 손 안 댄 프로필은 지운다", not os.path.exists(profiles._path(gone)))
check("멀쩡한 프로필은 안 지운다", os.path.exists(profiles._path(ME)))

# ---------- 6) 하루 한도 ----------
real = profiles.LIMITS["daily_writes"]
profiles.LIMITS["daily_writes"] = 2
for name in os.listdir(WORK):
    if name.startswith("quota-"):
        os.remove(os.path.join(WORK, name))
try:
    put("7" * 24, nick="a", avatar="AAAA")
    put("8" * 24, nick="b", avatar="AAAA")
    over = put("a" * 24, nick="c", avatar="AAAA")
    check(f"하루 한도를 넘으면 거절({over.status_code})", over.status_code == 429, over.text[:120])
finally:
    profiles.LIMITS["daily_writes"] = real

# ---------- 9) 무슨 프로그램을 쓰는지 ----------
# IRC 로 물어보던 것을 서버에 적는 방식으로 바꿨다. 아무에게도 안 묻고 lookup 한 번에
# 같이 온다 - 다만 이 값은 **남의 화면에 배지로 뜨므로** 아무 글자나 받으면 안 된다
WHO9 = "9" * 24
first9 = put(WHO9, nick="폰사람", avatar="AAAA",
             client={"app": "ChupChat", "version": "2.6.6", "platform": "mobile"})
TOKEN9 = first9.json()["token"]
seen = client.get(f"/profiles/{WHO9}").json()
check("무슨 프로그램인지 같이 돌려준다",
      seen.get("client", {}).get("platform") == "mobile", seen)
check("프로그램 이름과 버전도 그대로",
      (seen["client"]["app"], seen["client"]["version"]) == ("ChupChat", "2.6.6"), seen)

bad = put(WHO9, token=TOKEN9, client={"app": "<script>", "version": "1.0",
                                      "platform": "pc"})
check(f"이상한 이름은 거절({bad.status_code})", bad.status_code == 400, bad.text[:160])

bad = put(WHO9, token=TOKEN9, client={"app": "ChupChat", "version": "1.0",
                                      "platform": "냉장고"})
check(f"모르는 자리는 거절({bad.status_code})", bad.status_code == 400, bad.text[:160])

# **안 보낸 칸은 건드리지 않는다** - 모바일은 아이콘 편집기가 없어서 "나는 춥채팅
# 모바일"만 올린다. 그때 빈 아이콘으로 덮어쓰면 PC에서 정해둔 얼굴이 지워진다
again = client.put(f"/profiles/{WHO9}", content=json.dumps(
    {"token": TOKEN9,
     "client": {"app": "ChupChat", "version": "2.6.7", "platform": "mobile"}}))
check(f"표를 내면 고칠 수 있다({again.status_code})", again.status_code == 200,
      again.text[:160])
after = client.get(f"/profiles/{WHO9}").json()
check("아이콘을 안 보내면 그대로 남는다", after.get("avatar") == "AAAA", after)
check("이름도 그대로 남는다", after.get("nick") == "폰사람", after)
check("버전만 바뀐다", after["client"]["version"] == "2.6.7", after)

# 반대로 아이콘만 바꿀 때 프로그램 정보가 사라지면 안 된다
client.put(f"/profiles/{WHO9}",
           content=json.dumps({"token": TOKEN9, "avatar": "BBBB"}))
after = client.get(f"/profiles/{WHO9}").json()
check("아이콘만 바꿔도 프로그램 정보가 남는다",
      after["client"].get("platform") == "mobile", after)

check("서버가 이 기능을 알려준다",
      any(f["name"] == "profiles" for f in client.get("/").json()["features"]),
      client.get("/").json()["features"])

shutil.rmtree(WORK, ignore_errors=True)

print("=== 검증 결과 (참여자 프로필) ===")
all_ok = True
for name, passed, *detail in checks:
    extra = f"  <- {detail[0]}" if detail and detail[0] and not passed else ""
    print(f"[{'OK' if passed else 'FAIL'}] {name}{extra}")
    all_ok = all_ok and passed
print(f"\n검사 {len(checks)}개")
print("전체 통과:", all_ok)
sys.exit(0 if all_ok else 1)
