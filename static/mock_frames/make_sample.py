"""mock 프레임 합성: 전차 사전 사진을 들판 배경에 붙여 영상 한 장면처럼 만들고, 같은 좌표로 탐지 JSON·crop 생성."""
import json, random, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

IMG = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
W, H = 1920, 1080
FONT = ImageFont.load_default(size=22)
rng = np.random.default_rng(7); random.seed(7)

def background():
    sky = np.linspace([150, 170, 190], [205, 210, 210], 430)            # 하늘 그라데이션
    ground = np.linspace([120, 118, 80], [85, 80, 55], H - 430)        # 들판
    arr = np.concatenate([sky, ground])[:, None, :].repeat(W, 1)
    arr[430:] += rng.normal(0, 9, (H - 430, W, 3))                      # 풀 질감
    im = Image.fromarray(arr.clip(0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for x in range(0, W, 6):                                            # 먼 숲 실루엣
        h = 30 + 25 * np.sin(x / 70) + rng.integers(0, 20)
        d.line([(x, 430), (x, 430 - h)], fill=(70, 85, 60), width=6)
    return im.filter(ImageFilter.GaussianBlur(0.8))

def paste(bg, tank_id, x, y, w):
    src = next(IMG.glob(tank_id + ".*"))
    im = Image.open(src).convert("RGB")
    h = int(im.height * w / im.width); im = im.resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)                                    # 가장자리를 흐려 사진 경계를 줄임
    ImageDraw.Draw(mask).ellipse([w * .04, h * .06, w * .96, h * .98], fill=255)
    bg.paste(im, (x, y), mask.filter(ImageFilter.GaussianBlur(w * .05)))
    # bbox = 마스크가 진한 영역 (실제 탐지 박스처럼 약간 안쪽)
    return {"x": x + int(w * .08), "y": y + int(h * .12), "w": int(w * .84), "h": int(h * .82)}

def antenna(bg, b):                                                     # 지휘전차용 추가 안테나 2개
    d = ImageDraw.Draw(bg); cx, top = b["x"] + b["w"] * .45, b["y"] + b["h"] * .25
    for dx, ln in ((0, .9), (b["w"] * .12, .7)):
        d.line([(cx + dx, top), (cx + dx + 6, top - b["h"] * ln)], fill=(25, 25, 25), width=3)
    return {"x": int(cx - 6), "y": int(top - b["h"] * .9), "w": int(b["w"] * .12 + 18), "h": int(b["h"] * .9)}

def cope_cage(bg, b):                                                   # 포탑 위 격자 지붕 (cope cage)
    d = ImageDraw.Draw(bg)
    x0, x1 = b["x"] + b["w"] * .22, b["x"] + b["w"] * .72
    y0, y1 = b["y"] - b["h"] * .12, b["y"] + b["h"] * .28
    for i in range(9):
        x = x0 + (x1 - x0) * i / 8; d.line([(x, y0), (x, y1)], fill=(55, 55, 45), width=3)
    for j in range(4):
        y = y0 + (y1 - y0) * j / 3; d.line([(x0, y), (x1, y)], fill=(55, 55, 45), width=3)
    return {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)}

def topk(label, family, s, alt):
    return [{"label": label, "family": family, "score": s}] + alt

def emb(seed, noise=0.05):
    base = np.random.default_rng(seed).normal(size=16)
    v = base + np.random.default_rng(seed * 31 + int(noise * 100)).normal(scale=noise * 4, size=16)
    return [round(float(x), 4) for x in v / np.linalg.norm(v)]

