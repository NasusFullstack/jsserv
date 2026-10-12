"""site 의 로봇 규칙 층 - 어떤 로봇은 들이고(검색·링크 미리보기) 어떤 로봇은 막는지(AI 학습·SEO 수집 등).

HTTP 를 모른다. 브라우저 이름(User-Agent)을 받아 판정하고, 주소별 요청 횟수를 센다.

## 들이는 로봇
    검색엔진     구글(모든 Google 로봇)·빙·네이버(Yeti)·다음·덕덕고·애플
    링크 미리보기 카카오톡·페이스북·트위터(X)·슬랙·디스코드·텔레그램·링크드인·라인
  → 이 둘이 막히면 검색에 안 나오고, 링크를 보냈을 때 간판(제목·그림)이 안 뜬다.

## 막는 로봇
    이름이 알려진 AI 학습·SEO 수집 로봇(GPTBot·CCBot·ClaudeBot·Bytespider·AhrefsBot …)과,
    이름에 bot·crawl·spider·scrap 이 들어가는데 위 목록에 없는 것 전부.
    robots.txt 는 "부탁"이라 안 지키는 로봇이 있어서, 사이트 주소에서는 서버가 직접 403 으로 돌려보낸다.

## 막지 않는 것
    사람이 쓰는 브라우저, 그리고 프로그램(춥채팅 앱·게임 올리기 도구 등). 앱이 쓰는 주소는 아예 검사하지 않는다.
"""
import re
import threading
import time

SEARCH = re.compile(r"google|bingbot|bingpreview|msnbot|adidxbot|yeti|daum|duckduckbot|duckassistbot|applebot(?!-extended)", re.I)
PREVIEW = re.compile(r"kakaotalk-scrap|kakao|facebookexternalhit|facebot|twitterbot|slackbot|slack-imgproxy|discordbot|"
                     r"telegrambot|linkedinbot|whatsapp|line/|linespider|skypeuripreview|pinterestbot|redditbot|embedly", re.I)
# 이름이 알려진 수집 로봇 (위 허용 목록보다 먼저 본다 — 예: Google-Extended·Applebot-Extended 는 AI 학습용)
BAD = re.compile(r"gptbot|chatgpt-user|oai-searchbot|ccbot|claudebot|claude-web|claude-searchbot|anthropic-ai|perplexity|"
                 r"bytespider|amazonbot|meta-externalagent|meta-externalfetcher|diffbot|ahrefs|semrush|mj12bot|dotbot|"
                 r"petalbot|blexbot|dataforseo|barkrowler|serpstat|scrapy|imagesift|youbot|timpibot|omgili|cohere|"
                 r"google-extended|applebot-extended|baiduspider|yandex|sogou|seznambot|zoominfo|velenpublic|"
                 r"friendlycrawler|ia_archiver|archive\.org_bot|mojeek|awario|brightbot|newsnow|magpie-crawler", re.I)
# 이름에 bot 이 붙은 것: "XxxBot/1.0", "XxxBot;", "bot" 단어. 휴대폰 이름(예: Cubot X30)은 안 걸리게 띄어쓰기 앞은 안 본다
GENERIC_BOT = re.compile(r"[a-z]bot[;/)+]|(?<![a-z])bot\b|crawl|spider|scrap|slurp|harvest|indexer", re.I)


def classify(agent):
    """'bad'(막음) | 'search' | 'preview' | 'bot'(이름 없는 로봇 — 막음) | None(사람·프로그램)."""
    agent = agent or ""
    if BAD.search(agent):
        return "bad"
    if SEARCH.search(agent):
        return "search"
    if PREVIEW.search(agent):
        return "preview"
    if GENERIC_BOT.search(agent):
        return "bot"
    return None


def blocked(agent):
    return classify(agent) in ("bad", "bot")


# robots.txt 에 이름을 적어 둘 수집 로봇 (서버 차단과 별개로, 지키는 로봇은 여기서 알아서 안 온다)
ROBOTS_DENY = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "CCBot", "ClaudeBot", "Claude-Web", "anthropic-ai",
               "PerplexityBot", "Bytespider", "Amazonbot", "meta-externalagent", "Diffbot", "AhrefsBot", "SemrushBot",
               "MJ12bot", "DotBot", "PetalBot", "BLEXBot", "DataForSeoBot", "Barkrowler", "Google-Extended",
               "Applebot-Extended", "Baiduspider", "YandexBot", "cohere-ai", "ImagesiftBot", "Timpibot"]
ROBOTS_ALLOW = ["Googlebot", "Googlebot-Image", "Google-InspectionTool", "Bingbot", "Yeti", "Daumoa", "DuckDuckBot",
                "Applebot", "kakaotalk-scrap", "facebookexternalhit", "Twitterbot", "Slackbot", "Discordbot",
                "TelegramBot", "LinkedInBot"]


class RateLimit:
    """주소(IP)마다 1분 동안의 요청 수. 넘으면 True(막아야 함). 프로세스 안에서만 센다(가벼운 방어)."""

    def __init__(self, per_minute):
        self.per_minute = per_minute
        self.hits = {}        # 주소 → [창 시작 시각, 횟수]
        self.lock = threading.Lock()

    def over(self, ip, now=None):
        now = now or time.time()
        with self.lock:
            rec = self.hits.get(ip)
            if not rec or now - rec[0] >= 60:
                rec = self.hits[ip] = [now, 0]
            rec[1] += 1
            if len(self.hits) > 20000:          # 잊힌 주소가 쌓이지 않게
                for k in [k for k, v in self.hits.items() if now - v[0] >= 60]:
                    self.hits.pop(k, None)
            return rec[1] > self.per_minute
