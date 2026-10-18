# dashboard/__init__.py — 화면·API 주소 (Flask Blueprint)

파일: `dashboard/__init__.py` (전체 226줄)

브라우저가 부르는 **주소(URL)** 와 그 주소에서 실행할 함수를 정하는 파일입니다. 계산은 하지 않고 `threat/` 패키지에 맡깁니다.

- **Flask**: 파이썬 웹 서버 라이브러리. `@bp.get("/주소")` 처럼 함수 위에 붙인 줄을 **데코레이터**(함수에 기능을 덧붙이는 표시)라 하며, "이 주소로 GET 요청이 오면 아래 함수를 실행"이라는 뜻입니다.
- **Blueprint**: 주소 묶음. `app.py:12` 에서 앱에 등록합니다.
- **GET** 은 읽기, **POST** 는 새로 만들기(분석 실행), **PATCH** 는 일부 수정(전술·지휘전차 변경).
- 응답은 JSON. 오류는 `{"error": "이유"}` 와 상태 코드(400 잘못된 요청, 404 없음).

### 머리말 — 주소 목록 (__init__.py:1~14)

```python
  3  주소
  4    GET   /                                   대시보드 화면 (templates/dashboard/index.html)
  5    POST  /api/analyze                        탐지 결과 분석 (본문 비우면 샘플 영상 A → B) → AnalysisResult + videos
  6    GET   /api/threats[?video=이름]           마지막 분석 결과 (video 를 주면 그 영상으로 화면 전환, 분석 전이면 404)
  7    GET   /api/threats/<tracking_id>          표적 1건 + 소속 군집
  8    PATCH /api/clusters/<cluster_id>/tactic   군집 전술 지정 {"tactic": 1~10 또는 null(자동)} → 재분석 결과
  9    PATCH /api/threats/<tracking_id>/commander 지휘전차 지정·해제 {"is_commander": true|false|null(자동)} → 재분석 결과
 10    GET   /api/unknowns?limit=20              Unknown 그룹 순위
 11    GET   /api/unknowns/<group_id>            Unknown 그룹 상세 (출현 기록, crop, 병합 후보)
 12    GET   /unknowns                           분석관 화면 (Unknown 그룹 순위·crop 갤러리·출현 지도)
 13    GET   /report?stage=N                     인쇄용 보고서 (stage = 지휘관이 조정한 단계, 없으면 AI 권고)
```
→ 이 파일이 제공하는 주소 전체. 자세한 요청·응답 예시는 `정리/08_API_명세.md`.

### import, Blueprint, 서버 상태(STATE) (__init__.py:15~38)

```python
 15  import json
 16  import logging
 17  from datetime import datetime  # 보고서 작성 시각
 19  from flask import Blueprint, jsonify, render_template, request, url_for
 21  from . import media, threat          # crop 저장, 위협도 계산 패키지 (dashboard/threat/)
 22  from .threat import track as TR      # v2 입력 판별
 23  from . import unknown_registry as registry
 24  from .threat import config as C      # 단계 이름 (LEVELS), 전술 가중치 목록
 25  from .threat.core import TACTIC_NAMES  # 전술 번호 → 이름
 26  from .threat.pipeline import MOCK_V2   # 기본 샘플 (영상 A, B)
```
→ 필요한 도구를 가져옵니다. `media`(crop 저장), `threat`(계산), `registry`(미확인 레지스트리), `MOCK_V2`(샘플 영상 A·B 경로).

```python
 28  bp = Blueprint("dashboard", __name__,
 29                 template_folder="templates",            # dashboard/templates/dashboard/*.html
 30                 static_folder="static",                 # dashboard/static/dashboard.js, dashboard.css
 31                 static_url_path="/dashboard-static")    # 브라우저 주소: /dashboard-static/dashboard.js
 32  log = logging.getLogger(__name__)
```
→ Blueprint 생성. 이 폴더의 `templates/`(HTML 틀)·`static/`(JS·CSS)을 쓰며, JS·CSS 는 브라우저에서 `/dashboard-static/...` 주소로 열립니다.

```python
 34  # 서버 메모리 상태 (요청 사이에 유지). 영상마다 분석 1건(run)을 들고 있고, 화면은 current 영상을 본다.
 35  # ponytail: 프로세스 메모리 — 서버 재시작 시 사라지고 사용자 간 공유됨. 다중 사용자면 DB(cluster_assessment) 저장으로.
 36  #   (Unknown 레지스트리는 DB 라 재시작해도 남는다)
 37  STATE = {"runs": {},       # 영상 이름 → {"payload", "prev", "result", "overrides": {군집: 전술}, "commanders": {표적: bool}}
 38           "current": None}  # 화면에 보이는 영상 이름
```
→ **STATE**: 서버 메모리에 영상별 분석 결과(run)를 들고 있는 딕셔너리. 서버를 끄면 사라지고 모든 사용자가 같은 값을 봅니다 (**한계**, 12번 문서). 미확인 레지스트리는 DB 라 남습니다.

