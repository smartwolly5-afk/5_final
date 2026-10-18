"""v2 입력(프레임 단위 탐지, contract.md) → 트랙(tracking_id) 단위 집계. 순수 계산 (파일·DB 를 건드리지 않음).

프레임마다 판정하면 흔들리므로 지휘전차·cope cage·분류·임베딩·대표 crop 을 트랙 단위로 모은다.
"""
from collections import Counter

from . import config as C
from .core import CATEGORIES


def is_v2(payload):
    """프레임 단위 입력인지 (v1 은 detections 평면 리스트)."""
    return isinstance(payload, dict) and "frames" in payload


def _num(d, k):
    return isinstance(d, dict) and isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)


def _box_ok(b):
    return all(_num(b, k) for k in "xywh") and b["w"] > 0 and b["h"] > 0


def validate(payload):
    """입력 검증 (외부 입력). 문제가 있으면 ValueError → API 400."""
    src = payload.get("source")
    obs = (src or {}).get("observer") if isinstance(src, dict) else None
    if not (_num(obs, "lat") and _num(obs, "lon")):
        raise ValueError("source.observer.lat/lon 필요")
    if obs.get("heading_deg") is not None and not _num(obs, "heading_deg"):
        raise ValueError("source.observer.heading_deg 는 숫자")
    size = src.get("frame_size")
    if not (_num(size, "w") and _num(size, "h") and size["w"] > 0 and size["h"] > 0):
        raise ValueError("source.frame_size.w/h 필요 (bbox_px → 화면 % 변환)")
    frames = payload["frames"]
    if not isinstance(frames, list) or not frames:
        raise ValueError("frames 리스트 필요")
    for f in frames:
        if not isinstance(f, dict) or not _num(f, "frame_idx") or not isinstance(f.get("detections"), list):
            raise ValueError("각 프레임에 frame_idx, detections 필요")
        if f.get("image_path") is not None and not isinstance(f["image_path"], str):
            raise ValueError(f"frame {f['frame_idx']}: image_path 는 문자열")
        ids = [d.get("tracking_id") if isinstance(d, dict) else None for d in f["detections"]]
        if not all(ids):
            raise ValueError(f"frame {f['frame_idx']}: 각 탐지에 tracking_id 필요")
        if len(ids) != len(set(ids)):
            raise ValueError(f"frame {f['frame_idx']}: 한 프레임 안 tracking_id 중복")
        for d in f["detections"]:
            tid = d["tracking_id"]
            if d.get("category") not in CATEGORIES:
                raise ValueError(f"{tid}: category 는 {'/'.join(CATEGORIES)} 중 하나")
            if not (_box_ok(d.get("bbox_px")) or _box_ok(d.get("bbox"))):
                raise ValueError(f"{tid}: bbox_px(픽셀) 또는 bbox(%) x,y,w,h 필요")
            if d.get("det_confidence") is not None and not (_num(d, "det_confidence") and 0 <= d["det_confidence"] <= 1):
                raise ValueError(f"{tid}: det_confidence 는 0~1 숫자 또는 null")
            for p in d.get("parts") or []:
                if not (isinstance(p, dict) and isinstance(p.get("cls"), str) and _num(p, "conf")):
                    raise ValueError(f"{tid}: parts 는 cls·conf 필요")
            top_k = ((d.get("classification") or {}).get("top_k")) or []
            if not all(isinstance(k, dict) and isinstance(k.get("label"), str) and _num(k, "score") for k in top_k):
                raise ValueError(f"{tid}: classification.top_k 는 label·score 필요")
            emb = (d.get("classification") or {}).get("embedding")
            if emb is not None and not (isinstance(emb, list) and emb and all(_num({"v": v}, "v") for v in emb)):
                raise ValueError(f"{tid}: embedding 은 숫자 리스트")
    return frames


def px_box(d, size):
    """탐지의 픽셀 bbox. % bbox 만 있으면(하위 호환) frame_size 로 픽셀로 바꾼다."""
    if _box_ok(d.get("bbox_px")):
        return d["bbox_px"]
    b = d["bbox"]
    return {"x": b["x"] * size["w"] / 100, "y": b["y"] * size["h"] / 100, "w": b["w"] * size["w"] / 100, "h": b["h"] * size["h"] / 100}


def to_pct(b, size):
    """픽셀 bbox → 화면 % 좌표 (화면 박스·위치 추정용)."""
    return {"x": round(b["x"] / size["w"] * 100, 2), "y": round(b["y"] / size["h"] * 100, 2),
            "w": round(b["w"] / size["w"] * 100, 2), "h": round(b["h"] / size["h"] * 100, 2)}


def ioa(part, box):
    """IoA = 부품 면적 중 전차 bbox 와 겹치는 비율 (0~1)."""
    w = min(part["x"] + part["w"], box["x"] + box["w"]) - max(part["x"], box["x"])
    h = min(part["y"] + part["h"], box["y"] + box["h"]) - max(part["y"], box["y"])
    return max(w, 0) * max(h, 0) / (part["w"] * part["h"]) if part["w"] * part["h"] > 0 else 0.0


