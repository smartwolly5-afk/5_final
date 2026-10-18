# core.py — 위협도 계산 단계별 함수

파일: `dashboard/threat/core.py` (전체 136줄)

전차 1대 위협도와 **군집 대응단계**(같이 움직이는 전차 무리에 대해 1~4단계로 대응 수준을 정한 것)를 계산하는 **순수 계산 함수** 모음입니다.
'순수'란 Flask(웹 서버)·DB 를 전혀 모르고, 입력을 받아 결과만 돌려준다는 뜻입니다. 그래서 테스트하기 쉽습니다.

- v1 입력(기존 mock): 제원은 `tank_specs.json`(4종)에서 읽고 이 파일의 `quant_score`·`tank_threat` 로 점수를 냅니다.
- v2 입력(모델 연동): 전차 점수는 `judge.py` 가 사전 DB 값으로 내고, 이 파일에서는 **제대·전술·대응단계** 함수만 씁니다.
- 계산 순서: `classify_echelon` → `infer_tactic` → `quant_score` → `tank_threat` → `threat_grade` → `cluster_response_level`

### 파일 머리말 — 입력 형식 (core.py:1~13)

```python
  1  """위협도 산출 단계별 함수 (순수 계산 — Flask·DB 의존 없음, 화면 코드와 분리).
  3  탐지 결과 1건(dict) 형식:
  4    {"tracking_id": "Tank-03",                       # 추적 ID (영상 안에서 고유)
  5     "category": "전차"|"기갑차"|"포병"|"인원"|"미확인",  # 분류
  6     "model": "T-90M" 또는 None,                      # 기종명 (tank_specs.json 키와 맞으면 제원 조회)
  7     "confidence": 0.93,                              # 탐지 신뢰도 0~1
  8     "bbox": {"x", "y", "w", "h"},                    # 화면 기준 % 좌표
  9     "is_commander": false,                           # 지휘전차 여부
 10     "cluster_id": "C-1"}                             # 군집 ID (없으면 C-1)
 12  계산 순서: classify_echelon → infer_tactic → quant_score → tank_threat → threat_grade → cluster_response_level
 13  """
```
→ docstring 으로 탐지 결과 1건의 모양을 적어 두었습니다. `bbox` 는 화면 크기 대비 **%** 좌표입니다 (v2 는 `track.py` 가 픽셀 → % 로 바꿔서 넘깁니다).

### import 와 기본 표 (core.py:14~42)

```python
 14  import json                    # tank_specs.json 읽기
 15  from enum import IntEnum       # 전술 번호를 이름 있는 정수로
 16  from pathlib import Path       # 이 파일 옆의 JSON 경로 계산
 18  from . import config as C      # 가중치·경계값 (config.py)
```
→ **import**(다른 모듈 기능 가져오기). `from . import config as C` 의 `.` 은 '같은 폴더(threat 패키지)'라는 뜻이고, `as C` 는 줄여 부르는 이름입니다. 이후 `C.ECHELONS` 처럼 씁니다.

```python
 20  CATEGORIES = ("전차", "기갑차", "포병", "인원", "미확인")  # 입력 검증에 쓰는 허용 분류
```
→ 입력에 허용하는 분류 5가지. `pipeline.py:84`·`track.py` 입력 검사에 씁니다.

```python
 21  SPECS = {k: v for k, v in                                   # 기종명 → 제원 dict
 22           json.loads(Path(__file__).with_name("tank_specs.json").read_text(encoding="utf-8")).items()
 23           if not k.startswith("_")}                          # "_note" 같은 설명 키는 제외
```
→ **딕셔너리 컴프리헨션**(`{k: v for ... if ...}`, 반복문으로 딕셔너리를 한 줄에 만드는 문법). `tank_specs.json` 을 읽어 `"_note"` 처럼 `_` 로 시작하는 설명 키는 빼고 `기종명 → 제원` 표를 만듭니다. (v1 전용)

