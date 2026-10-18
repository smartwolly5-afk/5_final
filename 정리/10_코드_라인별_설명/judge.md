# judge.py — Known / Known_Variant / Unknown 판정과 위협도

파일: `dashboard/threat/judge.py` (전체 109줄)

트랙의 평균 분류 점수로 **기종을 얼마나 확신하는지** 판정하고, 그 결과에 맞는 위협도를 사전 DB 에서 가져옵니다.

| 상태 | 뜻 | 위협도 출처 |
|---|---|---|
| Known | 기종까지 확정 | 그 기종의 사전 F·M·P 를 전술 가중 평균 |
| Known_Variant | 계열(예: T-72 계열)만 확정 | 그 계열 기종들의 **상위 25%** 값 |
| Unknown | 모름 | 추정 계열 상위 25% → (표본 부족 시) 유형 상위 25% → 주력전차 상위 25% |

상위 25%(p75) = 값을 작은 순으로 줄 세웠을 때 75% 지점. '모르면 위험한 쪽으로 본다'는 보수적 기준입니다.

### import 와 라벨 매핑 읽기 (judge.py:9~18)

```python
  9  import json
 10  import logging
 11  from pathlib import Path
 13  from . import config as C
 14  from . import dictdb
 15  from .core import tactic_weights
```
→ `dictdb` 는 사전 위협도 DB 조회 모듈, `tactic_weights` 는 전술 가중치 함수(`core.py:91`).

```python
 17  LABELS = json.loads(Path(__file__).with_name("label_map.json").read_text(encoding="utf-8"))["labels"]
```
→ `label_map.json` 을 읽어 '분류 라벨 → tank_id 또는 계열' 표를 만듭니다. 모델 팀의 실제 클래스 목록이 오면 이 파일을 바꿉니다 (**현재는 샘플 라벨 12개만 있음**).

```python
 18  log = logging.getLogger(__name__)
```
→ **logging**(실행 기록 남기기). 매핑에 없는 라벨 같은 경고를 서버 로그에 남깁니다.

### 함수 `resolve(label)` — 라벨 → 사전 정보 (judge.py:21~33)

```python
 23      m = LABELS.get(label)
 24      if m is None:
 25          log.warning("label_map.json 에 없는 분류 라벨 → Unknown 처리: %s", label)
 26          return None
```
→ 매핑에 없는 라벨은 경고를 남기고 None → 그 후보는 판정에서 무시(결과적으로 Unknown 쪽으로).

```python
 27      if "tank_id" in m:
 28          row = dictdb.tank(m["tank_id"])
 29          if row is None:
 30              log.warning("사전에 없는 tank_id: %s (라벨 %s)", m["tank_id"], label)
 31              return {"tank_id": None, "family": None, "name": None}
 32          return {"tank_id": row["tank_id"], "family": row["family_name"], "name": row["canonical_name"]}
```
→ tank_id 라벨이면 사전 DB 에서 그 행을 찾아 **사전의 계열**을 씁니다. 샘플 JSON 에 TANK_0230 이 'T-72' 로 적혀 있어도 사전 값 'T-90' 을 따릅니다.

```python
 33      return {"tank_id": None, "family": m.get("family"), "name": None}
```
→ 계열 라벨이면 계열만 돌려줍니다.

### 함수 `judge(track)` — 상태 판정 (judge.py:36~62)

이 부분이 하는 일: 1위 점수 s1, 1·2위 차이 margin, 계열별 점수 합을 구해 위 표의 순서대로 판정합니다.

```python
 38      top = track["top_k"]
 39      res = [(k, resolve(k["label"])) for k in top]
 40      s1 = top[0]["score"] if top else 0.0
 41      margin = s1 - (top[1]["score"] if len(top) > 1 else 0.0)
```
→ s1 = 1위 점수, margin = 1위 − 2위. 후보가 1개뿐이면 2위를 0 으로 봅니다.

```python
 42      fam_sum = {}
 43      for k, r in res:
 44          if r and r["family"]:
 45              fam_sum[r["family"]] = fam_sum.get(r["family"], 0.0) + k["score"]
 46      family, fam_score = max(fam_sum.items(), key=lambda x: x[1], default=(None, 0.0))
```
→ 같은 계열 후보 점수를 더합니다. `max(..., key=lambda x: x[1])` 은 합이 가장 큰 계열. 예: Tank-02 → T-72: 0.41 + 0.368 = 0.78.

