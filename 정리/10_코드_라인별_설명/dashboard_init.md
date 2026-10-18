# dashboard/__init__.py — 화면·API 주소 (Flask Blueprint)

파일: `dashboard/__init__.py` (전체 363줄)

브라우저가 부르는 **주소(URL)** 와 그 주소에서 실행할 함수를 정하는 파일입니다. 계산은 하지 않고 `threat/` 패키지에 맡기고,
판정·조치 **기록**은 `response_level.py`(저장소 루트)의 함수로 DB 에 남깁니다.

- **Flask**: 파이썬 웹 서버 라이브러리. `@bp.get("/주소")` 처럼 함수 위에 붙인 줄을 **데코레이터**(함수에 기능을 덧붙이는 표시)라 하며, "이 주소로 GET 요청이 오면 아래 함수를 실행"이라는 뜻입니다.
- **Blueprint**: 주소 묶음. `app.py:12` 에서 앱에 등록합니다.
- **GET** 은 읽기, **POST** 는 새로 만들기(분석 실행·단계 조정 기록), **PATCH** 는 일부 수정(전술·지휘전차·핵심표적 변경).
- 응답은 JSON. 오류는 `{"error": "이유"}` 와 상태 코드(400 잘못된 요청, 404 없음, 503 기록 DB 를 읽지 못함).

### 머리말 — 주소 목록 (__init__.py:1~17)

```python
  3  주소
  4    GET   /                                   대시보드 화면 (templates/dashboard/index.html)
  5    POST  /api/analyze                        탐지 결과 분석 (본문 비우면 샘플 영상 A → B) → AnalysisResult + videos
  6    GET   /api/threats[?video=이름]           마지막 분석 결과 (video 를 주면 그 영상으로 화면 전환, 분석 전이면 404)
  7    GET   /api/threats/<tracking_id>          표적 1건 + 소속 군집
  8    PATCH /api/clusters/<cluster_id>/tactic   군집 전술 지정 {"tactic": 1~10 또는 null(자동)} → 재분석 결과
  9    PATCH /api/threats/<tracking_id>/commander 지휘전차 지정·해제 {"is_commander": true|false|null(자동)} → 재분석 결과
 10    PATCH /api/threats/<tracking_id>/core-target 핵심표적 지정·해제 {"core": true|false} → 재분석 결과 (최소 2단계)
 11    POST  /api/clusters/<cluster_id>/stage    단계 조정 기록 {"stage": 1~4 또는 null} (계산은 그대로, 이력에만)
 12    GET   /api/clusters/<cluster_id>/history  판정·지휘관 조치 이력 (?video=)
 13    GET   /api/unknowns?limit=20              Unknown 그룹 순위
 14    GET   /api/unknowns/<group_id>            Unknown 그룹 상세 (출현 기록, crop, 병합 후보)
 15    GET   /unknowns                           분석관 화면 (Unknown 그룹 순위·crop 갤러리·출현 지도)
 16    GET   /report?stage=N                     인쇄용 보고서 (stage = 지휘관이 조정한 단계, 없으면 AI 권고)
```
→ 이 파일이 제공하는 주소 전체. 엔진 통합으로 핵심표적·단계 조정 기록·이력 조회 주소가 늘었습니다. 자세한 요청·응답 예시는 `정리/08_API_명세.md`.

### import, Blueprint, 서버 상태(STATE) (__init__.py:18~46)

```python
 18  import json
 19  import logging
 20  from datetime import datetime  # 보고서 작성 시각
 22  from flask import Blueprint, jsonify, render_template, request, url_for
 24  from . import media, threat          # crop 저장, 위협도 계산 패키지 (dashboard/threat/)
 25  from .threat import track as TR      # v2 입력 판별
 26  from . import unknown_registry as registry
 27  from .threat import config as C      # 단계 이름 (LEVELS), 전술 가중치 목록
 28  from .threat.core import TACTIC_NAMES  # 전술 번호 → 이름
 29  from .threat.pipeline import MOCK_V2   # 기본 샘플 (영상 A, B)
```
→ 필요한 도구를 가져옵니다. `media`(crop 저장), `threat`(계산), `registry`(미확인 레지스트리), `MOCK_V2`(샘플 영상 A·B 경로).

