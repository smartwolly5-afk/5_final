# track.py — 프레임 → 트랙 집계

파일: `dashboard/threat/track.py` (전체 183줄)

탐지 모델은 **프레임**(영상의 한 장면 사진)마다 결과를 냅니다. 프레임마다 판정하면 한 장에서 안테나가 잘못 보이는 것만으로 결과가 흔들리므로,
같은 `tracking_id`(추적 ID, 영상 안에서 같은 개체에 붙는 번호)끼리 모아 **트랙**(한 개체가 여러 프레임에 걸쳐 나온 기록) 단위로 정리합니다.

- 지휘전차·cope cage 여부 → 프레임 비율 규칙
- 분류 점수(top_k, 모델이 낸 기종 후보 상위 몇 개와 점수) → 프레임 평균
- 임베딩 → 품질 좋은 프레임 평균
- 대표 crop → 품질 점수가 높은 프레임 3장

**현재 입력은 mock**: `static/mock_frames/mock_video_A_5f.json`, `mock_video_B_5f.json` (영상당 5프레임, `make_frames.py` 로 생성).
이 파일은 파일·DB 를 건드리지 않는 순수 계산입니다.

### import (track.py:1~8)

```python
  5  from collections import Counter
```
→ `Counter`: 개수를 세는 딕셔너리. 없는 키를 읽으면 0 으로 시작해서 `scores[라벨] += 점수` 처럼 바로 더할 수 있습니다.

```python
  7  from . import config as C
  8  from .core import CATEGORIES
```
→ 설정값(`C`)과 허용 분류 목록(`CATEGORIES`)을 가져옵니다.

### 함수 `is_v2(payload)` — 새 형식 입력인지 (track.py:11~13)

```python
 13      return isinstance(payload, dict) and "frames" in payload
```
→ 입력에 `frames` 키가 있으면 v2(프레임 단위), 없으면 v1(기존 `detections` 목록). `pipeline.py:157` 이 이 결과로 처리 경로를 고릅니다.

### 함수 `_num`, `_box_ok` — 숫자·박스 검사 도우미 (track.py:16~21)

```python
 16  def _num(d, k):
 17      return isinstance(d, dict) and isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)
```
→ 값이 숫자인지 검사. `isinstance(x, bool)` 을 따로 빼는 이유: 파이썬에서 True/False 도 숫자(1/0)로 취급되기 때문.

```python
 20  def _box_ok(b):
 21      return all(_num(b, k) for k in "xywh") and b["w"] > 0 and b["h"] > 0
```
→ 박스에 x, y, w, h 가 모두 숫자이고 폭·높이가 0 보다 큰지.

### 함수 `validate(payload)` — 입력 검사 (track.py:24~65)

이 부분이 하는 일: 외부(모델)에서 오는 JSON 이라 모양이 틀릴 수 있습니다. 틀리면 `ValueError` 를 내고, API 는 400(잘못된 요청)으로 답합니다.

```python
 26      src = payload.get("source")
 27      obs = (src or {}).get("observer") if isinstance(src, dict) else None
 28      if not (_num(obs, "lat") and _num(obs, "lon")):
 29          raise ValueError("source.observer.lat/lon 필요")
 30      if obs.get("heading_deg") is not None and not _num(obs, "heading_deg"):
 31          raise ValueError("source.observer.heading_deg 는 숫자")
```
→ 관측 위치(위도·경도)가 숫자인지, 카메라 방향이 있으면 숫자인지.

```python
 32      size = src.get("frame_size")
 33      if not (_num(size, "w") and _num(size, "h") and size["w"] > 0 and size["h"] > 0):
 34          raise ValueError("source.frame_size.w/h 필요 (bbox_px → 화면 % 변환)")
```
→ `frame_size`(원본 프레임 가로·세로 픽셀)가 있어야 픽셀 좌표를 화면 % 로 바꿀 수 있습니다.

