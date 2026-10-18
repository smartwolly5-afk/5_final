# unknown_registry.py — 미확인 전차 레지스트리 (영상 간 그룹화·순위)

파일: `dashboard/unknown_registry.py` (전체 226줄)

**레지스트리**(등록부): 미확인(Unknown) 전차를 DB 에 계속 쌓아 두는 곳입니다. 영상이 달라도 **같은 미확인 기종으로 보이면 한 그룹**으로 묶고,
자주·여러 영상에서·최근에 나온 위험한 그룹이 위로 오도록 순위를 매깁니다. 분석관은 `/unknowns` 화면에서 이 순위를 봅니다.

- '같은 기종으로 보인다' = **임베딩**(사진을 숫자 벡터로 바꾼 것)의 **코사인 유사도**(두 벡터 방향이 얼마나 비슷한지, 1에 가까울수록 비슷함)가 0.85 이상
- **centroid**(중심): 그룹에 속한 임베딩들의 평균. 새 표적은 각 그룹의 centroid 와 비교합니다.
- 테이블: `unknown_group`(그룹), `unknown_sighting`(출현 1건 = 트랙 1개), `unknown_crop`(잘라 둔 사진), `unknown_action`(분석관 조치 — **아직 쓰는 코드 없음, TODO**)
- **아직 없는 기능 (TODO)**: 확정·병합·기각 API 와 버튼. `_live` 함수는 병합된 그룹을 따라가는 준비만 되어 있습니다.

샘플 결과: 영상 A 의 UNK-001 → 새 그룹 UNK-G0001, 영상 B 의 UNK-007 → 유사도 0.9646 ≥ 0.85 → 같은 그룹. 트랙 2, 영상 2, 순위 점수 277.5.

### import 와 DB 모듈 연결 (unknown_registry.py:11~29)

```python
 11  import json
 12  import logging
 13  import math
 14  import sys
 15  from datetime import datetime, timedelta
 16  from pathlib import Path
 18  import numpy as np
 20  from . import media
 21  from .threat import config as C
```
→ `numpy`(np): 벡터·행렬 계산 라이브러리. 유사도 계산에 씁니다.

```python
 23  ROOT = Path(__file__).resolve().parents[1]
 24  if str(ROOT) not in sys.path:
 25      sys.path.insert(0, str(ROOT))
 26  import threat_db as tdb  # noqa: E402
```
→ 저장소 루트의 `threat_db.py`(MySQL/SQLite 공통 DB 접근)를 가져오려고 루트 폴더를 import 경로에 넣습니다.

```python
 28  log = logging.getLogger(__name__)
```
→ 로그 도구.

```python
 29  ensure_schema = tdb.ensure_schema   # 레지스트리 테이블이 없으면 만든다 (threat_db 한 곳에서 관리)
```
→ `ensure_schema` = 테이블이 없으면 만드는 함수. 판정 기록과 같은 `threat_db.ensure_schema` 를 그대로 씁니다 (DB 연결 대상마다 처음 한 번만 `schema_threat.sql` 실행). `global` 같은 별도 표시가 필요 없도록 한 곳에서 관리합니다.

### 함수 `_now`, `_when`, `_unit` — 시간·벡터 도우미 (unknown_registry.py:32~49)

```python
 32  def _now():
 33      return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```
→ 지금 시각 문자열 'YYYY-MM-DD HH:MM:SS'.

```python
 36  def _when(captured_at):
 37      """source.captured_at ('2024-03-15' 또는 '2024-03-15 10:20:00') → DATETIME 문자열. 못 읽으면 지금."""
 38      for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
 39          try:
 40              return datetime.strptime(str(captured_at)[:n], fmt).strftime("%Y-%m-%d %H:%M:%S")
 41          except ValueError:
 42              continue
 43      return _now()
```
→ 영상 촬영일(`captured_at`)을 DB 날짜 형식으로. 세 가지 형식을 차례로 시도하고, 다 실패하면 지금 시각.

```python
 46  def _unit(v):
 47      a = np.asarray(v, dtype=float)
 48      n = np.linalg.norm(a)
 49      return a / n if n else a
```
→ 벡터를 길이 1로 맞춤(L2 정규화). 길이가 0 이면 그대로.

