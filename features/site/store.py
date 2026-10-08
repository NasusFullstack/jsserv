"""site 의 저장 층 - 작품 목록·설정(JSON)과 작품 파일(그림·다운로드·웹 빌드)을 디스크에 둔다.

**무엇이 올바른 값인지는 모른다.** 그건 service 가 검사해서 넘긴다. 여기서는 안전하게 쓰고 읽기만 한다.
- JSON 은 임시 파일에 다 쓴 뒤 한 번에 바꿔 끼운다(쓰다 끊겨도 반쪽짜리 파일이 안 남는다)
- 파일 경로는 언제나 작품 폴더 안인지 확인한다(`..` 로 서버의 다른 파일에 닿지 못하게)
- 새 파일을 다 놓은 뒤에 옛 파일을 지운다(바꾸는 도중에 빈 화면이 안 보이게)
"""
import copy
import datetime
import json
import os
import secrets
import shutil
import threading

from . import config as C

_lock = threading.RLock()
_cache = {}   # 경로 → (수정 시각, 값). 요청마다 디스크를 다시 읽지 않게


def now_iso():
    return datetime.datetime.now(C.KST).isoformat(timespec="seconds")


# ---- JSON ----
def _read_json(path, default):
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return default
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return copy.deepcopy(hit[1])
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, ValueError):
        return default
    _cache[path] = (mtime, value)
    return copy.deepcopy(value)


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%s.part" % (path, secrets.token_hex(4))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    _cache.pop(path, None)


# ---- 작품 목록 ----
def has_works_file():
    return os.path.isfile(C.WORKS_FILE)


def works():
    return _read_json(C.WORKS_FILE, {"works": []}).get("works", [])


def save_works(items):
    with _lock:
        _write_json(C.WORKS_FILE, {"works": items})


def work(slug):
    for w in works():
        if w.get("slug") == slug:
            return w
    return None


def put_work(slug, fields):
    """있으면 fields 를 덮어쓰고, 없으면 새로 만든다. 저장된 작품을 돌려준다."""
    with _lock:
        items = works()
        for w in items:
            if w.get("slug") == slug:
                w.update(fields)
                w["updated"] = now_iso()
                break
        else:
            w = dict(fields, slug=slug, created=now_iso(), updated=now_iso())
            items.append(w)
        save_works(items)
        return copy.deepcopy(w)


def delete_work(slug):
    with _lock:
        items = works()
        left = [w for w in items if w.get("slug") != slug]
        if len(left) == len(items):
            return False
        save_works(left)
    for base in (C.MEDIA, C.DOWNLOADS, C.BUILDS):
        shutil.rmtree(os.path.join(base, slug), ignore_errors=True)
    return True


# ---- 사이트 설정 ----
def settings():
    return _read_json(C.SETTINGS_FILE, None)


def save_settings(value):
    with _lock:
        _write_json(C.SETTINGS_FILE, value)


# ---- 경로 ----
def inside(base, *parts):
    """base 안의 경로면 그 경로, 밖으로 나가면 None."""
    base = os.path.realpath(base)
    path = os.path.realpath(os.path.join(base, *parts))
    return path if path.startswith(base + os.sep) else None


def temp_path(kind):
    """같은 디스크 위의 임시 자리(다 쓴 뒤 rename 한 번으로 옮기려고)."""
    os.makedirs(C.DATA, exist_ok=True)
    return os.path.join(C.DATA, ".%s-%s" % (kind, secrets.token_hex(6)))


# ---- 그림(대표 그림·스크린샷) ----
def save_image(slug, prefix, ext, data):
    """그림 한 장을 저장하고 파일 이름을 돌려준다. 이름에 무작위 꼬리를 붙여 바뀌면 주소도 바뀌게."""
    folder = inside(C.MEDIA, slug)
    os.makedirs(folder, exist_ok=True)
    name = "%s-%s%s" % (prefix, secrets.token_hex(4), ext)
    part = os.path.join(folder, name + ".part")
    with open(part, "wb") as f:
        f.write(data)
    os.replace(part, os.path.join(folder, name))
    return name


def remove_image(slug, name):
    path = inside(C.MEDIA, slug, name) if name else None
    if path and os.path.isfile(path):
        os.remove(path)


def image_path(slug, name):
    path = inside(C.MEDIA, slug, name)
    return path if path and os.path.isfile(path) else None


# ---- 다운로드 파일 (작품당 하나) ----
def commit_download(slug, tmp, name):
    """다 받아 둔 임시 파일을 그 작품의 다운로드 파일로 바꿔 끼운다."""
    folder = inside(C.DOWNLOADS, slug)
    os.makedirs(folder, exist_ok=True)
    olds = [f for f in os.listdir(folder) if f != name]
    os.replace(tmp, os.path.join(folder, name))
    for f in olds:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass


def download_path(slug, name):
    path = inside(C.DOWNLOADS, slug, name) if name else None
    return path if path and os.path.isfile(path) else None


def remove_download(slug):
    shutil.rmtree(os.path.join(C.DOWNLOADS, slug), ignore_errors=True)


# ---- 웹 빌드 (작품당 폴더 하나) ----
def commit_build(slug, tmp_dir):
    """다 풀어 둔 임시 폴더를 그 작품의 웹 빌드로 한 번에 바꿔 끼운다."""
    os.makedirs(C.BUILDS, exist_ok=True)
    root = inside(C.BUILDS, slug)
    old = None
    if os.path.isdir(root):
        old = temp_path("build-old")
        os.rename(root, old)
    os.rename(tmp_dir, root)
    if old:
        shutil.rmtree(old, ignore_errors=True)


def build_file(slug, rel):
    path = inside(C.BUILDS, slug, *rel.split("/"))
    return path if path and os.path.isfile(path) else None


def remove_build(slug):
    shutil.rmtree(os.path.join(C.BUILDS, slug), ignore_errors=True)


# ---- 관리 화면용: 자리별 크기 ----
def folder_bytes(path):
    total = 0
    for dp, _, fns in os.walk(path):
        for f in fns:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total