```python
 35      frames = payload["frames"]
 36      if not isinstance(frames, list) or not frames:
 37          raise ValueError("frames 리스트 필요")
```
→ `frames` 가 비어 있지 않은 리스트인지.

```python
 38      for f in frames:
 39          if not isinstance(f, dict) or not _num(f, "frame_idx") or not isinstance(f.get("detections"), list):
 40              raise ValueError("각 프레임에 frame_idx, detections 필요")
 41          if f.get("image_path") is not None and not isinstance(f["image_path"], str):
 42              raise ValueError(f"frame {f['frame_idx']}: image_path 는 문자열")
 43          ids = [d.get("tracking_id") if isinstance(d, dict) else None for d in f["detections"]]
 44          if not all(ids):
 45              raise ValueError(f"frame {f['frame_idx']}: 각 탐지에 tracking_id 필요")
 46          if len(ids) != len(set(ids)):
 47              raise ValueError(f"frame {f['frame_idx']}: 한 프레임 안 tracking_id 중복")
```
→ 프레임마다 번호·탐지 목록이 있는지, 한 프레임 안에서 `tracking_id` 가 겹치지 않는지 (`set` 은 중복을 없앤 묶음이라 길이가 줄면 중복이 있다는 뜻).

```python
 48          for d in f["detections"]:
 49              tid = d["tracking_id"]
 50              if d.get("category") not in CATEGORIES:
 51                  raise ValueError(f"{tid}: category 는 {'/'.join(CATEGORIES)} 중 하나")
 52              if not (_box_ok(d.get("bbox_px")) or _box_ok(d.get("bbox"))):
 53                  raise ValueError(f"{tid}: bbox_px(픽셀) 또는 bbox(%) x,y,w,h 필요")
 54              if d.get("det_confidence") is not None and not (_num(d, "det_confidence") and 0 <= d["det_confidence"] <= 1):
 55                  raise ValueError(f"{tid}: det_confidence 는 0~1 숫자 또는 null")
```
→ 탐지마다 분류가 허용 목록에 있는지, 박스(픽셀 `bbox_px` 또는 예전 % `bbox`)가 있는지, 신뢰도가 0~1 인지.

```python
 56              for p in d.get("parts") or []:
 57                  if not (isinstance(p, dict) and isinstance(p.get("cls"), str) and _num(p, "conf")):
 58                      raise ValueError(f"{tid}: parts 는 cls·conf 필요")
 59              top_k = ((d.get("classification") or {}).get("top_k")) or []
 60              if not all(isinstance(k, dict) and isinstance(k.get("label"), str) and _num(k, "score") for k in top_k):
 61                  raise ValueError(f"{tid}: classification.top_k 는 label·score 필요")
 62              emb = (d.get("classification") or {}).get("embedding")
 63              if emb is not None and not (isinstance(emb, list) and emb and all(_num({"v": v}, "v") for v in emb)):
 64                  raise ValueError(f"{tid}: embedding 은 숫자 리스트")
```
→ 부품(cls·conf), 분류 후보(label·score), 임베딩(숫자 리스트) 모양 검사.

```python
 65      return frames
```
→ 검사를 통과한 프레임 목록을 돌려줍니다.

### 함수 `px_box`, `to_pct` — 좌표 변환 (track.py:68~79)

```python
 68  def px_box(d, size):
 69      """탐지의 픽셀 bbox. % bbox 만 있으면(하위 호환) frame_size 로 픽셀로 바꾼다."""
 70      if _box_ok(d.get("bbox_px")):
 71          return d["bbox_px"]
 72      b = d["bbox"]
 73      return {"x": b["x"] * size["w"] / 100, "y": b["y"] * size["h"] / 100, "w": b["w"] * size["w"] / 100, "h": b["h"] * size["h"] / 100}
```
→ 픽셀 박스가 있으면 그대로, 예전 % 박스만 있으면 프레임 크기로 픽셀로 바꿉니다 (하위 호환 = 옛 형식도 받아 줌).