```python
 26  class Tactic(IntEnum):
 27      """11개 전술 기능 번호. infer_tactic 은 1·10번만 자동 추정하고, 나머지는 화면의 '전술 선택'으로 지정한다."""
 28      MANEUVER = 1         # 기동·직접전투
 29      TRANSPORT = 2        # 병력수송·지원
 30      ANTI_TANK = 3        # 대전차
 31      INDIRECT_FIRE = 4    # 간접화력
 32      LONG_RANGE_FIRE = 5  # 장거리화력
 33      AIR_DEFENSE = 6      # 방공
 34      RECON = 7            # 정찰·표적획득
 35      ENGINEER = 8         # 공병
 36      CBRN = 9             # CBRN·연막차폐
 37      COMMAND = 10         # 지휘통제
 38      SUSTAINMENT = 11     # 전투근무지원 (화력 0 → 전차에는 쓰지 않음, 가중치 없음)
```
→ `class Tactic(IntEnum)`: **IntEnum**(이름이 붙은 정수). `Tactic.COMMAND` 는 숫자 10 과 같게 취급되면서 이름으로 읽혀 코드가 읽기 쉬워집니다. 11가지 전술 기능 번호입니다.

```python
 41  TACTIC_NAMES = {1: "기동·직접전투", 2: "병력수송·지원", 3: "대전차", 4: "간접화력", 5: "장거리화력", 6: "방공",  # 화면 표시용 이름
 42                  7: "정찰·표적획득", 8: "공병", 9: "CBRN·연막차폐", 10: "지휘통제", 11: "전투근무지원"}
```
→ 화면에 보여 줄 전술 이름. 예: `TACTIC_NAMES[10]` → '지휘통제'.

### 함수 `spec_of(det)` — 제원 찾기 (v1) (core.py:45~47)

이 부분이 하는 일: 탐지 1건이 전차이고 기종명이 `tank_specs.json` 에 있으면 그 제원을 돌려줍니다. 아니면 `None`(값 없음).

```python
 45  def spec_of(det):
 46      """전차이고 기종이 제원표에 있으면 제원 dict, 아니면 None."""
 47      return SPECS.get(det.get("model")) if det.get("category") == "전차" else None  # 전차가 아니면 제원 조회 안 함
```
→ `A if 조건 else B` 는 **조건 표현식**(한 줄 if). `dict.get(키)` 는 키가 없으면 오류 대신 `None` 을 돌려줍니다.

### 함수 `is_unknown(det)` — 미확인 표적인지 (core.py:50~54)

이 부분이 하는 일: v2 입력은 판정 결과(`status`)가 'Unknown' 인지로, v1 입력은 '분류가 미확인이거나 제원표에 없는 전차'인지로 판단합니다.

```python
 52      if det.get("status"):                                    # v2: Known / Known_Variant / Unknown (judge.py)
 53          return det["status"] == "Unknown"
```
→ v2 표적에는 `status` 가 있으므로 그 값을 따릅니다. Known_Variant(계열만 확정)는 미확인으로 치지 않습니다.

```python
 54      return det.get("category") == "미확인" or (det.get("category") == "전차" and spec_of(det) is None)
```
→ v1: 분류가 '미확인'이거나, 전차인데 제원이 없으면 미확인. 이 결과는 대응단계 하한 규칙(`core.py:128`)과 근거 태그에 쓰입니다.

### 함수 `classify_echelon(detections)` — 제대 판정 (core.py:57~63)

이 부분이 하는 일: 군집 안 전차+기갑차 대수를 세어 소대(×1)·중대(×2)·대대(×3)를 정합니다.

```python
 59      n = sum(d.get("category") in C.ECHELON_CATEGORIES for d in detections)  # 전차·기갑차만 셈 (True=1)
```
→ `sum(조건 for d in ...)`: 파이썬에서 `True` 는 1, `False` 는 0 이라 조건을 만족하는 개수가 됩니다. 포병·인원·미확인은 세지 않습니다.

```python
 60      for lo, weight, name in C.ECHELONS:   # 대대(16) → 중대(5) → 소대(1) 순서로 검사
 61          if n >= lo:                        # 최소 대수 이상이면 그 제대
 62              return {"n": n, "weight": weight, "name": name}
```
→ `ECHELONS` 를 큰 제대부터 보며 최소 대수 이상인 첫 제대를 돌려줍니다. 예: 샘플 영상 A 는 전차 2대(UNK-001 은 '미확인' 분류라 제외) → 소대, 가중치 1.

```python
 63      return {"n": 0, "weight": 0, "name": "없음"}  # 전투차량이 없으면 가중치 0 → 군집점수 0
```
→ 전투차량이 0대면 가중치 0 → 군집점수도 0.

### 함수 `infer_tactic(detections)` — 군집 전술 자동 추정 (core.py:66~69)

이 부분이 하는 일: 전차 중 지휘전차가 하나라도 있으면 ⑩지휘통제, 없으면 ①기동·직접전투로 추정합니다. 다른 전술(2~9번)은 지휘관이 화면에서 고릅니다.