```python
 30  from .threat.adapter import rl         # 판정 엔진·기록 (저장소 루트 response_level.py)
 31  from threat_api import _actor          # 조치한 사람 (X-User 헤더 → 본문 actor → 기본값)
```
→ `rl` = 판정 엔진과 기록 함수(`response_level.py`), `_actor` = 조치한 사람 이름을 정하는 함수(`threat_api.py` 와 같은 규칙: X-User 헤더 → 본문 actor → 기본값).

```python
 33  bp = Blueprint("dashboard", __name__,
 34                 template_folder="templates",            # dashboard/templates/dashboard/*.html
 35                 static_folder="static",                 # dashboard/static/dashboard.js, dashboard.css
 36                 static_url_path="/dashboard-static")    # 브라우저 주소: /dashboard-static/dashboard.js
 37  log = logging.getLogger(__name__)
```
→ Blueprint 생성. 이 폴더의 `templates/`(HTML 틀)·`static/`(JS·CSS)을 쓰며, JS·CSS 는 브라우저에서 `/dashboard-static/...` 주소로 열립니다.

```python
 39  # 서버 메모리 상태 (요청 사이에 유지). 영상마다 분석 1건(run)을 들고 있고, 화면은 current 영상을 본다.
 40  # 기록의 기준은 DB 다: 판정마다 cluster_assessment, 지휘관 조치마다 commander_override 에 남는다 (response_level).
 41  #   STATE 는 화면 속도를 위한 캐시일 뿐이라 서버를 다시 켜면 사라진다.
 42  # ponytail: 화면 상태(지정 전술·핵심표적·단계 조정)는 프로세스 메모리 하나라 모든 사용자가 공유한다.
 43  #   사용자별 화면이 필요하면 run 을 사용자 키로 나누거나 DB 에서 복원 (기록·레지스트리는 이미 DB 라 재시작해도 남음)
 44  STATE = {"runs": {},       # 영상 이름 → {"payload", "prev", "result", "overrides": {군집: 전술}, "commanders": {표적: bool},
 45                             #              "core": {핵심표적 tracking_id}, "stages": {군집: 지휘관이 화면에서 조정한 단계}}
 46           "current": None}  # 화면에 보이는 영상 이름
```
→ **STATE**: 서버 메모리에 영상별 분석 결과(run)와 지휘관 조치 상태(지정 전술·지휘전차·핵심표적·단계 조정)를 들고 있는 딕셔너리. **기록의 기준은 DB**(판정·조치 이력)이고 STATE 는 화면 속도를 위한 캐시입니다. 모든 사용자가 같은 화면 상태를 공유합니다(**한계**, 12번 문서).

### 도우미 함수 `_bad`, `_video`, `_run` (__init__.py:49~60)

```python
 49  def _bad(e, code):
 50      """오류를 JSON 으로 돌려준다 (화면이 error 메시지를 배너로 보여줌)."""
 51      return jsonify(error=str(e)), code
```
→ 오류 응답 만들기: `{"error": 메시지}` + 상태 코드. 화면은 이 메시지를 빨간 배너로 보여 줍니다.

```python
 54  def _video(payload):
 55      return str((payload.get("source") or {}).get("video") or "영상")
```
→ 입력의 영상 이름(없으면 '영상').

```python
 58  def _run(video=None):
 59      """?video= 로 고른 영상(없으면 지금 영상)의 run. 분석 전이면 None."""
 60      return STATE["runs"].get(video or request.args.get("video") or STATE["current"])
```
→ 주소의 `?video=` 로 고른 영상, 없으면 지금 화면 영상의 run 을 찾습니다.

### 함수 `_attach(result, new)` — crop·미확인 그룹·판정 기록 붙이기 (__init__.py:63~89)

이 부분이 하는 일: 계산 결과(`pipeline.analyze`)에 파일·DB 작업 결과를 붙입니다. 계산 코드를 순수하게 두려고 저장 작업을 여기로 뺐습니다.

```python
 67      video = _video(result)
 68      for t in result["targets"]:
 69          if "_track" not in t:
 70              continue
```
→ v2 표적(`_track` 이 있는 것)만 crop·레지스트리 처리를 합니다.

```python
 71          crop = media.track_crop(video, t)
 72          t["crop_url"] = url_for("static", filename=crop) if crop else None
```
→ 대표 crop 을 저장(`media.track_crop`)하고 브라우저 주소(`/static/track_crops/...`)를 붙입니다.