### 도우미 함수 `_bad`, `_video`, `_run` (__init__.py:41~52)

```python
 41  def _bad(e, code):
 42      """오류를 JSON 으로 돌려준다 (화면이 error 메시지를 배너로 보여줌)."""
 43      return jsonify(error=str(e)), code
```
→ 오류 응답 만들기: `{"error": 메시지}` + 상태 코드. 화면은 이 메시지를 빨간 배너로 보여 줍니다.

```python
 46  def _video(payload):
 47      return str((payload.get("source") or {}).get("video") or "영상")
```
→ 입력의 영상 이름(없으면 '영상').

```python
 50  def _run(video=None):
 51      """?video= 로 고른 영상(없으면 지금 영상)의 run. 분석 전이면 None."""
 52      return STATE["runs"].get(video or request.args.get("video") or STATE["current"])
```
→ 주소의 `?video=` 로 고른 영상, 없으면 지금 화면 영상의 run 을 찾습니다.

### 함수 `_attach(result, new)` — crop 주소·미확인 그룹 붙이기 (__init__.py:55~71)

이 부분이 하는 일: 계산 결과(`pipeline.analyze`)에 파일·DB 작업 결과를 붙입니다. 계산 코드를 순수하게 두려고 저장 작업을 여기로 뺐습니다.

```python
 59      for t in result["targets"]:
 60          if "_track" not in t:
 61              continue
```
→ v2 표적(`_track` 이 있는 것)만 처리합니다.

```python
 62          crop = media.track_crop(video, t)
 63          t["crop_url"] = url_for("static", filename=crop) if crop else None
```
→ 대표 crop 을 저장(`media.track_crop`)하고 브라우저 주소(`/static/track_crops/...`)를 붙입니다.

```python
 64          if t["status"] == "Unknown":
 65              try:
 66                  info = registry.record(video, t, result["source"]) if new else {"group_id": registry.lookup(video, t["tracking_id"])}
 67                  t["unknown_group_id"] = info and info["group_id"]
```
→ Unknown 이면: 새 분석일 때 레지스트리에 저장(`registry.record`), 재계산일 때는 저장된 그룹만 찾기(`registry.lookup`).

```python
 68              except Exception as e:                                     # 레지스트리 DB 가 꺼져 있어도 대시보드는 보여 준다
 69                  log.warning("Unknown 레지스트리 저장 실패 (%s %s): %s", video, t["tracking_id"], e)
```
→ 레지스트리 DB 가 꺼져 있어도 대시보드는 보이도록 오류를 기록만 하고 넘어갑니다 (**try/except**: 오류가 나면 except 부분 실행).

```python
 70          del t["_track"]
 71      return result
```
→ 내부 필드 `_track`(임베딩 등 큰 데이터)은 화면으로 보내기 전에 지웁니다.

### 함수 `_reanalyze`, `_respond` (__init__.py:74~85)

```python
 74  def _reanalyze(run, overrides=None, commanders=None):
 75      """같은 입력을 지정 전술·지휘전차만 바꿔 다시 계산 (실패하면 예외, run 은 그대로)."""
 76      ov = run["overrides"] if overrides is None else overrides
 77      cm = run["commanders"] if commanders is None else commanders
 78      result = _attach(threat.analyze(run["payload"], run["prev"], ov, cm), new=False)
 79      run.update(overrides=ov, commanders=cm, result=result)
 80      return result
```
→ 같은 입력을 지정 전술·지휘전차만 바꿔 다시 계산하고 run 을 갱신합니다. 계산이 실패하면 예외가 나서 run 은 그대로 남습니다.

```python
 83  def _respond(result):
 84      """화면 응답 = 분석 결과 + 분석해 둔 영상 목록·지금 영상 (A/B 탭)."""
 85      return jsonify(dict(result, videos=list(STATE["runs"]), video=STATE["current"]))
```
→ 응답 = 분석 결과 + 분석한 영상 목록(`videos`) + 지금 영상(`video`). 화면의 A/B 탭이 이 값을 씁니다.

### GET `/` — 대시보드 화면 (__init__.py:88~92)