```python
 68      tanks = [d for d in detections if d.get("category") == "전차"]                   # 전차만 추림
```
→ **리스트 컴프리헨션**(`[d for d in ... if ...]`, 조건에 맞는 것만 골라 새 리스트 만들기)으로 전차만 추립니다.

```python
 69      return Tactic.COMMAND if any(d.get("is_commander") for d in tanks) else Tactic.MANEUVER
```
→ `any(...)`: 하나라도 참이면 True. 샘플 영상 A 는 Tank-01 이 지휘전차라 군집 C-1 전술이 ⑩지휘통제가 됩니다.

### 함수 `_firepower(s)` / `quant_score(spec, base)` — 정량 점수 (v1) (core.py:72~88)

이 부분이 하는 일: `tank_specs.json` 제원으로 화력·기동력·방호력을 기준전차(M1A1)=100 으로 환산합니다. v2(사전 DB) 경로는 이 함수 대신 DB 의 f·m·p 를 씁니다(`judge.py:88`).

```python
 72  def _firepower(s):
 73      """화력 원점수 = 구경 × 구경장^지수 (기준전차로 나누기 전 값)."""
 74      return s["caliber_mm"] * s["gun_length"] ** C.GUN_LENGTH_EXP
```
→ 화력 원점수 = 구경 × 구경장^0.5. 함수 이름 앞 `_` 는 '이 파일 안에서만 쓰는 도우미'라는 관례입니다.

```python
 80      b = base or SPECS[C.BASE_MODEL]                                   # 비교 기준 제원 (기본 M1A1)
```
→ `base or SPECS[...]`: base 를 안 주면(None) 기준전차 M1A1 제원을 씁니다.

```python
 81      fire = _firepower(spec) / _firepower(b)                           # 화력 비율
 82      mob = spec["pw"] / b["pw"]                                        # 기동력 비율 = 출력대중량비 비
 83      prot = ((spec["ke"] / b["ke"] + spec["ce"] / b["ce"]) / 2         # 방호력 = KE·CE 정면방호 비율의 평균
 84              * (b["height"] / spec["height"]) ** C.HEIGHT_EXP)         #        × 차체 높이 보정
```
→ 화력 비율, 기동력 비율(출력대중량비 비), 방호력 = (운동에너지탄 방호 비 + 화학에너지탄 방호 비)/2 × (기준높이/높이)^0.5. 예: T-90M → 화력 108.8, 기동 89.4, 방호 96.5 (`dashboard/tests/test_threat.py:45` 의 기대값).

```python
 85      w = C.QUANT_WEIGHTS                                               # 종합 점수 가중치 (0.5/0.3/0.2)
 86      total = fire * w["firepower"] + mob * w["mobility"] + prot * w["protection"]  # MPI 종합 (참고값)
 87      return {k: round(v * 100, 1) for k, v in                          # 비율 × 100, 소수 1자리
 88              (("firepower", fire), ("mobility", mob), ("protection", prot), ("total", total))}
```
→ 참고용 종합점수(MPI)도 계산하고, 모든 비율을 ×100 해 소수 1자리로 반올림한 딕셔너리를 돌려줍니다.

### 함수 `tactic_weights(tactic, is_commander)` — 적용할 가중치 (core.py:91~96)

이 부분이 하는 일: 실제로 적용한 전술과 (화력, 기동, 방호) 가중치를 돌려줍니다. 지휘전차는 군집 전술과 상관없이 ⑩지휘통제 가중치를 씁니다.

```python
 93      t = Tactic.COMMAND if is_commander else Tactic(tactic)   # 지휘전차면 전술 무시하고 지휘통제
```
→ 지휘전차면 `Tactic.COMMAND`(10), 아니면 받은 번호를 `Tactic` 으로 바꿉니다.

```python
 94      if t not in C.TACTIC_WEIGHTS:                             # 11번 등 가중치 없는 전술
 95          raise ValueError(f"가중치 미정 전술: {TACTIC_NAMES[t]}")
 96      return t, C.TACTIC_WEIGHTS[t]
```
→ 가중치가 없는 전술(11번)이면 **예외**(`raise ValueError`, 오류를 일으켜 위로 알림)를 냅니다. API 는 이것을 400 오류로 바꿉니다.

### 함수 `tank_threat(spec, tactic, is_commander)` — 전차 1대 위협도 (v1) (core.py:99~103)

