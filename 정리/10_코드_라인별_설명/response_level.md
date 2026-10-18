# response_level.py — DB 기반 대응수준 엔진 (/api/threat)

파일: `response_level.py` (전체 183줄)

대시보드 엔진(`dashboard/threat/`)과 **별도로 있는 두 번째 대응수준 엔진**입니다. 사전 DB(`tank_threat`, `type_threat_summary`, `threat_coef`)
값을 써서 군집 1개의 대응단계(1~4)를 판정하고, 결과와 지휘관 수정 이력을 DB 에 남깁니다. 주소는 `threat_api.py` 의 `/api/threat/*` 입니다.

**대시보드 엔진과 다른 점** (발표 질문 대비)
| 항목 | 대시보드 (`core.py`) | 이 파일 |
|---|---|---|
| 제대 대수 | 전차+기갑차 | 전차+기갑차+**Unknown**(포병·인원 제외), 프레임별 대수의 최댓값 |
| 하한 | 미확인·T≥75 → 3단계 | 같음 + **핵심표적 지정 → 최소 2단계** |
| 결과 저장 | 서버 메모리 | DB `cluster_assessment`, `commander_override` |
| 화면 | 대시보드가 씀 | 화면 없음 (API 만) |

**TODO**: v2 판정 결과(`judge.py`)를 이 엔진 입력(`vehicles[].status`, `tank_id`, `type_group`)으로 바꾸는 어댑터는 아직 없습니다.

### 머리말 — 판정 순서 ①~⑦과 입력 예 (response_level.py:1~20)

```python
  3  판정 순서 (대응수준_산출_설명.docx 와 같은 번호)
  4    ① 전차별 T   Known=사전 T_k / Known_Variant=원형 기종 T_k / Unknown=유형별 상위 25% T_k
  5    ② 전술 k     지휘관 override > (지휘전차 10번, 그 외 시스템 추정 전술). 전차는 1~10번만
  6    ③ T_cluster  군집 내 전차 T의 최댓값
  7    ④ 대수 N     전차+기갑차+Unknown (포병·인원 제외, 프레임별 대수의 최댓값) → 제대가중치 E
  8    ⑤ S = T_cluster × E → 경계값(threat_coef lv1/lv2/lv3)으로 단계
  9    ⑥ 하한       Unknown·T≥floor_t → 최소 3단계, 핵심표적 → 최소 2단계
 10    ⑦ 우선순위   핵심표적 → 지휘전차 → T 내림차순
```
→ 판정 순서. ① 전차별 T → ② 전술 → ③ 군집 최고 T → ④ 대수 N·제대가중치 E → ⑤ S = T×E → ⑥ 하한 → ⑦ 표적 우선순위.

```python
 14  입력 예:
 15  {"cluster_id": "C-001", "system_tactic": 1, "tactic_override": null, "core_targets": ["trk-3"],
 16   "vehicles": [{"track_id": "trk-1", "status": "Known", "tank_id": "TANK_0216", "category": "전차",
 17                 "is_command": false, "confidence": 0.91},
 18                {"track_id": "trk-9", "status": "Unknown", "category": "전차", "type_group": "주력전차"}],
 19   "frames": [["trk-1", "trk-9"], ["trk-1"]]}
```
→ 입력 예: 군집 ID, 시스템 추정 전술, 지휘관 수정 전술, 핵심표적, 차량 목록(상태·사전 ID·분류), 프레임별 보이는 차량.

### 상수와 작은 함수 (response_level.py:21~47)

```python
 23  LEVELS = {1: ("즉시 보고", "적"), 2: ("우선 감시", "주황"), 3: ("지속 감시", "황"), 4: ("관심", "청")}
 24  ECHELONS = [(16, 3, "대대"), (5, 2, "중대"), (1, 1, "소대")]  # (최소 대수, E, 제대명)
 25  COMMAND_TACTIC = 10
```
→ 단계 이름·색, 제대 표, 지휘전차 전술 번호(10).

```python
 28  def echelon(n):
 29      return next(((e, name) for lo, e, name in ECHELONS if n >= lo), (0, "없음"))
```
→ 대수 → (제대가중치, 제대명).

```python
 32  def level_of(score, coef):
 33      for lv, key in ((1, "lv1"), (2, "lv2"), (3, "lv3")):
 34          if score >= coef[key]:
 35              return lv
 36      return 4
```
→ S 를 DB 경계값(lv1=225, lv2=150, lv3=75)과 비교해 단계.

```python
 39  def _counts(r):
 40      """제대 대수 N 에 넣는 차량: 전차·기갑차, 그리고 분류가 포병·인원이 아닌 Unknown (④)."""
 41      return r["category"] in ("전차", "기갑차") or (r["status"] == "Unknown" and r["category"] not in ("포병", "인원"))
```
→ 제대 대수에 넣을 차량: 전차·기갑차, 그리고 포병·인원이 아닌 Unknown.