# 장면 정의: (tracking_id, tank_id 사진, x, y, 폭, 분류, 부품)
SCENES = {
  "mock_video_A": [
    ("Tank-01", "TANK_0230", 120, 470, 520, topk("TANK_0230", "T-72", .88, [{"label": "TANK_0221", "family": "T-72", "score": .06}]), ["antenna"], 101),
    ("Tank-02", "TANK_0216", 700, 520, 470, topk("TANK_0216", "T-72", .41, [{"label": "TANK_0220", "family": "T-72", "score": .37}]), ["cope_cage"], 102),
    ("UNK-001", "TANK_0194", 1250, 480, 560, topk("TANK_0231", "T-90", .22, [{"label": "TANK_0226", "family": "T-80", "score": .19}]), [], 900),
  ],
  "mock_video_B": [
    ("Tank-11", "TANK_0222", 160, 540, 480, topk("TANK_0222", "T-72", .91, [{"label": "TANK_0221", "family": "T-72", "score": .04}]), [], 103),
    ("UNK-007", "TANK_0194", 880, 500, 640, topk("TANK_0226", "T-80", .24, [{"label": "TANK_0231", "family": "T-90", "score": .21}]), ["cope_cage"], 900),
  ],
}

frames_json = []
for video, tanks in SCENES.items():
    bg = background(); dets = []
    for tid, img, x, y, w, tk, parts, eseed in tanks:
        b = paste(bg, img, x, y, w)
        p = []
        for part in parts:
            pb = (antenna if part == "antenna" else cope_cage)(bg, b)
            p.append({"cls": part, "conf": round(random.uniform(.62, .8), 2), "bbox_px": pb})
        dets.append({"tracking_id": tid, "category": "미확인" if tid.startswith("UNK") else "전차",
                     "det_confidence": round(random.uniform(.8, .95), 2), "bbox_px": b, "cluster_id": "C-1",
                     "parts": p, "classification": {"model": "dino-mock", "level": "tank_id", "top_k": tk,
                                                   "embedding": emb(eseed, .03 if video.endswith("B") else .05)},
                     "_mock_image": img})
    d = ImageDraw.Draw(bg); d.text((20, 20), f"MOCK FRAME · {video} · synthetic", font=FONT, fill=(255, 255, 255))
    raw = OUT / f"{video}_000120.jpg"; bg.save(raw, quality=92)

    ann = bg.copy(); a = ImageDraw.Draw(ann)                            # 박스 그린 확인용
    for det in dets:
        b = det["bbox_px"]; col = (230, 60, 60) if det["category"] == "미확인" else (255, 200, 0)
        a.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=col, width=4)
        a.text((b["x"] + 4, b["y"] - 28), f"{det['tracking_id']} {det['classification']['top_k'][0]['label']} {det['classification']['top_k'][0]['score']:.2f}", font=FONT, fill=col)
        for p in det["parts"]:
            pb = p["bbox_px"]; a.rectangle([pb["x"], pb["y"], pb["x"] + pb["w"], pb["y"] + pb["h"]], outline=(80, 200, 255), width=2)
            a.text((pb["x"], pb["y"] - 24), p["cls"], font=FONT, fill=(80, 200, 255))
        # crop (패딩 10%)
        px, py = int(b["w"] * .1), int(b["h"] * .1)
        crop = bg.crop((max(0, b["x"] - px), max(0, b["y"] - py), min(W, b["x"] + b["w"] + px), min(H, b["y"] + b["h"] + py)))
        (OUT / "crops").mkdir(exist_ok=True); crop.save(OUT / "crops" / f"{video}_{det['tracking_id']}_000120.jpg", quality=92)
    ann.save(OUT / f"{video}_000120_annotated.jpg", quality=90)
    frames_json.append((video, raw.name, dets))

for video, name, dets in frames_json:
    payload = {"source": {"video": f"{video}.mp4", "captured_at": "2026-10-18", "source": "MOCK",
                          "observer": {"lat": 48.60, "lon": 38.00, "heading_deg": 90}, "frame_size": {"w": W, "h": H}},
               "frames": [{"frame_idx": 120, "t_sec": 4.0, "image_path": f"mock_frames/{name}", "detections": dets}]}
    (OUT / f"{video}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
