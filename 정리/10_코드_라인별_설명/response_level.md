# response_level.py — 군집 대응단계 판정 엔진과 기록 (하나뿐인 엔진)

파일: `response_level.py` (전체 257줄)

군집 1개의 대응단계(1~4)를 판정하는 **유일한 엔진**입니다. 엔진 통합 후 대시보드 화면(`adapter.py` 경유), `/api/threat/*`(`threat_api.py`),
보고서가 모두 이 파일의 `assess()` 와 같은 경계값(`load_coef`)·같은 기록 테이블(`cluster_assessment`, `commander_override`)을 씁니다.

- `assess()` 는 **순수 함수**(DB 를 직접 읽지 않음). 조회 데이터와 경계값을 인자로 받습니다.
- 차량에 미리 계산된 위협도 `"T"` 가 있으면 그대로 쓰고(대시보드), 없으면 사전 DB 의 전술별 T 를 찾습니다(외부 API).
- 기록 함수(`save_assessment`, `record_override`, `history`)도 여기 한 곳에 있습니다.
- 숫자: 경계값은 DB `threat_coef`(없으면 `dashboard/threat/config.py`), 제대 표는 이 파일 `ECHELONS`.

### 머리말 — 판정 순서 ①~⑦과 입력 예 (response_level.py:1~21)

```python
  3  판정 순서 (대응수준_산출_설명.docx 와 같은 번호)
  4    ① 전차별 T   Known=사전 T_k / Known_Variant=원형 기종 T_k / Unknown=유형별 상위 25% T_k
  5                 (차량에 "T" 가 있으면 그 값을 그대로 씀 — 대시보드가 judge.threat_of 로 미리 계산한 T. tags·threat_source 도 같이 받음)
  6    ② 전술 k     지휘관 override > (지휘전차 10번, 그 외 시스템 추정 전술). 전차는 1~10번만
  7    ③ T_cluster  군집 내 전차 T의 최댓값
  8    ④ 대수 N     전차+기갑차+Unknown (포병·인원 제외, 프레임별 대수의 최댓값) → 제대가중치 E
  9    ⑤ S = T_cluster × E → 경계값(threat_coef lv1/lv2/lv3)으로 단계
 10    ⑥ 하한       Unknown·T≥floor_t → 최소 3단계, 핵심표적 → 최소 2단계
 11    ⑦ 우선순위   핵심표적 → 지휘전차 → T 내림차순
```
→ 판정 순서. ① 전차별 T(입력에 T 가 있으면 그 값) → ② 전술 → ③ 군집 최고 T → ④ 대수 N·제대가중치 E → ⑤ S = T×E → ⑥ 하한 → ⑦ 표적 우선순위.

```python
 15  입력 예:
 16  {"cluster_id": "C-001", "system_tactic": 1, "tactic_override": null, "core_targets": ["trk-3"],
 17   "vehicles": [{"track_id": "trk-1", "status": "Known", "tank_id": "TANK_0216", "category": "전차",
 18                 "is_command": false, "confidence": 0.91},
 19                {"track_id": "trk-9", "status": "Unknown", "category": "전차", "type_group": "주력전차"}],
 20   "frames": [["trk-1", "trk-9"], ["trk-1"]]}
```
→ 입력 예: 군집 ID, 시스템 추정 전술, 지휘관 수정 전술, 핵심표적, 차량 목록(상태·사전 ID·분류), 프레임별 보이는 차량.

### 상수와 작은 함수 (response_level.py:22~54)

```python
 22  import hashlib
 23  import json
 24  import logging
 25  from datetime import datetime
```
→ `hashlib`(짧은 고유값 만들기), `json`, `logging`(경고 기록), `datetime`(기록 시각).

```python
 27  LEVELS = {1: ("즉시 보고", "적"), 2: ("우선 감시", "주황"), 3: ("지속 감시", "황"), 4: ("관심", "청")}
 28  ECHELONS = [(16, 3, "대대"), (5, 2, "중대"), (1, 1, "소대")]  # (최소 대수, E, 제대명)
 29  COMMAND_TACTIC = 10
 30  log = logging.getLogger(__name__)
```
→ 단계 이름·색, **제대 표(한 곳)**, 지휘전차 전술 번호(10), 로그.

```python
 33  def echelon(n):
 34      return next(((e, name) for lo, e, name in ECHELONS if n >= lo), (0, "없음"))
```
→ 대수 → (제대가중치, 제대명). 16대 이상 대대 3, 5대 이상 중대 2, 1대 이상 소대 1, 0대 없음 0.

