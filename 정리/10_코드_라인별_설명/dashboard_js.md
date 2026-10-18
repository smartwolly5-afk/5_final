# dashboard.js — 대시보드 화면 동작 (브라우저 JavaScript)

파일: `dashboard/static/dashboard.js` (전체 449줄)

브라우저에서 돌아가는 화면 코드입니다. **계산은 하지 않고**, 서버 API 응답(JSON)을 받아 표·박스·패널·지도를 그립니다.

흐름: `init()` → `fetchResult()`(API 호출) → `load(결과)` → `render()` → `renderBoxes` / `renderCountBar` / `renderTable` / `renderPanelA` / `renderMap` → 1위 표적 `selectTarget` → `renderPanelB`

JavaScript 문법 메모 (처음 나올 때 한 번만 설명)
- `const`/`let`: 변수 선언 (`const` 는 다시 대입 불가).
- `(x) => ...`: **화살표 함수**(짧은 함수 표기).
- `` `글자 ${값}` ``: **템플릿 문자열**(글자 안에 값 끼워 넣기).
- `async`/`await`: 서버 응답처럼 시간이 걸리는 일을 **기다렸다가** 다음 줄을 실행.
- `fetch(url)`: 브라우저가 서버에 HTTP 요청을 보내는 기본 함수.
- `$("id")`: 이 파일에서 만든 도우미. HTML 에서 그 id 의 요소를 찾습니다.

### 표시용 상수 (dashboard.js:6~14)

```javascript
  7  const STAGE_LABEL = { 1: "1단계 · 즉시 보고", 2: "2단계 · 우선 감시", 3: "3단계 · 지속 감시", 4: "4단계 · 관심" };  // 군집 대응단계 긴 이름
  8  const STAGE_SHORT = { 1: "1단계", 2: "2단계", 3: "3단계", 4: "4단계" };                                           // 짧은 이름
  9  const GRADE_CLASS = { "매우 높음": "g1", "높음": "g2", "보통": "g3", "낮음": "g4" };                                // 전차 위협도 단계 → CSS 색 클래스
 10  const STAT_LABEL = { firepower: "화력", mobility: "기동력", protection: "방호력" };                                  // 상세 막대 이름
 11  const BAR_MAX = 150;                                                                                              // 상세 막대 100% = 기준전차의 1.5배
```
→ 단계 이름, 위협도 단계 → CSS 색 클래스, 막대 이름. `BAR_MAX = 150`: 상세 막대 100% = 기준전차(100)의 1.5배.

```javascript
 12  const STATUS = {                                                                                                  // 판정 상태 → 표시 이름·배지 클래스
 13      Known: ["Known", "known"], Known_Variant: ["계열 확정", "variant"], Unknown: ["미확인", "unknown"] };
 14  const PART_LABEL = { antenna: "안테나", cope_cage: "cope cage" };                                                  // 부품 이름
```
→ 판정 상태 → 화면 이름과 배지 색 클래스(Known 파랑, 계열 확정 회색, 미확인 보라), 부품 이름.

### 화면 상태 변수 (dashboard.js:16~22)

```javascript
 17  let data = null;              // 마지막 API 응답 (AnalysisResult — threat/pipeline.py 머리말 참고)
 18  let targets = [];             // data.targets (랭킹 순서)
 19  let selectedId = null;        // 선택된 표적 tracking_id
 20  let hasManualSelection = false; // 사용자가 직접 골랐는지 (아니면 1위 자동 선택)
 21  let commanderStage = null;    // '단계 조정'으로 지휘관이 바꾼 단계 (null = AI 권고 그대로)
 22  let map = null, mapLayer = null, markers = {};  // Leaflet 지도, 마커 레이어, tracking_id → 마커
```
→ 마지막 응답(`data`), 표적 목록, 선택된 표적, 직접 골랐는지, 지휘관이 조정한 단계(서버에 보내지 않는 화면 전용 값), 지도 객체.

### 짧은 도우미 함수 (dashboard.js:24~32)

```javascript
 25  const $ = (id) => document.getElementById(id);                                       // id 로 요소 찾기
 26  const pad = (n) => String(n).padStart(2, "0");                                         // 두 자리 숫자
 27  const now = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };  // 현재 시각
```
→ id 로 요소 찾기, 두 자리 숫자, 지금 시각.

```javascript
 28  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));  // HTML 이스케이프 (API 값은 외부 입력)
```
→ **HTML 이스케이프**: `<` 같은 글자를 `&lt;` 로 바꿔, 서버(외부 입력)에서 온 문자열이 HTML 코드로 실행되지 않게 합니다(**XSS** 방지 — 남이 넣은 스크립트가 실행되는 공격).

```javascript
 29  const aiStage = () => (data ? data.alert.level : 4);                                   // AI 권고 단계 (가장 심각한 군집)
 30  const effectiveStage = () => (commanderStage != null ? commanderStage : aiStage());    // 화면에 쓰는 단계 (지휘관 조정 우선)
```
→ AI 권고 단계(서버 값), 화면에 쓸 단계(지휘관이 조정했으면 그 값).

```javascript
 31  const modelName = (t) => t.model || t.unknown_group_id || "미확인";                    // 기종명 없으면 미확인 그룹 ID, 그것도 없으면 '미확인'
 32  const stageColor = (lv) => getComputedStyle(document.documentElement).getPropertyValue(`--stage${lv}`).trim();  // CSS 변수 색 (지도용)
```
→ 표시 이름: 기종명 → 없으면 미확인 그룹 ID → 없으면 '미확인'. 단계 색은 CSS 변수에서 읽습니다(지도 색을 CSS 와 맞추려고).

### 함수 `init()` — 시작 (dashboard.js:35~65)

이 부분이 하는 일: 페이지가 열리면(맨 아래 449줄) 한 번 실행. 버튼마다 동작을 연결하고 지도를 준비한 뒤 결과를 가져옵니다.