### 함수 `priority(g, today)` — 순위 점수 (unknown_registry.py:52~59)

이 부분이 하는 일: 순위 점수 = 최고 위협도 × (1 + 0.5 × ln(1 + 트랙 수)) × (1 + 0.5 × (영상 수 − 1)), 최근 7일 안에 나왔으면 × 1.2.

```python
 54      p = (g["max_threat"] or 0) * (1 + C.PRIORITY_FREQ_K * math.log(1 + (g["n_tracks"] or 0))) \
 55          * (1 + C.PRIORITY_VIDEO_K * max((g["n_videos"] or 1) - 1, 0))
```
→ 위협도가 높을수록, 여러 번(트랙 수) 그리고 여러 영상에서 나올수록 점수가 오릅니다. log 를 쓴 이유: 트랙이 아주 많아져도 점수가 한없이 커지지 않게.

```python
 56      last = g.get("last_seen")
 57      if last and datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S") >= (today or datetime.now()) - timedelta(days=C.RECENT_DAYS):
 58          p *= C.RECENT_BOOST
 59      return round(p, 1)
```
→ 마지막 출현이 최근 7일 안이면 ×1.2. 예: UNK-G0001 → 99.5 × (1 + 0.5×ln3) × 1.5 × 1.2 = 277.5.

### 함수 `_group`, `_live`, `_new_group_id` — 그룹 찾기·번호 (unknown_registry.py:62~79)

```python
 62  def _group(gid):
 63      rows = tdb.query("SELECT * FROM unknown_group WHERE group_id = %s", (gid,))
 64      return rows[0] if rows else None
```
→ 그룹 1행 읽기.

```python
 67  def _live(gid):
 68      """병합된 그룹이면 병합 대상 그룹으로 따라간다."""
 69      seen = set()
 70      g = _group(gid)
 71      while g and g["status"] == "merged" and g["merged_into"] and g["group_id"] not in seen:
 72          seen.add(g["group_id"])
 73          g = _group(g["merged_into"])
 74      return g
```
→ 병합된 그룹이면 병합 대상 그룹으로 따라갑니다(같은 그룹을 두 번 보면 멈춤). **병합 기능 자체는 아직 없음(TODO)**.

```python
 77  def _new_group_id():
 78      n = tdb.query("SELECT COUNT(*) AS n FROM unknown_group")[0]["n"]
 79      return f"UNK-G{n + 1:04d}"
```
→ 그룹 수 + 1 로 'UNK-G0001' 형식 번호를 만듭니다. `:04d` 는 4자리로 앞을 0 으로 채움. 서버 1대 가정(동시에 두 분석이 돌면 번호가 겹칠 수 있음 — 한계).

### 함수 `_match(emb)` — 비슷한 그룹 찾기 (unknown_registry.py:82~96)

이 부분이 하는 일: 새 미확인 표적의 임베딩을 열린(open)·확정(confirmed) 그룹들의 centroid 와 한꺼번에 비교합니다.

```python
 84      groups = [g for g in tdb.query("SELECT group_id, centroid FROM unknown_group WHERE status IN ('open', 'confirmed')")
 85                if g["centroid"]]
 86      if not groups:
 87          return None, None, []
```
→ 비교할 그룹이 없으면 (None, None, []).

```python
 88      mat = np.array([_unit(json.loads(g["centroid"])) for g in groups])
 89      sims = mat @ _unit(emb)
 90      order = np.argsort(-sims)
 91      best = order[0]
```
→ 모든 centroid 를 행렬로 쌓고 `mat @ 벡터`(**행렬 곱**)로 유사도를 한 번에 구합니다. 길이 1 벡터끼리의 곱 = 코사인 유사도. 높은 순으로 정렬.

```python
 92      if sims[best] >= C.GROUP_SIM_MIN:
 93          return groups[best]["group_id"], round(float(sims[best]), 4), []
```
→ 최고 유사도 ≥ 0.85 → 그 그룹.

```python
 94      review = [{"group_id": groups[i]["group_id"], "similarity": round(float(sims[i]), 4)}
 95                for i in order if sims[i] >= C.GROUP_SIM_REVIEW]
 96      return None, None, review
```
→ 아니면 새 그룹. 0.75 이상인 그룹들은 '병합 후보'로 넘깁니다(분석관 검토용).

