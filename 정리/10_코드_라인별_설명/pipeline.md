# pipeline.py — 탐지 결과 → 화면 응답 JSON 조립 (핵심 흐름)

파일: `dashboard/threat/pipeline.py` (전체 243줄)

**이 프로젝트의 중심 파일**입니다. 탐지 결과(입력)를 받아 군집별 대응단계, 표적 랭킹, 근거 태그, 위치 추정까지 붙여
화면(`dashboard.js`)이 그대로 쓰는 **응답 JSON(AnalysisResult)** 을 만듭니다.

```
analyze(payload)
 ├─ v2 입력이면 _v2_detections → track.aggregate → judge.judge
 ├─ v1 입력이면 _validate
 ├─ 군집마다: core.infer_tactic → (표적마다) judge.threat_of 또는 core.tank_threat → _target_tags
 │            → core.cluster_response_level
 └─ 랭킹 정렬 → 카운터 → 경보(alert) → 응답
```
파일·DB 쓰기는 하지 않습니다(사전 DB 읽기는 `judge` → `dictdb` 가 함). crop 저장·레지스트리 저장은 `dashboard/__init__.py` 가 합니다.

### 머리말 — 입력·응답 형식 (pipeline.py:1~30)

```python
  3  입력 (POST /api/analyze 본문, 비우면 static/mock_frames 샘플 A → B):
  4    v2 (프레임 단위, 모델 출력 계약은 contract.md): {"source": {..., "frame_size"}, "frames": [{"frame_idx", "image_path", "detections"}]}
  5       → track.aggregate (트랙 집계) → judge.judge (Known/Known_Variant/Unknown) → judge.threat_of (사전 DB 위협도·cope cage)
  6    v1 (하위 호환, mock_detections.json): {"source": {"video", "captured_at", "source", "observer": {"lat", "lon", "heading_deg"}},
  7     "detections": [탐지 결과 (core.py 머리말 형식), ...]}
```
→ 입력 형식 두 가지: v2(프레임 단위, 모델 연동용, 자세한 계약은 `dashboard/threat/contract.md`)와 v1(기존 mock 형식).

```python
  9  응답 AnalysisResult (/api/analyze, /api/threats, /api/clusters/<id>/tactic 공통):
 10    {"source":   입력 source 그대로,
 11     "counts":   {"total", "tank", "apc", "artillery", "infantry", "new"},       # 상단 카운터
 12     "alert":    {"level", "label", "prev_level", "banner", "message"},          # 상단 배너·상황 패널 (가장 심각한 군집 기준)
 13     "clusters": [Cluster, ...],                                                # 군집별 대응단계
 14     "targets":  [Target, ...]}                                                 # rank 순서 (전차·미확인), 그 뒤 순위 없는 표적
 15    Cluster = {"cluster_id", "level", "label", "score", "t_cluster", "echelon": {"n", "weight", "name"},
 16               "tactic", "tactic_name", "tactic_source": "시스템 추정"|"지휘관 지정", "reasons": [...], "track_ids": [...]}
```
→ 응답 구조: source(영상 정보), counts(카운터), alert(경보), clusters(군집별 대응단계), targets(표적 목록, 랭킹 순).

```python
 17    Target  = {"tracking_id", "category", "model", "confidence", "bbox", "is_commander", "is_unknown", "is_new",
 18               "cluster_id", "rank"|null, "threat"|null, "grade"|null,                    # 전차 1대 위협도와 단계
 19               "scores": {"firepower","mobility","protection","total"}|null, "weights": {...}|null,
 20               "tactic", "tactic_name", "level", "label",                                # level/label = 소속 군집 대응단계
 21               "tags": [...],                                                           # 근거 태그 (이 전차에 대한 것만)
 22               "position": {"bearing_deg","distance_m","lat","lon","estimated": true},
 23               # v2 에서 채움 (v1 은 status 만 Known/Unknown, 나머지 null·빈값)
 24               "status": "Known"|"Known_Variant"|"Unknown", "tank_id", "family", "type_group", "threat_source",   # 위협도를 어디서 가져왔는지
 25               "threat_before_bonus", "has_cope_cage", "cope_tag", "commander_evidence": {"n", "m", "on", "override"}|null,
 26               "parts": [{"cls", "conf", "bbox"}], "n_frames",
 27               "unknown_group_id", "crop_url"}                                          # 이 둘은 dashboard/__init__.py 가 채움
 28    source 에는 v2 일 때 "frame_image" (화면에 띄울 프레임, static 기준 경로), "frame_idx" 가 붙는다.
```
→ 표적(Target) 한 개에 들어가는 필드 목록. v2 에서만 채워지는 필드(status, tank_id, family, threat_source, cope 관련, parts, unknown_group_id, crop_url)도 적혀 있습니다.