```javascript
 36      $("analyze-btn").addEventListener("click", () => fetchResult("/api/analyze", { method: "POST" }));  // 분석 시작 = 새 분석
 37      $("pa-confirm").addEventListener("click", confirmPanelA);                                          // 확인 = 배너·깜빡임 끄기
 38      $("pa-adjust").addEventListener("click", () => togglePicker("stage-pick"));                        // 단계 조정 펼치기
 39      $("pa-tactic").addEventListener("click", () => togglePicker("tactic-pick"));                       // 전술 선택 펼치기
 40      $("pa-report").addEventListener("click", openReport);                                              // 보고서 출력
```
→ `addEventListener("click", 함수)`: 클릭하면 그 함수를 실행. 분석 시작·확인·단계 조정·전술 선택·보고서 버튼.

```javascript
 41      $("stage-pick").addEventListener("click", (e) => {                                                 // 단계 버튼 클릭
 42          const stage = e.target.dataset.stage;                                                          // data-stage 값
 43          if (!stage) return;                                                                            // 버튼 바깥 클릭은 무시
 44          commanderStage = Number(stage) === aiStage() ? null : Number(stage);                           // AI 권고와 같으면 조정 해제
 45          $("stage-pick").hidden = true;                                                                 // 고르고 나면 단계 버튼 줄 닫기
 46          renderPanelA();                                                                                // 사다리·'지휘관 결정' 문구 다시 그림
 47          fetch(`/api/clusters/${encodeURIComponent(data.alert.cluster_id)}/stage`, {                    // 이력에만 기록 (계산값은 그대로)
```
→ 단계 조정: 고른 단계를 화면 상태에 저장하고 사다리를 다시 그립니다. AI 권고와 같은 단계를 고르면 조정 해제.

```javascript
 48              method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage: commanderStage }),
 49          }).catch(() => {});                                                                            // 기록 실패해도 화면은 그대로
 50      });
```
→ 그 단계를 `POST /api/clusters/<가장 심각한 군집>/stage` 로 **이력에만 기록**합니다 (계산값은 그대로). 기록에 실패해도 화면은 그대로(`.catch`).

```javascript
 51      $("tp-cluster").addEventListener("change", syncTacticSelect);                                      // 군집 바꾸면 현재 전술 표시
 52      $("tp-apply").addEventListener("click", applyTactic);                                              // 전술 적용
 53      $("alert-banner-close").addEventListener("click", hideBanner);                                     // 배너 닫기
 54      $("pb-commander").addEventListener("click", toggleCommander);                                      // 지휘전차 지정·해제
 55      $("pb-core").addEventListener("click", toggleCore);                                                // 핵심표적 지정·해제
```
→ 전술 선택 목록·적용 버튼, 배너 닫기, 지휘전차 지정·해제, 핵심표적 지정·해제 버튼.

```javascript
 56      $("video-tabs").addEventListener("click", (e) => {                                                 // 영상 A/B 탭
 57          const v = e.target.dataset.video;
 58          if (v && v !== data.video) fetchResult(`/api/threats?video=${encodeURIComponent(v)}`, {});
 59      });
```
→ 영상 A/B 탭: 지금과 다른 영상을 누르면 `/api/threats?video=...` 로 전환.

```javascript
 60      new ResizeObserver(fitFrame).observe($("video"));                                                  // 영상 칸 크기가 바뀌면 프레임 크기 다시 맞춤
 61      initMap();                                                                                         // 지도 준비
```
→ 영상 칸 크기가 바뀌면 프레임 크기를 다시 맞추고(`ResizeObserver`), 지도를 만듭니다.

```javascript
 63      const ok = await fetchResult("/api/threats", {}, true);                                            // 마지막 결과 가져오기
 64      if (!ok) await fetchResult("/api/analyze", { method: "POST" });                                    // 없으면(서버 첫 실행) 바로 분석
```
→ 마지막 결과를 가져오고, 없으면(서버를 막 켰을 때 404) 바로 분석을 요청합니다.

### 함수 `togglePicker(id)` — 펼침 영역 (dashboard.js:67~72)

```javascript
 68      const other = id === "stage-pick" ? "tactic-pick" : "stage-pick";   // 두 펼침 영역은 하나만 열림
 69      $(other).hidden = true;                                              // 다른 쪽은 닫고
 70      $(id).hidden = !$(id).hidden;                                        // 누른 쪽은 열려 있으면 닫고, 닫혀 있으면 엶
 71      if (id === "tactic-pick") syncTacticSelect();                        // 열 때 선택 군집의 현재 전술로 맞춤
```
→ '단계 조정'·'전술 선택' 펼침 영역은 하나만 열리게. 전술 선택을 열 때 현재 전술로 맞춤.

### 함수 `fetchResult(url, opts, quiet404)` — API 호출 (dashboard.js:75~87)

```javascript
 76      try {                                                                // 네트워크 오류·서버 오류를 아래 catch 에서 한꺼번에 처리
 77          const res = await fetch(url, opts);                              // 요청
 78          if (quiet404 && res.status === 404) return false;                // '분석 결과 없음'은 조용히 넘김
 79          const body = await res.json();                                   // JSON 응답
 80          if (!res.ok) throw new Error(body.error || res.status);          // 서버 오류 메시지
 81          load(body);                                                      // 화면 갱신
 82          return true;                                                     // 성공
```
→ 요청 → JSON → 오류 상태면 서버 메시지로 오류 발생, 정상이면 `load` 로 화면 갱신. `try { } catch { }` 는 오류가 나면 catch 부분을 실행하는 문법.

```javascript
 83      } catch (err) {                                                      // 실패하면
 84          showBanner(`분석 결과를 불러오지 못했습니다: ${err.message}`);   // 오류는 상단 배너로
 85          return false;                                                    // 실패
 86      }
```
→ 실패하면 화면 맨 위 빨간 배너에 이유를 보여 줍니다.

### 함수 `load(result)` — 새 결과 반영 (dashboard.js:89~106)