```python
 73          if t["status"] == "Unknown":
 74              try:
 75                  info = registry.record(video, t, result["source"]) if new else {"group_id": registry.lookup(video, t["tracking_id"])}
 76                  t["unknown_group_id"] = info and info["group_id"]
 77              except Exception as e:                                     # 레지스트리 DB 가 꺼져 있어도 대시보드는 보여 준다
 78                  log.warning("Unknown 레지스트리 저장 실패 (%s %s): %s", video, t["tracking_id"], e)
```
→ Unknown 이면: 새 분석일 때 레지스트리에 저장(`registry.record`), 재계산일 때는 저장된 그룹만 찾기(`registry.lookup`). 레지스트리 DB 가 꺼져 있어도 대시보드는 보이도록 오류는 기록만 하고 넘어갑니다(**try/except**: 오류가 나면 except 부분 실행).

```python
 79          del t["_track"]
```
→ 내부 필드 `_track`(임베딩 등 큰 데이터)은 화면으로 보내기 전에 지웁니다.

```python
 80      saved = True
 81      for c in result["clusters"]:                                       # 군집 판정 기록 (cluster_assessment)
 82          inp, res = c.pop("_assess_input"), c.pop("_assess_result")
 83          try:
 84              rl.save_assessment(dict(inp, cluster_id=rl.cluster_key(video, c["cluster_id"])), res)
 85          except Exception as e:                                         # DB 가 없어도 화면 분석은 계속
 86              saved = False
 87              log.warning("판정 기록 저장 실패 (%s %s): %s", video, c["cluster_id"], e)
```
→ **군집 판정 기록**: 군집마다 판정 엔진 입력·결과를 `cluster_assessment` 에 1행 저장(`rl.save_assessment`). 군집 ID 는 '영상:군집'(`rl.cluster_key`) 이라 영상이 달라도 겹치지 않습니다. 저장에 실패해도 분석은 계속합니다.

```python
 88      result["alert"]["saved"] = saved                                   # 화면·API 에서 기록 여부 확인용
 89      return result
```
→ 기록 성공 여부를 `alert.saved` 로 응답에 넣습니다 (실패 시 false).

### 함수 `_reanalyze`, `_level`, `_log_action`, `_respond` (__init__.py:92~119)

```python
 92  def _reanalyze(run, overrides=None, commanders=None, core=None):
 93      """같은 입력을 지정 전술·지휘전차·핵심표적만 바꿔 다시 계산 (실패하면 예외, run 은 그대로)."""
 94      ov = run["overrides"] if overrides is None else overrides
 95      cm = run["commanders"] if commanders is None else commanders
 96      co = run["core"] if core is None else core
 97      result = _attach(threat.analyze(run["payload"], run["prev"], ov, cm, co), new=False)
 98      run.update(overrides=ov, commanders=cm, core=co, result=result)
 99      return result
```
→ 같은 입력을 지정 전술·지휘전차·핵심표적만 바꿔 다시 계산하고 run 을 갱신합니다. 재계산도 판정 1건이라 `_attach` 가 기록합니다. 계산이 실패하면 예외가 나서 run 은 그대로 남습니다.

```python
102  def _level(result, cluster_id):
103      return next((c["level"] for c in result["clusters"] if c["cluster_id"] == cluster_id), None)
```
→ 결과에서 그 군집의 단계 꺼내기 (조치 전·후 비교용).

```python
106  def _log_action(video, cluster_id, item, before, after, level_before, level_after):
107      """지휘관 조치 1건을 commander_override 에 기록. DB 가 없어도 화면 동작은 계속 (False 반환)."""
108      try:
109          rl.record_override(rl.cluster_key(video, cluster_id), _actor("commander"), item, before, after,
110                             level_before, level_after)
111          return True
112      except Exception as e:
113          log.warning("지휘관 조치 기록 실패 (%s %s %s): %s", video, cluster_id, item, e)
114          return False
```
→ **지휘관 조치 1건 기록**(`rl.record_override` → `commander_override`). 조치자는 X-User 헤더 → 본문 actor → 'commander'. DB 가 없어도 화면 동작은 계속하고 False 를 돌려줍니다.

