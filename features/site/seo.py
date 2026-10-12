"""site 의 간판·검색 규칙 층 - 페이지 머리의 간판(제목·설명·대표 그림), 구글용 구조화 정보,
robots.txt, 사이트맵, 웹 앱 정보(manifest), 자바스크립트 없이도 보이는 작품 목록.

HTTP 도 디스크도 모른다. 설정·작품을 받아 글자(HTML·XML·JSON)를 돌려준다.

## 간판이 어디에 뜨나
    브라우저 탭        제목(title) + 아이콘(favicon)
    카톡·페북 링크     og:site_name(간판 이름) · og:title · og:description · og:image(1200×630)
    구글 검색 결과      WebSite 구조화 정보의 사이트 이름 + 아이콘, 제목·설명
    휴대폰 홈 화면      manifest 의 이름·아이콘, apple-touch-icon
작품 주소(/w/<작품>)는 그 작품 제목·소개·그림이 간판이 된다 — 링크만 봐도 무슨 작품인지 구분되게.
"""
import html
import json

from . import bots

DEFAULT_DESC = "직접 만든 게임·앱·도구를 모아 둔 개인 개발 포트폴리오입니다."
PRIVATE_PATHS = ("/admin", "/api/admin/", "/dl/", "/files/", "/logs/", "/profiles/", "/battle", "/chat")


def _e(v):
    return html.escape(v or "", quote=True)


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def site_title(s):
    name = s.get("name") or "Portfolio"
    tail = s.get("headline") or "개인 개발 포트폴리오"
    return _clip("%s — %s" % (name, tail), 70)


def work_title(w, s):
    return _clip("%s — %s" % (w.get("title") or w.get("slug"), s.get("name") or "Portfolio"), 70)


def work_desc(w):
    bits = [w.get("tagline") or "", w.get("desc") or ""]
    text = " · ".join(b for b in bits if b) or DEFAULT_DESC
    return _clip(text, 150)


def verify_tags(s):
    """검색엔진 소유 확인 메타 태그 (관리 화면 설정에 코드를 넣으면 생김)."""
    out = []
    if s.get("google_verify"):
        out.append('<meta name="google-site-verification" content="%s">' % _e(s["google_verify"]))
    if s.get("naver_verify"):
        out.append('<meta name="naver-site-verification" content="%s">' % _e(s["naver_verify"]))
    return "\n".join(out)


def _ld(data):
    """JSON-LD 를 <script> 안에 안전하게 (</script> 로 끊기지 않게)."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def owner_ld(s, url):
    owner = {"@type": "Person", "@id": url + "/#owner", "name": s.get("name") or "Portfolio", "url": url + "/",
             "image": url + "/static/icons/icon-512.png"}
    if s.get("github"):
        owner["sameAs"] = [s["github"]]
    return owner


def home_ld(s, url, works):
    return _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "@id": url + "/#website", "url": url + "/", "name": s.get("name") or "Portfolio",
         "description": s.get("headline") or DEFAULT_DESC, "inLanguage": "ko-KR", "publisher": {"@id": url + "/#owner"}},
        owner_ld(s, url),
        {"@type": "ItemList", "name": "작품", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": "%s/w/%s" % (url, w["slug"]), "name": w.get("title") or w["slug"]}
            for i, w in enumerate(works)]},
    ]})


def work_ld(w, s, url, image):
    game = (w.get("kind") or "") == "게임"
    app = {"@type": "VideoGame" if game else "SoftwareApplication", "name": w.get("title") or w["slug"],
           "description": work_desc(w), "url": "%s/w/%s" % (url, w["slug"]), "image": image,
           "applicationCategory": "GameApplication" if game else "Application",
           "operatingSystem": "Web" if w.get("play") else "Windows, Android",
           "author": {"@id": url + "/#owner"}, "inLanguage": "ko-KR"}
    if w.get("version"):
        app["softwareVersion"] = w["version"]
    if w.get("updated"):
        app["dateModified"] = w["updated"]
    return _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "@id": url + "/#website", "url": url + "/", "name": s.get("name") or "Portfolio"},
        owner_ld(s, url), app,
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": s.get("name") or "Portfolio", "item": url + "/"},
            {"@type": "ListItem", "position": 2, "name": w.get("title") or w["slug"], "item": "%s/w/%s" % (url, w["slug"])}]},
    ]})


def works_html(works):
    """자바스크립트 없이도 보이는 작품 목록(검색엔진·느린 연결용). 화면이 뜨면 자바스크립트가 예쁜 카드로 바꾼다."""
    if not works:
        return ""
    items = []
    for w in works:
        meta = " · ".join(x for x in (w.get("kind"), w.get("status"), w.get("version")) if x)
        items.append('<a class="ssr-work" href="/w/%s"><strong>%s</strong><span>%s</span><span>%s</span></a>'
                     % (_e(w["slug"]), _e(w.get("title") or w["slug"]), _e(meta), _e(w.get("tagline"))))
    return "\n".join(items)


def robots_txt(url):
    lines = ["# 검색엔진·링크 미리보기 로봇은 환영합니다"]
    lines += ["User-agent: %s" % a for a in bots.ROBOTS_ALLOW]
    lines += ["Allow: /"] + ["Disallow: %s" % p for p in PRIVATE_PATHS]
    lines += ["", "# AI 학습·SEO 수집 로봇은 사이트 전체를 거절합니다"]
    lines += ["User-agent: %s" % a for a in bots.ROBOTS_DENY]
    lines += ["Disallow: /", "", "# 그 밖의 로봇도 거절합니다", "User-agent: *", "Disallow: /", "",
              "Sitemap: %s/sitemap.xml" % url]
    return "\n".join(lines) + "\n"


def sitemap_xml(url, works):
    def entry(loc, lastmod, priority):
        mod = "<lastmod>%s</lastmod>" % _e(lastmod[:10]) if lastmod else ""
        return "<url><loc>%s</loc>%s<priority>%s</priority></url>" % (_e(loc), mod, priority)
    newest = max((w.get("updated") or "" for w in works), default="")
    rows = [entry(url + "/", newest, "1.0")] + [entry("%s/w/%s" % (url, w["slug"]), w.get("updated") or "", "0.8") for w in works]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def manifest(s):
    name = s.get("name") or "Portfolio"
    return {
        "name": name, "short_name": name[:12], "description": s.get("headline") or DEFAULT_DESC,
        "start_url": "/", "scope": "/", "display": "standalone", "lang": "ko",
        "background_color": "#05060a", "theme_color": "#05060a",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