```python
 37  def level_of(score, coef):
 38      for lv, key in ((1, "lv1"), (2, "lv2"), (3, "lv3")):
 39          if score >= coef[key]:
 40              return lv
 41      return 4
```
→ S 를 경계값(lv1=225, lv2=150, lv3=75)과 비교해 단계.

```python
 44  def _counts(r, count_unknown=True):
 45      """제대 대수 N 에 넣는 차량: 전차·기갑차, 그리고 분류가 포병·인원이 아닌 Unknown (④).
 46      count_unknown=False 면 전차·기갑차만 (예전 대시보드 방식, dashboard/threat/config.py ECHELON_COUNT_UNKNOWN)."""
 47      return r["category"] in ("전차", "기갑차") or (count_unknown and r["status"] == "Unknown"
 48                                                     and r["category"] not in ("포병", "인원"))
```
→ 제대 대수에 넣을 차량: 전차·기갑차, 그리고 포병·인원이 아닌 Unknown. `count_unknown=False` 면 전차·기갑차만 (대시보드 스위치 `ECHELON_COUNT_UNKNOWN`).

```python
 51  def _tactic(t):
 52      if not isinstance(t, int) or not 1 <= t <= 10:
 53          raise ValueError(f"전차 전술은 1~10번만 허용: {t!r}")
 54      return t
```
→ 전술 번호가 1~10 정수인지 검사.

### 함수 `assess(cluster, tanks, unknown_t, coef)` — 군집 판정 (순수 함수) (response_level.py:57~138)

이 부분이 하는 일: DB 를 직접 읽지 않고, 조회해 둔 표(tanks, unknown_t)와 경계값(coef)을 인자로 받아 계산만 합니다.

```python
 61      override = cluster.get("tactic_override")
 62      system = _tactic(cluster.get("system_tactic") or 1)
 63      if override is not None:
 64          _tactic(override)
 65      vehicles = cluster.get("vehicles", [])
 66      ids = {v["track_id"] for v in vehicles}
 67      core = [c for c in cluster.get("core_targets", []) if c in ids]
```
→ 지휘관 수정 전술·시스템 전술 검사, 차량 목록과 (실제 있는 차량만) 핵심표적.

```python
 69      rows = []
 70      for v in vehicles:
 71          k = override or (COMMAND_TACTIC if v.get("is_command") else system)
 72          status, cat = v.get("status", "Unknown"), v.get("category", "전차")
 73          row = {"track_id": v["track_id"], "status": status, "category": cat, "tactic": k,
 74                 "is_command": bool(v.get("is_command")), "core_target": v["track_id"] in core,
 75                 "detect_confidence": v.get("confidence"), "tank_id": v.get("tank_id"), "name": None,
 76                 "T": None, "data_confidence": None, "tags": []}
```
→ 차량마다 전술 k = 지휘관 수정 > (지휘전차면 10) > 시스템 전술. 결과 행 기본값.

```python
 77          if "T" in v:                                       # 미리 계산된 T (대시보드: cope cage·계열 p75·지휘전차 반영)
 78              row.update(T=v["T"], name=v.get("name") or (tanks.get(v.get("tank_id")) or {}).get("name"),
 79                         data_confidence=v.get("data_confidence"), threat_source=v.get("threat_source"))
 80              row["tags"] += list(v.get("tags") or [])
```
→ **미리 계산된 T** 가 있으면 그대로 씁니다 (대시보드: cope cage·계열 p75·지휘전차가 반영된 값). 이름·근거·태그도 받은 값.

```python
 81          elif cat == "전차":
 82              info = tanks.get(v.get("tank_id")) if status in ("Known", "Known_Variant") else None
 83              if info and info["computable"]:
 84                  row.update(name=info["name"], T=info["t"][k - 1], data_confidence=info["confidence"])
 85                  if status == "Known_Variant":
 86                      row["tags"].append(f"{info['name']} 계열 추정")
```
→ T 가 없고 전차이며 Known/Known_Variant, 사전에서 계산 가능하면 사전 T_k 를 씁니다 (외부 API 의 lookup 형식).

```python
 87              else:
 88                  tg = (info or {}).get("type_group") or v.get("type_group") or "주력전차"
 89                  row.update(T=unknown_t.get((tg, k)), data_confidence="대체")
 90                  row["tags"].append("분석관 검토" if status == "Unknown" else "T 산출불가 → 유형 대체")
 91                  row["tags"].append(f"{tg} 상위25% 대체")
 92                  if info:
 93                      row["name"] = info["name"]
```
→ 아니면 유형별 상위 25% T 로 대체하고 '분석관 검토'·'유형 대체' 태그.