### import 와 상수 (pipeline.py:31~46)

```python
 31  import json          # mock 파일 읽기
 32  import math          # 위치 추정 삼각함수
 33  from pathlib import Path
 35  from . import config as C
 36  from . import judge as J
 37  from . import track as TR
 38  from .core import (CATEGORIES, TACTIC_NAMES, Tactic, cluster_response_level, infer_tactic, is_unknown,
 39                     quant_score, spec_of, tactic_weights, tank_threat, threat_grade)
```
→ `json`(JSON 읽기), `math`(삼각함수), `Path`(파일 경로). `J`=judge, `TR`=track 으로 줄여 부릅니다.

```python
 41  MOCK_FILE = Path(__file__).with_name("mock_detections.json")  # v1 탐지 결과 (하위 호환 테스트용)
 42  MOCK_DIR = Path(__file__).resolve().parents[2] / "static" / "mock_frames"
 43  MOCK_V2 = [MOCK_DIR / "mock_video_A_5f.json", MOCK_DIR / "mock_video_B_5f.json"]  # 기본 mock: 영상 A → B (5프레임)
```
→ mock 입력 파일 위치. 본문 없이 분석하면 영상 A → B 의 5프레임 샘플(`MOCK_V2`)을 씁니다. **현재 모델 대신 mock JSON 이 들어갑니다.**

```python
 44  RANKED = ("전차", "미확인")                                    # 랭킹 표에 올리는 분류
 45  COUNT_KEYS = {"전차": "tank", "기갑차": "apc", "포병": "artillery", "인원": "infantry"}  # 카운터 키
 46  AXIS_LABELS = {"firepower": "화력", "mobility": "기동력", "protection": "방호력"}       # 근거 태그용 이름
```
→ 랭킹에 올리는 분류(전차·미확인), 카운터 키, 근거 태그용 한국어 이름.

### 함수 `load_mock(path)` — v1 mock 읽기 (pipeline.py:49~51)

```python
 51      return json.loads(Path(path).read_text(encoding="utf-8"))
```
→ JSON 파일을 읽어 파이썬 딕셔너리로. 지금은 테스트(`dashboard/tests/test_threat.py`)에서 v1 경로를 확인할 때 씁니다.

### 함수 `estimate_position(det, observer)` — 박스로 위치 추정 (현재 mock) (pipeline.py:54~64)

이 부분이 하는 일: 카메라(관측 지점) 위치와 방향, 박스의 화면 위치·크기로 표적의 위도·경도를 **어림**합니다. 실제 거리 측정이 아니므로 화면에 '추정 위치'로 표시합니다.

```python
 57      b = det["bbox"]                                                                   # 화면 % 좌표
```
→ 탐지 박스(% 좌표)를 꺼냅니다.

```python
 58      bearing = (observer.get("heading_deg", 0)                                         # 카메라가 보는 방위
 59                 + (b["x"] + b["w"] / 2 - 50) / 100 * C.CAMERA_FOV_DEG) % 360           # + 화면 중심에서 벗어난 만큼
```
→ 방위 = 카메라 방향 + (박스 중심이 화면 가운데(50%)에서 벗어난 비율 × 시야각 60°). 박스가 오른쪽 끝이면 +30°. `% 360` 은 360 으로 나눈 나머지(0~359°로 맞춤).

```python
 60      dist = C.DISTANCE_K * 10 / max(b["h"], 1)                                         # 박스가 클수록 가까움 (m)
```
→ 거리 = 2000 × 10 / 박스 높이(%). 박스가 클수록 가깝다고 봅니다. 예: UNK-001 높이 20.65% → 약 969m.

```python
 61      lat = observer["lat"] + dist * math.cos(math.radians(bearing)) / 111_320          # 북쪽 이동 (위도 1도 ≈ 111.32km)
 62      lon = observer["lon"] + dist * math.sin(math.radians(bearing)) / (111_320 * math.cos(math.radians(observer["lat"])))  # 동쪽 이동
```
→ 방위·거리로 위도·경도 이동량 계산. 위도 1도 ≈ 111.32km. 경도는 위도가 높을수록 1도의 거리가 줄어 cos(위도)로 나눕니다.

