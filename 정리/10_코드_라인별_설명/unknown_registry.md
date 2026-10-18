# unknown_registry.py — 미확인 전차 레지스트리 (영상 간 그룹화·순위)

파일: `dashboard/unknown_registry.py` (전체 234줄)

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
 29  _ready = False
```
→ 로그 도구와 '테이블을 이미 만들었는지' 표시(`_ready`).

### 함수 `ensure_schema()` — 테이블 준비 (unknown_registry.py:32~37)

```python
 34      global _ready
 35      if not _ready:
 36          tdb.init_schema()
 37          _ready = True
```
→ 처음 한 번만 `schema_threat.sql` 을 실행해 테이블을 만듭니다(이미 있으면 그대로). `global` 은 함수 밖 변수 `_ready` 를 바꾸겠다는 표시.

### 함수 `_now`, `_when`, `_unit` — 시간·벡터 도우미 (unknown_registry.py:40~57)

```python
 40  def _now():
 41      return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```
→ 지금 시각 문자열 'YYYY-MM-DD HH:MM:SS'.

```python
 44  def _when(captured_at):
 45      """source.captured_at ('2024-03-15' 또는 '2024-03-15 10:20:00') → DATETIME 문자열. 못 읽으면 지금."""
 46      for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
 47          try:
 48              return datetime.strptime(str(captured_at)[:n], fmt).strftime("%Y-%m-%d %H:%M:%S")
 49          except ValueError:
 50              continue
 51      return _now()
```
→ 영상 촬영일(`captured_at`)을 DB 날짜 형식으로. 세 가지 형식을 차례로 시도하고, 다 실패하면 지금 시각.

```python
 54  def _unit(v):
 55      a = np.asarray(v, dtype=float)
 56      n = np.linalg.norm(a)
 57      return a / n if n else a
```
→ 벡터를 길이 1로 맞춤(L2 정규화). 길이가 0 이면 그대로.

### 함수 `priority(g, today)` — 순위 점수 (unknown_registry.py:60~67)

이 부분이 하는 일: 순위 점수 = 최고 위협도 × (1 + 0.5 × ln(1 + 트랙 수)) × (1 + 0.5 × (영상 수 − 1)), 최근 7일 안에 나왔으면 × 1.2.

```python
 62      p = (g["max_threat"] or 0) * (1 + C.PRIORITY_FREQ_K * math.log(1 + (g["n_tracks"] or 0))) \
 63          * (1 + C.PRIORITY_VIDEO_K * max((g["n_videos"] or 1) - 1, 0))
```
→ 위협도가 높을수록, 여러 번(트랙 수) 그리고 여러 영상에서 나올수록 점수가 오릅니다. log 를 쓴 이유: 트랙이 아주 많아져도 점수가 한없이 커지지 않게.

```python
 64      last = g.get("last_seen")
 65      if last and datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S") >= (today or datetime.now()) - timedelta(days=C.RECENT_DAYS):
 66          p *= C.RECENT_BOOST
 67      return round(p, 1)
```
→ 마지막 출현이 최근 7일 안이면 ×1.2. 예: UNK-G0001 → 99.5 × (1 + 0.5×ln3) × 1.5 × 1.2 = 277.5.

### 함수 `_group`, `_live`, `_new_group_id` — 그룹 찾기·번호 (unknown_registry.py:70~87)

```python
 70  def _group(gid):
 71      rows = tdb.query("SELECT * FROM unknown_group WHERE group_id = %s", (gid,))
 72      return rows[0] if rows else None
```
→ 그룹 1행 읽기.

```python
 75  def _live(gid):
 76      """병합된 그룹이면 병합 대상 그룹으로 따라간다."""
 77      seen = set()
 78      g = _group(gid)
 79      while g and g["status"] == "merged" and g["merged_into"] and g["group_id"] not in seen:
 80          seen.add(g["group_id"])
 81          g = _group(g["merged_into"])
 82      return g
```
→ 병합된 그룹이면 병합 대상 그룹으로 따라갑니다(같은 그룹을 두 번 보면 멈춤). **병합 기능 자체는 아직 없음(TODO)**.

```python
 85  def _new_group_id():
 86      n = tdb.query("SELECT COUNT(*) AS n FROM unknown_group")[0]["n"]
 87      return f"UNK-G{n + 1:04d}"