```python
 76  def to_pct(b, size):
 77      """픽셀 bbox → 화면 % 좌표 (화면 박스·위치 추정용)."""
 78      return {"x": round(b["x"] / size["w"] * 100, 2), "y": round(b["y"] / size["h"] * 100, 2),
 79              "w": round(b["w"] / size["w"] * 100, 2), "h": round(b["h"] / size["h"] * 100, 2)}
```
→ 픽셀 → %. 예: x=161px, 폭 1920 → 8.39%. 화면은 % 를 쓰므로 창 크기가 바뀌어도 박스가 사진의 같은 자리에 있습니다.

### 함수 `ioa(part, box)` — 부품이 전차 안에 얼마나 들어 있나 (track.py:82~86)

이 부분이 하는 일: IoA(Intersection over Area) = 겹친 넓이 ÷ 부품 넓이. 0~1. 부품 상자 전체가 전차 상자 안이면 1.

```python
 84      w = min(part["x"] + part["w"], box["x"] + box["w"]) - max(part["x"], box["x"])
 85      h = min(part["y"] + part["h"], box["y"] + box["h"]) - max(part["y"], box["y"])
```
→ 두 상자의 겹친 가로·세로 길이. 안 겹치면 음수가 나옵니다.

```python
 86      return max(w, 0) * max(h, 0) / (part["w"] * part["h"]) if part["w"] * part["h"] > 0 else 0.0
```
→ 음수는 0 으로 바꿔 겹친 넓이를 구하고 부품 넓이로 나눕니다. 테스트 예: 부품 (50,50,100,100) vs 전차 (0,0,100,100) → 0.25.

### 함수 `attach_parts(detections, parts, size)` — 따로 나온 부품을 전차에 붙이기 (track.py:89~101)

이 부분이 하는 일: 모델이 부품을 전차와 별도 목록으로 줄 때 쓰는 연결 함수. 각 부품을 IoA 가 가장 큰 전차에 붙이고, 0.5 미만이면 버립니다. (샘플은 부품이 이미 전차 안에 들어 있어서 이 함수가 붙이는 것은 없음)

```python
 92      tanks = [d for d in detections if d.get("category") in ("전차", "미확인")]
 93      n = 0
```
→ 전차·미확인 탐지만 후보로 삼습니다.

```python
 97          best = max(tanks, key=lambda d: ioa(p["bbox_px"], px_box(d, size)), default=None)
```
→ **lambda**(이름 없는 짧은 함수)로 '이 부품과의 IoA' 를 기준으로 가장 큰 전차를 고릅니다. 후보가 없으면 `default=None`.

```python
 98          if best is not None and ioa(p["bbox_px"], px_box(best, size)) >= C.PART_IOA_MIN:
 99              best.setdefault("parts", []).append(p)
100              n += 1
```
→ 기준을 넘으면 그 전차의 `parts` 에 추가. **`setdefault(키, [])`** 는 키가 없으면 빈 리스트를 만들어 넣고 그 리스트를 돌려줍니다.

### 함수 `_flag(obs, cls, ratio, min_frames)` — 부품 비율 규칙 (track.py:104~108)

이 부분이 하는 일: 지휘전차(안테나)·cope cage 판정. 해당 부품이 신뢰도 0.5 이상으로 보인 프레임 수 n, 전체 프레임 수 m → n/m ≥ 0.3 그리고 n ≥ 3 이면 on.

```python
106      n = sum(any(p["cls"] == cls and p["conf"] >= C.PART_CONF_MIN for p in d.get("parts") or []) for _, d in obs)
107      m = len(obs)
108      return {"n": n, "m": m, "on": n / m >= ratio and n >= min_frames}
```
→ 샘플: Tank-01 안테나 5/5 → on(지휘전차). Tank-11 은 안테나가 1/5 프레임에만 보임 → 0.2 < 0.3 이고 1 < 3 → off (오탐을 걸러 냄).