```python
 63      return {"bearing_deg": round(bearing, 1), "distance_m": round(dist), "lat": round(lat, 6), "lon": round(lon, 6),
 64              "estimated": True}                                                        # 화면에 '추정 위치'로 표시
```
→ 반올림해서 돌려주고 `estimated: True` 로 추정값임을 표시.

### 함수 `_num`, `_validate(payload)` — v1 입력 검사 (pipeline.py:67~95)

```python
 67  def _num(d, k):
 68      """d[k] 가 숫자인지 (True/False 는 숫자로 치지 않음)."""
 69      return isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)
```
→ 숫자인지 검사(True/False 제외).

```python
 74      dets = payload.get("detections") if isinstance(payload, dict) else None
 75      if not isinstance(dets, list):
 76          raise ValueError("detections 리스트 필요")
```
→ `detections` 가 리스트가 아니면 400 오류.

```python
 77      seen = set()                                                                       # tracking_id 중복 검사
 78      for d in dets:
 79          if not isinstance(d, dict) or not d.get("tracking_id"):
 80              raise ValueError("각 탐지에 tracking_id 필요")
 81          if d["tracking_id"] in seen:
 82              raise ValueError(f"tracking_id 중복: {d['tracking_id']}")
 83          seen.add(d["tracking_id"])
 84          if d.get("category") not in CATEGORIES:
 85              raise ValueError(f"{d['tracking_id']}: category 는 {'/'.join(CATEGORIES)} 중 하나")
 86          if not all(_num(d.get("bbox") or {}, k) for k in "xywh"):
 87              raise ValueError(f"{d['tracking_id']}: bbox x,y,w,h 숫자 필요")
 88          if d.get("confidence") is not None and not (_num(d, "confidence") and 0 <= d["confidence"] <= 1):
 89              raise ValueError(f"{d['tracking_id']}: confidence 는 0~1 숫자 또는 null")  # 화면이 toFixed() 로 표시
```
→ 탐지마다 tracking_id 가 있고 겹치지 않는지, 분류가 허용 목록인지, 박스가 숫자인지, 신뢰도가 0~1 인지.

```python
 90      obs = (payload.get("source") or {}).get("observer") or {}
 91      if not all(_num(obs, k) for k in ("lat", "lon")):
 92          raise ValueError("source.observer.lat/lon 필요")
 93      if obs.get("heading_deg") is not None and not _num(obs, "heading_deg"):
 94          raise ValueError("source.observer.heading_deg 는 숫자")                       # 위치 추정 계산에 씀
 95      return dets
```
→ 관측 위치(위도·경도)와 방향 검사 후 탐지 목록을 돌려줍니다.

### 함수 `_commander_tag(row)` — 지휘전차 근거 문장 (pipeline.py:98~104)

```python
 99      ev = row["commander_evidence"]
100      if ev and ev["override"] is not None:                                              # 지휘관이 화면에서 바꿈
101          return "지휘전차 (지휘관 지정)" if row["is_commander"] else "지휘전차 해제 (지휘관)"
```
→ 지휘관이 화면에서 지정·해제했으면 그 사실을 씁니다.

```python
102      if ev and ev["on"]:
103          return f"안테나 탐지 {ev['n']}/{ev['m']}프레임 → 지휘전차 추정"
```
→ 탐지 규칙으로 지휘전차가 됐으면 '안테나 탐지 5/5프레임 → 지휘전차 추정' 처럼 근거 숫자를 씁니다.

```python
104      return "지휘전차" if row["is_commander"] else None
```
→ v1 입력(근거 정보 없음)에서 지휘전차면 그냥 '지휘전차'.

### 함수 `_target_tags(row, scores)` — 근거 태그 만들기 (pipeline.py:107~128)

이 부분이 하는 일: 랭킹 표·상세 패널에 회색 칩으로 보이는 **판단 이유**. 이 표적의 위협도를 설명하는 사실만 넣습니다.

```python
109      tags = []
110      cmd = _commander_tag(row)
111      if cmd:
112          tags.append(cmd)                                                               # 지휘통제 가중치가 적용된 이유
```
→ 지휘전차 근거 (위 함수).

