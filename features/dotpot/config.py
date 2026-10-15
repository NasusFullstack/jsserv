"""화분키우기 서버의 설정 층 - 자리·한도·뽑기 확률. 숫자는 여기서만.

게임(desk-garden game/scripts/data.gd)과 같은 확률을 쓴다. 게임 쪽 숫자를 바꾸면 여기도 같이 바꾼다.
"""
import datetime
import os


def _base_dir():
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return os.path.join("/data", "jsserv")
    return os.path.join(os.path.expanduser("~"), ".jsserv")


DATA = os.path.realpath(os.environ.get("JSSERV_DOTPOT_DIR", os.path.join(_base_dir(), "dotpot")))
DB = os.path.join(DATA, "dotpot.sqlite3")
KST = datetime.timezone(datetime.timedelta(hours=9))

# ---- 처음 등록 ----
START_BUNDLES = 5          # 새로 시작하는 설치본
START_TICKETS = 1
MIGRATE_MAX_BUNDLES = 20   # 예전 판에서 가져오는 꾸러미 상한 (저장 파일을 고쳐 부풀리는 것 막기)
MIGRATE_MAX_TICKETS = 10
MIGRATE_MAX_LEGACY = 60    # 예전 판에서 키우던 식물·씨앗 (보상 받을 자격) 상한
BALANCE_MAX = 999

# ---- 뽑기 확률: 기본값 (관리 화면 「확률」에서 바꾸면 DB 값이 우선 — 게임은 켤 때·뽑을 때 받아 보여 줌) ----
RATE_DEFAULTS = {"premium": 0.05, "tree": 0.35, "rare": 0.05, "lux": 0.20}
RATE_LIMITS = {"premium": (0.0, 0.5), "tree": (0.0, 1.0), "rare": (0.0, 0.5), "lux": (0.0, 1.0)}
RATE_NAMES = {"premium": "고급 나무 (씨앗 꾸러미)", "tree": "묘목 · 나무 (고급이 아닐 때)",
              "rare": "신비한 씨앗·묘목 (고급이 아닐 때)", "lux": "고급 화분 (화분 뽑기)"}
POT_SIZES = ("small", "big", "huge")
PREMIUM_TREES = {"pine": "", "rubber": "", "cherry": "spring", "ginkgo": "autumn", "maple": "autumn", "xmas": "winter"}
SEASON_MONTHS = {"spring": (3, 4, 5), "autumn": (9, 10, 11), "winter": (12,)}

# ---- 보상: 뽑은 뒤 이만큼(서버 시계, 시간)은 지나야 「다 키움」 보상 (게임은 켜 둔 시간만 자라므로 실제 시간은 더 걸림) ----
GROW_HOURS = {"flower": 48.0, "tree": 72.0, "premium": 96.0}
GROW_SLACK = 0.6    # 가장 빠르면 건강 110% × 영양 넉넉 1.4 = 1.54배로 자람 (1/1.54 ≈ 0.65) → 그보다 조금 여유

# ---- 한도 ----
REGISTER_PER_HOUR = 20     # 한 주소에서 한 시간에 새 설치본 등록
CALLS_PER_HOUR = 300       # 한 설치본이 한 시간에 부르는 횟수
MAX_BODY = 16 * 1024
EVENT_DAYS = 7             # 이벤트를 따로 끝 날짜 없이 만들면 이 기간 안에 켠 사람까지
