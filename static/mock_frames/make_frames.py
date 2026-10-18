"""1장짜리 샘플(mock_video_A.json / B.json)을 영상당 5프레임으로 늘린다: python static/mock_frames/make_frames.py

make_sample.py (사전 사진으로 1장 합성) 다음에 돌린다: python static/mock_frames/make_sample.py <사진폴더> static/mock_frames
→ python static/mock_frames/make_frames.py. 원본 프레임에서 창을 조금씩 옮기고 확대해(카메라가 천천히
움직이는 것처럼) 새 프레임 이미지를 만들고, bbox·부품 좌표도 같은 변환으로 바꾼다. 그래서 박스가 사진과 맞는다.
- 출력: mock_video_A_5f.json, mock_video_B_5f.json, mock_video_{A,B}_000121~000124.jpg (000120 은 원본 그대로)
- 넣어 둔 상황: Tank-01 안테나 5/5프레임(지휘전차), Tank-11 안테나 1/5프레임(오탐 → 지휘전차 아님)
- 원래 1장짜리 JSON 은 그대로 둔다 (crop 정답 비교 테스트용)
"""
import copy
import json
import random
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
N_FRAMES = 5            # 영상당 프레임 수 (COMMANDER_MIN_FRAMES=3 규칙을 시험할 수 있게 5장)
PAN_PX = (10, 5)        # 프레임마다 창이 오른쪽·아래로 움직이는 양 (px)
ZOOM_STEP = 0.01        # 프레임마다 1%씩 확대
FALSE_ANTENNA = ("mock_video_B", "Tank-11", 2)   # (영상, 표적, 프레임 번호): 안테나 오탐 1프레임


def move(b, dx, dy, s):
    """원본 좌표 bbox → 잘라 확대한 프레임 좌표 (x' = (x - dx) / s)."""
    return {"x": round((b["x"] - dx) / s), "y": round((b["y"] - dy) / s), "w": round(b["w"] / s), "h": round(b["h"] / s)}


def jitter(v, rnd, amount):
    return round(min(max(v + rnd.uniform(-amount, amount), 0.0), 1.0), 2)


def unit(v):
    n = sum(x * x for x in v) ** 0.5
    return [round(x / n, 4) for x in v]


def make(name):
    src = json.loads((HERE / f"{name}.json").read_text(encoding="utf-8"))
    base = src["frames"][0]
    img = Image.open(HERE / Path(base["image_path"]).name)
    W, H = img.size
    rnd = random.Random(name)                       # 같은 이름이면 늘 같은 결과
    out = copy.deepcopy(src)
    out["frames"] = []
    for i in range(N_FRAMES):
        dx, dy, s = PAN_PX[0] * i, PAN_PX[1] * i, 1 - ZOOM_STEP * i
        idx = base["frame_idx"] + i
        file = f"{name}_{idx:06d}.jpg"
        if i:                                       # 0번은 원본 파일 그대로
            img.crop((dx, dy, dx + round(W * s), dy + round(H * s))).resize((W, H)).save(HERE / file, quality=90)
        frame = {"frame_idx": idx, "t_sec": round(base["t_sec"] + i / 30, 3), "image_path": f"mock_frames/{file}",
                 "detections": []}
        for d in base["detections"]:
            d = copy.deepcopy(d)
            d["bbox_px"] = move(d["bbox_px"], dx, dy, s)
            d["det_confidence"] = jitter(d["det_confidence"], rnd, 0.02)
            for p in d.get("parts", []):
                p["bbox_px"] = move(p["bbox_px"], dx, dy, s)
                p["conf"] = jitter(p["conf"], rnd, 0.03)
            if (name, d["tracking_id"], i) == FALSE_ANTENNA:
                b = d["bbox_px"]
                d.setdefault("parts", []).append({"cls": "antenna", "conf": 0.61, "bbox_px":
                                                  {"x": b["x"] + b["w"] // 2, "y": b["y"] + 4, "w": 30, "h": b["h"] // 3}})
            c = d["classification"]
            for k in c["top_k"]:
                k["score"] = jitter(k["score"], rnd, 0.01)
            c["embedding"] = unit([x + rnd.uniform(-0.01, 0.01) for x in c["embedding"]])
            frame["detections"].append(d)
        out["frames"].append(frame)
    (HERE / f"{name}_5f.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}_5f.json: {N_FRAMES}프레임")


if __name__ == "__main__":
    for n in ("mock_video_A", "mock_video_B"):
        make(n)