```python
113      if row["threat_source"] and row["status"] != "Known":
114          tags.append(row["threat_source"])                                              # 'T-72 계열 상위25%' 등
115      if row["cope_tag"]:
116          tags.append(row["cope_tag"])                                                   # 'cope cage → 방호 ×1.10' 
```
→ Known 이 아니면 위협도 출처('T-72 계열 상위25%' 등), cope cage 보정이 있으면 '× 1.10' 태그.

```python
117      if row["is_unknown"]:
118          tags.append("제원 없음 · 분석관 검토" if row["category"] == "전차" and row["threat_source"] is None
119                      else "미확인 · 분석관 검토")                                    # v2 미확인은 대체값이 있어도 검토 대상
```
→ 미확인이면 '미확인 · 분석관 검토'. v1 에서 제원이 없는 전차는 '제원 없음 · 분석관 검토'.

```python
120      if row["is_new"]:
121          tags.append("신규")                                                            # 직전 분석에 없던 표적
```
→ 직전 분석에 없던 표적이면 '신규'.

```python
122      if scores:                                                                        # 점수가 있는 전차만
123          axes = {k: scores[k] for k in AXIS_LABELS}                                    # 화력·기동·방호
124          hi, lo = max(axes, key=axes.get), min(axes, key=axes.get)                     # 가장 강한/약한 지수
125          tags.append(f"강점 {AXIS_LABELS[hi]} {axes[hi]:g}")
126          tags.append(f"약점 {AXIS_LABELS[lo]} {axes[lo]:g}")
127          tags.append(f"{row['tactic_name']} 가중치")                                     # 어떤 전술 가중치로 계산했는지
```
→ 점수가 있으면 가장 강한 축·약한 축, 적용 전술 이름. 예: Tank-01 → '강점 화력 108.8', '약점 기동력 69.4', '지휘통제 가중치'. `:g` 는 불필요한 0 을 빼는 숫자 형식.

### 함수 `_v2_detections(payload, commander_overrides)` — v2 입력을 표적 목록으로 (pipeline.py:131~148)

이 부분이 하는 일: 트랙 집계(`track.aggregate`)와 판정(`judge.judge`)을 하고, 아래 `analyze` 가 v1 과 같은 방식으로 처리할 수 있는 탐지 목록으로 바꿉니다.

```python
133      tracks, shown = TR.aggregate(payload)
134      dets = []
```
→ 트랙 목록과 화면 프레임을 받습니다.

```python
135      for t in tracks:
136          j = J.judge(t) if t["category"] in RANKED else None
137          ov = commander_overrides.get(t["tracking_id"])                              # 지휘관 지정·해제 (없으면 None)
```
→ 전차·미확인만 판정합니다. 지휘관이 지휘전차를 지정·해제했는지(`ov`)도 확인합니다.

```python
138          model = None
139          if j and j["status"] == "Known":
140              model = j["name"]
141          elif j and j["status"] == "Known_Variant":
142              model = f"{j['family']} 계열"
```
→ 화면 표시 이름: Known 이면 기종명(T-90), Known_Variant 면 'T-72 계열', Unknown 이면 None(화면에서 그룹 ID 로 표시).

```python
143          dets.append({"tracking_id": t["tracking_id"], "category": t["category"], "model": model,
144                       "confidence": t["confidence"], "bbox": t["bbox"], "cluster_id": t["cluster_id"],
145                       "is_commander": t["commander"]["on"] if ov is None else ov,
146                       "status": j["status"] if j else None,
147                       "_v2": {"track": t, "judge": j, "commander": dict(t["commander"], override=ov)}})
```
→ v1 형식 필드 + `status` + 내부용 `_v2`(트랙·판정·지휘전차 근거). 지휘전차는 지휘관 값이 있으면 그것, 없으면 탐지 규칙 결과.

### 함수 `analyze(payload, prev, tactic_overrides, commander_overrides)` — 메인 (pipeline.py:151~243)

이 부분이 하는 일: 입력 → 응답 JSON. `dashboard/__init__.py` 의 분석·전술 변경·지휘전차 변경 API 가 모두 이 함수를 부릅니다.

```python
157      if TR.is_v2(payload):
158          dets, shown = _v2_detections(payload, commander_overrides or {})
159          source = dict(payload["source"], frame_image=shown.get("image_path"), frame_idx=shown["frame_idx"])
160      else:
161          dets, source = _validate(payload), payload["source"]                           # 입력 검증
```
→ v2 면 트랙 집계 경로, v1 이면 입력 검사. v2 의 source 에는 화면에 띄울 프레임 이미지 경로를 붙입니다.

