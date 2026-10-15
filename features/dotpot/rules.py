"""화분키우기 서버의 규칙 층 - 뽑기 결과를 서버가 정한다 (HTTP·디스크 모름).

씨앗: 꽃·나무·고급 나무(그 달에 나오는 종류)·신비한 씨앗 여부 + 모습 번호(n).
게임은 모습 번호로 색·모양을 정한다(같은 번호면 언제나 같은 모습) → 뽑는 순간 모습까지 정해짐.
"""
import datetime
import secrets

from . import config as C

_rand = secrets.SystemRandom()


def season(month):
    for name, months in C.SEASON_MONTHS.items():
        if month in months:
            return name
    return ""


def premium_pool(month):
    se = season(month)
    return [t for t, s in C.PREMIUM_TREES.items() if s == "" or s == se]


def now_month():
    return datetime.datetime.now(C.KST).month


def roll_seed(rates, month=None):
    """rates = 지금 확률 {premium, tree, rare, lux} (store.get_rates)"""
    month = month or now_month()
    pool = premium_pool(month)
    out = {"sid": "s" + secrets.token_hex(8), "kind": "flower", "ptype": "", "rare": False, "n": _rand.randrange(1, 2 ** 31)}
    if pool and _rand.random() < rates["premium"]:
        out["kind"] = "premium"
        out["ptype"] = _rand.choice(pool)
    else:
        out["kind"] = "tree" if _rand.random() < rates["tree"] else "flower"
        out["rare"] = _rand.random() < rates["rare"]
    return out


def roll_pot(size, rates):
    return {"pid": "p" + secrets.token_hex(8), "size": size, "lux": _rand.random() < rates["lux"], "n": _rand.randrange(1, 2 ** 31)}


def clean_rates(d):
    """관리 화면이 보낸 확률 (0~1) → 바꿀 것만. 범위를 벗어나면 ValueError"""
    out = {}
    for k, (lo, hi) in C.RATE_LIMITS.items():
        if k not in d:
            continue
        v = d[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= float(v) <= hi:
            raise ValueError("%s 확률은 %g%% ~ %g%% 사이여야 합니다" % (C.RATE_NAMES[k], lo * 100, hi * 100))
        out[k] = round(float(v), 4)
    return out


def min_hours(kind):
    return C.GROW_HOURS.get(kind, 48.0) * C.GROW_SLACK


def migrate_counts(bundles, tickets):
    """예전 판에서 가져오는 수: 이상한 값은 처음 지급량, 너무 많으면 상한"""
    try:
        b = int(bundles)
        t = int(tickets)
    except (TypeError, ValueError):
        return C.START_BUNDLES, C.START_TICKETS
    return max(0, min(C.MIGRATE_MAX_BUNDLES, b)), max(0, min(C.MIGRATE_MAX_TICKETS, t))
