"""파일·사진 올리기 - **한도가 실제로 막는가**가 핵심이다.

서버 디스크는 남의 것이다. 상한을 적어만 두고 안 막으면 아무 의미가 없으므로,
실제로 넘겨보고 거절되는지 확인한다.

    python test_files.py
"""
import os
import shutil
import sys
import tempfile
import time
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


# 이모티콘은 **서버가 줄여서** 저장하므로 진짜 그림이어야 한다
import io as _io  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402


def png(width=40, height=40, color=(200, 30, 30)):
    out = _io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def moving_gif(frames=4, size=200):
    """진짜로 움직이는 GIF.

    단색 그림만 늘어놓으면 Pillow가 한 장으로 합쳐버려서, 움짤을 넣었다고 생각하는데
    사실은 안 움직이는 그림으로 시험하게 된다(실제로 그렇게 헛검사를 했다).
    """
    pages = []
    for i in range(frames):
        page = Image.new("RGB", (size, size), (255, 255, 255))
        ImageDraw.Draw(page).rectangle(
            [i * size // frames, 10, i * size // frames + 30, size - 10], fill=(200, 20, 20))
        pages.append(page.convert("P"))
    out = _io.BytesIO()
    pages[0].save(out, format="GIF", save_all=True, append_images=pages[1:], duration=80)
    return out.getvalue()


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

# 주소는 채팅 한 줄에 그대로 실린다 - 공백이 섞이면 거기서 잘려 링크가 두 조각이 된다
spaced = put(payload, name="우리집 사진.png")
spaced_url = spaced.json()["url"]
check(f"주소에 공백이 없다({spaced_url})", " " not in spaced_url, spaced_url)
check("한글 이름도 부호화돼 들어간다", "%" in spaced_url, spaced_url)
check(f"그 주소로 그대로 내려받아진다", client.get(spaced_url).content == payload)
check("원래 이름은 그대로 알려준다", spaced.json()["name"] == "우리집 사진.png", spaced.json())

# ---------- 1-1) 카드로 보여주려면 알아야 하는 것 ----------
# 채팅에 뜬 파일 카드는 주소만으로는 이름도 크기도 남은 기간도 모른다
card = put(b"z" * 4000, name="문서.pdf")
info2 = card.json()
check(f"언제까지 받을 수 있는지 알려준다({info2.get('expires', 0) - time.time():.0f}초 남음)",
      info2.get("expires", 0) > time.time(), info2)
check("올린 사람에게 내릴 수 있는 표를 준다", len(info2.get("token", "")) >= 16, info2)

seen = client.get(f"/files/{info2['id']}/meta").json()
check(f"나중에 다시 물어볼 수 있다({seen.get('name')}, {seen.get('size')}바이트)",
      seen.get("name") == "문서.pdf" and seen.get("size") == 4000, seen)
check("다시 물을 때는 표를 안 준다(남이 물어볼 수도 있다)", "token" not in seen, seen)
# **확장자가 아니라 내용으로 가린다.** 이름이 .dat여도 사진이면 사진으로 보여줘야 한다
disguised = put(png(40, 40, (3, 3, 3)), name="이름은아무거나.dat").json()
check(f"이름이 거짓말해도 그림인 걸 알아본다({disguised.get('image')})",
      disguised.get("image") is True, disguised)
lying = put('PK 이건 압축파일이다'.encode('utf-8') * 20, name='사진인척.png').json()
check(f"그림 확장자를 달아도 내용이 아니면 그림이 아니다({lying.get('image')})",
      lying.get("image") is False, lying)

check("없는 파일을 물으면 404",
      client.get("/files/000000000000000000000000/meta").status_code == 404)

# 이모티콘은 기한이 없다 - 보관함에서 영원히 참조된다
forever = put(png(30, 30, (7, 7, 7)), name="계속쓸것.png", kind="emoji").json()
check(f"이모티콘은 기한이 없다({forever.get('expires')})", forever.get("expires") == 0, forever)

# ---------- 1-2) 올린 것을 도로 내리기 ----------
check("표가 없으면 못 내린다",
      client.delete(f"/files/{info2['id']}").status_code == 403)
check("표가 틀려도 못 내린다",
      client.delete(f"/files/{info2['id']}",
                    headers={"X-File-Token": "0" * 32}).status_code == 403)
check("아직 파일이 있다", client.get(info2["url"]).status_code == 200)

gone = client.delete(f"/files/{info2['id']}", headers={"X-File-Token": info2["token"]})
check(f"표가 맞으면 내린다({gone.status_code})", gone.status_code == 200, gone.text[:120])
check("내린 뒤에는 못 받는다", client.get(info2["url"]).status_code == 404)
check("곁딸린 것도 남지 않는다",
      not any(n.startswith(info2["id"]) for n in os.listdir(WORK)),
      [n for n in os.listdir(WORK) if n.startswith(info2["id"])])

# 이모티콘은 같이 쓰는 것이라 한 사람이 내리면 안 된다
check("이모티콘은 내릴 수 없다(남의 보관함이 깨진다)",
      client.delete(f"/files/{forever['id']}",
                    headers={"X-File-Token": "aaaa"}).status_code == 403)

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
    # 개수를 박아두면 앞에서 하나만 더 올려도 깨진다 - "늘지 않았는가"를 본다
    before = len([n for n in os.listdir(WORK) if n.endswith(".bin")])
    big = put(b"a" * 5000)
    check(f"상한을 넘으면 거절({big.status_code})", big.status_code == 413, big.text[:120])
    check(f"이유를 알려준다({big.json().get('error')})", "큽니다" in big.json().get("error", ""))
    after = len([n for n in os.listdir(WORK) if n.endswith(".bin")])
    check(f"거절된 파일은 안 남는다({before} -> {after})", after == before, os.listdir(WORK))
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
# 사람들이 이모티콘으로 삼는 건 대개 큰 사진이다 - 그대로 두면 보이지도 않을 화소를
# 영원히 들고 있게 된다(이모티콘은 기한으로 안 지운다)
big_photo = png(2400, 1600)
shrunk = put(big_photo, name="큰사진.jpg", kind="emoji")
check(f"큰 그림도 이모티콘으로 받아준다({shrunk.status_code})", shrunk.status_code == 200,
      shrunk.text[:200])
check(f"서버가 줄여서 저장한다({len(big_photo)} -> {shrunk.json().get('size')}바이트)",
      shrunk.json().get("size", 0) < len(big_photo), shrunk.json())
made = client.get(shrunk.json()["url"])
saved_image = Image.open(_io.BytesIO(made.content))
check(f"이모티콘 크기로 줄었다({saved_image.size})", max(saved_image.size) <= 320,
      saved_image.size)
check("비율이 안 망가졌다(3:2 그대로)",
      abs(saved_image.size[0] / saved_image.size[1] - 1.5) < 0.05, saved_image.size)
check(f"확장자를 실제 저장 형식에 맞춘다({shrunk.json().get('name')})",
      shrunk.json().get("name", "").endswith(".png"), shrunk.json())

# 같은 짤을 여럿이 저장하는 건 흔한 일이다 - 그때마다 쌓이면 안 지우는 종류라 계속 남는다
emoji_before = len([n for n in os.listdir(WORK)
                    if n.endswith(".bin") and files._kind_of(n[:-4]) == "emoji"])
again = put(big_photo, name="같은사진.png", kind="emoji")
check("같은 그림을 또 올리면 있던 것을 그대로 준다",
      again.json().get("id") == shrunk.json().get("id"), again.json())
emoji_after = len([n for n in os.listdir(WORK)
                   if n.endswith(".bin") and files._kind_of(n[:-4]) == "emoji"])
check(f"파일이 두 벌 생기지 않는다({emoji_before} -> {emoji_after})",
      emoji_after == emoji_before, emoji_after)

# 움직이는 이모티콘을 첫 장으로 납작하게 만들면 쓸 이유가 없어진다
animated = put(moving_gif(), name="움짤.gif", kind="emoji")
check(f"움짤도 받아준다({animated.status_code})", animated.status_code == 200,
      animated.text[:200])
moved = Image.open(_io.BytesIO(client.get(animated.json()["url"]).content))
check(f"움짤은 움짤로 남는다({animated.json().get('name')}, {moved.n_frames}장)",
      moved.is_animated and moved.n_frames == 4, animated.json())
check(f"움짤도 이모티콘 크기로 줄인다({moved.size})", max(moved.size) <= 320, moved.size)

check("그림이 아니면 이모티콘으로 안 받는다",
      put("이건 그림이 아니다".encode("utf-8") * 20, name="아님.png",
          kind="emoji").status_code == 400)

emoji = put(png(60, 60, (10, 200, 10)), name="웃음.png", kind="emoji")
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
    kept = [put(png(20, 20, (n * 90, 10, 10)), name=f"{n}.png", kind="emoji")
            for n in range(2)]
    check(f"한도 안에서는 저장된다({[r.status_code for r in kept]})",
          all(r.status_code == 200 for r in kept), [r.text[:80] for r in kept])
    refused = put(png(21, 21, (5, 5, 200)), name="셋.png", kind="emoji")
    check(f"개수가 차면 새로 저장하는 걸 거절한다({refused.status_code})",
          refused.status_code == 429, refused.text[:140])
    check("먼저 저장한 이모티콘은 그대로 있다",
          os.path.exists(os.path.join(WORK, emoji_id + ".bin")))
finally:
    files.LIMITS["emoji_per_person"] = real_count

real_emoji_cap = files.LIMITS["emoji_bytes"]
files.LIMITS["emoji_bytes"] = 20
try:
    too_big = put(png(300, 300, (1, 2, 3)), name="큰.png", kind="emoji")
    check(f"이모티콘은 작아야 한다({too_big.status_code})", too_big.status_code == 413,
          too_big.text[:120])
finally:
    files.LIMITS["emoji_bytes"] = real_emoji_cap

# ---------- 5-0) 이모티콘은 같이 쓴다 ----------
# 혼자 쓰려고 저장하는 게 아니라 대화에 쓰려고 저장하는 것이다 - 한 사람이 챙기면
# 같은 채팅 서버를 쓰는 나머지는 그냥 꺼내 쓰면 된다
OURS = "1" * 24
THEIRS = "2" * 24


def put_emoji(data, name, group=OURS):
    headers = {"X-File-Name": urllib.parse.quote(name), "X-File-Kind": "emoji"}
    if group:
        headers["X-Emoji-Group"] = group
    return client.post("/files", content=data, headers=headers)


mine = put_emoji(png(50, 50, (9, 9, 200)), "내가챙긴짤.png")
check(f"무리를 달아 올릴 수 있다({mine.status_code})", mine.status_code == 200, mine.text[:160])

shared = client.get("/files/emoji", params={"group": OURS}).json()
names = [item["name"] for item in shared["emoji"]]
check(f"같은 서버 사람이 목록에서 본다({names})", "내가챙긴짤.png" in names, shared)
check("주소가 같이 온다(바로 쓸 수 있게)",
      all(item["url"].startswith("/files/") for item in shared["emoji"]), shared)

other = client.get("/files/emoji", params={"group": THEIRS}).json()
check(f"다른 서버 사람에게는 안 보인다({len(other['emoji'])}개)",
      "내가챙긴짤.png" not in [i["name"] for i in other["emoji"]], other)

# 같은 그림을 다른 서버 사람이 저장하면 - 파일은 한 벌, 목록은 양쪽에
same_image = png(50, 50, (9, 9, 200))
copied = put_emoji(same_image, "쟤네가챙긴짤.png", group=THEIRS)
check("같은 그림이면 있던 것을 준다", copied.json()["id"] == mine.json()["id"], copied.json())
check("그래도 다른 서버 목록에도 뜬다",
      mine.json()["id"] in [i["id"] for i in
                            client.get("/files/emoji", params={"group": THEIRS}).json()["emoji"]],
      client.get("/files/emoji", params={"group": THEIRS}).json())
check("우리 목록에서 사라지지 않는다",
      mine.json()["id"] in [i["id"] for i in
                            client.get("/files/emoji", params={"group": OURS}).json()["emoji"]])

# 무리를 안 알려주면 목록에 안 뜬다(그 사람만 쓴다)
alone = put_emoji(png(51, 51, (1, 90, 90)), "혼자쓸것.png", group="")
check(f"무리 없이 올린 것은 목록에 안 뜬다({alone.status_code})",
      alone.status_code == 200
      and alone.json()["id"] not in
      [i["id"] for i in client.get("/files/emoji", params={"group": OURS}).json()["emoji"]],
      alone.json())

check("무리 id가 아니면 거절",
      client.get("/files/emoji", params={"group": "짧음"}).status_code == 400)
check("무리를 안 주면 거절", client.get("/files/emoji").status_code == 400)

# 최근에 챙긴 것이 위로 와야 바로 찾는다
put_emoji(png(52, 52, (200, 200, 9)), "방금챙긴짤.png")
top = client.get("/files/emoji", params={"group": OURS}).json()["emoji"][0]
check(f"최근에 챙긴 것이 맨 위({top['name']})", top["name"] == "방금챙긴짤.png", top)

# ---------- 5-1) 큰 파일은 더 짧게 둔다 ----------
# 1GB짜리 몇 개면 하루 만에 수십 GB가 된다
check(f"보통 파일은 하루({files.keep_seconds(1000) / 3600:.0f}시간)",
      files.keep_seconds(1000) == 24 * 3600, files.keep_seconds(1000))
check(f"500MB 넘으면 6시간({files.keep_seconds(600 * 1024 ** 2) / 3600:.0f}시간)",
      files.keep_seconds(600 * 1024 ** 2) == 6 * 3600,
      files.keep_seconds(600 * 1024 ** 2))

real_big = files.LIMITS["big_bytes"]
files.LIMITS["big_bytes"] = 100
reset_quota()
try:
    small_id = put(b"s" * 50, name="작은.bin").json()["id"]
    big_id = put(b"b" * 500, name="큰.bin").json()["id"]
    # 7시간 전에 올린 것처럼 만든다 - 큰 것만 사라져야 한다
    seven_hours_ago = time.time() - 7 * 3600
    for target in (small_id, big_id):
        os.utime(os.path.join(WORK, target + ".bin"), (seven_hours_ago, seven_hours_ago))
    files._sweep()
    check("7시간 지난 큰 파일은 지운다",
          not os.path.exists(os.path.join(WORK, big_id + ".bin")))
    check("같은 시각에 올린 작은 파일은 그대로 있다(하루까지 둔다)",
          os.path.exists(os.path.join(WORK, small_id + ".bin")))
finally:
    files.LIMITS["big_bytes"] = real_big

# ---------- 5-2) 자리가 없으면 지우지 말고 막는다 ----------
# 넘칠 때 오래된 것부터 지우면 남이 방금 올린 파일이 소리 없이 사라진다
real_total = files.LIMITS["total_bytes"]
files.LIMITS["total_bytes"] = files.used_bytes() + 100
reset_quota()
try:
    before_files = sorted(n for n in os.listdir(WORK) if n.endswith(".bin"))
    full = put(b"x" * 500, name="자리없음.bin")
    check(f"가득 차면 거절한다({full.status_code})", full.status_code == 507, full.text[:140])
    check(f"이유를 알려준다({full.json().get('error')})",
          "가득" in full.json().get("error", ""), full.json())
    check("**있던 파일을 지우지 않는다**",
          sorted(n for n in os.listdir(WORK) if n.endswith(".bin")) == before_files,
          sorted(n for n in os.listdir(WORK) if n.endswith(".bin")))
finally:
    files.LIMITS["total_bytes"] = real_total
    reset_quota()

# ---------- 6) 상태 페이지 ----------
status = client.get("/files").json()
check(f"한도를 밖에서 볼 수 있다({sorted(status.get('limits', {}))[:3]})",
      "file_bytes" in status.get("limits", {}) and "emoji_bytes" in status["limits"], status)
check(f"얼마나 쓰고 있는지 알려준다({status.get('used_bytes')}바이트)",
      isinstance(status.get("used_bytes"), int), status)

shutil.rmtree(WORK, ignore_errors=True)
print("\n전체 통과:", ok)
sys.exit(0 if ok else 1)