```javascript
 90      data = result;                                                       // 새 결과 저장
 91      targets = result.targets;                                            // 표적 목록 (서버가 랭킹 순서로 정렬해 보냄)
 92      commanderStage = null;                                               // 새 계산이 오면 지휘관 단계 조정 해제
```
→ 응답을 저장하고 지휘관 단계 조정을 풉니다(새 계산이 왔으므로).

```javascript
 93      $("src-video").textContent = result.source.video || "";              // 파일 이름
 94      renderTabs();                                                        // 영상 A/B 탭
 95      const img = $("frame-img");                                          // 원본 프레임 (v2 입력만)
 96      img.hidden = !result.source.frame_image;
 97      if (result.source.frame_image) img.src = `/static/${result.source.frame_image}`;
 98      fitFrame();
 99      $("video-meta").textContent = `${result.source.captured_at || ""} (${result.source.source || ""})`;  // 촬영일 (출처)
```
→ 영상 이름·탭, 원본 프레임 이미지(`/static/mock_frames/...`), 프레임 크기 맞춤, 촬영일.

```javascript
100      if (!targets.some((t) => t.tracking_id === selectedId)) hasManualSelection = false;  // 선택 표적이 사라지면 자동 선택으로
101      render();                                                            // 표·박스·패널·지도 전부 다시 그림
```
→ 선택했던 표적이 사라졌으면 자동 선택으로 돌리고 전체를 다시 그립니다.

```javascript
103      const { level, prev_level: prev } = result.alert;                    // 지금 단계와 직전 분석 단계 꺼내기
104      if (result.alert.banner) showBanner(`⚠ ${STAGE_LABEL[level]} — ${result.alert.message}`);  // 1단계면 배너
105      if (prev != null && level < prev) flashPanelA();                     // 단계가 올라갔으면 상황 패널 깜빡임
```
→ 1단계면 배너, 단계가 올라갔으면 상황 패널 깜빡임.

### 함수 `render()` — 전체 다시 그리기 (dashboard.js:109~117)

```javascript
110      renderBoxes();                                                       // 영상 위 박스
111      renderCountBar();                                                    // 상단 카운터
112      const ranked = renderTable();                                        // 랭킹 표
113      renderPanelA();                                                      // 상황 패널 (군집 대응단계)
114      renderMap();                                                         // 미니맵
115      if (!hasManualSelection && ranked.length) selectTarget(ranked[0].tracking_id, { auto: true });  // 1위 자동 선택
116      else if (selectedId) selectTarget(selectedId, { auto: true });      // 기존 선택 유지
```
→ 박스 → 카운터 → 랭킹 표 → 상황 패널 → 지도 순서로 그린 뒤, 직접 고른 표적이 없으면 1위를 자동 선택.

### 함수 `renderTabs()`, `fitFrame()` — 영상 탭·프레임 크기 (dashboard.js:120~134)

```javascript
120  function renderTabs() {                                                  // 분석한 영상이 2개 이상이면 탭으로 전환
121      const videos = data.videos || [];
122      $("video-tabs").hidden = videos.length < 2;
123      $("video-tabs").innerHTML = videos.map((v) => `<button type="button" role="tab" data-video="${esc(v)}"
124          aria-selected="${v === data.video}">${esc(v.replace(/\.[^.]+$/, ""))}</button>`).join("");  // 확장자는 빼고 표시
125  }
```
→ 영상이 2개 이상이면 탭 버튼을 만듭니다. 이름은 확장자(.mp4)를 뺀 값.

```javascript
127  function fitFrame() {                                                    // 프레임을 원본 비율 그대로 영상 칸 안에 최대 크기로 (박스 % 좌표가 사진과 맞게)
128      const frame = $("frame"), size = data && data.source.frame_image && data.source.frame_size;
129      if (!size) { frame.style.width = frame.style.height = ""; return; }  // 이미지가 없으면(v1 mock) 칸 전체
130      const box = $("video").getBoundingClientRect();
131      const k = Math.min(box.width / size.w, box.height / size.h);         // 가로·세로 중 먼저 닿는 쪽에 맞춤
132      frame.style.width = `${size.w * k}px`;
133      frame.style.height = `${size.h * k}px`;
134  }
```
→ 원본 프레임을 비율을 지키며 칸 안에 가장 크게 맞춥니다. 박스 좌표가 % 라서, 프레임 영역이 사진과 정확히 같아야 박스가 전차 위에 맞게 놓입니다.

### 함수 `renderBoxes()` — 바운딩 박스·부품 그리기 (dashboard.js:137~162)

```javascript
138      const video = $("frame");                                            // 박스를 넣을 프레임 영역
139      video.querySelectorAll(".bbox, .part").forEach((b) => b.remove());   // 이전 박스·부품 지우기
```
→ 이전 박스·부품을 지웁니다.

```javascript
140      targets.forEach((t) => (t.parts || []).forEach((p) => {              // 부품 표시: 흰 점선 작은 박스 + 이름
141          const el = document.createElement("div");
142          el.className = "part";
143          Object.assign(el.style, { left: `${p.bbox.x}%`, top: `${p.bbox.y}%`, width: `${p.bbox.w}%`, height: `${p.bbox.h}%` });
144          el.innerHTML = `<span class="part-label">${esc(PART_LABEL[p.cls] || p.cls)} ${Math.round(p.conf * 100)}%</span>`;
145          video.appendChild(el);
146      }));
```
→ 부품: 흰 점선 작은 상자 + '안테나 66%' 같은 이름표.