```python
 94          elif status == "Unknown":
 95              row["tags"].append("분석관 검토")
 96          rows.append(row)
```
→ 전차가 아닌 Unknown 도 '분석관 검토' 태그.

```python
 98      counted = {r["track_id"] for r in rows if _counts(r, cluster.get("echelon_count_unknown", True))}
 99      frames = cluster.get("frames")
100      if frames:
101          n = max(sum(1 for t in f if t in counted) for f in frames)
102      else:
103          n = len(counted)
104      e, ech = echelon(n)
```
→ ④ 대수 N: 프레임 정보가 있으면 **프레임별로 동시에 보인 대수의 최댓값**(같은 차량을 여러 번 세지 않음), 없으면 전체 수.

```python
106      ts = [r["T"] for r in rows if r["T"] is not None]
107      t_cluster = max(ts) if ts else 0.0
108      score = round(t_cluster * e, 1)
109      base = level_of(score, coef)
```
→ ③ 군집 최고 T, ⑤ S = T × E, 점수만으로 본 단계.

```python
111      floors = []
112      unknowns = [r["track_id"] for r in rows if r["status"] == "Unknown" and r["category"] != "포병"]
113      strong = [r for r in rows if r["T"] is not None and r["status"] != "Unknown" and r["T"] >= coef["floor_t"]]
114      if unknowns:
115          floors.append({"min_level": 3, "rule": "Unknown 포함", "reason": f"Unknown {len(unknowns)}대: {', '.join(unknowns)}"})
116      if strong:
117          top = max(strong, key=lambda r: r["T"])
118          floors.append({"min_level": 3, "rule": f"T≥{coef['floor_t']:g} 전차 포함",
119                         "reason": f"{len(strong)}대, 최고 {top['name']} {top['T']}"})
120      if core:
121          floors.append({"min_level": 2, "rule": "핵심표적 지정", "reason": ", ".join(core)})
122      final = min([base] + [f["min_level"] for f in floors])
```
→ ⑥ 하한: Unknown(포병 제외) 포함 → 최소 3, T≥75 인 확인 전차 → 최소 3, 핵심표적 → 최소 2. **항상** 적용해 가장 높은(숫자가 작은) 단계를 고릅니다.

```python
124      rows.sort(key=lambda r: (not r["core_target"], not r["is_command"], -(r["T"] if r["T"] is not None else -1)))
125      for i, r in enumerate(rows, 1):
126          r["rank"] = i
```
→ ⑦ 우선순위: 핵심표적 → 지휘전차 → T 높은 순 (대시보드 랭킹은 지휘전차를 순서에 넣지 않음 — 팀 결정 필요).

```python
128      name, color = LEVELS[final]
129      out = {"cluster_id": cluster.get("cluster_id"), "level": final, "level_name": name, "color": color,
130             "score_level": base, "S": score, "T_cluster": t_cluster, "E": e, "echelon": ech, "N": n,
131             "tactic": override or system, "tactic_source": "지휘관 수정" if override else "시스템 추정",
132             "floors_applied": [f for f in floors if f["min_level"] < base], "floors_checked": floors,
133             "vehicles": rows}
```
→ 결과: 단계·이름·색·S·T·E·N·전술·적용된 하한(`floors_applied`)·검사한 하한(`floors_checked`)·차량.

```python
134      if _with_before:
135          plain = dict(cluster, tactic_override=None, core_targets=[])
136          out["level_before_override"] = assess(plain, tanks, unknown_t, coef, _with_before=False)["level"]
137          out["level_after_override"] = final
138      return out
```
→ 지휘관 수정 전 단계도 함께 계산합니다(전술 수정·핵심표적을 뺀 입력으로 한 번 더). T 가 미리 계산된 입력에서는 전술 효과가 T 에 이미 들어 있어서, 대시보드는 조치 전 단계를 `pipeline.py:253~256` 에서 따로 구합니다.

### 함수 `load_coef()` — 경계값 (한 곳) (response_level.py:141~156)

```python
142  COEF_KEYS = ("lv1", "lv2", "lv3", "floor_t")
```
→ 경계값 키 4개.

