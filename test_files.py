"""파일·사진 올리기 - **한도가 실제로 막는가**가 핵심이다.

서버 디스크는 남의 것이다. 상한을 적어만 두고 안 막으면 아무 의미가 없으므로,
실제로 넘겨보고 거절되는지 확인한다.

    python test_files.py
"""
import os
import shutil
import sys
import tempfile
import urllib.parse

WORK = tempfile.mkdtemp(prefix="jsserv_files_")
os.environ["JSSERV_FILE_DIR"] = WORK

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from features import files  # noqa: E402

client = TestClient(server.app)
ok = True


def check(name, passed, detail=""):
    global ok
    ok = ok and passed
    extra = f"  <- {detail}" if detail and not passed else ""
    print(f"[{'OK' if passed else 'FAIL'}] {name}{extra}")


def reset_quota():
    """앞선 검사가 쓴 사용량을 지운다 - 구간마다 독립적으로 봐야 한다."""
    for entry in os.listdir(WORK):
        if entry.startswith(("quota-", "emoji-")):
            os.remove(os.path.join(WORK, entry))


def put(data: bytes, name="사진.png", kind=None):
    # 헤더는 ASCII만 되므로 이름을 부호화해서 보낸다(앱도 같은 방식으로 보낸다)
    headers = {"X-File-Name": urllib.parse.quote(name)}
    if kind:
        headers["X-File-Kind"] = kind
    return client.post("/files", content=data, headers=headers)


# ---------- 1) 올리고 내려받기 ----------
payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20
response = put(payload)
check(f"올라간다({response.status_code})", response.status_code == 200, response.text[:200])
info = response.json()
check(f"주소를 돌려준다({info.get('url')})", info.get("url", "").startswith("/files/"), info)
check(f"크기를 알려준다({info.get('size')})", info.get("size") == len(payload), info)
check(f"기본은 일반 파일({info.get('kind')})", info.get("kind") == "file", info)

got = client.get(info["url"])
check(f"내려받아진다({got.status_code})", got.status_code == 200, got.status_code)
check("내용이 한 바이트도 다르지 않다", got.content == payload)
check(f"그림은 화면에 바로 뜬다({got.headers.get('content-type')})",
      got.headers.get("content-type") == "image/png", dict(got.headers))
check("브라우저가 다른 걸로 해석하지 않게 못 박는다",
      got.headers.get("x-content-type-options") == "nosniff", dict(got.headers))

# ---------- 2) 위험한 것들 ----------
evil = put(b"<html><script>alert(1)</script></html>", name="나쁜.html")
served = client.get(evil.json()["url"])
check(f"HTML은 페이지로 안 열린다({served.headers.get('content-type')})",
      served.headers.get("content-type") == "application/octet-stream", dict(served.headers))
check("내려받기로 준다", "attachment" in served.headers.get("content-disposition", ""),
      dict(served.headers))

check("이름에 섞인 경로를 떼어낸다",
      files.safe_name(r"..\..\Windows\system32\evil.exe") == "evil.exe",
      files.safe_name(r"..\..\Windows\system32\evil.exe"))
check("쓸 수 없는 글자를 바꾼다", files.safe_name('a<b>c:d|e?.txt') == "a_b_c_d_e_.txt")
check("이름이 없어도 뭔가는 된다", files.safe_name("") == "파일")

for bad in ("/files/짧은id/a.png", "/files/" + "z" * 24 + "/a.png",
            "/files/../../etc/passwd", "/files/" + "0" * 24 + "/a.png"):
    check(f"없는 주소는 404({bad[:34]})", client.get(bad).status_code == 404, bad)

check("빈 파일은 거절", put(b"").status_code == 400)

# ---------- 3) 파일 하나 크기 상한 ----------
real_cap = files.LIMITS["file_bytes"]
files.LIMITS["file_bytes"] = 2048
try:
    small = put(b"a" * 1000)
    check(f"상한 아래는 통과({small.status_code})", small.status_code == 200)
    big = put(b"a" * 5000)
    check(f"상한을 넘으면 거절({big.status_code})", big.status_code == 413, big.text[:120])
    check(f"이유를 알려준다({big.json().get('error')})", "큽니다" in big.json().get("error", ""))
    check("거절된 파일은 안 남는다",
          len([n for n in os.listdir(WORK) if n.endswith(".bin")]) == 3,
          os.listdir(WORK))
