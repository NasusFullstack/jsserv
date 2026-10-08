"""site 의 바깥 연결 층 - GitHub 릴리스에서 최신 버전과 파일 목록을 읽어 온다.

작품에 `release: "주인/저장소"` 가 적혀 있으면 사이트가 그 저장소의 최신 릴리스를 보여준다
(버전 이름 + 파일마다 다운로드 버튼). GitHub 에 새 버전을 올리면 사이트도 따라 바뀐다.

- 30분 동안은 받아 둔 것을 쓴다(GitHub 는 로그인 없이 시간당 60번까지만 물을 수 있다)
- GitHub 가 대답을 안 하면 예전에 받아 둔 것을 계속 쓰고, 그것도 없으면 없는 셈 친다
  (사이트가 GitHub 때문에 멈추거나 느려지면 안 된다 - 기다리는 시간도 3초까지)
"""
import json
import re
import threading
import time
import urllib.request

REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
FRESH = 30 * 60        # 이만큼은 다시 안 묻는다
RETRY = 5 * 60         # 실패하면 이만큼 뒤에 다시
TIMEOUT = 3

_cache = {}            # 저장소 → (물어본 시각, 결과 또는 None)
_lock = threading.Lock()


def _fetch(repo):
    """GitHub API 로 최신 릴리스를 읽는다. 실패하면 예외."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % repo,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "jsserv-site"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {
        "tag": str(data.get("tag_name") or "")[:40],
        "name": str(data.get("name") or "")[:100],
        "url": data["html_url"] if str(data.get("html_url", "")).startswith("https://github.com/") else "https://github.com/%s/releases" % repo,
        "published": data.get("published_at") or "",
        "assets": [{"name": a["name"], "size": a.get("size", 0), "url": a["browser_download_url"]}
                   for a in data.get("assets", [])[:12]
                   if a.get("name") and str(a.get("browser_download_url", "")).startswith("https://github.com/")],
    }


fetch = _fetch     # 시험에서 바꿔 끼운다


def latest(repo):
    """최신 릴리스 정보 또는 None. 받아 둔 것이 있으면 그걸 먼저 쓴다."""
    if not repo or not REPO_RE.match(repo):
        return None
    now = time.time()
    with _lock:
        hit = _cache.get(repo)
    if hit:
        age = now - hit[0]
        if (hit[1] is not None and age < FRESH) or (hit[1] is None and age < RETRY):
            return hit[1]
    try:
        value = fetch(repo)
    except Exception:          # noqa: BLE001 - 네트워크·JSON·없는 저장소 전부 '지금은 모름'
        value = hit[1] if hit else None    # 예전 것이 있으면 계속 쓴다
        with _lock:
            _cache[repo] = (now - (FRESH - RETRY) if value else now, value)
        return value
    with _lock:
        _cache[repo] = (now, value)
    return value


def asset_url(repo, name):
    """릴리스 파일 하나의 진짜 주소 (다운로드를 세고 넘겨줄 때)."""
    info = latest(repo)
    for a in (info or {}).get("assets", []):
        if a["name"] == name:
            return a["url"]
    return None
