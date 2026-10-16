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
# kiln_small·big·huge = 공방에서 나오는 화분 크기 비율 (셋의 합으로 나눠 씀, 기본은 고루)
RATE_DEFAULTS = {"premium": 0.05, "tree": 0.35, "rare": 0.05, "lux": 0.20, "fuse": 0.05, "kiln": 0.05,
                 "kiln_small": 0.3333, "kiln_big": 0.3333, "kiln_huge": 0.3333}
RATE_LIMITS = {"premium": (0.0, 0.5), "tree": (0.0, 1.0), "rare": (0.0, 0.5), "lux": (0.0, 1.0), "fuse": (0.0, 1.0), "kiln": (0.0, 1.0),
               "kiln_small": (0.0, 1.0), "kiln_big": (0.0, 1.0), "kiln_huge": (0.0, 1.0)}
RATE_NAMES = {"premium": "고급 나무 (씨앗 꾸러미)", "tree": "묘목 · 나무 (고급이 아닐 때)",
              "rare": "신비한 씨앗·묘목 (고급이 아닐 때)", "lux": "고급 화분 (화분 뽑기)",
              "fuse": "고급 묘목 (의문의 상인 — 씨앗 3개)", "kiln": "고급 화분 (공방 — 화분 3개)",
              "kiln_small": "공방 크기 비율 — 작은 화분", "kiln_big": "공방 크기 비율 — 큰 화분", "kiln_huge": "공방 크기 비율 — 아주 큰 화분"}
KILN_SIZE_KEYS = ("kiln_small", "kiln_big", "kiln_huge")   # POT_SIZES 순서
# 관리 화면 「확률」 묶음
RATE_GROUPS = [["뽑기 (씨앗 꾸러미 · 화분 뽑기)", ["premium", "tree", "rare", "lux"]],
               ["재조합 (의문의 상인 · 공방)", ["fuse", "kiln", "kiln_small", "kiln_big", "kiln_huge"]]]

# ---- 의문의 상인(씨앗 3개 → 고른 씨앗 하나) · 공방(화분 3개 → 다시 구운 화분 하나) ----
CRAFT_COUNT = 3
LEGACY_POTS_MAX = 60       # 예전 판에서 모아 둔 화분 (처음 한 번 등록)

# ---- 도전과제: 이름 → (꾸러미, 화분 뽑기권). 한 유저에 한 번 ----
ACH_POTS = 30              # 화분 수집가: 화분 30개 모으기
ACH_SEEDS = 30             # 씨앗 매니아: 꾸러미 30번 열기
ACHIEVEMENTS = {"pots30": (0, 5), "seeds30": (0, 5)}
for _n in range(2, 13):    # 처음으로 2~12단계: 짝수 단계 = 화분 뽑기권, 홀수 = 꾸러미
    ACHIEVEMENTS["stage%d" % _n] = (0, 1) if _n % 2 == 0 else (1, 0)
# 수집 목표 (게임이 종류를 확인, 서버는 다 키운 식물 수로만 확인): 이름 → 다 키운 식물이 이만큼은 있어야
COLLECT_NEED = {"col_spring": 3, "col_field": 3, "col_quiet": 2, "col_autumn": 2, "col_evergreen": 2,
                "col_flowers": 10, "col_trees": 8, "col_pastel": 1, "col_cactus": 4}   # 꽃 10종(할미꽃·제비꽃) · 나무 8종(몬스테라·무궁화·치자나무)
ACHIEVEMENTS.update({"col_spring": (1, 0), "col_field": (1, 0), "col_quiet": (1, 0), "col_autumn": (0, 1), "col_evergreen": (0, 1),
                     "col_flowers": (2, 2), "col_trees": (2, 2), "col_pastel": (1, 0), "col_premium": (0, 2), "col_cactus": (1, 1)})   # col_premium = 고급 나무 다 키움 (서버가 셈)

# ---- 우편함: 받은 이벤트 우편은 며칠 동안 「받았어요」로 남김 · 한 번에 보여 줄 우편 수 ----
MAIL_KEEP_DAYS = 14
MAIL_MAX = 30

# ---- 일일 퀘스트 (서버 날짜 KST 하루에 한 번씩): 이름 → (꾸러미, 화분 뽑기권) ----
DAILY = {"care1": (1, 0), "care3": (1, 0), "draw1": (0, 2)}
DAILY_CARE = {"care1": 1, "care3": 3}   # 오늘 물·영양제를 각각 이만큼 (게임이 센 값)
STAGE_HOURS = 0.6          # 처음 키우는 유저(옮겨 온 게 아님)는 등록 뒤 (단계-1)×이만큼 시간이 지나야 단계 도전과제 인정
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
