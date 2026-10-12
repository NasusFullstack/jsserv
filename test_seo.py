"""간판·검색·로봇 - 링크 미리보기에 간판이 뜨는가, 구글이 들어올 수 있는가, 수집 로봇은 막히는가.

이 기능의 값은 셋이다: **페이지마다 간판(제목·설명·1200×630 그림·사이트 이름)이 제대로 붙는가**,
**구글·네이버·카톡 미리보기 로봇은 들어오고 사이트맵·구조화 정보가 있는가**,
**AI 학습·SEO 수집 로봇은 막히되 사람·앱(춥채팅 등)은 영향이 없는가.**
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile

WORK = tempfile.mkdtemp(prefix="jsserv_seo_")
TOKEN = "test-token-123"
os.environ["JSSERV_SITE_DIR"] = os.path.join(WORK, "site")
os.environ["JSSERV_GAME_DIR"] = os.path.join(WORK, "game")
os.environ["JSSERV_GAME_TOKEN_SHA256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
os.environ.pop("JSSERV_ADMIN_TOKEN_SHA256", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import app  # noqa: E402
from features.site import releases  # noqa: E402

releases.fetch = lambda repo: None
client = TestClient(app)
checks = []
KEY = {"X-Admin-Key": TOKEN}
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
GOOGLE = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
KAKAO = "kakaotalk-scrap/1.0; +https://devtalk.kakao.com/"
GPT = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"
UNKNOWN_BOT = "Mozilla/5.0 (compatible; SomeNewBot/0.1; +http://x.example)"


def check(name, passed, detail=""):
    checks.append((name, passed, detail))


def get(path, ua=BROWSER, ip="1.1.1.1", html=True):
    headers = {"User-Agent": ua, "X-Forwarded-For": ip}
    if html:
        headers["Accept"] = "text/html"
    return client.get(path, headers=headers, follow_redirects=False)


def meta(page, prop):
    m = re.search(r'<meta (?:property|name)="%s" content="([^"]*)"' % re.escape(prop), page)
    return m.group(1) if m else None


def png(w=800, h=800, color=(200, 50, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# ---- 첫 화면 간판 ----
page = get("/").text
check("제목에 사이트 이름과 소개가 같이", "<title>NasusFullstack — " in page, re.search(r"<title>[^<]*", page).group(0))
check("링크 미리보기용 간판 이름(og:site_name)", meta(page, "og:site_name") == "NasusFullstack")
check("간판 그림은 1200×630 이라고 알려 준다", meta(page, "og:image:width") == "1200" and meta(page, "og:image:height") == "630")
check("간판 그림 주소가 실제로 열린다", get(meta(page, "og:image").replace("https://jsserv.pdlab.kr", ""), html=False).status_code == 200, meta(page, "og:image"))
check("트위터·디스코드용 그림·제목", meta(page, "twitter:image") and meta(page, "twitter:title"))
check("대표 주소(canonical)", '<link rel="canonical" href="https://jsserv.pdlab.kr/">' in page)
check("한국어 페이지라고 알려 준다", meta(page, "og:locale") == "ko_KR" and '<html lang="ko">' in page)
check("빈칸({{…}})이 하나도 안 남는다", "{{" not in page, re.findall(r"\{\{[A-Z_]+\}\}", page))
ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
types = [g["@type"] for g in ld["@graph"]]
check("구글용 구조화 정보: 사이트 이름·주인·작품 목록", types == ["WebSite", "Person", "ItemList"] and ld["@graph"][0]["name"] == "NasusFullstack", types)
check("자바스크립트 없이도 작품 링크가 보인다", 'href="/w/danmak"' in page and 'href="/w/chupchat"' in page)
check("아이콘·홈 화면 정보 링크", 'rel="apple-touch-icon"' in page and 'rel="manifest"' in page)

# ---- 작품 주소 간판 ----
client.post("/api/admin/works/danmak/cover", content=png(1600, 900), headers=KEY)
page = get("/w/danmak").text
check("작품 주소는 작품 제목이 간판", "<title>탄막게임 — NasusFullstack</title>" in page and meta(page, "og:title") == "탄막게임 — NasusFullstack")
img = meta(page, "og:image")
check("작품 미리보기 그림은 JPEG 주소", img and "/og/danmak.jpg?v=" in img, img)
r = get(img.replace("https://jsserv.pdlab.kr", ""), html=False)
im = Image.open(io.BytesIO(r.content))
check("작품 미리보기 그림이 1200×630 JPEG 로 만들어진다", r.status_code == 200 and im.format == "JPEG" and im.size == (1200, 630), (r.status_code, im.format, im.size))
ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
game = next(g for g in ld["@graph"] if g["@type"] in ("VideoGame", "SoftwareApplication"))
check("작품 구조화 정보: 게임이면 VideoGame", game["@type"] == "VideoGame" and game["name"] == "탄막게임", game)
client.post("/api/admin/works/danmak/cover", content=png(1600, 900, (10, 200, 90)), headers=KEY)
olds = [f for f in os.listdir(os.path.join(WORK, "site", "media", "danmak")) if f.startswith("og-")]
check("대표 그림을 바꾸면 옛 미리보기 그림은 지운다", olds == [], olds)
check("새 대표 그림이면 미리보기 주소도 바뀐다(카톡 캐시 피하기)", meta(get("/w/danmak").text, "og:image") != img)

# ---- 간판 그림 바꾸기 ----
check("열쇠 없이는 간판 그림을 못 바꾼다", client.post("/api/admin/site/og", content=png()).status_code == 403)
check("그림이 아니면 거절", client.post("/api/admin/site/og", content=b"nope", headers=KEY).status_code == 400)
r = client.post("/api/admin/site/og", content=png(900, 900), headers=KEY)
check("간판 그림을 올린다", r.status_code == 200 and r.json()["image"].startswith("/og/site.jpg?v="), r.text)
og = Image.open(io.BytesIO(get("/og/site.jpg", html=False).content))
check("간판 그림도 1200×630 JPEG 로 맞춘다", og.format == "JPEG" and og.size == (1200, 630), (og.format, og.size))
check("첫 화면 간판이 새 그림으로", "/og/site.jpg?v=" in (meta(get("/").text, "og:image") or ""))
client.put("/api/admin/settings", headers=KEY, json={"name": "NasusFullstack", "headline": "만든 것들"})
check("설정을 저장해도 간판 그림은 그대로", "/og/site.jpg?v=" in (meta(get("/").text, "og:image") or ""))
r = client.delete("/api/admin/site/og", headers=KEY)
check("기본 간판 그림으로 되돌린다", r.status_code == 200 and meta(get("/").text, "og:image").endswith("/static/og.png"))

# ---- 검색엔진 확인 코드 ----
r = client.put("/api/admin/settings", headers=KEY, json={"name": "NasusFullstack", "google_verify": '<meta name="google-site-verification" content="abc_DEF-123456" />', "naver_verify": "naver0123456789"})
page = get("/").text
check("구글 확인 코드: 태그째 붙여도 값만 저장", r.status_code == 200 and r.json()["site"]["google_verify"] == "abc_DEF-123456", r.text)
check("확인 코드가 페이지 머리에", meta(page, "google-site-verification") == "abc_DEF-123456" and meta(page, "naver-site-verification") == "naver0123456789")
for acc in ("*/*", None):
    hdr = {"User-Agent": "Mozilla/5.0 (compatible; Google-Site-Verification/1.0)", "Accept": acc} if acc else {"User-Agent": "Mozilla/5.0 (compatible; Google-Site-Verification/1.0)"}
    rr = client.get("/", headers=hdr)
    check("구글 확인 로봇이 Accept %s 로 물어도 화면(확인 태그)을 받는다" % (acc or "없음"),
          "text/html" in rr.headers["content-type"] and meta(rr.text, "google-site-verification") == "abc_DEF-123456", rr.headers["content-type"])
rr = client.get("/", headers={"User-Agent": "kakaotalk-scrap/1.0", "Accept": "*/*"})
check("카톡 미리보기 로봇이 */* 로 물어도 간판을 받는다", meta(rr.text, "og:site_name") == "NasusFullstack", rr.headers["content-type"])
check("JSON 은 원한다고 밝혀야만 (?format=json)", client.get("/?format=json").headers["content-type"].startswith("application/json"))
r = client.put("/api/admin/settings", headers=KEY, json={"name": "NasusFullstack", "google_verify": '"><script>x</script>'})
check("이상한 확인 코드는 거절", r.status_code == 400, r.status_code)

# ---- robots.txt · 사이트맵 · manifest ----
robots = get("/robots.txt", ua=GPT, html=False)
txt = robots.text
check("수집 로봇도 robots.txt 는 읽을 수 있다(읽어야 물러간다)", robots.status_code == 200)
check("구글·네이버·카톡은 들어오게", all(("User-agent: %s" % a) in txt for a in ("Googlebot", "Yeti", "kakaotalk-scrap")))
google_block = txt.split("# AI")[0]
check("구글 그룹은 화면 그리기에 필요한 자료(/api/overview)를 막지 않는다", "Disallow: /api/\n" not in google_block and "Disallow: /api/admin/" in google_block)
check("AI 학습 로봇은 전부 거절", "User-agent: GPTBot" in txt and "User-agent: CCBot" in txt and txt.count("Disallow: /\n") >= 2)
check("사이트맵 위치를 알려 준다", "Sitemap: https://jsserv.pdlab.kr/sitemap.xml" in txt)
sm = get("/sitemap.xml", ua=GOOGLE, html=False)
check("사이트맵에 첫 화면과 작품 주소", sm.status_code == 200 and "<loc>https://jsserv.pdlab.kr/w/danmak</loc>" in sm.text and "<loc>https://jsserv.pdlab.kr/</loc>" in sm.text)
client.put("/api/admin/works/chupchat", headers=KEY, json={"title": "춥채팅", "hidden": True})
check("숨긴 작품은 사이트맵·첫 화면 목록에서 빠진다", "/w/chupchat" not in get("/sitemap.xml", html=False).text and 'href="/w/chupchat"' not in get("/").text)
client.put("/api/admin/works/chupchat", headers=KEY, json={"title": "춥채팅", "hidden": False})
mf = get("/site.webmanifest", html=False).json()
check("홈 화면 정보(manifest)에 이름·아이콘", mf["name"] == "NasusFullstack" and len(mf["icons"]) == 3)
for icon in [i["src"] for i in mf["icons"]] + ["/static/icons/apple-touch-icon.png"]:
    check("아이콘 파일이 열린다: " + icon, get(icon, html=False).status_code == 200)
fav = get("/favicon.ico", html=False)
check("favicon.ico 는 진짜 ICO", fav.status_code == 200 and fav.headers["content-type"] == "image/x-icon")

# ---- 로봇 막기 ----
check("구글은 들어온다", get("/", ua=GOOGLE).status_code == 200 and get("/w/danmak", ua=GOOGLE).status_code == 200)
check("구글은 화면 그리기용 자료도 받는다", get("/api/overview", ua=GOOGLE, html=False).status_code == 200)
check("카톡 미리보기 로봇은 들어온다", get("/", ua=KAKAO).status_code == 200 and get("/og/site.jpg", ua=KAKAO, html=False).status_code == 200)
check("AI 학습 로봇은 막는다", get("/", ua=GPT).status_code == 403 and get("/api/overview", ua=GPT, html=False).status_code == 403)
check("이름 없는 로봇도 막는다", get("/w/danmak", ua=UNKNOWN_BOT).status_code == 403)
before = client.get("/api/overview").json()["stats"]["today"]["views"]
get("/", ua=GPT, ip="3.3.3.3")
get("/w/danmak", ua=UNKNOWN_BOT, ip="3.3.3.4")
after_bots = client.get("/api/overview").json()["stats"]["today"]["views"]
get("/", ip="3.3.3.5")
after_human = client.get("/api/overview").json()["stats"]["today"]["views"]
check("막힌 로봇은 방문으로 안 세고, 사람은 센다", after_bots == before and after_human == before + 1, (before, after_bots, after_human))
check("춥채팅 앱이 쓰는 주소는 검사하지 않는다(로봇 이름이어도)", get("/profiles", ua=GPT, html=False).status_code != 403 and get("/health", ua=GPT, html=False).status_code == 200)
check("프로그램(파이썬·curl)은 그대로", get("/", ua="Python-urllib/3.13", html=False).status_code == 200 and get("/robots.txt", ua="curl/8.4", html=False).status_code == 200)

# ---- 겹친 슬래시 ----
r = client.get("http://testserver//", follow_redirects=False)
check("// 는 / 로 고쳐 보낸다 (nginx http→https 가 // 로 보내던 것)", r.status_code == 301 and r.headers["location"] == "/", (r.status_code, r.headers.get("location")))
r = client.get("http://testserver//w//danmak?x=1", follow_redirects=False)
check("겹친 슬래시는 어디든 하나로 (뒤 물음표는 그대로)", r.status_code == 301 and r.headers["location"] == "/w/danmak?x=1", r.headers.get("location"))

# ---- 너무 잦은 요청 ----
codes = [get("/", ip="9.9.9.9").status_code for _ in range(125)]
check("한 주소가 1분에 120번 넘게 열면 잠시 막는다", codes[:120].count(200) == 120 and codes[-1] == 429, (codes.count(200), codes[-1]))
check("다른 주소는 그대로", get("/", ip="9.9.9.8").status_code == 200)
check("검색엔진은 횟수 제한을 안 받는다", all(get("/", ua=GOOGLE, ip="9.9.9.9").status_code == 200 for _ in range(3)))

shutil.rmtree(WORK, ignore_errors=True)
bad = [c for c in checks if not c[1]]
for name, passed, detail in checks:
    print(("통과 " if passed else "실패 ") + name + ("" if passed else "  (%s)" % (detail,)))
print("%d개 중 %d개 통과" % (len(checks), len(checks) - len(bad)))
sys.exit(1 if bad else 0)
