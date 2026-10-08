"""site 의 열쇠 층 - 관리 기능은 열쇠(헤더 X-Admin-Key)가 맞을 때만.

계정이 없다. 주인이 한 명이라 열쇠 하나가 곧 비밀번호다. 열쇠 원본은 주인 PC 에만 있고
서버 코드에는 지문만 있다(config.ADMIN_SHA256).
같은 주소에서 열쇠를 여러 번 틀리면 잠시 잠근다 - 열쇠가 길어서 맞힐 수는 없지만, 계속 두드리는 것은 막는다.
"""
import threading
import time

from . import config as C

_fails = {}     # 주소 → [틀린 횟수, 처음 틀린 시각]
_lock = threading.Lock()


def check(key, ip):
    """'ok' | 'bad'(틀림) | 'locked'(너무 많이 틀려서 잠김)."""
    now = time.time()
    with _lock:
        rec = _fails.get(ip)
        if rec and now - rec[1] > C.LOCK_WINDOW:
            rec = None
            _fails.pop(ip, None)
        if rec and rec[0] >= C.LOCK_FAILS:
            return "locked"
    if C.key_matches(key):
        return "ok"
    with _lock:
        rec = _fails.setdefault(ip, [0, now])
        rec[0] += 1
        if len(_fails) > 5000:     # 잊힌 기록이 쌓이지 않게
            for k in [k for k, v in _fails.items() if now - v[1] > C.LOCK_WINDOW]:
                _fails.pop(k, None)
    return "bad"