```python
 47      notes = [f"{k['label']}: 샘플 family {k['family_json']} ≠ 사전 {r['family']}"            # 라벨 임시값과 사전 불일치
 48               for k, r in res if r and r["family"] and k.get("family_json") and k["family_json"] != r["family"]]
```
→ 샘플 JSON 의 계열과 사전 계열이 다르면 메모를 남깁니다 (판정에는 사전 값을 씀).

```python
 50      top1 = res[0][1] if res else None
 51      if top1 and top1["tank_id"] and s1 >= C.KNOWN_SCORE and margin >= C.KNOWN_MARGIN:
 52          row = dictdb.tank(top1["tank_id"])
 53          return {"status": "Known", "tank_id": row["tank_id"], "name": row["canonical_name"], "family": row["family_name"],
 54                  "type_group": row["type_group"] or C.DEFAULT_TYPE_GROUP, "label_notes": notes,
 55                  "evidence": f"분류 {row['canonical_name']} {s1:.2f} (2위와 차이 {margin:.2f}) → Known"}
```
→ **Known**: 1위가 사전에 있는 기종이고 s1 ≥ 0.6, margin ≥ 0.2. 예: Tank-01 → 0.884, 차이 0.826 → Known(T-90).

```python
 56      if family and fam_score >= C.FAMILY_SCORE:
 57          return {"status": "Known_Variant", "tank_id": None, "name": None, "family": family,
 58                  "type_group": dictdb.family_type_group(family) or C.DEFAULT_TYPE_GROUP, "label_notes": notes,
 59                  "evidence": f"{family} 계열 점수 합 {fam_score:.2f} (기종 1·2위 차이 {margin:.2f}) → 계열만 확정"}
```
→ **Known_Variant**: 계열 합 ≥ 0.6. 예: Tank-02 → 1·2위 차이 0.042 로 기종은 못 정하지만 T-72 합 0.78 → 계열 확정.

```python
 60      return {"status": "Unknown", "tank_id": None, "name": None, "family": family,
 61              "type_group": (dictdb.family_type_group(family) if family else None) or C.DEFAULT_TYPE_GROUP,
 62              "label_notes": notes, "evidence": f"분류 불확실 (1위 {s1:.2f}) → 미확인" + (f", 추정 계열 {family}" if family else "")}
```
→ **Unknown**: 나머지. 추정 계열(합이 가장 큰 계열)은 기록합니다. 예: UNK-001 → s1 0.222 → 미확인, 추정 계열 T-90.

### 함수 `_group_p75(j, k)` — 대체 위협도 고르기 (judge.py:65~78)

이 부분이 하는 일: 계열 상위 25% → (계열 표본 3개 미만이면) 유형 상위 25% → 주력전차 상위 25% 순으로 찾습니다. (값, 방호력 p75, 근거 문장)을 돌려줍니다.

```python
 67      if j["family"]:
 68          st = dictdb.family_stats(j["family"], k)
 69          if st["n"] >= C.FAMILY_MIN_N:
 70              return st["t"], st["p"], f"{j['family']} 계열 상위25%"
```
→ 계열 통계(`dictdb.family_stats`). 표본이 3개 이상이면 계열 값을 씁니다. 예: T-72 계열 6종, 전술 10 → 85.6.

```python
 71          short = f"{j['family']} 계열 표본 {st['n']} < {C.FAMILY_MIN_N}"
 72      else:
 73          short = "계열 추정 불가"
```
→ 표본이 부족하면 이유를 적어 둡니다. 예: T-90 계열은 사전에 2종뿐 → 'T-90 계열 표본 2 < 3'.

```python
 74      for tg in dict.fromkeys([j["type_group"], C.DEFAULT_TYPE_GROUP]):     # 유형 → 주력전차 순
 75          t = dictdb.type_p75(tg, k)
 76          if t is not None:
 77              return round(t, 1), None, f"{tg} 상위25% ({short})"
```
→ `dict.fromkeys([...])` 는 순서를 지키며 중복을 없애는 요령입니다(유형이 이미 주력전차면 한 번만 봄). 예: UNK-001 → 주력전차 상위25%(전술 10) = 88.93 → 88.9.