### 함수 `_refresh(gid, today)` — 그룹 집계 다시 계산 (unknown_registry.py:99~113)

이 부분이 하는 일: 그룹의 출현 기록(sighting) 전체로 트랙 수·영상 수·최고 위협도·centroid·처음/마지막 출현·순위 점수를 다시 계산해 저장합니다.

```python
101      rows = tdb.query("SELECT video, threat, embedding, captured_at FROM unknown_sighting WHERE group_id = %s", (gid,))
102      if not rows:
103          return
104      embs = [_unit(json.loads(r["embedding"])) for r in rows if r["embedding"]]
105      centroid = json.dumps([round(float(v), 6) for v in _unit(np.mean(embs, axis=0))]) if embs else None
```
→ 임베딩들을 길이 1로 맞춰 평균 → 다시 길이 1 = centroid. 누적 평균을 매번 다시 구하는 것과 같은 값입니다.

```python
106      seen = sorted(str(r["captured_at"])[:19] for r in rows if r["captured_at"])
107      g = {"n_tracks": len(rows), "n_videos": len({r["video"] for r in rows}),
108           "max_threat": max((r["threat"] for r in rows if r["threat"] is not None), default=None),
109           "last_seen": seen[-1] if seen else None}
```
→ 출현 빈도는 **프레임 수가 아니라** 고유 트랙 수·고유 영상 수로 셉니다. 같은 전차가 100프레임 나와도 1트랙.

```python
110      tdb.execute("UPDATE unknown_group SET n_tracks = %s, n_videos = %s, max_threat = %s, centroid = %s, first_seen = %s, "
111                  "last_seen = %s, priority = %s, updated_at = %s WHERE group_id = %s",
112                  (g["n_tracks"], g["n_videos"], g["max_threat"], centroid, seen[0] if seen else None, g["last_seen"],
113                   priority(g, today), _now(), gid))
```
→ DB 에 저장(UPDATE). `%s` 는 값 자리표시자 — 값을 SQL 문자열에 직접 붙이지 않아 **SQL 인젝션**(입력으로 DB 명령을 끼워 넣는 공격)을 막습니다.

### 함수 `_prune`, `_save_crops` — crop 저장·정리 (unknown_registry.py:116~135)

```python
116  def _prune(gid):
117      """그룹 crop 은 품질 상위 GROUP_CROP_MAX 장만 남기고 나머지는 파일·행 삭제."""
118      rows = tdb.query("SELECT id, path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id", (gid,))
119      for r in rows[C.GROUP_CROP_MAX:]:
120          f = media.OUT / r["path"]
121          if f.is_file():
122              f.unlink()
123          tdb.execute("DELETE FROM unknown_crop WHERE id = %s", (r["id"],))
```
→ 그룹 crop 이 12장을 넘으면 품질 낮은 것부터 파일과 DB 행을 함께 지웁니다.

```python
126  def _save_crops(gid, sighting_id, video, target):
127      """트랙의 대표 crop (최대 CROP_KEEP 장) 을 그룹 폴더에 저장. 같은 경로는 다시 저장하지 않는다."""
128      for c in target["_track"]["crops"]:
129          dest = f"unknown_crops/{gid}/{media.safe(video)}_{media.safe(target['tracking_id'])}_{c['frame_idx']}.jpg"
130          if tdb.query("SELECT id FROM unknown_crop WHERE path = %s", (dest,)):
131              continue
```
→ 트랙의 crop 후보(최대 3장)를 `unknown_crops/<그룹>/<영상>_<표적>_<프레임>.jpg` 로 저장. 같은 경로가 이미 있으면 건너뜁니다.

```python
132          if media.save_crop(c["image_path"], c["bbox_px"], dest):
133              tdb.execute("INSERT INTO unknown_crop (sighting_id, group_id, path, quality, frame_idx, created_at) "
134                          "VALUES (%s, %s, %s, %s, %s, %s)", (sighting_id, gid, dest, c["quality"], c["frame_idx"], _now()))
135      _prune(gid)
```
→ 원본 프레임에서 잘라 저장되면(`media.save_crop`) DB 에 기록하고, 마지막에 12장 정리.