def attach_parts(detections, parts, size):
    """모델이 부품을 전차와 따로 출력한 경우: 각 부품을 IoA 가 가장 큰 전차에 붙인다 (PART_IOA_MIN 미만이면 버림).
    detections 의 parts 리스트에 추가한다. 붙인 개수를 돌려준다."""
    tanks = [d for d in detections if d.get("category") in ("전차", "미확인")]
    n = 0
    for p in parts:
        if not (isinstance(p, dict) and _box_ok(p.get("bbox_px"))):
            continue
        best = max(tanks, key=lambda d: ioa(p["bbox_px"], px_box(d, size)), default=None)
        if best is not None and ioa(p["bbox_px"], px_box(best, size)) >= C.PART_IOA_MIN:
            best.setdefault("parts", []).append(p)
            n += 1
    return n


def _flag(obs, cls, ratio, min_frames):
    """부품이 보인 프레임 수 규칙: 비율 ≥ ratio 그리고 장수 ≥ min_frames 이면 True."""
    n = sum(any(p["cls"] == cls and p["conf"] >= C.PART_CONF_MIN for p in d.get("parts") or []) for _, d in obs)
    m = len(obs)
    return {"n": n, "m": m, "on": n / m >= ratio and n >= min_frames}


def _quality(d, size):
    """대표 crop 점수 = 탐지 신뢰도 × bbox 면적 비율."""
    b = px_box(d, size)
    return (d.get("det_confidence") or 0.5) * b["w"] * b["h"] / (size["w"] * size["h"])


def _crop_ok(b, size):
    """화면 가장자리에 잘린 bbox, 너무 작은 bbox 는 crop 후보에서 뺀다."""
    m = C.EDGE_MARGIN_PX
    edge = b["x"] <= m or b["y"] <= m or b["x"] + b["w"] >= size["w"] - m or b["y"] + b["h"] >= size["h"] - m
    return not edge and min(b["w"], b["h"]) >= C.CROP_MIN_PX


def _top_k(obs):
    """프레임별 top_k 점수를 det_confidence 가중 평균. 그 프레임에 없는 라벨은 0점."""
    total, scores, family = 0.0, Counter(), {}
    for _, d in obs:
        w = d.get("det_confidence") or 1.0
        total += w
        for k in ((d.get("classification") or {}).get("top_k")) or []:
            scores[k["label"]] += w * k["score"]
            family.setdefault(k["label"], k.get("family"))              # JSON family 는 참고용 (판정은 사전 DB)
    return [{"label": lb, "score": round(s / total, 3), "family_json": family[lb]}
            for lb, s in sorted(scores.items(), key=lambda x: -x[1])] if total else []


def _embedding(obs, size):
    """품질 상위 EMB_TOP_N 프레임 임베딩의 평균을 다시 L2 정규화. 임베딩이 하나도 없으면 None."""
    embs = [d["classification"]["embedding"] for _, d in sorted(obs, key=lambda o: -_quality(o[1], size))
            if (d.get("classification") or {}).get("embedding")][:C.EMB_TOP_N]
    if not embs or len({len(e) for e in embs}) != 1:
        return None
    mean = [sum(col) / len(embs) for col in zip(*embs)]
    norm = sum(v * v for v in mean) ** 0.5
    return [v / norm for v in mean] if norm else None


def aggregate(payload):
    """v2 입력 → (트랙 목록, 화면에 띄울 프레임). 트랙 순서 = 처음 나온 순서.
    화면 프레임 = 첫 프레임 (박스 좌표는 그 프레임 기준, 그 프레임에 없는 트랙은 마지막 위치)."""
    size = payload["source"]["frame_size"]
    frames = sorted(validate(payload), key=lambda f: f["frame_idx"])
    shown = frames[0]
    by_id = {}
    for f in frames:
        attach_parts(f["detections"], f.get("parts") or [], size)        # 따로 나온 부품 연결
        for d in f["detections"]:
            by_id.setdefault(d["tracking_id"], []).append((f, d))

    tracks = []
    for tid, obs in by_id.items():
        f_disp, d_disp = next(((f, d) for f, d in obs if f is shown), obs[-1])
        b = px_box(d_disp, size)
        confs = [d["det_confidence"] for _, d in obs if d.get("det_confidence") is not None]
        crops = sorted(((f, d) for f, d in obs if f.get("image_path") and _crop_ok(px_box(d, size), size)),
                       key=lambda o: -_quality(o[1], size))[:C.CROP_KEEP]
        tracks.append({
            "tracking_id": tid,
            "category": Counter(d["category"] for _, d in obs).most_common(1)[0][0],
            "cluster_id": next((d["cluster_id"] for _, d in reversed(obs) if d.get("cluster_id")), "C-1"),
            "confidence": round(sum(confs) / len(confs), 2) if confs else None,
            "n_frames": len(obs),
            "bbox_px": b, "bbox": to_pct(b, size), "frame_idx": f_disp["frame_idx"],
            "parts": [{"cls": p["cls"], "conf": p["conf"], "bbox": to_pct(p["bbox_px"], size)}   # 화면 표시용 (그 프레임 부품)
                      for p in d_disp.get("parts") or [] if p["conf"] >= C.PART_CONF_MIN and _box_ok(p.get("bbox_px"))],
            "commander": _flag(obs, "antenna", C.COMMANDER_RATIO, C.COMMANDER_MIN_FRAMES),
            "cope_cage": _flag(obs, "cope_cage", C.COPE_CAGE_RATIO, C.COPE_CAGE_MIN_FRAMES),
            "top_k": _top_k(obs),
            "embedding": _embedding(obs, size),
            "crops": [{"frame_idx": f["frame_idx"], "image_path": f["image_path"], "bbox_px": px_box(d, size),
                       "quality": round(_quality(d, size), 5)} for f, d in crops],
        })
    return tracks, shown