### 함수 `_quality`, `_crop_ok` — 대표 crop 고르기 (track.py:111~121)

```python
111  def _quality(d, size):
112      """대표 crop 점수 = 탐지 신뢰도 × bbox 면적 비율."""
113      b = px_box(d, size)
114      return (d.get("det_confidence") or 0.5) * b["w"] * b["h"] / (size["w"] * size["h"])
```
→ 품질 점수 = 탐지 신뢰도 × (박스 넓이 ÷ 화면 넓이). 크고 선명하게 잡힌 프레임일수록 높습니다. 예: Tank-01 프레임 124 → 0.81 × (454×289)/(1920×1080) ≈ 0.0506.

```python
117  def _crop_ok(b, size):
118      """화면 가장자리에 잘린 bbox, 너무 작은 bbox 는 crop 후보에서 뺀다."""
119      m = C.EDGE_MARGIN_PX
120      edge = b["x"] <= m or b["y"] <= m or b["x"] + b["w"] >= size["w"] - m or b["y"] + b["h"] >= size["h"] - m
121      return not edge and min(b["w"], b["h"]) >= C.CROP_MIN_PX
```
→ 가장자리 8px 안에 닿은 박스(화면에 잘린 표적)나 짧은 변 48px 미만(너무 작은 표적)은 crop 후보에서 뺍니다.

### 함수 `_top_k(obs)` — 분류 점수 트랙 평균 (track.py:124~134)

이 부분이 하는 일: 프레임마다 나온 기종 후보 점수를 탐지 신뢰도로 가중 평균합니다. 어떤 프레임에 없는 라벨은 그 프레임에서 0점으로 칩니다.

```python
126      total, scores, family = 0.0, Counter(), {}
127      for _, d in obs:
128          w = d.get("det_confidence") or 1.0
129          total += w
130          for k in ((d.get("classification") or {}).get("top_k")) or []:
131              scores[k["label"]] += w * k["score"]
132              family.setdefault(k["label"], k.get("family"))              # JSON family 는 참고용 (판정은 사전 DB)
```
→ 프레임마다 신뢰도 w 를 곱해 라벨별로 더합니다. JSON 의 `family` 는 참고용으로만 보관합니다(판정은 사전 DB 의 계열을 씀).

```python
133      return [{"label": lb, "score": round(s / total, 3), "family_json": family[lb]}
134              for lb, s in sorted(scores.items(), key=lambda x: -x[1])] if total else []
```
→ 합 ÷ 신뢰도 합 = 가중 평균. 점수 높은 순으로 정렬. 예: Tank-01 → TANK_0230 0.884, TANK_0221 0.058.

### 함수 `_embedding(obs, size)` — 트랙 임베딩 (track.py:137~145)

이 부분이 하는 일: 품질 상위 5프레임의 임베딩을 평균한 뒤 길이 1로 다시 맞춥니다(**L2 정규화**, 벡터 길이를 1로 만들어 방향만 비교하게 함).

```python
139      embs = [d["classification"]["embedding"] for _, d in sorted(obs, key=lambda o: -_quality(o[1], size))
140              if (d.get("classification") or {}).get("embedding")][:C.EMB_TOP_N]
141      if not embs or len({len(e) for e in embs}) != 1:
142          return None
```
→ 품질 순으로 정렬해 앞 5개. 임베딩이 없거나 길이(차원)가 서로 다르면 None → 레지스트리 매칭을 건너뜁니다.

```python
143      mean = [sum(col) / len(embs) for col in zip(*embs)]
144      norm = sum(v * v for v in mean) ** 0.5
145      return [v / norm for v in mean] if norm else None
```
→ `zip(*embs)` 는 여러 벡터의 같은 칸끼리 묶습니다(열 단위). 칸별 평균 → 길이(제곱합의 제곱근)로 나눔.