```python
 78      return None, None, f"대체값 없음 ({short})"
```
→ 어디에도 값이 없으면 None (화면에 '산출 불가').

### 함수 `threat_of(j, tactic, is_commander, cope_cage)` — 전차 1대 위협도 (judge.py:81~109)

이 부분이 하는 일: 판정 결과와 전술로 위협도 T 와 보정 전 값, 화면용 점수·근거를 만듭니다. `pipeline.py:201` 이 표적마다 부릅니다.

```python
 83      used, (wf, wm, wp) = tactic_weights(tactic, is_commander)
 84      k, wsum = int(used), wf + wm + wp
 85      weights = {"firepower": wf, "mobility": wm, "protection": wp}
```
→ 적용 전술과 가중치. 지휘전차면 10번(`core.py:93`). wsum = 가중치 합(10번은 0.99).

```python
 86      row = dictdb.tank(j["tank_id"]) if j["status"] == "Known" else None
 87      scores = None
```
→ Known 이면 사전 행을 꺼냅니다.

```python
 88      if row and row["computable"]:                                         # Known: 사전 f·m·p 로 직접 계산
 89          f, m, p = (row[a] * 100 for a in "fmp")
 90          before = round((wf * f + wm * m + wp * p) / wsum, 1)
 91          p_after = p * C.COPE_CAGE_PROTECTION_MULT if cope_cage else p
 92          after = round((wf * f + wm * m + wp * p_after) / wsum, 1)
```
→ **Known 계산**: F·M·P(사전 값 ×100)로 T = (wF·F + wM·M + wP·P)/wsum. cope cage 가 있으면 P 에 ×1.10 한 뒤 다시 계산. 예: Tank-11(T-80, 전술 1) → (0.45×81.6 + 0.35×90.8 + 0.20×73.9)/1.00 = 83.3.

```python
 93          q = C.QUANT_WEIGHTS
 94          scores = {"firepower": round(f, 1), "mobility": round(m, 1), "protection": round(p_after, 1),
 95                    "total": round(f * q["firepower"] + m * q["mobility"] + p_after * q["protection"], 1)}
 96          source, cope_tag = f"사전 {row['canonical_name']}", (f"cope cage → 방호 ×{C.COPE_CAGE_PROTECTION_MULT:.2f}"
 97                                                               if cope_cage else None)
```
→ 상세 패널 막대용 점수와 근거 문장('사전 T-80'), cope cage 태그.

```python
 98      else:                                                                 # 변형·미확인·제원 결측: 상위 25% 대체
 99          before, p_p75, source = _group_p75(j, k)
100          if row:
101              source = f"{row['canonical_name']} 제원 결측 → " + source
```
→ **대체 계산**: Known_Variant·Unknown·구경 결측 Known 은 `_group_p75` 값. 결측 Known 이면 근거 앞에 '제원 결측'을 붙입니다.

```python
102          after, cope_tag = before, None
103          if cope_cage and before is not None and p_p75 is not None:        # T 가 스칼라라 P 만 떼어 보정
104              after = round(before + wp / wsum * p_p75 * (C.COPE_CAGE_PROTECTION_MULT - 1), 1)
105              cope_tag = f"cope cage → 방호 ×{C.COPE_CAGE_PROTECTION_MULT:.2f}"
```
→ cope cage 보정: T 는 이미 합쳐진 한 숫자라 방호 몫만 떼어 더합니다. ΔT = (wP/wsum) × 방호 p75 × 0.10. 예: Tank-02(T-72 계열, 전술 10) → 85.6 + 0.37/0.99 × 83.7 × 0.10 = 85.6 + 3.1 = 88.7.

```python
106          elif cope_cage:
107              cope_tag = "cope cage 탐지 (방호 보정값 없음)"
```
→ 방호 p75 가 없으면(유형 값으로 대체한 경우) 보정하지 않고 태그로만 알립니다.

```python
108      return {"threat": after, "threat_before_bonus": before, "scores": scores, "weights": weights,
109              "tactic": used, "source": source, "cope_tag": cope_tag}
```
→ 보정 후 T(threat), 보정 전 T(threat_before_bonus), 막대 점수, 가중치, 실제 전술, 근거, cope 태그.