```
→ 그룹 수 + 1 로 'UNK-G0001' 형식 번호를 만듭니다. `:04d` 는 4자리로 앞을 0 으로 채움. 서버 1대 가정(동시에 두 분석이 돌면 번호가 겹칠 수 있음 — 한계).

### 함수 `_match(emb)` — 비슷한 그룹 찾기 (unknown_registry.py:90~104)

이 부분이 하는 일: 새 미확인 표적의 임베딩을 열린(open)·확정(confirmed) 그룹들의 centroid 와 한꺼번에 비교합니다.

```python
 92      groups = [g for g in tdb.query("SELECT group_id, centroid FROM unknown_group WHERE status IN ('open', 'confirmed')")
 93                if g["centroid"]]
 94      if not groups:
 95          return None, None, []
```
→ 비교할 그룹이 없으면 (None, None, []).

```python
 96      mat = np.array([_unit(json.loads(g["centroid"])) for g in groups])
 97      sims = mat @ _unit(emb)
 98      order = np.argsort(-sims)
 99      best = order[0]
```
→ 모든 centroid 를 행렬로 쌓고 `mat @ 벡터`(**행렬 곱**)로 유사도를 한 번에 구합니다. 길이 1 벡터끼리의 곱 = 코사인 유사도. 높은 순으로 정렬.

```python
100      if sims[best] >= C.GROUP_SIM_MIN:
101          return groups[best]["group_id"], round(float(sims[best]), 4), []
```
→ 최고 유사도 ≥ 0.85 → 그 그룹.

```python
102      review = [{"group_id": groups[i]["group_id"], "similarity": round(float(sims[i]), 4)}
103                for i in order if sims[i] >= C.GROUP_SIM_REVIEW]
104      return None, None, review
```
→ 아니면 새 그룹. 0.75 이상인 그룹들은 '병합 후보'로 넘깁니다(분석관 검토용).

### 함수 `_refresh(gid, today)` — 그룹 집계 다시 계산 (unknown_registry.py:107~121)

이 부분이 하는 일: 그룹의 출현 기록(sighting) 전체로 트랙 수·영상 수·최고 위협도·centroid·처음/마지막 출현·순위 점수를 다시 계산해 저장합니다.

```python
109      rows = tdb.query("SELECT video, threat, embedding, captured_at FROM unknown_sighting WHERE group_id = %s", (gid,))
110      if not rows:
111          return
112      embs = [_unit(json.loads(r["embedding"])) for r in rows if r["embedding"]]
113      centroid = json.dumps([round(float(v), 6) for v in _unit(np.mean(embs, axis=0))]) if embs else None
```
→ 임베딩들을 길이 1로 맞춰 평균 → 다시 길이 1 = centroid. 누적 평균을 매번 다시 구하는 것과 같은 값입니다.

```python
114      seen = sorted(str(r["captured_at"])[:19] for r in rows if r["captured_at"])
115      g = {"n_tracks": len(rows), "n_videos": len({r["video"] for r in rows}),
116           "max_threat": max((r["threat"] for r in rows if r["threat"] is not None), default=None),
117           "last_seen": seen[-1] if seen else None}
```
→ 출현 빈도는 **프레임 수가 아니라** 고유 트랙 수·고유 영상 수로 셉니다. 같은 전차가 100프레임 나와도 1트랙.

```python
118      tdb.execute("UPDATE unknown_group SET n_tracks = %s, n_videos = %s, max_threat = %s, centroid = %s, first_seen = %s, "
119                  "last_seen = %s, priority = %s, updated_at = %s WHERE group_id = %s",
120                  (g["n_tracks"], g["n_videos"], g["max_threat"], centroid, seen[0] if seen else None, g["last_seen"],
121                   priority(g, today), _now(), gid))
```
→ DB 에 저장(UPDATE). `%s` 는 값 자리표시자 — 값을 SQL 문자열에 직접 붙이지 않아 **SQL 인젝션**(입력으로 DB 명령을 끼워 넣는 공격)을 막습니다.

### 함수 `_prune`, `_save_crops` — crop 저장·정리 (unknown_registry.py:124~143)

```python
124  def _prune(gid):
125      """그룹 crop 은 품질 상위 GROUP_CROP_MAX 장만 남기고 나머지는 파일·행 삭제."""
126      rows = tdb.query("SELECT id, path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id", (gid,))
127      for r in rows[C.GROUP_CROP_MAX:]:
128          f = media.OUT / r["path"]
129          if f.is_file():
130              f.unlink()
131          tdb.execute("DELETE FROM unknown_crop WHERE id = %s", (r["id"],))
```
→ 그룹 crop 이 12장을 넘으면 품질 낮은 것부터 파일과 DB 행을 함께 지웁니다.

```python
134  def _save_crops(gid, sighting_id, video, target):
135      """트랙의 대표 crop (최대 CROP_KEEP 장) 을 그룹 폴더에 저장. 같은 경로는 다시 저장하지 않는다."""
136      for c in target["_track"]["crops"]:
137          dest = f"unknown_crops/{gid}/{media.safe(video)}_{media.safe(target['tracking_id'])}_{c['frame_idx']}.jpg"
138          if tdb.query("SELECT id FROM unknown_crop WHERE path = %s", (dest,)):
139              continue
```
→ 트랙의 crop 후보(최대 3장)를 `unknown_crops/<그룹>/<영상>_<표적>_<프레임>.jpg` 로 저장. 같은 경로가 이미 있으면 건너뜁니다.

```python
140          if media.save_crop(c["image_path"], c["bbox_px"], dest):
141              tdb.execute("INSERT INTO unknown_crop (sighting_id, group_id, path, quality, frame_idx, created_at) "
142                          "VALUES (%s, %s, %s, %s, %s, %s)", (sighting_id, gid, dest, c["quality"], c["frame_idx"], _now()))
143      _prune(gid)
```
→ 원본 프레임에서 잘라 저장되면(`media.save_crop`) DB 에 기록하고, 마지막에 12장 정리.

### 함수 `record(video, target, source, today)` — 미확인 표적 저장 (메인) (unknown_registry.py:146~184)

이 부분이 하는 일: 새 분석에서 Unknown 표적 1건마다 `dashboard/__init__.py:66` 이 부릅니다. 결과: {그룹 id, 유사도, 새 그룹인지}.

```python
148      t = target["_track"]
149      if not t.get("embedding"):
150          log.warning("임베딩 없음 → 레지스트리 매칭 건너뜀: %s %s", video, target["tracking_id"])
151          return None
```
→ 임베딩이 없으면 비교할 수 없어 저장하지 않습니다(경고 로그).

```python
152      ensure_schema()
153      pos = target["position"]
154      vals = {"cluster_id": target["cluster_id"], "top_k_json": json.dumps(t["top_k"], ensure_ascii=False),
155              "embedding": json.dumps([round(v, 6) for v in t["embedding"]]), "threat": target["threat"],
156              "lat": pos["lat"], "lon": pos["lon"], "captured_at": _when(source.get("captured_at"))}
```
→ 저장할 값: 군집, 분류 후보, 임베딩, 위협도, 추정 위치, 촬영일.

```python
157      old = tdb.query("SELECT id, group_id, similarity FROM unknown_sighting WHERE video = %s AND tracking_id = %s",
158                      (video, target["tracking_id"]))
159      if old:                                                        # 같은 영상 재분석: 그 행만 고친다 (그룹은 유지)
160          g = _live(old[0]["group_id"])
161          gid, sim, new = g["group_id"], old[0]["similarity"], False
162          tdb.execute("UPDATE unknown_sighting SET group_id = %s, " + ", ".join(f"{k} = %s" for k in vals) + " WHERE id = %s",
163                      (gid, *vals.values(), old[0]["id"]))
164          sighting_id = old[0]["id"]
```
→ **같은 영상·같은 tracking_id 가 이미 있으면** 그 행만 고칩니다 → 같은 영상을 다시 분석해도 중복 저장되지 않습니다(테스트 `test_reanalysis_does_not_duplicate`).

```python
165      else:
166          gid, sim, review = _match(t["embedding"])
167          new = gid is None
168          if new:                                                    # 새 그룹
169              gid = _new_group_id()
170              tdb.execute("INSERT INTO unknown_group (group_id, status, family_guess, type_group, review_candidates, updated_at) "
171                          "VALUES (%s, 'open', %s, %s, %s, %s)",
172                          (gid, target["family"], target.get("type_group"), json.dumps(review) if review else None, _now()))
```
→ 처음 보는 표적이면 그룹 매칭. 맞는 그룹이 없으면 새 그룹을 만들고 추정 계열·유형·병합 후보를 적습니다.

```python
173          sighting_id = tdb.execute("INSERT INTO unknown_sighting (group_id, video, tracking_id, similarity, created_at, "
174                                    + ", ".join(vals) + ") VALUES (" + ", ".join(["%s"] * (5 + len(vals))) + ")",
175                                    (gid, video, target["tracking_id"], sim, _now(), *vals.values()))
```
→ 출현 기록(sighting) 1행 추가. `tdb.execute` 가 새 행 번호를 돌려줍니다(crop 연결용).

```python
176      g = _group(gid)
177      if target["threat"] is not None and (g["max_threat"] is None or target["threat"] >= g["max_threat"]):
178          tdb.execute("UPDATE unknown_group SET threat_source = %s WHERE group_id = %s", (target["threat_source"], gid))
179      tdb.execute("UPDATE unknown_group SET has_cope_cage = %s, commander_seen = %s, family_guess = COALESCE(family_guess, %s) "
180                  "WHERE group_id = %s", (int(bool(g["has_cope_cage"]) or target["has_cope_cage"]),
181                                          int(bool(g["commander_seen"]) or target["is_commander"]), target["family"], gid))
```
→ 그룹의 위협도 근거·cope cage·지휘전차 동반 여부를 갱신. `COALESCE(a, b)` 는 a 가 비었을 때만 b. 그래서 **추정 계열은 첫 표적 값이 유지**됩니다(샘플: T-90 — 12번 문서 참고).

```python
182      _refresh(gid, today)
183      _save_crops(gid, sighting_id, video, target)
184      return {"group_id": gid, "similarity": sim, "new": new}
```
→ 집계 재계산 → crop 저장 → 결과 반환.

### 함수 `lookup`, `_cover` — 저장된 그룹 찾기·대표 사진 (unknown_registry.py:187~197)

```python
187  def lookup(video, tracking_id):
188      """이미 저장된 표적의 그룹 id (재분석·전술 변경 때 다시 저장하지 않고 붙이기). 없으면 None."""
189      ensure_schema()
190      rows = tdb.query("SELECT group_id FROM unknown_sighting WHERE video = %s AND tracking_id = %s", (video, tracking_id))
191      g = _live(rows[0]["group_id"]) if rows else None
192      return g["group_id"] if g else None
```
→ 전술·지휘전차만 바꿔 재계산할 때는 다시 저장하지 않고, 저장돼 있던 그룹 id 만 찾아 붙입니다.

```python
195  def _cover(gid):
196      rows = tdb.query("SELECT path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id LIMIT 1", (gid,))
197      return rows[0]["path"] if rows else None
```
→ 그룹에서 품질이 가장 좋은 crop 1장(목록 썸네일용).

### 함수 `ranking(limit, today)` — 순위 목록 (unknown_registry.py:200~208)

```python
203      groups = tdb.query("SELECT * FROM unknown_group WHERE status = 'open' AND max_threat >= %s",
204                         (C.UNKNOWN_RANK_MIN_THREAT,))
```
→ 열린(open) 그룹 중 최고 위협도 ≥ 40 인 것만. 40 미만은 저장은 하되 순위에서 뺍니다.

```python
205      for g in groups:
206          g["priority"] = priority(g, today)
207      groups.sort(key=lambda g: -g["priority"])
208      return [_public(g, rank=i, cover=_cover(g["group_id"])) for i, g in enumerate(groups[:limit], 1)]
```
→ 순위 점수를 **지금 기준으로 다시 계산**해(최근 7일 기준이 날마다 바뀌므로) 높은 순으로 상위 N개.

### 함수 `detail(gid)`, `_public(g)` — 그룹 상세 (unknown_registry.py:211~234)

```python
217      sightings = tdb.query("SELECT id, video, tracking_id, cluster_id, similarity, threat, lat, lon, captured_at "
218                            "FROM unknown_sighting WHERE group_id = %s ORDER BY captured_at, id", (gid,))
219      crops = tdb.query("SELECT c.path, c.quality, c.frame_idx, s.video, s.tracking_id FROM unknown_crop c "
220                        "LEFT JOIN unknown_sighting s ON s.id = c.sighting_id WHERE c.group_id = %s ORDER BY c.quality DESC, c.id",
221                        (gid,))
```
→ 출현 기록(영상·표적·위치·위협도)과 crop 목록. crop 은 출현 기록과 **JOIN**(두 테이블을 연결해 읽기)해서 어느 영상·표적의 사진인지 함께 가져옵니다.

```python
222      for s in sightings:
223          s["captured_at"] = str(s["captured_at"])[:19] if s["captured_at"] else None
224      return {"group": _public(g, cover=_cover(gid)), "sightings": sightings, "crops": crops}
```
→ 날짜를 문자열로 바꿔 돌려줍니다.

```python
227  def _public(g, **extra):
228      """API 로 내보낼 그룹 (centroid 는 빼고, 날짜는 문자열)."""
229      out = {k: v for k, v in g.items() if k != "centroid"}
230      for k in ("first_seen", "last_seen", "updated_at"):
231          out[k] = str(out[k])[:19] if out.get(k) else None
232      out["review_candidates"] = json.loads(g["review_candidates"]) if g.get("review_candidates") else []
233      out["has_cope_cage"], out["commander_seen"] = bool(g["has_cope_cage"]), bool(g["commander_seen"])
234      return dict(out, **extra)
```
→ API 로 내보낼 형태: centroid(큰 숫자 목록)는 빼고, 날짜·병합 후보·참거짓 값을 화면에서 쓰기 쉽게 바꿉니다.