finally:
    files.LIMITS["file_bytes"] = real_cap

# ---------- 4) 하루 총량 ----------
real_daily = files.LIMITS["daily_bytes"]
files.LIMITS["daily_bytes"] = 3000
reset_quota()
try:
    first = put(b"b" * 2000)
    check(f"하루 한도 안에서는 올라간다({first.status_code})", first.status_code == 200)
    second = put(b"b" * 2000)
    check(f"하루 한도를 넘으면 거절({second.status_code})", second.status_code == 429,
          second.text[:120])
    check(f"이유를 알려준다({second.json().get('error')})",
          "용량" in second.json().get("error", ""))
finally:
    files.LIMITS["daily_bytes"] = real_daily

# ---------- 5) 이모티콘은 다르게 다룬다 ----------
emoji = put(b"\x89PNG\r\n\x1a\n" + b"e" * 500, name="웃음.png", kind="emoji")
check(f"이모티콘으로 올라간다({emoji.status_code})", emoji.status_code == 200, emoji.text[:200])
check(f"이모티콘이라고 표시된다({emoji.json().get('kind')})",
      emoji.json().get("kind") == "emoji", emoji.json())

emoji_id = emoji.json()["id"]
check("이모티콘은 기한으로 안 지운다(보관함에서 영원히 참조되므로)",
      files._kind_of(emoji_id) == "emoji")

# 기한이 한참 지난 것처럼 만들어도 이모티콘은 살아남고 일반 파일은 지워진다
old_file = put(b"c" * 100, name="옛날.bin").json()["id"]
long_ago = 0
for target in (old_file, emoji_id):
    os.utime(os.path.join(WORK, target + ".bin"), (long_ago, long_ago))
files._sweep()
check("기한 지난 일반 파일은 지워진다",
      not os.path.exists(os.path.join(WORK, old_file + ".bin")))
check("기한이 지나도 이모티콘은 남는다",
      os.path.exists(os.path.join(WORK, emoji_id + ".bin")))

# 이모티콘은 개수로 막는다(꽉 차면 **옛것을 지우는 대신 거절**한다)
real_count = files.LIMITS["emoji_per_person"]
files.LIMITS["emoji_per_person"] = 2
reset_quota()
try:
    kept = [put(b"\x89PNG\r\n\x1a\n" + bytes([n]) * 10, name=f"{n}.png", kind="emoji")
            for n in range(2)]
    check(f"한도 안에서는 저장된다({[r.status_code for r in kept]})",
          all(r.status_code == 200 for r in kept), [r.text[:80] for r in kept])
    refused = put(b"\x89PNG\r\n\x1a\n" + b"g" * 10, name="셋.png", kind="emoji")
    check(f"개수가 차면 새로 저장하는 걸 거절한다({refused.status_code})",
          refused.status_code == 429, refused.text[:140])
    check("먼저 저장한 이모티콘은 그대로 있다",
          os.path.exists(os.path.join(WORK, emoji_id + ".bin")))
finally:
    files.LIMITS["emoji_per_person"] = real_count

real_emoji_cap = files.LIMITS["emoji_bytes"]
files.LIMITS["emoji_bytes"] = 100
try:
    too_big = put(b"h" * 500, name="큰.png", kind="emoji")
    check(f"이모티콘은 작아야 한다({too_big.status_code})", too_big.status_code == 413,
          too_big.text[:120])
finally:
    files.LIMITS["emoji_bytes"] = real_emoji_cap

# ---------- 6) 상태 페이지 ----------
status = client.get("/files").json()
check(f"한도를 밖에서 볼 수 있다({sorted(status.get('limits', {}))[:3]})",
      "file_bytes" in status.get("limits", {}) and "emoji_bytes" in status["limits"], status)
check(f"얼마나 쓰고 있는지 알려준다({status.get('used_bytes')}바이트)",
      isinstance(status.get("used_bytes"), int), status)

shutil.rmtree(WORK, ignore_errors=True)
print("\n전체 통과:", ok)
sys.exit(0 if ok else 1)