```python
 91      tactics = [(n, TACTIC_NAMES[n]) for n in sorted(C.TACTIC_WEIGHTS)]  # 가중치가 있는 전술 (1~10번)
 92      return render_template("dashboard/index.html", tactics=tactics)
```
→ 전술 선택 목록(1~10번)만 채워 HTML 을 돌려줍니다. 나머지 데이터는 화면이 열린 뒤 JS 가 API 로 가져옵니다.

### POST `/api/analyze` — 분석 실행 (__init__.py:95~114)

이 부분이 하는 일: 본문이 있으면 그 탐지 결과 1건, 없으면 샘플 영상 A → B 를 분석합니다. 두 영상을 다 넣어야 영상 간 미확인 그룹 묶음이 보입니다.

```python
 98      body = request.get_json(silent=True)
 99      payloads = [body] if body else [json.loads(f.read_text(encoding="utf-8")) for f in MOCK_V2]
```
→ 본문 JSON 을 읽고(`silent=True`: JSON 이 아니어도 오류 대신 None), 없으면 mock 파일 2개를 읽습니다.

```python
100      results = []
101      try:
102          for p in payloads:                                              # 먼저 전부 계산 (입력 오류면 상태를 안 바꿈)
103              if not isinstance(p, dict):
104                  raise ValueError("본문은 JSON 객체")
105              run = STATE["runs"].get(_video(p))
106              prev = run["result"] if run else None                       # 같은 영상의 직전 결과 → '신규' 표적 판단
107              results.append((p, prev, threat.analyze(p, prev)))          # 새 입력은 지정 전술·지휘전차 없이 시스템 추정부터
108      except ValueError as e:
109          return _bad(e, 400)                                             # 입력 형식 오류
```
→ 먼저 전부 계산만 합니다. 하나라도 입력 오류(ValueError)면 400 을 돌려주고 서버 상태는 그대로 둡니다. 같은 영상의 직전 결과를 '신규' 판단에 씁니다.

```python
110      for p, prev, result in results:
111          STATE["runs"][_video(p)] = {"payload": p, "prev": prev, "result": _attach(result, new=True),
112                                      "overrides": {}, "commanders": {}}
```
→ 계산이 모두 성공하면 crop·레지스트리 저장(`_attach(new=True)`) 후 영상별로 저장합니다. 지정 전술·지휘전차는 초기화.

```python
113      STATE["current"] = _video(payloads[0])                              # 화면은 첫 영상부터
114      return _respond(STATE["runs"][STATE["current"]]["result"])
```
→ 화면은 첫 영상(A)부터 보여 줍니다.

### GET `/api/threats` — 마지막 결과 / 영상 전환 (__init__.py:117~128)

```python
120      video = request.args.get("video")
121      if video and video not in STATE["runs"]:
122          return _bad(f"분석한 적 없는 영상: {video}", 404)
123      if video:
124          STATE["current"] = video
```
→ `?video=` 가 있으면 그 영상으로 전환(분석한 적 없으면 404).

```python
125      run = _run()
126      if run is None:
127          return _bad("분석 결과 없음. POST /api/analyze 먼저 실행", 404)  # 화면은 404 를 받으면 자동으로 분석 요청
128      return _respond(run["result"])
```
→ 결과가 없으면 404. 화면은 404 를 받으면 자동으로 분석을 요청합니다(`dashboard.js:59~60`).

### GET `/api/threats/<tracking_id>` — 표적 1건 (__init__.py:131~138)

```python
134      result = (_run() or {}).get("result") or {"targets": [], "clusters": []}
135      t = next((t for t in result["targets"] if t["tracking_id"] == tracking_id), None)
136      if t is None:
137          return _bad(f"표적 없음: {tracking_id}", 404)
138      return jsonify(target=t, cluster=next(c for c in result["clusters"] if c["cluster_id"] == t["cluster_id"]))
```
→ 지금 영상 결과에서 그 표적과 소속 군집을 찾아 돌려줍니다. 없으면 404.

### PATCH `/api/clusters/<cluster_id>/tactic` — 전술 선택 (__init__.py:141~160)

이 부분이 하는 일: 지휘관이 군집 전술을 1~10번 중에서 고르면 그 군집 전차 위협도와 대응단계를 다시 계산합니다. null 이면 자동 추정으로 되돌립니다.

```python
147      tactic = (request.get_json(silent=True) or {}).get("tactic")       # 1~10 또는 None
148      overrides = dict(run["overrides"])                                  # 실패하면 원래 값 유지하도록 복사본에 적용
149      if tactic is None:
150          overrides.pop(cluster_id, None)                                 # 지정 해제
151      elif isinstance(tactic, int) and not isinstance(tactic, bool):
152          overrides[cluster_id] = tactic
153      else:
154          return _bad("tactic 은 1~10 정수 또는 null", 400)
```
→ 복사본(`dict(...)`)에 바꿔 넣습니다. 숫자가 아니면 400. 실패해도 원래 값이 그대로 남게 하려는 것.