### 함수 `record(video, target, source, today)` — 미확인 표적 저장 (메인) (unknown_registry.py:138~176)

이 부분이 하는 일: 새 분석에서 Unknown 표적 1건마다 `dashboard/__init__.py:66` 이 부릅니다. 결과: {그룹 id, 유사도, 새 그룹인지}.

```python
140      t = target["_track"]
141      if not t.get("embedding"):
142          log.warning("임베딩 없음 → 레지스트리 매칭 건너뜀: %s %s", video, target["tracking_id"])
143          return None
```
→ 임베딩이 없으면 비교할 수 없어 저장하지 않습니다(경고 로그).

```python
144      ensure_schema()
145      pos = target["position"]
146      vals = {"cluster_id": target["cluster_id"], "top_k_json": json.dumps(t["top_k"], ensure_ascii=False),
147              "embedding": json.dumps([round(v, 6) for v in t["embedding"]]), "threat": target["threat"],
148              "lat": pos["lat"], "lon": pos["lon"], "captured_at": _when(source.get("captured_at"))}
```
→ 저장할 값: 군집, 분류 후보, 임베딩, 위협도, 추정 위치, 촬영일.

```python
149      old = tdb.query("SELECT id, group_id, similarity FROM unknown_sighting WHERE video = %s AND tracking_id = %s",
150                      (video, target["tracking_id"]))
151      if old:                                                        # 같은 영상 재분석: 그 행만 고친다 (그룹은 유지)
152          g = _live(old[0]["group_id"])
153          gid, sim, new = g["group_id"], old[0]["similarity"], False
154          tdb.execute("UPDATE unknown_sighting SET group_id = %s, " + ", ".join(f"{k} = %s" for k in vals) + " WHERE id = %s",
155                      (gid, *vals.values(), old[0]["id"]))
156          sighting_id = old[0]["id"]
```
→ **같은 영상·같은 tracking_id 가 이미 있으면** 그 행만 고칩니다 → 같은 영상을 다시 분석해도 중복 저장되지 않습니다(테스트 `test_reanalysis_does_not_duplicate`).

```python
157      else:
158          gid, sim, review = _match(t["embedding"])
159          new = gid is None
160          if new:                                                    # 새 그룹
161              gid = _new_group_id()
162              tdb.execute("INSERT INTO unknown_group (group_id, status, family_guess, type_group, review_candidates, updated_at) "
163                          "VALUES (%s, 'open', %s, %s, %s, %s)",
164                          (gid, target["family"], target.get("type_group"), json.dumps(review) if review else None, _now()))
```
→ 처음 보는 표적이면 그룹 매칭. 맞는 그룹이 없으면 새 그룹을 만들고 추정 계열·유형·병합 후보를 적습니다.

```python
165          sighting_id = tdb.execute("INSERT INTO unknown_sighting (group_id, video, tracking_id, similarity, created_at, "
166                                    + ", ".join(vals) + ") VALUES (" + ", ".join(["%s"] * (5 + len(vals))) + ")",
167                                    (gid, video, target["tracking_id"], sim, _now(), *vals.values()))
```
→ 출현 기록(sighting) 1행 추가. `tdb.execute` 가 새 행 번호를 돌려줍니다(crop 연결용).

```python
168      g = _group(gid)
169      if target["threat"] is not None and (g["max_threat"] is None or target["threat"] >= g["max_threat"]):
170          tdb.execute("UPDATE unknown_group SET threat_source = %s WHERE group_id = %s", (target["threat_source"], gid))
171      tdb.execute("UPDATE unknown_group SET has_cope_cage = %s, commander_seen = %s, family_guess = COALESCE(family_guess, %s) "
172                  "WHERE group_id = %s", (int(bool(g["has_cope_cage"]) or target["has_cope_cage"]),
173                                          int(bool(g["commander_seen"]) or target["is_commander"]), target["family"], gid))
```
→ 그룹의 위협도 근거·cope cage·지휘전차 동반 여부를 갱신. `COALESCE(a, b)` 는 a 가 비었을 때만 b. 그래서 **추정 계열은 첫 표적 값이 유지**됩니다(샘플: T-90 — 12번 문서 참고).