### 함수 `aggregate(payload)` — 트랙 집계 (메인) (track.py:148~183)

이 부분이 하는 일: v2 입력을 받아 (트랙 목록, 화면에 띄울 프레임)을 돌려줍니다. `pipeline._v2_detections` (`pipeline.py:133`) 가 부릅니다.

```python
151      size = payload["source"]["frame_size"]
152      frames = sorted(validate(payload), key=lambda f: f["frame_idx"])
153      shown = frames[0]
```
→ 프레임 크기, 검사·정렬된 프레임, 화면 표시용 첫 프레임. **주의**: 151줄이 `validate` 보다 먼저 `source` 를 읽어서, `source` 가 아예 없으면 400 대신 500 오류가 납니다 (12번 문서 '발견한 문제').

```python
154      by_id = {}
155      for f in frames:
156          attach_parts(f["detections"], f.get("parts") or [], size)        # 따로 나온 부품 연결
157          for d in f["detections"]:
158              by_id.setdefault(d["tracking_id"], []).append((f, d))
```
→ `tracking_id` 별로 (프레임, 탐지) 쌍을 모읍니다. 따로 나온 부품이 있으면 먼저 붙입니다.

```python
161      for tid, obs in by_id.items():
162          f_disp, d_disp = next(((f, d) for f, d in obs if f is shown), obs[-1])
163          b = px_box(d_disp, size)
164          confs = [d["det_confidence"] for _, d in obs if d.get("det_confidence") is not None]
165          crops = sorted(((f, d) for f, d in obs if f.get("image_path") and _crop_ok(px_box(d, size), size)),
166                         key=lambda o: -_quality(o[1], size))[:C.CROP_KEEP]
```
→ 트랙마다: 화면 프레임에서의 위치(없으면 마지막 위치), 신뢰도 목록, crop 후보 상위 3장.

```python
167          tracks.append({
168              "tracking_id": tid,
169              "category": Counter(d["category"] for _, d in obs).most_common(1)[0][0],
170              "cluster_id": next((d["cluster_id"] for _, d in reversed(obs) if d.get("cluster_id")), "C-1"),
171              "confidence": round(sum(confs) / len(confs), 2) if confs else None,
172              "n_frames": len(obs),
173              "bbox_px": b, "bbox": to_pct(b, size), "frame_idx": f_disp["frame_idx"],
```
→ 트랙 정보: 가장 많이 나온 분류, 마지막 군집 ID(없으면 C-1), 평균 신뢰도, 프레임 수, 박스(픽셀·%).

```python
174              "parts": [{"cls": p["cls"], "conf": p["conf"], "bbox": to_pct(p["bbox_px"], size)}   # 화면 표시용 (그 프레임 부품)
175                        for p in d_disp.get("parts") or [] if p["conf"] >= C.PART_CONF_MIN and _box_ok(p.get("bbox_px"))],
```
→ 화면에 그릴 부품 (화면 프레임에서 신뢰도 0.5 이상인 것만).

```python
176              "commander": _flag(obs, "antenna", C.COMMANDER_RATIO, C.COMMANDER_MIN_FRAMES),
177              "cope_cage": _flag(obs, "cope_cage", C.COPE_CAGE_RATIO, C.COPE_CAGE_MIN_FRAMES),
178              "top_k": _top_k(obs),
179              "embedding": _embedding(obs, size),
180              "crops": [{"frame_idx": f["frame_idx"], "image_path": f["image_path"], "bbox_px": px_box(d, size),
181                         "quality": round(_quality(d, size), 5)} for f, d in crops],
```
→ 지휘전차·cope cage 판정, 평균 분류 점수, 임베딩, crop 후보(프레임 번호·이미지 경로·박스·품질).

```python
183      return tracks, shown
```
→ 결과를 돌려줍니다.