```python
148      from dashboard.threat import config as C          # 함수 안에서 import (dashboard 패키지와 순환 import 방지)
149      coef = {f"lv{lv}": th for th, lv in C.LEVEL_THRESHOLDS}
150      coef["floor_t"] = C.FLOOR_TANK_THREAT
```
→ 기본값은 `dashboard/threat/config.py` 의 `LEVEL_THRESHOLDS`·`FLOOR_TANK_THREAT`. 함수 안에서 import 해서 두 파일이 서로를 import 하는 순환을 피합니다.

```python
151      try:
152          import threat_db as tdb
153          coef.update({r["k"]: r["v"] for r in tdb.query("SELECT k, v FROM threat_coef") if r["k"] in COEF_KEYS})
154      except Exception as e:                            # DB 없음·테이블 없음 → 기본값
155          log.warning("threat_coef 를 못 읽어 config 기본 경계값 사용: %s", e)
156      return coef
```
→ DB `threat_coef` 에 값이 있으면 덮어씁니다. 테이블이 없으면(DB 없는 데모) 경고만 남기고 기본값.

### 함수 `load_lookup()` — 외부 API 형식용 사전 표 (response_level.py:159~165)

```python
159  def load_lookup():
160      import threat_db as tdb
161      tanks = {r["tank_id"]: {"name": r["canonical_name"], "type_group": r["type_group"], "computable": bool(r["computable"]),
162                              "confidence": r["confidence"], "t": [r[f"t{i}"] for i in range(1, 11)]}
163               for r in tdb.query("SELECT * FROM tank_threat")}
164      unknown_t = {(r["type_group"], r["tactic_no"]): r["t_p75"] for r in tdb.query("SELECT * FROM type_threat_summary")}
165      return tanks, unknown_t, load_coef()
```
→ DB 에서 기종별 T_1~T_10, 유형별 p75 를 읽고 경계값은 `load_coef()` 로. 차량에 T 가 없는 입력에만 필요합니다.

### 기록 함수 — `cluster_key`, `save_assessment`, `record_override`, `history` (response_level.py:168~216)

```python
168  def _now():
169      return datetime.now().strftime("%Y-%m-%d %H:%M:%S")      # 시각을 직접 넣음 (SQLite 기본값은 UTC 라 MySQL 과 달라짐)
```
→ 기록 시각을 직접 넣습니다 (SQLite 기본값은 UTC 라 MySQL 과 9시간 차이).

```python
172  def cluster_key(video, cluster_id):
173      """기록용 군집 ID '영상:군집' — 영상이 달라도 C-1 이 겹치지 않게. DB 컬럼(64자)보다 길면 앞부분 + 해시로 줄인다."""
174      key = f"{video}:{cluster_id}"
175      if len(key) <= 64:
176          return key
177      tail = f"~{hashlib.sha1(key.encode()).hexdigest()[:8]}:{cluster_id}"[-64:]
178      return str(video)[:64 - len(tail)] + tail
```
→ 기록용 군집 ID '영상:군집' (예: mock_video_A.mp4:C-1) — 영상마다 C-1 이 있어도 겹치지 않게. DB 컬럼(64자)보다 길면 앞부분을 자르고 해시(내용으로 만든 짧은 고유값)를 붙입니다.

```python
181  def save_assessment(cluster, result):
182      """판정 1건 기록 (cluster_assessment). cluster = assess 입력 그대로 → apply_override 가 이 입력으로 다시 판정한다."""
183      import threat_db as tdb
184      tdb.ensure_schema()
185      return tdb.execute("INSERT INTO cluster_assessment (cluster_id, level, score, t_cluster, echelon_e, n_vehicles, tactic_no,"
186                         " input_json, result_json, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
187                         (cluster.get("cluster_id"), result["level"], result["S"], result["T_cluster"], result["E"],
188                          result["N"], result["tactic"], json.dumps(cluster, ensure_ascii=False),
189                          json.dumps(result, ensure_ascii=False), _now()))
```
→ **판정 1건 기록** (`cluster_assessment`). 입력 JSON 을 그대로 저장해서 나중에 `apply_override` 가 같은 입력으로 다시 판정할 수 있습니다.

```python
192  def record_override(cluster_id, actor, item, before, after, level_before, level_after):
193      """지휘관 조치 1건 기록 (commander_override). item: tactic | core_target | commander | stage."""
194      import threat_db as tdb
195      tdb.ensure_schema()
196      tdb.execute("INSERT INTO commander_override (cluster_id, actor, item, before_value, after_value, level_before,"
197                  " level_after, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
198                  (cluster_id, actor, item, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
199                   level_before, level_after, _now()))
```
→ **지휘관 조치 1건 기록** (`commander_override`): 누가(actor), 무엇을(item: tactic·core_target·commander·stage), 전→후, 단계 전→후.