```python
 44  def _tactic(t):
 45      if not isinstance(t, int) or not 1 <= t <= 10:
 46          raise ValueError(f"전차 전술은 1~10번만 허용: {t!r}")
 47      return t
```
→ 전술 번호가 1~10 정수인지 검사.

### 함수 `assess(cluster, tanks, unknown_t, coef)` — 군집 판정 (순수 함수) (response_level.py:50~126)

이 부분이 하는 일: DB 를 직접 읽지 않고, 조회해 둔 표(tanks, unknown_t, coef)를 인자로 받아 계산만 합니다.

```python
 53      override = cluster.get("tactic_override")
 54      system = _tactic(cluster.get("system_tactic") or 1)
 55      if override is not None:
 56          _tactic(override)
 57      vehicles = cluster.get("vehicles", [])
 58      ids = {v["track_id"] for v in vehicles}
 59      core = [c for c in cluster.get("core_targets", []) if c in ids]
```
→ 지휘관 수정 전술·시스템 전술 검사, 차량 목록과 (실제 있는 차량만) 핵심표적.

```python
 61      rows = []
 62      for v in vehicles:
 63          k = override or (COMMAND_TACTIC if v.get("is_command") else system)
 64          status, cat = v.get("status", "Unknown"), v.get("category", "전차")
 65          row = {"track_id": v["track_id"], "status": status, "category": cat, "tactic": k,
 66                 "is_command": bool(v.get("is_command")), "core_target": v["track_id"] in core,
 67                 "detect_confidence": v.get("confidence"), "tank_id": v.get("tank_id"), "name": None,
 68                 "T": None, "data_confidence": None, "tags": []}
```
→ 차량마다 전술 k = 지휘관 수정 > (지휘전차면 10) > 시스템 전술. 결과 행 기본값.

```python
 69          if cat == "전차":
 70              info = tanks.get(v.get("tank_id")) if status in ("Known", "Known_Variant") else None
 71              if info and info["computable"]:
 72                  row.update(name=info["name"], T=info["t"][k - 1], data_confidence=info["confidence"])
 73                  if status == "Known_Variant":
 74                      row["tags"].append(f"{info['name']} 계열 추정")
```
→ 전차이고 Known/Known_Variant 이며 사전에서 계산 가능하면 사전 T_k 를 그대로 씁니다.

```python
 75              else:
 76                  tg = (info or {}).get("type_group") or v.get("type_group") or "주력전차"
 77                  row.update(T=unknown_t.get((tg, k)), data_confidence="대체")
 78                  row["tags"].append("분석관 검토" if status == "Unknown" else "T 산출불가 → 유형 대체")
 79                  row["tags"].append(f"{tg} 상위25% 대체")
 80                  if info:
 81                      row["name"] = info["name"]
```
→ 아니면 유형별 상위 25% T 로 대체하고 '분석관 검토'·'유형 대체' 태그.

```python
 82          elif status == "Unknown":
 83              row["tags"].append("분석관 검토")
 84          rows.append(row)
```
→ 전차가 아닌 Unknown 도 '분석관 검토' 태그.

```python
 86      counted = {r["track_id"] for r in rows if _counts(r)}
 87      frames = cluster.get("frames")
 88      if frames:
 89          n = max(sum(1 for t in f if t in counted) for f in frames)
 90      else:
 91          n = len(counted)
 92      e, ech = echelon(n)
```
→ ④ 대수 N: 프레임 정보가 있으면 **프레임별로 동시에 보인 대수의 최댓값**(같은 차량을 여러 번 세지 않음), 없으면 전체 수.

```python
 94      ts = [r["T"] for r in rows if r["T"] is not None]
 95      t_cluster = max(ts) if ts else 0.0
 96      score = round(t_cluster * e, 1)
 97      base = level_of(score, coef)
```
→ ③ 군집 최고 T, ⑤ S = T × E, 기본 단계.

```python
 99      floors = []
100      unknowns = [r["track_id"] for r in rows if r["status"] == "Unknown" and r["category"] != "포병"]
101      strong = [r for r in rows if r["T"] is not None and r["status"] != "Unknown" and r["T"] >= coef["floor_t"]]
102      if unknowns:
103          floors.append({"min_level": 3, "rule": "Unknown 포함", "reason": f"Unknown {len(unknowns)}대: {', '.join(unknowns)}"})
104      if strong:
105          top = max(strong, key=lambda r: r["T"])
106          floors.append({"min_level": 3, "rule": f"T≥{coef['floor_t']:g} 전차 포함",
107                         "reason": f"{len(strong)}대, 최고 {top['name']} {top['T']}"})
108      if core:
109          floors.append({"min_level": 2, "rule": "핵심표적 지정", "reason": ", ".join(core)})
110      final = min([base] + [f["min_level"] for f in floors])
```
→ ⑥ 하한: Unknown(포병 제외) 포함 → 최소 3, T≥75 인 확인 전차 → 최소 3, 핵심표적 → 최소 2. 가장 높은(숫자가 작은) 단계를 고릅니다.

