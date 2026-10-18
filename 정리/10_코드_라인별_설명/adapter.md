# adapter.py — 대시보드 ↔ 판정 엔진(response_level.assess) 변환

파일: `dashboard/threat/adapter.py` (전체 83줄)

**엔진 통합의 연결 부분**입니다. 예전에는 대시보드(`core.cluster_response_level`)와 DB 엔진(`response_level.assess`)이 군집 대응단계를 따로 계산했는데,
이제 대시보드도 `response_level.assess` 하나로 판정합니다. 이 파일은 그 사이에서 **모양만 바꿔 주는 변환기(어댑터)** 입니다.

```
pipeline 의 표적 행(row)들 ──to_assess_input──▶ assess 입력 ──response_level.assess──▶ assess 결과 ──from_assess_output──▶ 화면 Cluster
```

- 전차 1대 위협도 T 는 대시보드가 이미 계산한 값(cope cage 보정·계열 상위 25%·지휘전차 가중치 반영)을 `"T"` 로 넘깁니다 → 판정 엔진이 사전 DB 를 다시 찾지 않습니다.
- 화면(`dashboard.js`)이 쓰는 필드 이름(`level`, `label`, `score`, `t_cluster`, `echelon`, `reasons`)은 예전과 같게 돌려줍니다.

### 머리말과 import (adapter.py:1~18)

```python
 1  """대시보드 표적 행 ↔ response_level.assess 입력·출력 변환. 군집 대응단계 판정 엔진은 response_level.assess 하나다.
 3  - 전차 1대 위협도 T 는 대시보드(judge.threat_of · core.tank_threat)가 계산해 "T" 로 넘긴다 → cope cage 보정·계열 p75·지휘전차 가중치가 판정에 그대로 쓰임
 4  - 결과는 화면(dashboard.js)이 쓰는 Cluster 형식(level, label, score, t_cluster, echelon, reasons)으로 되돌린다
 5  - 경계값은 response_level.load_coef() (DB threat_coef 우선, 없으면 config 기본값)
 6  """
```
→ 이 파일의 역할 요약.

```python
10  from . import config as C
11  from .core import infer_tactic, is_unknown
```
→ 설정값(`C`)과 전술 추정·미확인 판단 함수.

```python
13  ROOT = Path(__file__).resolve().parents[2]
14  if str(ROOT) not in sys.path:
15      sys.path.insert(0, str(ROOT))
16  import response_level as rl  # noqa: E402
```
→ 저장소 루트의 `response_level.py` 를 가져오려고 루트 폴더를 import 경로에 넣습니다. `rl` 로 줄여 부릅니다.

```python
18  RULE_KO = {"Unknown 포함": "미확인 포함", "핵심표적 지정": "핵심표적 지정"}   # 하한 규칙 이름 → 화면 문구
```
→ 하한 규칙 이름을 화면용 한국어로 바꾸는 표 ('Unknown 포함' → '미확인 포함').

### 함수 `load_coef()` — 판정 경계값 (adapter.py:21~23)

```python
21  def load_coef():
22      """판정 경계값 (lv1·lv2·lv3·floor_t)."""
23      return rl.load_coef()
```
→ `response_level.load_coef()` 를 그대로 부릅니다. DB `threat_coef` 의 lv1·lv2·lv3·floor_t 가 우선이고, 없으면 `config.py` 기본값(225/150/75, 75). 경계값 조회는 이 한 곳.

### 함수 `to_assess_input(...)` — 표적 행 → 판정 입력 (adapter.py:26~43)

이 부분이 하는 일: 대시보드 군집 1개를 `response_level.assess` 가 받는 형식으로 바꿉니다.

```python
30      override = int(tactic) if tactic_source == "지휘관 지정" else None
31      ids = {r["tracking_id"] for r in rows}
```
→ 지휘관이 전술을 지정했으면 그 번호가 `tactic_override`. 군집 표적 ID 집합도 만듭니다.

```python
32      out = {"cluster_id": cluster_id,
33             "system_tactic": int(infer_tactic(members)),                       # 지휘관이 바꾸기 전 시스템 추정
34             "tactic_override": override,
35             "core_targets": [t for t in core_targets if t in ids],
36             "echelon_count_unknown": C.ECHELON_COUNT_UNKNOWN,
```
→ 군집 ID, 시스템 추정 전술(지휘관이 바꾸기 전), 지휘관 전술, 이 군집에 속한 핵심표적, 미확인을 대수에 넣을지(`ECHELON_COUNT_UNKNOWN`).

```python
37             "vehicles": [{"track_id": r["tracking_id"], "status": r["status"], "category": r["category"],
38                           "tank_id": r.get("tank_id"), "type_group": r.get("type_group"), "name": r.get("model"),
39                           "is_command": bool(r["is_commander"]), "confidence": r.get("confidence"),
40                           "T": r["threat"], "threat_source": r.get("threat_source"), "tags": []} for r in rows]}
```
→ 차량 목록: 상태(Known/Known_Variant/Unknown), 분류, 사전 ID, 지휘전차 여부, 그리고 **미리 계산된 위협도 T**와 그 출처.