```python
162      prev_ids = {t["tracking_id"] for t in prev["targets"]} if prev else None           # 직전 표적 ID 목록
163      overrides = tactic_overrides or {}
```
→ 직전 결과의 표적 ID 집합('신규' 판단용)과 지휘관 지정 전술.

```python
165      groups = {}                                                                        # cluster_id → 탐지 목록
166      for d in dets:
167          groups.setdefault(d.get("cluster_id") or "C-1", []).append(d)                   # 군집 ID 없으면 C-1
```
→ 군집 ID 별로 탐지를 묶습니다. 군집 ID 가 없으면 'C-1'. (`setdefault` 설명은 track.md 참고)

```python
169      for cid, t in overrides.items():                                                   # 지정 전술 검증
170          if cid not in groups:
171              raise LookupError(f"군집 없음: {cid}")
172          if t not in C.TACTIC_WEIGHTS:
173              raise ValueError(f"가중치 없는 전술 번호: {t} (1~10만 가능)")
```
→ 지휘관이 지정한 전술이 실제 있는 군집인지(없으면 404), 가중치가 있는 1~10번인지(아니면 400) 검사.

```python
176      for cid, members in groups.items():                                                # 군집마다
177          override = overrides.get(cid)                                                  # 지휘관 지정 전술 (없으면 None)
178          tactic = Tactic(override) if override else infer_tactic(members)               # 지정이 없으면 시스템 추정
```
→ 군집마다 전술 결정: 지휘관 지정이 있으면 그것, 없으면 자동 추정(`core.infer_tactic`).

```python
180          for d in members:                                                              # 군집 안 표적마다
181              spec = spec_of(d)                                                          # 전차 제원 (없으면 None)
182              row = {"tracking_id": d["tracking_id"], "category": d["category"], "model": d.get("model"),
183                     "confidence": d.get("confidence"), "bbox": d["bbox"], "is_commander": bool(d.get("is_commander")),
184                     "is_unknown": is_unknown(d), "is_new": prev_ids is not None and d["tracking_id"] not in prev_ids,
185                     "cluster_id": cid, "rank": None, "threat": None, "grade": None, "scores": None, "weights": None,
186                     "tactic": int(tactic), "tactic_name": TACTIC_NAMES[tactic],
187                     "position": estimate_position(d, source["observer"]),
188                     "status": d.get("status") or ("Unknown" if is_unknown(d) else "Known"),
189                     "tank_id": None, "family": None, "type_group": None, "threat_source": None, "threat_before_bonus": None, "cope_tag": None,
190                     "has_cope_cage": False, "commander_evidence": None, "parts": [], "n_frames": 1,
191                     "unknown_group_id": None, "crop_url": None}
```
→ 표적마다 응답 행(row) 기본값을 만듭니다. 위치 추정, 신규 여부, 미확인 여부, v2 필드 기본값(None·빈값).

```python
192              v2 = d.get("_v2")
193              if v2:                                                                     # v2: 트랙 집계·판정 결과
194                  t, j = v2["track"], v2["judge"]
195                  row.update(has_cope_cage=t["cope_cage"]["on"], commander_evidence=v2["commander"],
196                             parts=t["parts"], n_frames=t["n_frames"], _track=t)
197                  if j:
198                      row.update(tank_id=j["tank_id"], family=j["family"], type_group=j["type_group"])
```
→ v2 면 트랙 결과(cope cage, 지휘전차 근거, 부품, 프레임 수)와 판정 결과(tank_id, 계열, 유형)를 채웁니다. `_track` 은 레지스트리 저장용 내부 필드.

```python
199              if v2 and v2["judge"]:                                                     # 사전 DB 위협도 (판정 상태별)
200                  cmd = row["is_commander"] and not override
201                  th = J.threat_of(v2["judge"], tactic, cmd, row["has_cope_cage"])
202                  row.update(threat=th["threat"], threat_before_bonus=th["threat_before_bonus"], scores=th["scores"],
203                             weights=th["weights"], threat_source=th["source"], cope_tag=th["cope_tag"],
204                             tactic=int(th["tactic"]), tactic_name=TACTIC_NAMES[th["tactic"]])
205                  row["grade"] = threat_grade(row["threat"])
```
→ v2 위협도: `judge.threat_of`. 지휘관이 군집 전술을 지정했으면 지휘전차도 그 전술을 따릅니다(`not override`).