```javascript
147      targets.forEach((t) => {                                             // 표적마다
148          const box = document.createElement("div");                       // 박스 요소 새로 만들기
149          box.className = `bbox stage${t.level} ${t.is_unknown ? "unknown" : "known"}`;  // 단계 색 + 미확인 점선
150          box.dataset.id = t.tracking_id;                                  // 나중에 선택 강조할 때 찾으려고 ID 를 붙여 둠
151          Object.assign(box.style, {                                       // bbox 는 화면 % 좌표
152              left: `${t.bbox.x}%`, top: `${t.bbox.y}%`,                   // 왼쪽 위 모서리 위치
153              width: `${t.bbox.w}%`, height: `${t.bbox.h}%`,               // 가로·세로 크기
154          });                                                              // (%라서 화면 크기가 바뀌어도 같은 자리)
```
→ 표적 박스: 색 = 소속 군집 대응단계(CSS 클래스 `stage3` 등), 미확인은 보라 점선. 위치·크기는 % 로 지정.

```javascript
155          const conf = `${Math.round((t.confidence || 0) * 100)}%`;        // 탐지 신뢰도
156          box.innerHTML = `<span class="bbox-label" title="${esc(`${t.tracking_id} · ${modelName(t)} · ${conf}`)}">${esc(t.tracking_id)} · ${conf}</span>`;  // 박스 위 라벨 'Tank-03 · 93%' (마우스 올리면 기종까지)
157          if (t.is_unknown) box.innerHTML += `<span class="bbox-unk-mark">?</span>`;  // 미확인 '?' 표시
158          box.addEventListener("click", () => selectTarget(t.tracking_id));            // 박스 클릭 = 표적 선택
159          video.appendChild(box);                                          // 영상 영역에 붙이기
```
→ 박스 위 라벨 'Tank-01 · 81%', 미확인 '?' 표시, 클릭하면 그 표적 선택.

```javascript
161      resolveLabelOverlaps();                                              // 다 붙인 뒤 라벨 겹침 정리
```
→ 라벨이 서로 겹치면 아래로 내립니다.

### 함수 `resolveLabelOverlaps()` — 라벨 겹침 정리 (dashboard.js:164~178)

```javascript
165      const labels = Array.from(document.querySelectorAll(".bbox-label")); // 모든 라벨
166      labels.forEach((l) => l.classList.remove("label-below"));            // 지난번에 내렸던 것 원위치
167      const placed = [];                                                   // 이미 놓인 라벨 위치
168      labels.forEach((label) => {                                          // 라벨마다
169          const r = label.getBoundingClientRect();                         // 지금 화면상 위치·크기
170          const overlaps = placed.some((p) => !(r.right <= p.left || r.left >= p.right || r.bottom <= p.top || r.top >= p.bottom));  // 이미 놓인 것과 사각형이 겹치는지
171          if (overlaps) {                                                  // 겹치면
172              label.classList.add("label-below");                          // 박스 아래쪽으로 옮김 (CSS)
173              placed.push(label.getBoundingClientRect());                  // 내린 뒤 위치로 기록
174          } else {                                                         // 안 겹치면
175              placed.push(r);                                              // 그 자리 그대로 기록
176          }
177      });
```
→ 라벨을 차례로 보며 이미 놓인 라벨과 사각형이 겹치면 박스 아래쪽으로 옮깁니다.

### 함수 `bump`, `renderCountBar` — 상단 카운터 (dashboard.js:181~196)

```javascript
181  function bump(id, value) {                                               // 값이 바뀌면 숫자 깜빡임
182      const el = $(id);                                                    // 숫자 칸
183      if (el.textContent !== String(value)) {                              // 값이 바뀌었을 때만
184          el.textContent = value;                                          // 새 숫자
185          el.classList.remove("pulse");                                    // 애니메이션 초기화
186          requestAnimationFrame(() => el.classList.add("pulse"));          // 다음 프레임에 다시 붙여야 애니메이션이 재생됨
187      }
188  }
```
→ 숫자가 바뀌면 잠깐 커졌다 돌아오는 효과. `requestAnimationFrame` 은 다음 화면 갱신 때 실행.

```javascript
189  function renderCountBar() {                                              // 상단 '전체·전차·기갑차·포병·신규' 숫자
190      const c = data.counts;                                               // 서버가 센 값
191      bump("cb-total", c.total);                                           // 전체
192      bump("cb-tank", c.tank);                                             // 전차
193      bump("cb-apc", c.apc);                                               // 기갑차
194      bump("cb-arty", c.artillery + c.infantry);                           // '포병' 칸 = 포병 + 인원 (둘 다 위협도 계산 대상이 아님)
195      bump("cb-new", c.new);                                               // 신규 (직전 분석에 없던 표적)
196  }
```
→ 서버가 센 전체·전차·기갑차·포병(+인원)·신규 개수.

### 함수 `threatCell`, `statusBadge`, `renderTable` — 랭킹 표 (dashboard.js:199~229)

```javascript
199  function threatCell(t) {                                                 // '95.8 [매우 높음]' 또는 '산출 불가'
200      if (t.threat == null) return `<span class="grade gx" title="제원이 없어 위협도를 계산할 수 없음">산출 불가</span>`;  // 점수 없음 (미확인)
201      return `<span class="threat-cell"><b>${t.threat.toFixed(1)}</b><span class="grade ${GRADE_CLASS[t.grade]}">${esc(t.grade)}</span></span>`;  // 점수(소수 1자리) + 색 배지
202  }
```
→ 위협도 칸: 점수(소수 1자리) + 단계 색 배지, 점수가 없으면 '산출 불가'.

```javascript
203  function statusBadge(t) {                                                // 판정 상태 작은 배지 (Known / 계열 확정 / 미확인)
204      const [label, cls] = STATUS[t.status] || STATUS.Unknown;
205      return `<span class="st-badge st-${cls}">${label}</span>`;
206  }
```
→ 기종 칸 앞 판정 상태 배지.

```javascript
208      const ranked = targets.filter((t) => t.rank != null);                // 순위 있는 표적 (전차·미확인)
209      $("target-count").textContent = `(${ranked.length})`;                // 제목 옆 '(9)'
210      const body = $("rank-body");                                         // 표 본문
211      if (!ranked.length) {                                                // 표적이 하나도 없으면
212          body.innerHTML = `<tr><td colspan="6" class="empty"></td></tr>`; // 빈 행 하나 (CSS 가 안내 문구 표시)
213          return ranked;                                                   // 빈 목록
214      }
```
→ 순위가 있는 표적(전차·미확인)만. 없으면 빈 안내.