```python
202  def history(cluster_id):
203      """그 군집의 판정·지휘관 조치 이력 (시간순). 각 항목: {"kind": "판정"|"조치", "at", ...}."""
204      import threat_db as tdb
205      tdb.ensure_schema()
206      out = [{"kind": "판정", "at": str(r["created_at"])[:19], "level": r["level"], "score": r["score"],
207              "tactic": r["tactic_no"], "id": r["id"]}
208             for r in tdb.query("SELECT id, level, score, tactic_no, created_at FROM cluster_assessment WHERE cluster_id = %s",
209                                (cluster_id,))]
210      out += [{"kind": "조치", "at": str(r["created_at"])[:19], "actor": r["actor"], "item": r["item"],
211               "before": json.loads(r["before_value"]) if r["before_value"] else None,
212               "after": json.loads(r["after_value"]) if r["after_value"] else None,
213               "level_before": r["level_before"], "level_after": r["level_after"], "id": r["id"]}
214              for r in tdb.query("SELECT id, actor, item, before_value, after_value, level_before, level_after, created_at "
215                                 "FROM commander_override WHERE cluster_id = %s", (cluster_id,))]
216      return sorted(out, key=lambda e: (e["at"], e["kind"] == "조치", e["id"]))   # 같은 시각이면 기록된 순서(판정 → 조치)
```
→ **이력 조회**: 그 군집의 판정과 조치를 시간순으로 합칩니다. 같은 시각이면 기록된 순서(판정 → 조치).

### 판정+기록 함수 — `assess_and_save`, `latest_cluster`, `apply_override` (response_level.py:219~257)

```python
219  def assess_and_save(cluster, lookup=None):
220      """판정 + 기록. 모든 차량에 T 가 있으면(대시보드 형식) 사전 lookup 없이 경계값만 읽는다."""
221      if lookup is None:
222          lookup = ({}, {}, load_coef()) if all("T" in v for v in cluster.get("vehicles", [])) else load_lookup()
223      result = assess(cluster, *lookup)
224      save_assessment(cluster, result)
225      return result
```
→ 판정하고 기록. 모든 차량에 T 가 있으면(대시보드 형식) 사전 표 없이 경계값만 읽습니다.

```python
228  def latest_cluster(cluster_id):
229      import threat_db as tdb
230      rows = tdb.query("SELECT input_json, level FROM cluster_assessment WHERE cluster_id = %s ORDER BY id DESC LIMIT 1",
231                       (cluster_id,))
232      return (json.loads(rows[0]["input_json"]), rows[0]["level"]) if rows else (None, None)
```
→ 그 군집의 가장 최근 판정 입력과 단계.

```python
235  def apply_override(cluster_id, item, value, actor="unknown", remove=False, lookup=None):
236      """item='tactic': value=전술 번호(None 이면 해제). item='core_target': value=track_id, remove=True 면 해제.
237      그 군집만 재판정하고 commander_override 에 변경 전→후를 남긴다."""
238      cluster, level_before = latest_cluster(cluster_id)
239      if cluster is None:
240          raise LookupError(cluster_id)
241      if item == "tactic":
242          before = cluster.get("tactic_override")
243          if value is not None:
244              _tactic(value)
245          cluster["tactic_override"] = value
246          after = value
247      elif item == "core_target":
248          before = list(cluster.get("core_targets", []))
249          if value not in {v["track_id"] for v in cluster.get("vehicles", [])}:
250              raise ValueError(f"군집에 없는 track_id: {value}")
251          cluster["core_targets"] = [c for c in before if c != value] + ([] if remove else [value])
252          after = cluster["core_targets"]
253      else:
254          raise ValueError(f"알 수 없는 항목: {item}")
```
→ `apply_override` (`/api/threat/cluster/<id>/...`): 최근 입력에 지휘관 수정(전술 또는 핵심표적)을 반영. 없는 군집이면 LookupError(404), 잘못된 값이면 ValueError(400). **주의**: T 가 미리 계산된 입력은 전술을 바꿔도 T 가 다시 계산되지 않습니다 (대시보드는 전술 변경 때 위협도부터 다시 계산).

```python
255      result = assess_and_save(cluster, lookup)
256      record_override(cluster_id, actor, item, before, after, level_before, result["level"])
257      return result
```
→ 다시 판정·기록하고 `commander_override` 에 남깁니다.