```python
117  def _respond(result):
118      """화면 응답 = 분석 결과 + 분석해 둔 영상 목록·지금 영상 (A/B 탭)."""
119      return jsonify(dict(result, videos=list(STATE["runs"]), video=STATE["current"]))
```
→ 응답 = 분석 결과 + 분석한 영상 목록(`videos`) + 지금 영상(`video`). 화면의 A/B 탭이 이 값을 씁니다.

### GET `/` — 대시보드 화면 (__init__.py:122~126)

```python
125      tactics = [(n, TACTIC_NAMES[n]) for n in sorted(C.TACTIC_WEIGHTS)]  # 가중치가 있는 전술 (1~10번)
126      return render_template("dashboard/index.html", tactics=tactics)
```
→ 전술 선택 목록(1~10번)만 채워 HTML 을 돌려줍니다. 나머지 데이터는 화면이 열린 뒤 JS 가 API 로 가져옵니다.

### POST `/api/analyze` — 분석 실행 (__init__.py:129~148)

이 부분이 하는 일: 본문이 있으면 그 탐지 결과 1건, 없으면 샘플 영상 A → B 를 분석합니다. 두 영상을 다 넣어야 영상 간 미확인 그룹 묶음이 보입니다.

```python
132      body = request.get_json(silent=True)
133      payloads = [body] if body else [json.loads(f.read_text(encoding="utf-8")) for f in MOCK_V2]
```
→ 본문 JSON 을 읽고(`silent=True`: JSON 이 아니어도 오류 대신 None), 없으면 mock 파일 2개를 읽습니다.

```python
134      results = []
135      try:
136          for p in payloads:                                              # 먼저 전부 계산 (입력 오류면 상태를 안 바꿈)
137              if not isinstance(p, dict):
138                  raise ValueError("본문은 JSON 객체")
139              run = STATE["runs"].get(_video(p))
140              prev = run["result"] if run else None                       # 같은 영상의 직전 결과 → '신규' 표적 판단
141              results.append((p, prev, threat.analyze(p, prev)))          # 새 입력은 지정 전술·지휘전차 없이 시스템 추정부터
142      except ValueError as e:
143          return _bad(e, 400)                                             # 입력 형식 오류
```
→ 먼저 전부 계산만 합니다. 하나라도 입력 오류(ValueError)면 400 을 돌려주고 서버 상태는 그대로 둡니다. 같은 영상의 직전 결과를 '신규' 판단에 씁니다.

```python
144      for p, prev, result in results:
145          STATE["runs"][_video(p)] = {"payload": p, "prev": prev, "result": _attach(result, new=True),
146                                      "overrides": {}, "commanders": {}, "core": set(), "stages": {}}
```
→ 계산이 모두 성공하면 crop·레지스트리·판정 기록 저장(`_attach(new=True)`) 후 영상별로 저장합니다. 지정 전술·지휘전차·핵심표적·단계 조정은 초기화.

```python
147      STATE["current"] = _video(payloads[0])                              # 화면은 첫 영상부터
148      return _respond(STATE["runs"][STATE["current"]]["result"])
```
→ 화면은 첫 영상(A)부터 보여 줍니다.

### GET `/api/threats` — 마지막 결과 / 영상 전환 (__init__.py:151~162)

```python
154      video = request.args.get("video")
155      if video and video not in STATE["runs"]:
156          return _bad(f"분석한 적 없는 영상: {video}", 404)
157      if video:
158          STATE["current"] = video
```
→ `?video=` 가 있으면 그 영상으로 전환(분석한 적 없으면 404).

```python
159      run = _run()
160      if run is None:
161          return _bad("분석 결과 없음. POST /api/analyze 먼저 실행", 404)  # 화면은 404 를 받으면 자동으로 분석 요청
162      return _respond(run["result"])
```
→ 결과가 없으면 404. 화면은 404 를 받으면 자동으로 분석을 요청합니다(`dashboard.js:59~60`).

### GET `/api/threats/<tracking_id>` — 표적 1건 (__init__.py:165~172)

```python
168      result = (_run() or {}).get("result") or {"targets": [], "clusters": []}
169      t = next((t for t in result["targets"] if t["tracking_id"] == tracking_id), None)
170      if t is None:
171          return _bad(f"표적 없음: {tracking_id}", 404)
172      return jsonify(target=t, cluster=next(c for c in result["clusters"] if c["cluster_id"] == t["cluster_id"]))
```
→ 지금 영상 결과에서 그 표적과 소속 군집을 찾아 돌려줍니다. 없으면 404.