```python
155      try:
156          return _respond(_reanalyze(run, overrides=overrides))
157      except LookupError as e:
158          return _bad(e, 404)                                             # 없는 군집
159      except ValueError as e:
160          return _bad(e, 400)                                             # 가중치 없는 전술 번호
```
→ 재계산. 없는 군집이면 404(LookupError), 가중치 없는 번호(11 등)면 400(ValueError).

### PATCH `/api/threats/<tracking_id>/commander` — 지휘전차 지정·해제 (__init__.py:163~182)

이 부분이 하는 일: 안테나 오탐·누락을 지휘관이 바로잡습니다. true/false 는 지정/해제, null 은 탐지 규칙으로 되돌림. v2 입력에서만.

```python
166      run = _run()
167      if run is None:
168          return _bad("분석 결과 없음", 404)
169      if not TR.is_v2(run["payload"]):
170          return _bad("지휘전차 수정은 프레임 단위(v2) 입력에서만", 400)
171      if not any(t["tracking_id"] == tracking_id for t in run["result"]["targets"]):
172          return _bad(f"표적 없음: {tracking_id}", 404)
```
→ 분석 결과·v2 여부·표적 존재를 확인.

```python
173      body = request.get_json(silent=True)
174      value = body.get("is_commander", "없음") if isinstance(body, dict) else "없음"
175      if value is not None and not isinstance(value, bool):
176          return _bad("is_commander 는 true, false, null", 400)
```
→ 값이 true/false/null 이 아니면 400. 본문에 키가 없으면 '없음'(문자열)이 되어 역시 400.

```python
177      commanders = dict(run["commanders"])
178      if value is None:
179          commanders.pop(tracking_id, None)
180      else:
181          commanders[tracking_id] = value
182      return _respond(_reanalyze(run, commanders=commanders))
```
→ 복사본에 반영하고 재계산. 군집 전술이 지휘통제↔기동으로 바뀔 수 있어 군집 전체 점수가 달라집니다.

### GET `/api/unknowns`, `/api/unknowns/<group_id>`, `/unknowns` (__init__.py:185~213)

```python
185  def _crop_urls(rows, key="path"):
186      for r in rows:
187          r["url"] = url_for("static", filename=r[key]) if r.get(key) else None
188      return rows
```
→ DB 에 저장된 crop 경로(static 기준)를 브라우저 주소로 바꿉니다.

```python
191  @bp.get("/api/unknowns")
192  def unknowns():
193      """Unknown 그룹 순위 (open, 위협도 기준 이상, priority 순)."""
194      limit = request.args.get("limit", C.UNKNOWN_RANK_TOP, type=int)
195      groups = registry.ranking(max(1, min(limit, 200)))
196      return jsonify(groups=_crop_urls(groups, "cover"))
```
→ 미확인 그룹 순위. `limit` 은 1~200 으로 제한(너무 큰 요청 방지).

```python
199  @bp.get("/api/unknowns/<group_id>")
200  def unknown_detail(group_id):
201      """Unknown 그룹 상세: 그룹, 출현 기록(위치), crop, 병합 후보."""
202      d = registry.detail(group_id)
203      if d is None:
204          return _bad(f"그룹 없음: {group_id}", 404)
205      _crop_urls([d["group"]], "cover")
206      _crop_urls(d["crops"])
207      return jsonify(d)
```
→ 그룹 상세(그룹·출현 기록·crop). 없으면 404.

```python
210  @bp.get("/unknowns")
211  def unknowns_page():
212      """분석관 화면. 데이터는 JS 가 /api/unknowns 로 가져온다."""
213      return render_template("dashboard/unknowns.html")
```
→ 분석관 화면 HTML. 데이터는 `unknowns.js` 가 위 두 API 로 가져옵니다.

### GET `/report` — 보고서 (__init__.py:216~226)

```python
219      run = _run()
220      if run is None:
221          return _bad("분석 결과 없음", 404)
222      stage = request.args.get("stage", type=int)                         # 숫자가 아니면 None
223      if stage not in C.LEVELS:                                           # 1~4 가 아니면 무시
224          stage = None
```
→ 지금 영상 결과로 보고서를 만듭니다. `?stage=` 가 1~4 면 '지휘관 결정 N단계'를 함께 표시.

```python
225      return render_template("dashboard/report.html", r=run["result"], stage=stage, levels=C.LEVELS,
226                             generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
```
→ `report.html` 틀에 결과·단계·작성 시각을 넣어 인쇄용 페이지를 돌려줍니다.

