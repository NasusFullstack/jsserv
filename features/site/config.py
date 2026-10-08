"""site 의 설정 층 - 자리(경로)·한도·열쇠 지문. 다른 층은 숫자를 여기서만 가져다 쓴다.

숫자를 바꿀 일이 생기면 이 파일만 고친다.
"""
import datetime
import hashlib
import hmac
import os

# ---- 자리 ----
def _base_dir():
    """쌓이는 데이터의 자리: 서버의 영구 보존 폴더 /data, 없으면 집 폴더(내 PC)."""
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return os.path.join("/data", "jsserv")
    return os.path.join(os.path.expanduser("~"), ".jsserv")


DATA = os.path.realpath(os.environ.get("JSSERV_SITE_DIR", os.path.join(_base_dir(), "site")))
WORKS_FILE = os.path.join(DATA, "works.json")          # 작품 목록
SETTINGS_FILE = os.path.join(DATA, "settings.json")    # 사이트 이름·소개·연락처
MEDIA = os.path.join(DATA, "media")                    # media/<작품>/cover.webp, shot-*.webp
DOWNLOADS = os.path.join(DATA, "downloads")            # downloads/<작품>/<파일 하나>
BUILDS = os.path.join(DATA, "builds")                  # builds/<작품>/index.html … (웹 빌드)
STATS_DB = os.path.join(DATA, "stats.sqlite3")         # 방문 통계

# 화면 파일(HTML·CSS·JS)은 저장소 안 web/ 에 있다 - 공개해도 되는 것만
WEB = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web"))

# 하루의 경계는 한국 시간
KST = datetime.timezone(datetime.timedelta(hours=9))

# ---- 열쇠 ----
# 코드에는 SHA-256 지문만 둔다. 따로 정하지 않으면 게임 올리기 열쇠와 같은 열쇠를 쓴다
# (주인이 한 명이라 열쇠도 하나가 편하다). 바꾸려면 환경 변수 JSSERV_ADMIN_TOKEN_SHA256.
_GAME_KEY = "22ab5feafcd3f8d0d9e6e3874ad7639a5e9204b483644e4d2761a5e0d634079d"
ADMIN_SHA256 = (os.environ.get("JSSERV_ADMIN_TOKEN_SHA256")
                or os.environ.get("JSSERV_GAME_TOKEN_SHA256") or _GAME_KEY).lower()
LOCK_FAILS = 20            # 열쇠를 이만큼 틀리면
LOCK_WINDOW = 10 * 60      # 이 시간(초) 동안 그 주소는 잠근다

# ---- 한도 ----
MAX_WORKS = 200
MAX_IMAGE = 12 * 1024 * 1024          # 대표 그림·스크린샷 한 장 (올리는 원본)
MAX_SHOTS = 8                         # 작품당 스크린샷
IMAGE_EDGE = 1920                     # 줄여서 보관할 때 긴 변
MAX_DOWNLOAD = 500 * 1024 * 1024      # 다운로드 파일 하나
MAX_BUILD_ZIP = 120 * 1024 * 1024     # 웹 빌드 zip
MAX_BUILD_FILES = 4000
MAX_BUILD_UNPACKED = 400 * 1024 * 1024

DOWNLOAD_TYPES = {".zip", ".7z", ".rar", ".exe", ".msi", ".apk", ".dmg", ".html", ".pdf", ".jar"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# 웹 빌드로 내려줄 수 있는 종류
BUILD_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".pck": "application/octet-stream",    # Godot 웹 내보내기
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}

# web/ 에서 내려주는 종류
WEB_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".woff2": "font/woff2",
}

IMAGE_MEDIA = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif"}


def key_matches(key):
    """열쇠 문자열이 맞는가. 길이가 달라도 시간 차이가 안 나게 비교한다."""
    return bool(key) and hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), ADMIN_SHA256)