### PATCH `/api/clusters/<cluster_id>/tactic` — 전술 선택 (__init__.py:175~199)

이 부분이 하는 일: 지휘관이 군집 전술을 1~10번 중에서 고르면 그 군집 전차 위협도(T)부터 다시 계산하고 판정합니다. null 이면 자동 추정으로 되돌립니다.

```python
181      tactic = (request.get_json(silent=True) or {}).get("tactic")       # 1~10 또는 None
182      run_before = run["overrides"]                                       # 조치 기록용 (지정 전 값)
183      overrides = dict(run["overrides"])                                  # 실패하면 원래 값 유지하도록 복사본에 적용
184      if tactic is None:
185          overrides.pop(cluster_id, None)                                 # 지정 해제
186      elif isinstance(tactic, int) and not isinstance(tactic, bool):
187          overrides[cluster_id] = tactic
188      else:
189          return _bad("tactic 은 1~10 정수 또는 null", 400)
```
→ 지정 전 값을 기록용으로 잡아 두고, 복사본(`dict(...)`)에 바꿔 넣습니다. 숫자가 아니면 400.

```python
190      old = run["result"]
191      try:
192          new = _reanalyze(run, overrides=overrides)
193      except LookupError as e:
194          return _bad(e, 404)                                             # 없는 군집
195      except ValueError as e:
196          return _bad(e, 400)                                             # 가중치 없는 전술 번호
```
→ 재계산. 없는 군집이면 404(LookupError), 가중치 없는 번호(11 등)면 400(ValueError).

```python
197      _log_action(_video(new), cluster_id, "tactic", run_before.get(cluster_id), tactic,
198                  _level(old, cluster_id), _level(new, cluster_id))
199      return _respond(new)
```
→ 조치 기록: 항목 'tactic', 전→후 전술, 군집 단계 전→후.

### PATCH `/api/threats/<tracking_id>/commander` — 지휘전차 지정·해제 (__init__.py:202~229)

이 부분이 하는 일: 안테나 오탐·누락을 지휘관이 바로잡습니다. true/false 는 지정/해제, null 은 탐지 규칙으로 되돌림. v2 입력에서만.

```python
205      run = _run()
206      if run is None:
207          return _bad("분석 결과 없음", 404)
208      if not TR.is_v2(run["payload"]):
209          return _bad("지휘전차 수정은 프레임 단위(v2) 입력에서만", 400)
210      old_t = next((t for t in run["result"]["targets"] if t["tracking_id"] == tracking_id), None)
211      if old_t is None:
212          return _bad(f"표적 없음: {tracking_id}", 404)
```
→ 분석 결과·v2 여부·표적 존재를 확인.

```python
213      body = request.get_json(silent=True)
214      value = body.get("is_commander", "없음") if isinstance(body, dict) else "없음"
215      if value is not None and not isinstance(value, bool):
216          return _bad("is_commander 는 true, false, null", 400)
```
→ 값이 true/false/null 이 아니면 400. 본문에 키가 없으면 '없음'(문자열)이 되어 역시 400.

```python
217      commanders = dict(run["commanders"])
218      if value is None:
219          commanders.pop(tracking_id, None)
220      else:
221          commanders[tracking_id] = value
222      old = run["result"]
223      new = _reanalyze(run, commanders=commanders)
```
→ 복사본에 반영하고 재계산. 군집 전술이 지휘통제↔기동으로 바뀔 수 있어 군집 전체 점수가 달라집니다.

```python
224      new_t = next(t for t in new["targets"] if t["tracking_id"] == tracking_id)
225      cid = old_t["cluster_id"]
226      _log_action(_video(new), cid, "commander", {"tracking_id": tracking_id, "is_commander": old_t["is_commander"]},
227                  {"tracking_id": tracking_id, "is_commander": new_t["is_commander"], "지휘관 지정": value},
228                  _level(old, cid), _level(new, cid))
229      return _respond(new)
```
→ 조치 기록: 항목 'commander', 그 표적의 지휘전차 여부 전→후, 소속 군집 단계 전→후.

### PATCH `/api/threats/<tracking_id>/core-target` — 핵심표적 지정·해제 (__init__.py:232~249)

