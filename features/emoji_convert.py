"""이모티콘으로 쓸 수 있게 그림을 줄인다 - 순수 모듈(웹도 디스크도 모름).

## 왜 줄이는가
채팅에 뜨는 이모티콘은 한 변이 192px이다. 그런데 사람들이 이모티콘으로 삼는 그림은
대개 카메라 사진이나 스크린샷이라 4000px에 몇 MB씩 한다. 그걸 그대로 두면
**보이지도 않을 화소를 영원히 들고 있는 셈**이다 - 이모티콘은 기한으로 안 지우므로
그 낭비가 계속 쌓인다.

원본은 어차피 따로 하루 보관되므로, 여기서는 이모티콘으로 쓸 만큼만 남긴다.

## 움짤은 움짤로 남긴다
움직이는 이모티콘을 첫 장으로 납작하게 만들면 쓸 이유가 없어진다. 모든 장을 같이
줄여서 움짤로 저장한다. 다만 장수가 너무 많거나 그래도 큰 경우에는 **첫 장만 남긴다** -
이모티콘 하나가 몇 MB인 것보다는 안 움직이는 편이 낫다.

## Pillow가 없으면
서버에 이미지 라이브러리가 깔려 있지 않을 수 있다. 맨 위에서 그냥 import하면 **서버
전체가 안 뜬다** - 파일 올리기도 전투 중계도 같이 죽는다. 그래서 없으면 없는 대로 두고,
이모티콘 등록만 "지금은 안 된다"고 답하게 한다.
"""
import io

try:
    from PIL import Image, ImageSequence
except ImportError:          # 서버에 Pillow가 없어도 나머지 기능은 살아 있어야 한다
    Image = None
    ImageSequence = None

# 채팅에 192px로 뜬다. 화면 배율이 높은 컴퓨터에서도 또렷하게 보이도록 그보다 크게 남긴다
MAX_PX = 320

# 움짤로 남길 수 있는 최대 장수. 넘으면 첫 장만 남긴다
MAX_FRAMES = 150

# 이 크기를 넘으면 움짤을 포기하고 첫 장만 남긴다
ANIMATION_BYTE_LIMIT = 900 * 1024


def available() -> bool:
    """이 서버에서 이모티콘 변환을 할 수 있는가."""
    return Image is not None


def _fit(size) -> tuple[int, int]:
    """비율을 지키며 MAX_PX 안에 들어오는 크기. 원본이 작으면 **키우지 않는다**."""
    width, height = size
    if width <= 0 or height <= 0:
        return (1, 1)
    scale = min(MAX_PX / width, MAX_PX / height, 1.0)
    return (max(1, round(width * scale)), max(1, round(height * scale)))


def _still(image) -> bytes:
    """한 장짜리 PNG로."""
    frame = image.convert("RGBA")
    frame = frame.resize(_fit(frame.size), Image.LANCZOS)
    out = io.BytesIO()
    frame.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _animated(image) -> bytes | None:
    """움직이는 그대로 GIF로. 못 하겠으면 None(부르는 쪽이 첫 장만 남긴다)."""
    frames = []
    for frame in ImageSequence.Iterator(image):
        frames.append(frame.convert("RGBA").resize(_fit(frame.size), Image.LANCZOS))
        if len(frames) > MAX_FRAMES:
            return None
    if len(frames) < 2:
        return None
    out = io.BytesIO()
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:],
                   loop=image.info.get("loop", 0),
                   duration=image.info.get("duration", 100),
                   disposal=2, optimize=True)
    data = out.getvalue()
    return data if len(data) <= ANIMATION_BYTE_LIMIT else None


def shrink(data: bytes) -> tuple[bytes, str] | None:
    """이모티콘 크기로 줄인다. (바뀐 내용, 확장자). 그림이 아니면 None.

    돌려주는 확장자가 원본과 다를 수 있다(JPG를 넣어도 PNG가 나온다). 저장하는 쪽이
    이름을 그 확장자로 맞춰야 브라우저가 제대로 연다.
    """
    if not available() or not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
    except Exception:
        return None

    try:
        if getattr(image, "is_animated", False):
            moving = _animated(image)
            if moving is not None:
                return moving, ".gif"
            image.seek(0)      # 움짤을 포기했으면 첫 장으로 돌아가서 다시 읽는다
        return _still(image), ".png"
    except Exception:
        # 어떤 그림은 Pillow가 열기는 해도 읽다가 깨진다. 그럴 땐 등록을 안 하는 게 맞다
        return None