```python
174      _refresh(gid, today)
175      _save_crops(gid, sighting_id, video, target)
176      return {"group_id": gid, "similarity": sim, "new": new}
```
→ 집계 재계산 → crop 저장 → 결과 반환.

### 함수 `lookup`, `_cover` — 저장된 그룹 찾기·대표 사진 (unknown_registry.py:179~189)

```python
179  def lookup(video, tracking_id):
180      """이미 저장된 표적의 그룹 id (재분석·전술 변경 때 다시 저장하지 않고 붙이기). 없으면 None."""
181      ensure_schema()
182      rows = tdb.query("SELECT group_id FROM unknown_sighting WHERE video = %s AND tracking_id = %s", (video, tracking_id))
183      g = _live(rows[0]["group_id"]) if rows else None
184      return g["group_id"] if g else None
```
→ 전술·지휘전차만 바꿔 재계산할 때는 다시 저장하지 않고, 저장돼 있던 그룹 id 만 찾아 붙입니다.

```python
187  def _cover(gid):
188      rows = tdb.query("SELECT path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id LIMIT 1", (gid,))
189      return rows[0]["path"] if rows else None
```
→ 그룹에서 품질이 가장 좋은 crop 1장(목록 썸네일용).

### 함수 `ranking(limit, today)` — 순위 목록 (unknown_registry.py:192~200)

```python
195      groups = tdb.query("SELECT * FROM unknown_group WHERE status = 'open' AND max_threat >= %s",
196                         (C.UNKNOWN_RANK_MIN_THREAT,))
```
→ 열린(open) 그룹 중 최고 위협도 ≥ 40 인 것만. 40 미만은 저장은 하되 순위에서 뺍니다.

```python
197      for g in groups:
198          g["priority"] = priority(g, today)
199      groups.sort(key=lambda g: -g["priority"])
200      return [_public(g, rank=i, cover=_cover(g["group_id"])) for i, g in enumerate(groups[:limit], 1)]
```
→ 순위 점수를 **지금 기준으로 다시 계산**해(최근 7일 기준이 날마다 바뀌므로) 높은 순으로 상위 N개.

### 함수 `detail(gid)`, `_public(g)` — 그룹 상세 (unknown_registry.py:203~226)

```python
209      sightings = tdb.query("SELECT id, video, tracking_id, cluster_id, similarity, threat, lat, lon, captured_at "
210                            "FROM unknown_sighting WHERE group_id = %s ORDER BY captured_at, id", (gid,))
211      crops = tdb.query("SELECT c.path, c.quality, c.frame_idx, s.video, s.tracking_id FROM unknown_crop c "
212                        "LEFT JOIN unknown_sighting s ON s.id = c.sighting_id WHERE c.group_id = %s ORDER BY c.quality DESC, c.id",
213                        (gid,))
```
→ 출현 기록(영상·표적·위치·위협도)과 crop 목록. crop 은 출현 기록과 **JOIN**(두 테이블을 연결해 읽기)해서 어느 영상·표적의 사진인지 함께 가져옵니다.

```python
214      for s in sightings:
215          s["captured_at"] = str(s["captured_at"])[:19] if s["captured_at"] else None
216      return {"group": _public(g, cover=_cover(gid)), "sightings": sightings, "crops": crops}
```
→ 날짜를 문자열로 바꿔 돌려줍니다.

```python
219  def _public(g, **extra):
220      """API 로 내보낼 그룹 (centroid 는 빼고, 날짜는 문자열)."""
221      out = {k: v for k, v in g.items() if k != "centroid"}
222      for k in ("first_seen", "last_seen", "updated_at"):
223          out[k] = str(out[k])[:19] if out.get(k) else None
224      out["review_candidates"] = json.loads(g["review_candidates"]) if g.get("review_candidates") else []
225      out["has_cope_cage"], out["commander_seen"] = bool(g["has_cope_cage"]), bool(g["commander_seen"])
226      return dict(out, **extra)
```
→ API 로 내보낼 형태: centroid(큰 숫자 목록)는 빼고, 날짜·병합 후보·참거짓 값을 화면에서 쓰기 쉽게 바꿉니다.