이 부분이 하는 일: T = (w_F×화력 + w_M×기동 + w_P×방호) / (w_F + w_M + w_P). 가중치 합으로 나누므로 합이 0.99 인 전술도 100 기준이 유지됩니다.

```python
101      _, (wf, wm, wp) = tactic_weights(tactic, is_commander)    # 전술별 가중치
102      q = quant_score(spec)                                     # 화력·기동·방호 (100 기준)
103      return round((wf * q["firepower"] + wm * q["mobility"] + wp * q["protection"]) / (wf + wm + wp), 1)  # 합으로 나눠 정규화
```
→ `_, (wf, wm, wp) = ...`: 돌려받은 두 값 중 첫 번째(전술)는 버리고(`_`), 두 번째 튜플을 세 변수로 풉니다(**언패킹**).

### 함수 `threat_grade(score)` — 위협도 단계 이름 (core.py:106~110)

```python
108      if score is None:                                         # 미확인·제원 없음 → 단계 없음
109          return None
110      return next(name for lo, name in C.THREAT_GRADES if score >= lo)  # 위에서부터 처음 만족하는 구간
```
→ 점수가 없으면 None. 있으면 `THREAT_GRADES` 를 위에서부터 보며 처음 만족하는 이름. `next(...)` 는 '조건에 맞는 첫 번째 값'을 꺼냅니다. 예: 88.9 → '높음'.

### 함수 `cluster_response_level(cluster)` — 군집 대응단계 (core.py:113~136)

이 부분이 하는 일: 군집점수 S = 군집 최고 위협도 × 제대가중치 → 225/150/75 경계로 1~4단계. 4단계로 나왔더라도 미확인이 있거나 위협도 75 이상 전차가 있으면 3단계로 올립니다(하한).

```python
117      dets = cluster["detections"]                                               # 군집에 속한 모든 탐지
118      threats = [t for t in cluster.get("threats", []) if t is not None]        # 점수가 있는 전차만
119      ech = classify_echelon(dets)                                               # 제대 (소대·중대·대대)
120      t_cluster = max(threats, default=0.0)                                      # 군집 위협도 = 가장 위험한 전차 점수
```
→ 점수가 있는 위협도만 모아 제대를 구하고, 그중 최댓값을 군집 위협도로 씁니다 (평균이 아니라 **가장 위험한 1대** 기준).

```python
121      score = round(t_cluster * ech["weight"], 1)                                # 군집점수 = 군집 위협도 × 제대가중치
122      level = next((lv for th, lv in C.LEVEL_THRESHOLDS if score >= th), 4)      # 225/150/75 경계로 1~3단계, 미만은 4단계
```
→ S = 최고 위협도 × 제대가중치. 예: 영상 A → 88.9 × 1 = 88.9 → 75 이상이라 **3단계**.

```python
124      reasons = [f"{ech['name']}급 {ech['n']}대 ×{ech['weight']}" if ech["n"] else "전투차량 없음",  # 근거 1: 제대
125                 f"군집점수 {score:g} = 최고 위협도 {t_cluster:g} × {ech['weight']} → {level}단계"]    # 근거 2: 점수 판정
```
→ 판정 근거 문장 2개 (화면 군집 카드 아래 회색 글씨).

```python
126      if level == 4:                                                             # 하한 규칙은 4단계일 때만 의미 있음
127          floors = []                                                            # 적용된 하한 규칙
128          if any(is_unknown(d) for d in dets):                                   # 미확인 표적이 있으면
129              floors.append("미확인 포함 → 4단계 불가")
130          if any(t >= C.FLOOR_TANK_THREAT for t in threats):                     # 위협도 75 이상 전차가 있으면
131              floors.append(f"위협도 {C.FLOOR_TANK_THREAT} 이상 전차 → 4단계 불가")
132          if floors:                                                             # 하나라도 해당하면
133              level = 3                                                          # 3단계로 올림
134              reasons += floors                                                  # 근거에 하한 규칙 추가
```
→ 하한 규칙은 4단계일 때만 의미가 있어서 그때만 검사합니다. 해당하면 3단계로 올리고 근거에 이유를 덧붙입니다.

```python
135      return {"level": level, "label": C.LEVELS[level], "score": score, "t_cluster": t_cluster,
136              "echelon": ech, "reasons": reasons}
```
→ 결과 딕셔너리. `pipeline.py:216` 이 이 값을 군집(Cluster) 응답으로 씁니다.

