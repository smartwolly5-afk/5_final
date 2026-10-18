"""원본 프레임에서 표적 crop 을 잘라 static/ 아래에 저장한다 (Pillow).

- 입력 image_path 는 static 기준 경로다 (예: mock_frames/mock_video_A_000120.jpg). 외부 입력이라 static 밖은 읽지 않는다.
- 원본 프레임이 없으면(모델이 경로만 주고 파일은 없는 경우) 저장을 건너뛰고 경고만 남긴다.
"""
import logging
import re
from pathlib import Path

from PIL import Image

from .threat import config as C

STATIC = Path(__file__).resolve().parents[1] / "static"   # 원본 프레임을 읽는 곳 (image_path 기준)
OUT = STATIC                                                  # crop 을 쓰는 곳 (테스트는 임시 폴더로 바꿈)
log = logging.getLogger(__name__)


def safe(name):
    """파일 이름에 쓸 수 없는 글자는 _ 로 (영상 이름·tracking_id 는 외부 입력)."""
    return re.sub(r"[^\w.-]", "_", str(name))


def frame_file(image_path):
    """static 안의 실제 파일 경로 (없거나 static 밖이면 None)."""
    if not image_path:
        return None
    p = (STATIC / image_path).resolve()
    return p if p.is_relative_to(STATIC) and p.is_file() else None


def crop_box(b, size, pad=C.CROP_PAD):
    """bbox 에 각 변 pad 비율만큼 여백을 더하고 프레임 안으로 자른 (left, top, right, bottom)."""
    px, py = int(b["w"] * pad), int(b["h"] * pad)
    return (max(int(b["x"]) - px, 0), max(int(b["y"]) - py, 0),
            min(int(b["x"] + b["w"]) + px, size[0]), min(int(b["y"] + b["h"]) + py, size[1]))


def save_crop(image_path, bbox_px, dest):
    """프레임 crop 을 static/<dest> 에 저장하고 dest 를 돌려준다. 원본이 없으면 None."""
    src = frame_file(image_path)
    if src is None:
        log.warning("원본 프레임이 없어 crop 저장 건너뜀: %s", image_path)
        return None
    out = OUT / dest
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.convert("RGB").crop(crop_box(bbox_px, im.size)).save(out, quality=90)
    return dest


def track_crop(video, target):
    """상세 패널용 대표 crop (트랙의 품질 1위 프레임). 이미 있으면 다시 자르지 않는다. static 기준 경로 또는 None."""
    crops = (target.get("_track") or {}).get("crops") or []
    if not crops:
        return None
    c = crops[0]
    dest = f"track_crops/{safe(video)}/{safe(target['tracking_id'])}_{c['frame_idx']}.jpg"
    return dest if (OUT / dest).is_file() else save_crop(c["image_path"], c["bbox_px"], dest)