이 부분이 하는 일: 지휘관이 꼭 대응해야 할 표적을 지정합니다. 그 군집은 최소 2단계(하한 규칙), 표적은 랭킹 맨 위.

```python
235      run = _run()
236      if run is None:
237          return _bad("분석 결과 없음", 404)
238      old_t = next((t for t in run["result"]["targets"] if t["tracking_id"] == tracking_id), None)
239      if old_t is None:
240          return _bad(f"표적 없음: {tracking_id}", 404)
241      core = (request.get_json(silent=True) or {}).get("core")
242      if not isinstance(core, bool):
243          return _bad("core 는 true 또는 false", 400)
```
→ 표적 확인, 값이 true/false 가 아니면 400.

```python
244      old = run["result"]
245      new = _reanalyze(run, core=(run["core"] | {tracking_id}) if core else (run["core"] - {tracking_id}))
```
→ 핵심표적 집합에 넣거나 빼고 재계산. `|` 는 합집합, `-` 는 차집합(집합에서 빼기).

```python
246      cid = old_t["cluster_id"]
247      _log_action(_video(new), cid, "core_target", {"tracking_id": tracking_id, "core": old_t["is_core"]},
248                  {"tracking_id": tracking_id, "core": core}, _level(old, cid), _level(new, cid))
249      return _respond(new)
```
→ 조치 기록: 항목 'core_target', 지정 여부 전→후, 군집 단계 전→후 (예: 3 → 2).

### POST `/api/clusters/<cluster_id>/stage` — 단계 조정 기록 (__init__.py:252~271)

이 부분이 하는 일: 화면의 '단계 조정'(지휘관이 단계를 직접 바꿈)은 **계산값을 바꾸지 않고** 이력에만 남깁니다 (팀 결정 필요).

```python
256      run = _run()
257      if run is None:
258          return _bad("분석 결과 없음", 404)
259      ai = _level(run["result"], cluster_id)
260      if ai is None:
261          return _bad(f"군집 없음: {cluster_id}", 404)
262      stage = (request.get_json(silent=True) or {}).get("stage")
263      if stage is not None and (not isinstance(stage, int) or isinstance(stage, bool) or stage not in C.LEVELS):
264          return _bad("stage 는 1~4 정수 또는 null", 400)
```
→ 분석 결과·군집 확인, 단계는 1~4 정수 또는 null(AI 권고로 되돌림).

```python
265      before = run["stages"].get(cluster_id)
266      recorded = _log_action(_video(run["result"]), cluster_id, "stage", before, stage, before or ai, stage or ai)
267      if stage is None:
268          run["stages"].pop(cluster_id, None)
269      else:
270          run["stages"][cluster_id] = stage
271      return jsonify(cluster_id=cluster_id, stage=stage, ai_level=ai, recorded=recorded)
```
→ 조치 기록: 항목 'stage', 전→후 단계(없으면 AI 단계). 화면 상태 `stages` 에 저장하고 기록 여부(`recorded`)를 돌려줍니다.

### GET `/api/clusters/<cluster_id>/history` — 판정·조치 이력 (__init__.py:274~285)

```python
277      video = request.args.get("video") or STATE["current"]
278      if video is None:
279          return _bad("분석 결과 없음", 404)
280      try:
281          events = rl.history(rl.cluster_key(video, cluster_id))
282      except Exception as e:
283          log.warning("이력 조회 실패: %s", e)
284          return _bad("기록 DB 를 읽지 못함", 503)
285      return jsonify(cluster_id=cluster_id, video=video, events=events)
```
→ `?video=`(없으면 지금 영상)의 그 군집 이력을 `rl.history` 로 시간순 조회. DB 를 못 읽으면 503.

### GET `/api/unknowns`, `/api/unknowns/<group_id>`, `/unknowns` (__init__.py:288~316)

```python
288  def _crop_urls(rows, key="path"):
289      for r in rows:
290          r["url"] = url_for("static", filename=r[key]) if r.get(key) else None
291      return rows
```
→ DB 에 저장된 crop 경로(static 기준)를 브라우저 주소로 바꿉니다.

```python
294  @bp.get("/api/unknowns")
295  def unknowns():
296      """Unknown 그룹 순위 (open, 위협도 기준 이상, priority 순)."""
297      limit = request.args.get("limit", C.UNKNOWN_RANK_TOP, type=int)
298      groups = registry.ranking(max(1, min(limit, 200)))
299      return jsonify(groups=_crop_urls(groups, "cover"))
```
→ 미확인 그룹 순위. `limit` 은 1~200 으로 제한(너무 큰 요청 방지).