```python
206              elif spec:                                                                   # 제원이 있는 전차만 점수 계산
207                  cmd = row["is_commander"] and not override                             # 지휘관이 전술을 지정하면 그 전술이 우선
208                  used, (wf, wm, wp) = tactic_weights(tactic, cmd)                       # 실제 적용된 전술·가중치
209                  row.update(threat=tank_threat(spec, tactic, cmd), scores=quant_score(spec),
210                             weights={"firepower": wf, "mobility": wm, "protection": wp},
211                             tactic=int(used), tactic_name=TACTIC_NAMES[used])
212                  row["grade"] = threat_grade(row["threat"])                             # 매우 높음/높음/보통/낮음
```
→ v1 위협도: `tank_specs.json` 제원으로 `core.tank_threat`.

```python
213              row["tags"] = _target_tags(row, row["scores"])                             # 근거 태그
214              rows.append(row)
```
→ 근거 태그를 붙여 군집 목록에 넣습니다.

```python
216          res = cluster_response_level({"detections": members, "threats": [r["threat"] for r in rows]})  # 군집 대응단계
217          for r in rows:
218              r.update(level=res["level"], label=res["label"])                           # 표적에 소속 군집 단계 기록
219              r["tags"].append(f"{cid} 소속")                                              # 어느 군집인지
```
→ 군집 대응단계 계산(`core.cluster_response_level`). 군집 단계를 표적마다 기록하고 'C-1 소속' 태그를 붙입니다.

```python
220          clusters.append(dict(res, cluster_id=cid, tactic=int(tactic), tactic_name=TACTIC_NAMES[tactic],
221                               tactic_source="지휘관 지정" if override else "시스템 추정",
222                               track_ids=[r["tracking_id"] for r in rows]))
223          targets += rows
```
→ 군집 응답: 대응단계 결과 + 전술 이름 + '시스템 추정'/'지휘관 지정' + 속한 표적 ID.

```python
225      # 랭킹: 전차·미확인만. 위협도 높은 순, 점수 없는 미확인은 맨 뒤 (그 안에서는 군집 단계 순)
226      ranked = sorted((t for t in targets if t["category"] in RANKED),
227                      key=lambda t: (t["threat"] is None, -(t["threat"] or 0), t["level"]))
228      for i, t in enumerate(ranked, 1):
229          t["rank"] = i
230      targets = ranked + [t for t in targets if t["rank"] is None]                       # 순위 없는 표적(기갑차·포병·인원)은 뒤에
```
→ 랭킹: 전차·미확인만, 위협도 높은 순. 점수가 없으면 맨 뒤. `sorted(key=...)` 의 튜플 키는 앞 값부터 비교합니다. 기갑차·포병·인원은 순위 없이 뒤에 붙습니다.

```python
232      counts = {"total": len(targets), **{k: 0 for k in COUNT_KEYS.values()}, "new": sum(t["is_new"] for t in targets)}
233      for t in targets:
234          if t["category"] in COUNT_KEYS:
235              counts[COUNT_KEYS[t["category"]]] += 1                                    # 분류별 개수
```
→ 상단 카운터: 분류별 개수와 신규 개수.

```python
237      top = min(clusters, key=lambda c: (c["level"], -c["score"]), default=None)        # 가장 심각한 군집
238      level = top["level"] if top else 4
239      alert = {"level": level, "label": C.LEVELS[level], "prev_level": prev["alert"]["level"] if prev else None,
240               "banner": level == 1,                                                     # 1단계면 화면 상단 배너
241               "message": (f"{top['cluster_id']} {top['echelon']['name']}급 {top['echelon']['n']}대 · {top['tactic_name']}"
242                           f" · 군집점수 {top['score']:g}") if top else "탐지 표적 없음"}
```
→ 경보: 단계가 가장 높은(숫자가 작은) 군집 기준. 1단계면 화면 맨 위 빨간 배너(`banner: True`).

```python
243      return {"source": source, "counts": counts, "alert": alert, "clusters": clusters, "targets": targets}
```
→ 응답 JSON 을 돌려줍니다. 실제 값은 `정리/부록/샘플_응답.json` 참고.