```javascript
217      body.innerHTML = ranked.map((t) => `
218          <tr data-id="${esc(t.tracking_id)}">
219              <td class="rank-num">${t.rank}</td>
220              <td>${t.is_core ? `<span class="core-star" title="핵심표적 (지휘관 지정)">★</span>` : ""}${esc(t.tracking_id)}</td>
221              <td>${statusBadge(t)}${esc(modelName(t))}</td>
222              <td>${threatCell(t)}</td>
223              <td class="col-left tag-td"><div class="tag-cell">${t.tags.map((r) => `<span class="chip">${esc(r)}</span>`).join("")}</div></td>
224              <td>${(t.confidence || 0).toFixed(2)}</td>
225          </tr>`).join("");
```
→ 행 1개 = 표적 1개: 순위 | (핵심표적이면 ★) ID | 상태+기종(또는 그룹 ID) | 위협도 | 근거 태그 칩 | 신뢰도. 모든 값은 `esc()` 로 감쌉니다.

```javascript
226      body.querySelectorAll("tr[data-id]").forEach((tr) =>                 // 방금 만든 행마다
227          tr.addEventListener("click", () => selectTarget(tr.dataset.id)));  // 행 클릭 = 표적 선택
228      return ranked;                                                       // render() 가 1위 자동 선택에 씀
```
→ 행 클릭 = 표적 선택. 1위 자동 선택을 위해 목록을 돌려줍니다.

### 함수 `selectTarget`, `highlight` — 표적 선택 (표·영상·지도 공통) (dashboard.js:232~250)

```javascript
232  function selectTarget(id, opts) {                                        // 표적 하나를 고름 (opts.auto = 프로그램이 자동으로 고른 것)
233      selectedId = id;                                                     // 선택 기억
234      if (!(opts && opts.auto)) hasManualSelection = true;                 // 직접 고른 경우만 '수동 선택'
235      highlight();                                                         // 표·박스·마커 강조
236      const t = targets.find((x) => x.tracking_id === id);                 // 그 표적 데이터 찾기
237      if (t) renderPanelB(t);                                              // 오른쪽 상세 패널 채우기
238  }
```
→ 선택 ID 를 기억하고, 세 곳을 강조한 뒤 상세 패널을 채웁니다.

```javascript
240  function highlight() {                                                   // 표 행·박스·지도 마커를 함께 강조
241      document.querySelectorAll("#rank-body tr").forEach((tr) =>           // 표 행마다
242          tr.classList.toggle("selected", tr.dataset.id === selectedId));  // 선택된 행만 'selected' 클래스
243      document.querySelectorAll(".bbox").forEach((b) =>                    // 영상 박스마다
244          b.classList.toggle("selected", b.dataset.id === selectedId));    // 선택된 박스만 굵은 테두리
245      Object.entries(markers).forEach(([id, m]) => {                       // 지도 마커마다
246          const on = id === selectedId;                                    // 선택된 마커인지
247          m.setRadius(on ? 10 : 6).setStyle({ weight: on ? 3 : 1.5, color: on ? "#1f2419" : "#fff" });  // 선택 마커는 크고 테두리 진하게
248          if (on) { m.bringToFront(); m.openTooltip(); } else m.closeTooltip();  // 선택 마커는 맨 앞 + 이름표 열기, 나머지는 닫기
249      });
250  }
```
→ 표 행·영상 박스·지도 마커 중 선택된 것만 강조(굵은 테두리, 큰 마커, 이름표).

### 함수 `renderPanelA()` — 상황 패널 (군집 대응단계) (dashboard.js:253~287)

```javascript
254      const stage = effectiveStage();                                      // 지휘관 조정 > AI 권고
255      const a = data.alert;                                                // 서버가 계산한 경보 (가장 심각한 군집 기준)
256      document.querySelectorAll("#pa-ladder li").forEach((li) => {         // 단계 사다리: 지금 단계 칸만 칠함
257          const n = Number(li.dataset.stage);                              // 칸 번호 1~4
258          li.className = n === stage ? `on stage${n}` : n === a.level && commanderStage != null ? `ai stage${n}` : "";  // 조정했으면 AI 권고 칸은 테두리
259          li.setAttribute("aria-current", n === stage ? "step" : "false"); // 화면 읽기 프로그램용 현재 단계
260      });
```
→ 단계 사다리 1~4: 화면 단계 칸은 칠하고, 지휘관이 조정했다면 AI 권고 칸은 점선 테두리.

```javascript
261      $("pa-change").textContent = a.prev_level != null && a.prev_level !== a.level  // 직전 분석과 단계가 다르면
262          ? `${STAGE_SHORT[a.prev_level]} → ${STAGE_SHORT[a.level]} (${now()})` : "";  // 직전 분석 대비 변화
263      $("pa-override").hidden = commanderStage == null;                    // 지휘관 조정 표시
264      $("pa-override").textContent = commanderStage == null ? ""          // 조정 안 했으면 빈칸
265          : `AI 권고 ${STAGE_SHORT[a.level]} → 지휘관 결정 ${STAGE_SHORT[commanderStage]}`;  // 했으면 AI 값과 지휘관 값을 나란히
```
→ 직전 분석 대비 단계 변화, 'AI 권고 N단계 → 지휘관 결정 M단계' 문구.