```python
112      rows.sort(key=lambda r: (not r["core_target"], not r["is_command"], -(r["T"] if r["T"] is not None else -1)))
113      for i, r in enumerate(rows, 1):
114          r["rank"] = i
```
→ ⑦ 우선순위: 핵심표적 → 지휘전차 → T 높은 순.

```python
116      name, color = LEVELS[final]
117      out = {"cluster_id": cluster.get("cluster_id"), "level": final, "level_name": name, "color": color,
118             "score_level": base, "S": score, "T_cluster": t_cluster, "E": e, "echelon": ech, "N": n,
119             "tactic": override or system, "tactic_source": "지휘관 수정" if override else "시스템 추정",
120             "floors_applied": [f for f in floors if f["min_level"] < base], "floors_checked": floors,
121             "vehicles": rows}
```
→ 결과: 단계·이름·색·S·T·E·N·전술·적용된 하한 등.

```python
122      if _with_before:
123          plain = dict(cluster, tactic_override=None, core_targets=[])
124          out["level_before_override"] = assess(plain, tanks, unknown_t, coef, _with_before=False)["level"]
125          out["level_after_override"] = final
126      return out
```
→ 지휘관 수정 전 단계도 함께 계산해(수정·핵심표적을 뺀 입력으로 한 번 더 assess) 비교할 수 있게 합니다.

### DB 연동 함수 (response_level.py:129~183)

```python
130  def load_lookup():
131      import threat_db as tdb
132      tanks = {r["tank_id"]: {"name": r["canonical_name"], "type_group": r["type_group"], "computable": bool(r["computable"]),
133                              "confidence": r["confidence"], "t": [r[f"t{i}"] for i in range(1, 11)]}
134               for r in tdb.query("SELECT * FROM tank_threat")}
135      unknown_t = {(r["type_group"], r["tactic_no"]): r["t_p75"] for r in tdb.query("SELECT * FROM type_threat_summary")}
136      coef = {r["k"]: r["v"] for r in tdb.query("SELECT k, v FROM threat_coef")}
137      return tanks, unknown_t, coef
```
→ `load_lookup`: DB 에서 기종별 T_1~T_10, 유형별 p75, 경계값을 읽어 표로 만듭니다.

```python
140  def assess_and_save(cluster, lookup=None):
141      import threat_db as tdb
142      result = assess(cluster, *(lookup or load_lookup()))
143      tdb.execute("INSERT INTO cluster_assessment (cluster_id, level, score, t_cluster, echelon_e, n_vehicles, tactic_no,"
144                  " input_json, result_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
145                  (cluster.get("cluster_id"), result["level"], result["S"], result["T_cluster"], result["E"], result["N"],
146                   result["tactic"], json.dumps(cluster, ensure_ascii=False), json.dumps(result, ensure_ascii=False)))
147      return result
```
→ `assess_and_save`: 판정 후 입력·결과 JSON 을 `cluster_assessment` 에 저장(이력).

```python
150  def latest_cluster(cluster_id):
151      import threat_db as tdb
152      rows = tdb.query("SELECT input_json, level FROM cluster_assessment WHERE cluster_id = %s ORDER BY id DESC LIMIT 1",
153                       (cluster_id,))
154      return (json.loads(rows[0]["input_json"]), rows[0]["level"]) if rows else (None, None)
```
→ `latest_cluster`: 그 군집의 가장 최근 입력·단계.

```python
157  def apply_override(cluster_id, item, value, actor="unknown", remove=False, lookup=None):
158      """item='tactic': value=전술 번호(None 이면 해제). item='core_target': value=track_id, remove=True 면 해제.
159      그 군집만 재판정하고 commander_override 에 변경 전→후를 남긴다."""
160      import threat_db as tdb
161      cluster, level_before = latest_cluster(cluster_id)
162      if cluster is None:
163          raise LookupError(cluster_id)
164      if item == "tactic":
165          before = cluster.get("tactic_override")
166          if value is not None:
167              _tactic(value)
168          cluster["tactic_override"] = value
169          after = value
170      elif item == "core_target":
171          before = list(cluster.get("core_targets", []))
172          if value not in {v["track_id"] for v in cluster.get("vehicles", [])}:
173              raise ValueError(f"군집에 없는 track_id: {value}")
174          cluster["core_targets"] = [c for c in before if c != value] + ([] if remove else [value])
175          after = cluster["core_targets"]
176      else:
177          raise ValueError(f"알 수 없는 항목: {item}")
```
→ `apply_override`: 지휘관 수정(전술 또는 핵심표적)을 최근 입력에 반영. 없는 군집이면 LookupError(404), 잘못된 값이면 ValueError(400).

```python
178      result = assess_and_save(cluster, lookup)
179      tdb.execute("INSERT INTO commander_override (cluster_id, actor, item, before_value, after_value, level_before,"
180                  " level_after) VALUES (%s,%s,%s,%s,%s,%s,%s)",
181                  (cluster_id, actor, item, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
182                   level_before, result["level"]))
183      return result
```
→ 재판정·저장 후 `commander_override` 에 변경 전→후, 단계 전→후를 기록합니다.