```python
302  @bp.get("/api/unknowns/<group_id>")
303  def unknown_detail(group_id):
304      """Unknown 그룹 상세: 그룹, 출현 기록(위치), crop, 병합 후보."""
305      d = registry.detail(group_id)
306      if d is None:
307          return _bad(f"그룹 없음: {group_id}", 404)
308      _crop_urls([d["group"]], "cover")
309      _crop_urls(d["crops"])
310      return jsonify(d)
```
→ 그룹 상세(그룹·출현 기록·crop). 없으면 404.

```python
313  @bp.get("/unknowns")
314  def unknowns_page():
315      """분석관 화면. 데이터는 JS 가 /api/unknowns 로 가져온다."""
316      return render_template("dashboard/unknowns.html")
```
→ 분석관 화면 HTML. 데이터는 `unknowns.js` 가 위 두 API 로 가져옵니다.

### 보고서용 도우미 — `ITEM_NAMES`, `_value_text`, `_cluster_records` (__init__.py:319~350)

```python
319  ITEM_NAMES = {"tactic": "전술", "commander": "지휘전차", "core_target": "핵심표적", "stage": "단계 조정"}
```
→ 조치 항목 → 한국어 이름 (전술·지휘전차·핵심표적·단계 조정).

```python
322  def _value_text(item, v):
323      """조치 전·후 값 → 보고서 문구."""
324      if v is None:
325          return "자동 (AI)" if item in ("tactic", "stage") else "없음"
326      if item == "tactic":
327          return f"{v}. {TACTIC_NAMES.get(v, '')}"
328      if item == "stage":
329          return f"{v}단계"
330      if item == "commander":
331          return f"{v['tracking_id']} {'지휘전차' if v['is_commander'] else '지휘전차 아님'}"
332      if item == "core_target":
333          return f"{v['tracking_id']} {'지정' if v['core'] else '해제'}"
334      return str(v)
```
→ 조치 전·후 값을 보고서 문구로. 예: 전술 3 → '3. 대전차', 핵심표적 → 'Tank-01 지정'.

```python
337  def _cluster_records(run):
338      """보고서용 군집별 'AI 판정 → 지휘관 조치 → 최종 단계'와 조치 이력 (DB commander_override). DB 를 못 읽으면 이력 없이."""
339      out = []
340      for c in run["result"]["clusters"]:
341          try:
342              events = rl.history(rl.cluster_key(_video(run["result"]), c["cluster_id"]))
343          except Exception as e:
344              log.warning("보고서 이력 조회 실패: %s", e)
345              events = None
346          actions = [dict(e, item_name=ITEM_NAMES.get(e["item"], e["item"]), before_text=_value_text(e["item"], e["before"]),
347                          after_text=_value_text(e["item"], e["after"])) for e in events or [] if e["kind"] == "조치"]
348          out.append({"cluster": c, "ai": c["level_before_override"], "calc": c["level"],
349                      "final": run["stages"].get(c["cluster_id"]) or c["level"], "actions": actions, "db": events is not None})
350      return out
```
→ 군집마다 'AI 판정 단계(조치 전) → 지휘관 조치 → 최종 단계' 와 조치 목록을 DB 이력에서 만듭니다. 최종 단계는 단계 조정이 있으면 그 값, 없으면 계산 단계.

### GET `/report` — 보고서 (__init__.py:353~363)

```python
356      run = _run()
357      if run is None:
358          return _bad("분석 결과 없음", 404)
359      stage = request.args.get("stage", type=int)                         # 숫자가 아니면 None
360      if stage not in C.LEVELS:                                           # 1~4 가 아니면 무시
361          stage = None
```
→ 지금 영상 결과로 보고서를 만듭니다. `?stage=` 가 1~4 면 '지휘관 결정 N단계'를 함께 표시.

```python
362      return render_template("dashboard/report.html", r=run["result"], stage=stage, levels=C.LEVELS,
363                             records=_cluster_records(run), generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
```
→ `report.html` 틀에 결과·단계·군집별 조치 기록·작성 시각을 넣어 인쇄용 페이지를 돌려줍니다.