```javascript
270      $("pa-clusters").innerHTML = data.clusters.map((c) => `
271          <li class="cluster-item stage${c.level}">
272              <div class="ci-head">
273                  <b>${esc(c.cluster_id)}</b>
274                  <span class="badge stage${c.level}">${STAGE_SHORT[c.level]}</span>
275                  <span>${esc(c.echelon.name)}급 ${c.echelon.n}대 ×${c.echelon.weight}</span>
276                  <span class="ci-tactic${c.tactic_source === "지휘관 지정" ? " manual" : ""}"
277                        title="${esc(c.tactic_source)}">${esc(c.tactic_name)}${c.tactic_source === "지휘관 지정" ? " (지정)" : ""}</span>
278              </div>
279              <div class="ci-reasons">${c.reasons.slice(1).map(esc).join(" · ")}</div>
280          </li>`).join("");                                                // 군집마다 단계·제대·전술 + 판정 근거 (reasons[0] 제대는 머리줄과 같아 생략)
```
→ 군집 카드: ID | 단계 | '소대급 2대 ×1' | 전술 이름(지휘관 지정이면 주황 '(지정)'), 아래 줄은 판정 근거.

```javascript
282      const sel = $("tp-cluster");                                         // 전술 선택의 군집 목록
283      const keep = sel.value;                                              // 고르던 군집 유지
284      sel.innerHTML = data.clusters.map((c) => `<option value="${esc(c.cluster_id)}">${esc(c.cluster_id)} (${esc(c.echelon.name)}급)</option>`).join("");  // 'C-1 (중대급)' 같은 선택지
285      if (data.clusters.some((c) => c.cluster_id === keep)) sel.value = keep;  // 고르던 군집이 아직 있으면 그대로
286      syncTacticSelect();                                                  // 전술 목록도 그 군집 상태로
```
→ 전술 선택 펼침 영역의 군집 목록을 갱신(고르던 군집은 유지).

### 함수 `syncTacticSelect`, `applyTactic`, `openReport` (dashboard.js:289~309)

```javascript
289  function syncTacticSelect() {                                            // 전술 목록을 선택 군집의 현재 상태로 맞춤
290      const c = data && data.clusters.find((x) => x.cluster_id === $("tp-cluster").value);  // 고른 군집 데이터
291      if (!c) return;                                                      // 아직 데이터가 없으면 아무것도 안 함
292      $("tp-tactic").value = c.tactic_source === "지휘관 지정" ? String(c.tactic) : "";  // 자동이면 '자동' 선택
293  }
```
→ 전술 목록을 그 군집의 현재 전술로 맞춤(자동이면 '자동').

```javascript
295  async function applyTactic() {                                           // 전술 적용 → 서버 재계산
296      const cid = $("tp-cluster").value;                                   // 고른 군집 ID
297      const v = $("tp-tactic").value;                                      // 고른 전술 번호 ('' = 자동)
298      const ok = await fetchResult(`/api/clusters/${encodeURIComponent(cid)}/tactic`, {  // PATCH /api/clusters/C-1/tactic
299          method: "PATCH",                                                 // 기존 결과의 일부만 바꾸는 요청
300          headers: { "Content-Type": "application/json" },                 // 본문이 JSON 이라고 알림
301          body: JSON.stringify({ tactic: v === "" ? null : Number(v) }),     // '' = 자동으로 되돌림
302      });                                                                  // 성공하면 fetchResult 가 화면을 새 결과로 다시 그림
303      if (ok) $("tactic-pick").hidden = true;                              // 성공 시 펼침 영역 닫기
304  }
```
→ 전술 적용: `PATCH /api/clusters/<군집>/tactic` 에 `{tactic: 번호 또는 null}` 을 보내고, 성공하면 펼침 영역을 닫습니다. `JSON.stringify` 는 객체를 JSON 글자로 바꿈.

```javascript
306  function openReport() {                                                  // 보고서 출력: 인쇄용 페이지를 새 탭으로
307      const q = commanderStage != null ? `?stage=${commanderStage}` : "";  // 지휘관 조정 단계를 보고서에 전달
308      window.open(`/report${q}`, "_blank");                                // 새 탭으로 /report 열기
309  }
```
→ 보고서를 새 탭으로. 지휘관이 단계를 조정했으면 `?stage=` 로 함께 보냅니다.

### 배너·깜빡임 함수 (dashboard.js:311~328)

```javascript
311  function flashPanelA() {                                                 // 단계가 올라갔을 때 상황 패널을 잠깐 깜빡임
312      const el = $("pa-panel");                                            // 상황 패널
313      el.classList.add("flash");                                           // 깜빡임 시작 (CSS 애니메이션)
314      setTimeout(() => el.classList.remove("flash"), 900);                 // 0.9초 뒤 끔
315  }
316  function confirmPanelA() {                                               // '확인' 버튼
317      hideBanner();                                                        // 배너 닫기
318      $("pa-panel").classList.remove("flash");                             // 깜빡임 멈춤
319  }
```
→ 상황 패널 0.9초 깜빡임, '확인' 버튼은 배너와 깜빡임을 끕니다.

```javascript
320  function showBanner(text) {                                              // 화면 맨 위 경보 배너 보이기
321      $("alert-banner-text").textContent = text;                           // 문구
322      $("alert-banner").hidden = false;                                    // 보이기
323      document.body.classList.add("has-banner");                           // 배너 높이만큼 화면 내림
324  }
325  function hideBanner() {                                                  // 배너 숨기기
326      $("alert-banner").hidden = true;                                     // 숨김
327      document.body.classList.remove("has-banner");                        // 내렸던 화면 원위치
328  }
```
→ 화면 맨 위 경보 배너 보이기/숨기기 (배너 높이만큼 화면을 내림).

### 함수 `renderPanelB(t)` — 선택 표적 상세 (dashboard.js:331~381)

```javascript
332      $("pb-title").textContent = `${t.tracking_id} · ${modelName(t)}`;    // 'Tank-03 · T-90M'
333      const [stLabel, stCls] = STATUS[t.status] || STATUS.Unknown;          // 판정 상태
334      $("pb-status-badge").className = `badge ${stCls}`;                    // Known 파랑 · 계열 확정 회색 · 미확인 보라
335      $("pb-status-badge").textContent = stLabel;
```
→ 제목 'UNK-001 · UNK-G0001', 판정 상태 배지.