```python
41      if frames:                                                                  # v2: 프레임별로 동시에 보인 대수의 최댓값
42          out["frames"] = [[t for t in f if t in ids] for f in frames]
43      return out
```
→ v2 입력이면 프레임별로 그 군집 표적만 남긴 목록을 넣습니다 → 판정 엔진이 '프레임마다 동시에 보인 대수의 최댓값'으로 제대를 정합니다. v1 은 프레임 정보가 없어 생략.

### 함수 `floor_text(f)` — 하한 규칙 문장 (adapter.py:46~49)

```python
46  def floor_text(f):
47      """하한 규칙 1개 → 화면 문장. 예: '미확인 포함 → 최소 3단계 (미확인 1대: UNK-001)'."""
48      rule = RULE_KO.get(f["rule"], f["rule"])
49      return f"{rule} → 최소 {f['min_level']}단계 ({f['reason'].replace('Unknown', '미확인')})"
```
→ 판정 엔진의 하한 규칙 1개를 화면 문장으로. 예: '핵심표적 지정 → 최소 2단계 (Tank-01)', '미확인 포함 → 최소 3단계 (미확인 1대: UNK-001)'.

### 함수 `from_assess_output(result)` — 판정 결과 → 화면 Cluster (adapter.py:52~63)

이 부분이 하는 일: 판정 엔진 결과를 화면이 쓰던 형식으로 되돌리고, 새 정보(S·E·N, 하한 규칙 목록, 지휘관 조치 전 단계)를 덧붙입니다.

```python
54      n, e, s, t, base = result["N"], result["E"], result["S"], result["T_cluster"], result["score_level"]
55      applied = result["floors_applied"]
```
→ 대수 N, 제대가중치 E, 군집점수 S, 군집 최고 위협도 T, 점수만으로 본 단계, 실제로 적용된 하한 규칙.

```python
56      reasons = [f"{result['echelon']}급 {n}대 ×{e}" if n else "전투차량 없음",                     # 근거 1: 제대
57                 f"군집점수 {s:g} = 최고 위협도 {t:g} × {e} → {base}단계"]                          # 근거 2: 점수 판정
58      reasons += [floor_text(f) for f in applied]                                                  # 근거 3~: 적용된 하한
```
→ 판정 근거 문장 — 예전 문구 그대로: '소대급 3대 ×1', '군집점수 88.9 = 최고 위협도 88.9 × 1 → 3단계', 그리고 적용된 하한 규칙 문장.

```python
59      return {"level": result["level"], "label": C.LEVELS[result["level"]], "score": s, "t_cluster": t,
60              "echelon": {"n": n, "weight": e, "name": result["echelon"]}, "reasons": reasons,
61              "floors": [dict(f, text=floor_text(f), applied=f in applied) for f in result["floors_checked"]],
62              "score_level": base, "level_before_override": result.get("level_before_override", result["level"]),
63              "S": s, "E": e, "N": n, "core_targets": result.get("core_targets", [])}
```
→ 화면 필드 + `floors`(검사한 하한 규칙 전부, 적용 여부 포함) + `level_before_override` + S·E·N + 핵심표적 목록.

### 함수 `assess_cluster(...)` — 대시보드 군집 판정 (pipeline 이 부름) (adapter.py:66~71)

```python
69      inp = to_assess_input(cluster_id, rows, members, frames, tactic, tactic_source, core_targets)
70      res = rl.assess(inp, {}, {}, coef)                                          # T 를 모두 넘기므로 lookup 은 비워도 됨
```
→ 입력으로 바꿔 판정합니다. 모든 차량에 T 가 있으므로 사전 lookup 은 빈 표(`{}`)로 넘깁니다.

```python
71      return dict(from_assess_output(dict(res, core_targets=inp["core_targets"])), _assess_input=inp, _assess_result=res)
```
→ 화면 Cluster 를 돌려주되, 판정 기록 저장(`dashboard/__init__.py` `_attach`)에 쓰려고 입력·결과를 `_assess_input`·`_assess_result` 로 붙입니다. 이 두 필드는 API 응답으로 나가기 전에 지웁니다.

### 함수 `cluster_response_level(cluster, coef)` — 예전 호출 형식 호환 (adapter.py:74~83)

```python
77      dets, threats = cluster["detections"], cluster.get("threats", [])
78      rows = [{"tracking_id": d.get("tracking_id") or f"#{i}", "status": "Unknown" if is_unknown(d) else "Known",
79               "category": d.get("category"), "model": d.get("model"), "is_commander": d.get("is_commander", False),
80               "confidence": d.get("confidence"), "threat": threats[i] if i < len(threats) else None}
81              for i, d in enumerate(dets)]
```
→ 예전 형식 `{"detections": [...], "threats": [...]}` 를 표적 행으로 바꿉니다. i번째 위협도는 i번째 탐지의 것이고, 모자라면 점수 없음.

```python
82      out = assess_cluster("C", rows, dets, None, infer_tactic(dets), "시스템 추정", [], coef or load_coef())
83      return {k: v for k, v in out.items() if not k.startswith("_")}
```
→ 같은 판정 엔진으로 판정하고 내부 필드를 빼서 돌려줍니다. 지금은 v1 테스트(`dashboard/tests/test_threat.py`)가 씁니다.