```javascript
336      $("pb-crop").hidden = !t.crop_url;                                    // 대표 crop (원본 프레임에서 잘라 저장한 것)
337      if (t.crop_url) {
338          $("pb-crop-img").src = t.crop_url;
339          $("pb-crop-img").alt = `${t.tracking_id} 대표 crop`;
340          $("pb-crop-cap").textContent = [t.unknown_group_id && `미확인 그룹 ${t.unknown_group_id}`,
341              t.n_frames > 1 && `${t.n_frames}프레임 추적`, t.threat_source].filter(Boolean).join(" · ");
342      }
```
→ 대표 crop 사진과 설명(미확인 그룹, 추적 프레임 수, 위협도 근거). v1 입력이면 숨김.

```javascript
343      const ev = t.commander_evidence;                                      // 지휘전차 근거 (v2 만)
344      $("pb-commander").hidden = !ev || t.category !== "전차";
345      $("pb-commander").textContent = t.is_commander ? "지휘전차 해제" : "지휘전차로 지정";
346      $("pb-core").hidden = t.rank == null;                                 // 랭킹 표적(전차·미확인)만 핵심표적 지정 가능
347      $("pb-core").textContent = t.is_core ? "핵심표적 해제" : "핵심표적 지정";
348      $("pb-conf").innerHTML = `신뢰도 <b>${Math.round((t.confidence || 0) * 100)}%</b>`;  // 탐지 신뢰도
```
→ 지휘전차 지정·해제 버튼은 v2 의 전차에만, 핵심표적 지정·해제 버튼은 랭킹 표적(전차·미확인)에만 보입니다. 탐지 신뢰도.

```javascript
350      const bonus = t.threat_before_bonus != null && t.threat_before_bonus !== t.threat  // cope cage 보정이 있으면 보정 전 값도
351          ? ` · 보정 전 ${t.threat_before_bonus}` : "";
352      $("pb-score").innerHTML = `${t.threat ?? "—"}<small> 위협도${bonus}</small>`;    // 전차 위협도 점수
353      $("pb-grade").innerHTML = t.threat == null ? "" : `<span class="grade ${GRADE_CLASS[t.grade]}">${esc(t.grade)}</span>`;  // 위협도 단계 배지 (점수 없으면 비움)
354      $("pb-stage-badge").className = `badge stage${t.level}`;             // 소속 군집 단계 색
355      $("pb-stage-badge").textContent = `${t.cluster_id} ${STAGE_SHORT[t.level]}`;  // 소속 군집 대응단계
```
→ 위협도 점수(cope cage 보정이 있으면 '보정 전 97.8' 함께), 단계 배지, 소속 군집 단계.

```javascript
359      $("pb-bars").innerHTML = t.scores
360          ? ["firepower", "mobility", "protection"].map((k) => `
361          <div class="stat-row">
362              <span class="stat-label">${STAT_LABEL[k]}</span>
363              <span class="stat-track"><span class="stat-fill" style="width:${Math.min(t.scores[k] / BAR_MAX, 1) * 100}%"></span></span>
364              <span class="stat-value">${t.scores[k]} × ${t.weights[k]}</span>
365          </div>`).join("")                                                   // 점수 × 적용된 전술 가중치
366          : t.threat != null                                                  // 기종 미정(변형·미확인): 대체 위협도 근거
367              ? `<p class="muted">기종 제원 대신 ${esc(t.threat_source)} 값을 씀</p>`
368              : `<p class="muted">제원 없음 — 위협도 산출 불가 (${esc(t.category)})</p>`;  // 점수 없음
```
→ Known 이면 화력·기동·방호 막대(점수 × 적용 가중치), 변형·미확인이면 '기종 제원 대신 ○○ 값을 씀'.

```javascript
370      const tags = t.tags.filter((r) => !r.endsWith(" 소속"));               // 'C-1 소속'은 바로 위 단계 배지와 중복
371      $("pb-reasons").innerHTML = tags.length                                 // 태그가 있으면
372          ? tags.map((r) => `<span class="chip">${esc(r)}</span>`).join("")   // 칩으로 나열
373          : `<span class="muted">해당 없음</span>`;                            // 없으면 안내 문구
```
→ 근거 태그('C-1 소속'은 바로 위 배지와 겹쳐 뺌).

```javascript
375      const p = t.position;                                                   // 추정 위치
376      const cl = data.clusters.find((c) => c.cluster_id === t.cluster_id);   // 소속 군집 (지휘관 조치 전 단계 비교)
377      const before = cl && cl.level_before_override !== cl.level ? ` · 지휘관 조치 전 ${STAGE_SHORT[cl.level_before_override]}` : "";
378      $("pb-info").textContent = `추정 거리 ${(p.distance_m / 1000).toFixed(1)} km · 방위 ${p.bearing_deg}° · 전술 ${t.tactic_name}${before}`;  // m → km 변환해 표시
```
→ 추정 거리·방위·전술, 그리고 소속 군집의 단계가 지휘관 조치로 바뀌었으면 '지휘관 조치 전 3단계' (`level_before_override`).

```javascript
379      $("pb-dict-link").style.display = t.model ? "" : "none";                // 기종 없으면 사전 링크 숨김 (#pb-dict-link 의 display 규칙이 hidden 보다 우선)
380      $("pb-dict-link").href = `/dictionary?q=${encodeURIComponent(t.model || "")}`;  // 사전 페이지에서 기종명으로 검색
```
→ '사전에서 보기' 링크(기종명으로 사전 검색).

### 함수 `toggleCommander()`, `toggleCore()` — 지휘전차·핵심표적 지정·해제 (dashboard.js:383~399)

```javascript
384      const t = targets.find((x) => x.tracking_id === selectedId);
385      if (!t || !t.commander_evidence) return;
386      const want = !t.is_commander;                                           // 바꿀 값
387      const value = want === t.commander_evidence.on ? null : want;           // 탐지 규칙과 같아지면 지정 해제 (null = 자동)
```
→ 지금과 반대 값으로 바꾸되, 그 값이 탐지 규칙 결과와 같으면 null(지휘관 지정을 지우고 자동으로).

```javascript
388      await fetchResult(`/api/threats/${encodeURIComponent(t.tracking_id)}/commander`, {
389          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_commander: value }),
390      });
```
→ `PATCH /api/threats/<ID>/commander` 요청 → 결과로 화면 갱신.

```javascript
393  async function toggleCore() {                                               // 핵심표적 지정·해제 → 서버가 군집 재판정 (최소 2단계)
394      const t = targets.find((x) => x.tracking_id === selectedId);
395      if (!t) return;
396      await fetchResult(`/api/threats/${encodeURIComponent(t.tracking_id)}/core-target`, {
397          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ core: !t.is_core }),
398      });
```
→ 핵심표적: `PATCH /api/threats/<ID>/core-target {core: 반대 값}` → 서버가 그 군집을 다시 판정(최소 2단계)하고 이력에 남김.

### 함수 `mapFail`, `initMap`, `renderMap` — 미니맵 (dashboard.js:402~447)

```javascript
402  function mapFail() {                                                        // 지도를 못 불러왔을 때
403      $("map-fail").hidden = false;                                           // '지도를 불러올 수 없음'
404  }
406  function initMap() {                                                        // 페이지 시작 때 지도 한 번 만들기
407      if (typeof L === "undefined") return mapFail();                         // Leaflet CDN 로딩 실패 (오프라인 등)
408      map = L.map("minimap", { zoomControl: false });                         // #minimap 칸에 지도 생성 (+/- 버튼 없이)
409      let tileOk = false;                                                     // 타일이 한 장이라도 왔는지
410      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" })  // OpenStreetMap 지도 그림
411          .on("tileload", () => { tileOk = true; })                           // 한 장이라도 오면 성공으로 기록
412          .on("tileerror", () => { if (!tileOk) mapFail(); })                  // 처음부터 실패하면 안내 표시
413          .addTo(map);                                                        // 지도에 붙이기
414      mapLayer = L.layerGroup().addTo(map);                                   // 마커·원을 담는 레이어 (다시 그릴 때 통째로 비움)
415  }
```
→ **Leaflet**(지도 라이브러리)과 **OpenStreetMap**(무료 지도 그림)으로 지도를 만듭니다. 인터넷이 없어 지도를 못 받으면 안내 문구.

```javascript
417  function renderMap() {                                                      // 분석 결과가 올 때마다 마커 다시 그림
418      if (!map) return;                                                       // 지도가 없으면(로딩 실패) 건너뜀
419      mapLayer.clearLayers();                                                 // 이전 마커·원 전부 지우기
420      markers = {};                                                           // 마커 목록도 비움
421      const obs = data.source.observer;                                       // 관측 지점 (카메라 위치)
422      const points = [[obs.lat, obs.lon]];                                    // 화면 맞춤 범위
```
→ 이전 마커를 지우고 관측 지점부터 화면 맞춤 범위에 넣습니다.

```javascript
424      data.clusters.forEach((c) => {                                          // 군집은 원으로 묶어 표시
425          const pos = targets.filter((t) => t.cluster_id === c.cluster_id).map((t) => [t.position.lat, t.position.lon]);  // 이 군집 표적들의 [위도, 경도]
426          if (!pos.length) return;                                            // 표적이 없으면 원도 안 그림
427          const center = L.latLng(pos.reduce((s, p) => s + p[0], 0) / pos.length, pos.reduce((s, p) => s + p[1], 0) / pos.length);  // 평균 위치
428          const radius = Math.max(...pos.map((p) => center.distanceTo(p))) + 120;  // 가장 먼 표적 + 여유 120m
429          L.circle(center, { radius, color: stageColor(c.level), weight: 1.5, dashArray: "4 4", fillOpacity: 0.08 })  // 단계 색 점선 원
430              .bindTooltip(`${esc(c.cluster_id)} · ${STAGE_SHORT[c.level]} · ${esc(c.echelon.name)}급`).addTo(mapLayer);  // 마우스 올리면 'C-1 · 2단계 · 중대급'
431      });
```
→ 군집마다 표적 평균 위치를 중심으로 단계 색 점선 원.

```javascript
433      targets.forEach((t) => {                                                // 표적 마커 (색 = 군집 대응단계)
434          const ll = [t.position.lat, t.position.lon];                        // 추정 위치
435          points.push(ll);                                                    // 화면 맞춤 범위에 추가
436          markers[t.tracking_id] = L.circleMarker(ll, { radius: 6, color: "#fff", weight: 1.5, fillColor: stageColor(t.level), fillOpacity: 1 })  // 흰 테두리 동그라미
437              .bindTooltip(`${esc(t.tracking_id)} · ${esc(modelName(t))} (추정)`)  // 이름표
438              .on("click", () => selectTarget(t.tracking_id))                 // 마커 클릭 = 표적 선택
439              .addTo(mapLayer);                                               // 레이어에 붙이기
440      });
```
→ 표적 마커(색 = 군집 단계). 클릭하면 표적 선택. 위치는 **추정값**(`pipeline.estimate_position`).

```javascript
442      L.circleMarker([obs.lat, obs.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#1f2419", fillOpacity: 1 })  // 관측 지점 점
443          .bindTooltip("관측 지점").addTo(mapLayer);                          // 관측 지점은 검은 점
445      map.invalidateSize();                                                   // 패널 크기 변화 반영
446      map.fitBounds(points, { padding: [20, 20], maxZoom: 15 });              // 전체가 보이게 확대·이동
```
→ 관측 지점(검은 점)을 찍고 전체가 보이게 확대.

### 시작 (dashboard.js:449~449)

```javascript
449  init();                                                                     // 스크립트가 읽히면 바로 시작
```
→ 스크립트가 읽히면 `init()` 실행.

