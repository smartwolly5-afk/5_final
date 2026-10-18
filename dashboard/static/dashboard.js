// 위협도 대시보드 화면 동작. 데이터는 전부 서버 API(dashboard/__init__.py)에서 받고, 계산은 하지 않는다.
// 흐름: init() → API 호출 → load(결과) → render() 가 표·박스·패널·지도를 다시 그림
// 읽는 법: 서버 응답(data)의 모양은 dashboard/threat/pipeline.py 맨 위 주석, $("...") 의 id 는 templates/dashboard/index.html 에 있음
// 주의: 백틱(`) 안의 여러 줄 HTML 에는 // 주석을 넣을 수 없어서(화면에 글자로 찍힘) 그 위에 설명을 몰아 적었다

/* ===== 표시용 상수 ===== */
const STAGE_LABEL = { 1: "1단계 · 즉시 보고", 2: "2단계 · 우선 감시", 3: "3단계 · 지속 감시", 4: "4단계 · 관심" };  // 군집 대응단계 긴 이름
const STAGE_SHORT = { 1: "1단계", 2: "2단계", 3: "3단계", 4: "4단계" };                                           // 짧은 이름
const GRADE_CLASS = { "매우 높음": "g1", "높음": "g2", "보통": "g3", "낮음": "g4" };                                // 전차 위협도 단계 → CSS 색 클래스
const STAT_LABEL = { firepower: "화력", mobility: "기동력", protection: "방호력" };                                  // 상세 막대 이름
const BAR_MAX = 150;                                                                                              // 상세 막대 100% = 기준전차의 1.5배

/* ===== 화면 상태 ===== */
let data = null;              // 마지막 API 응답 (AnalysisResult — threat/pipeline.py 머리말 참고)
let targets = [];             // data.targets (랭킹 순서)
let selectedId = null;        // 선택된 표적 tracking_id
let hasManualSelection = false; // 사용자가 직접 골랐는지 (아니면 1위 자동 선택)
let commanderStage = null;    // '단계 조정'으로 지휘관이 바꾼 단계 (null = AI 권고 그대로)
let map = null, mapLayer = null, markers = {};  // Leaflet 지도, 마커 레이어, tracking_id → 마커

/* ===== 짧은 도우미 함수 ===== */
const $ = (id) => document.getElementById(id);                                       // id 로 요소 찾기
const pad = (n) => String(n).padStart(2, "0");                                         // 두 자리 숫자
const now = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };  // 현재 시각
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));  // HTML 이스케이프 (API 값은 외부 입력)
const aiStage = () => (data ? data.alert.level : 4);                                   // AI 권고 단계 (가장 심각한 군집)
const effectiveStage = () => (commanderStage != null ? commanderStage : aiStage());    // 화면에 쓰는 단계 (지휘관 조정 우선)
const modelName = (t) => t.model || "미확인";                                          // 기종명 없으면 '미확인'
const stageColor = (lv) => getComputedStyle(document.documentElement).getPropertyValue(`--stage${lv}`).trim();  // CSS 변수 색 (지도용)

/* ===== 시작 ===== */
async function init() {                                                                                // 페이지가 열리면 맨 아래 init() 으로 한 번 실행
    $("analyze-btn").addEventListener("click", () => fetchResult("/api/analyze", { method: "POST" }));  // 분석 시작 = 새 분석
    $("pa-confirm").addEventListener("click", confirmPanelA);                                          // 확인 = 배너·깜빡임 끄기
    $("pa-adjust").addEventListener("click", () => togglePicker("stage-pick"));                        // 단계 조정 펼치기
    $("pa-tactic").addEventListener("click", () => togglePicker("tactic-pick"));                       // 전술 선택 펼치기
    $("pa-report").addEventListener("click", openReport);                                              // 보고서 출력
    $("stage-pick").addEventListener("click", (e) => {                                                 // 단계 버튼 클릭
        const stage = e.target.dataset.stage;                                                          // data-stage 값
        if (!stage) return;                                                                            // 버튼 바깥 클릭은 무시
        commanderStage = Number(stage) === aiStage() ? null : Number(stage);                           // AI 권고와 같으면 조정 해제
        $("stage-pick").hidden = true;                                                                 // 고르고 나면 단계 버튼 줄 닫기
        renderPanelA();                                                                                // 큰 배지·'지휘관 결정' 문구 다시 그림
    });                                                                                                // (서버 호출 없음 — 화면·보고서에만 반영)
    $("tp-cluster").addEventListener("change", syncTacticSelect);                                      // 군집 바꾸면 현재 전술 표시
    $("tp-apply").addEventListener("click", applyTactic);                                              // 전술 적용
    $("alert-banner-close").addEventListener("click", hideBanner);                                     // 배너 닫기
    initMap();                                                                                         // 지도 준비

    const ok = await fetchResult("/api/threats", {}, true);                                            // 마지막 결과 가져오기
    if (!ok) await fetchResult("/api/analyze", { method: "POST" });                                    // 없으면(서버 첫 실행) 바로 분석
}

function togglePicker(id) {                                              // '단계 조정'·'전술 선택' 버튼: 아래 펼침 영역 열고 닫기
    const other = id === "stage-pick" ? "tactic-pick" : "stage-pick";   // 두 펼침 영역은 하나만 열림
    $(other).hidden = true;                                              // 다른 쪽은 닫고
    $(id).hidden = !$(id).hidden;                                        // 누른 쪽은 열려 있으면 닫고, 닫혀 있으면 엶
    if (id === "tactic-pick") syncTacticSelect();                        // 열 때 선택 군집의 현재 전술로 맞춤
}

/* ===== API 호출 ===== */
async function fetchResult(url, opts, quiet404) {                        // 서버에 요청 → 성공하면 화면 갱신. 성공 여부(true/false) 반환
    try {                                                                // 네트워크 오류·서버 오류를 아래 catch 에서 한꺼번에 처리
        const res = await fetch(url, opts);                              // 요청
        if (quiet404 && res.status === 404) return false;                // '분석 결과 없음'은 조용히 넘김
        const body = await res.json();                                   // JSON 응답
        if (!res.ok) throw new Error(body.error || res.status);          // 서버 오류 메시지
        load(body);                                                      // 화면 갱신
        return true;                                                     // 성공
    } catch (err) {                                                      // 실패하면
        showBanner(`분석 결과를 불러오지 못했습니다: ${err.message}`);   // 오류는 상단 배너로
        return false;                                                    // 실패
    }
}

function load(result) {                                                  // 새 분석 결과를 받아 화면 상태에 넣고 다시 그림
    data = result;                                                       // 새 결과 저장
    targets = result.targets;                                            // 표적 목록 (서버가 랭킹 순서로 정렬해 보냄)
    commanderStage = null;                                               // 새 계산이 오면 지휘관 단계 조정 해제
    $("src-video").textContent = result.source.video || "";              // 파일 이름
    $("video-meta").textContent = `${result.source.captured_at || ""} (${result.source.source || ""})`;  // 촬영일 (출처)
    if (!targets.some((t) => t.tracking_id === selectedId)) hasManualSelection = false;  // 선택 표적이 사라지면 자동 선택으로
    render();                                                            // 표·박스·패널·지도 전부 다시 그림

    const { level, prev_level: prev } = result.alert;                    // 지금 단계와 직전 분석 단계 꺼내기
    if (result.alert.banner) showBanner(`⚠ ${STAGE_LABEL[level]} — ${result.alert.message}`);  // 1단계면 배너
    if (prev != null && level < prev) flashPanelA();                     // 단계가 올라갔으면 상황 패널 깜빡임
}

/* ===== 전체 다시 그리기 ===== */
function render() {                                                      // 화면 각 부분을 차례로 그림
    renderBoxes();                                                       // 영상 위 박스
    renderCountBar();                                                    // 상단 카운터
    const ranked = renderTable();                                        // 랭킹 표
    renderPanelA();                                                      // 상황 패널 (군집 대응단계)
    renderMap();                                                         // 미니맵
    if (!hasManualSelection && ranked.length) selectTarget(ranked[0].tracking_id, { auto: true });  // 1위 자동 선택
    else if (selectedId) selectTarget(selectedId, { auto: true });      // 기존 선택 유지
}

/* ===== 영상 위 바운딩 박스 (색 = 소속 군집 대응단계) ===== */
function renderBoxes() {                                                 // 표적마다 영상 위에 네모 박스를 만듦
    const video = $("video");                                            // 박스를 넣을 영상 영역
    video.querySelectorAll(".bbox").forEach((b) => b.remove());          // 이전 박스 지우기
    targets.forEach((t) => {                                             // 표적마다
        const box = document.createElement("div");                       // 박스 요소 새로 만들기
        box.className = `bbox stage${t.level} ${t.is_unknown ? "unknown" : "known"}`;  // 단계 색 + 미확인 점선
        box.dataset.id = t.tracking_id;                                  // 나중에 선택 강조할 때 찾으려고 ID 를 붙여 둠
        Object.assign(box.style, {                                       // bbox 는 화면 % 좌표
            left: `${t.bbox.x}%`, top: `${t.bbox.y}%`,                   // 왼쪽 위 모서리 위치
            width: `${t.bbox.w}%`, height: `${t.bbox.h}%`,               // 가로·세로 크기
        });                                                              // (%라서 화면 크기가 바뀌어도 같은 자리)
        const conf = `${Math.round((t.confidence || 0) * 100)}%`;        // 탐지 신뢰도
        box.innerHTML = `<span class="bbox-label" title="${esc(`${t.tracking_id} · ${modelName(t)} · ${conf}`)}">${esc(t.tracking_id)} · ${conf}</span>`;  // 박스 위 라벨 'Tank-03 · 93%' (마우스 올리면 기종까지)
        if (t.is_unknown) box.innerHTML += `<span class="bbox-unk-mark">?</span>`;  // 미확인 '?' 표시
        box.addEventListener("click", () => selectTarget(t.tracking_id));            // 박스 클릭 = 표적 선택
        video.appendChild(box);                                          // 영상 영역에 붙이기
    });
    resolveLabelOverlaps();                                              // 다 붙인 뒤 라벨 겹침 정리
}

function resolveLabelOverlaps() {                                        // 라벨끼리 겹치면 박스 아래로 내림
    const labels = Array.from(document.querySelectorAll(".bbox-label")); // 모든 라벨
    labels.forEach((l) => l.classList.remove("label-below"));            // 지난번에 내렸던 것 원위치
    const placed = [];                                                   // 이미 놓인 라벨 위치
    labels.forEach((label) => {                                          // 라벨마다
        const r = label.getBoundingClientRect();                         // 지금 화면상 위치·크기
        const overlaps = placed.some((p) => !(r.right <= p.left || r.left >= p.right || r.bottom <= p.top || r.top >= p.bottom));  // 이미 놓인 것과 사각형이 겹치는지
        if (overlaps) {                                                  // 겹치면
            label.classList.add("label-below");                          // 박스 아래쪽으로 옮김 (CSS)
            placed.push(label.getBoundingClientRect());                  // 내린 뒤 위치로 기록
        } else {                                                         // 안 겹치면
            placed.push(r);                                              // 그 자리 그대로 기록
        }
    });
}

/* ===== 상단 카운터 ===== */
function bump(id, value) {                                               // 값이 바뀌면 숫자 깜빡임
    const el = $(id);                                                    // 숫자 칸
    if (el.textContent !== String(value)) {                              // 값이 바뀌었을 때만
        el.textContent = value;                                          // 새 숫자
        el.classList.remove("pulse");                                    // 애니메이션 초기화
        requestAnimationFrame(() => el.classList.add("pulse"));          // 다음 프레임에 다시 붙여야 애니메이션이 재생됨
    }
}
function renderCountBar() {                                              // 상단 '전체·전차·기갑차·포병·신규' 숫자
    const c = data.counts;                                               // 서버가 센 값
    bump("cb-total", c.total);                                           // 전체
    bump("cb-tank", c.tank);                                             // 전차
    bump("cb-apc", c.apc);                                               // 기갑차
    bump("cb-arty", c.artillery + c.infantry);                           // '포병' 칸 = 포병 + 인원 (둘 다 위협도 계산 대상이 아님)
    bump("cb-new", c.new);                                               // 신규 (직전 분석에 없던 표적)
}

/* ===== 위협도 랭킹 표 (순위는 서버가 매김: 전차 위협도 높은 순, 미확인은 뒤) ===== */
function threatCell(t) {                                                 // '95.8 [매우 높음]' 또는 '산출 불가'
    if (t.threat == null) return `<span class="grade gx" title="제원이 없어 위협도를 계산할 수 없음">산출 불가</span>`;  // 점수 없음 (미확인)
    return `<span class="threat-cell"><b>${t.threat.toFixed(1)}</b><span class="grade ${GRADE_CLASS[t.grade]}">${esc(t.grade)}</span></span>`;  // 점수(소수 1자리) + 색 배지
}
function renderTable() {                                                 // 랭킹 표 행 만들기. 순위 있는 표적 목록을 돌려줌
    const ranked = targets.filter((t) => t.rank != null);                // 순위 있는 표적 (전차·미확인)
    $("target-count").textContent = `(${ranked.length})`;                // 제목 옆 '(9)'
    const body = $("rank-body");                                         // 표 본문
    if (!ranked.length) {                                                // 표적이 하나도 없으면
        body.innerHTML = `<tr><td colspan="6" class="empty"></td></tr>`; // 빈 행 하나 (CSS 가 안내 문구 표시)
        return ranked;                                                   // 빈 목록
    }
    // 표적 1개 = 행 1개. 칸 순서: 순위 | Tracking ID | 기종 | 위협도(threatCell) | 근거 태그(칩) | 신뢰도(소수 2자리)
    // 값은 모두 esc() 로 감싸 HTML 로 해석되지 않게 함. data-id 는 행 클릭 시 어떤 표적인지 알기 위함
    body.innerHTML = ranked.map((t) => `
        <tr data-id="${esc(t.tracking_id)}">
            <td class="rank-num">${t.rank}</td>
            <td>${esc(t.tracking_id)}</td>
            <td>${esc(modelName(t))}</td>
            <td>${threatCell(t)}</td>
            <td class="col-left tag-td"><div class="tag-cell">${t.tags.map((r) => `<span class="chip">${esc(r)}</span>`).join("")}</div></td>
            <td>${(t.confidence || 0).toFixed(2)}</td>
        </tr>`).join("");
    body.querySelectorAll("tr[data-id]").forEach((tr) =>                 // 방금 만든 행마다
        tr.addEventListener("click", () => selectTarget(tr.dataset.id)));  // 행 클릭 = 표적 선택
    return ranked;                                                       // render() 가 1위 자동 선택에 씀
}

/* ===== 표적 선택 (표·영상·지도 공통) ===== */
function selectTarget(id, opts) {                                        // 표적 하나를 고름 (opts.auto = 프로그램이 자동으로 고른 것)
    selectedId = id;                                                     // 선택 기억
    if (!(opts && opts.auto)) hasManualSelection = true;                 // 직접 고른 경우만 '수동 선택'
    highlight();                                                         // 표·박스·마커 강조
    const t = targets.find((x) => x.tracking_id === id);                 // 그 표적 데이터 찾기
    if (t) renderPanelB(t);                                              // 오른쪽 상세 패널 채우기
}

function highlight() {                                                   // 표 행·박스·지도 마커를 함께 강조
    document.querySelectorAll("#rank-body tr").forEach((tr) =>           // 표 행마다
        tr.classList.toggle("selected", tr.dataset.id === selectedId));  // 선택된 행만 'selected' 클래스
    document.querySelectorAll(".bbox").forEach((b) =>                    // 영상 박스마다
        b.classList.toggle("selected", b.dataset.id === selectedId));    // 선택된 박스만 굵은 테두리
    Object.entries(markers).forEach(([id, m]) => {                       // 지도 마커마다
        const on = id === selectedId;                                    // 선택된 마커인지
        m.setRadius(on ? 10 : 6).setStyle({ weight: on ? 3 : 1.5, color: on ? "#1f2419" : "#fff" });  // 선택 마커는 크고 테두리 진하게
        if (on) { m.bringToFront(); m.openTooltip(); } else m.closeTooltip();  // 선택 마커는 맨 앞 + 이름표 열기, 나머지는 닫기
    });
}

/* ===== (A) 상황 패널: 군집 대응단계 ===== */
function renderPanelA() {                                                // 오른쪽 맨 위 패널
    const stage = effectiveStage();                                      // 지휘관 조정 > AI 권고
    const a = data.alert;                                                // 서버가 계산한 경보 (가장 심각한 군집 기준)
    document.querySelectorAll("#pa-ladder li").forEach((li) => {         // 단계 사다리: 지금 단계 칸만 칠함
        const n = Number(li.dataset.stage);                              // 칸 번호 1~4
        li.className = n === stage ? `on stage${n}` : n === a.level && commanderStage != null ? `ai stage${n}` : "";  // 조정했으면 AI 권고 칸은 테두리
        li.setAttribute("aria-current", n === stage ? "step" : "false"); // 화면 읽기 프로그램용 현재 단계
    });
    $("pa-change").textContent = a.prev_level != null && a.prev_level !== a.level  // 직전 분석과 단계가 다르면
        ? `${STAGE_SHORT[a.prev_level]} → ${STAGE_SHORT[a.level]} (${now()})` : "";  // 직전 분석 대비 변화
    $("pa-override").hidden = commanderStage == null;                    // 지휘관 조정 표시
    $("pa-override").textContent = commanderStage == null ? ""          // 조정 안 했으면 빈칸
        : `AI 권고 ${STAGE_SHORT[a.level]} → 지휘관 결정 ${STAGE_SHORT[commanderStage]}`;  // 했으면 AI 값과 지휘관 값을 나란히

    // 군집 카드 목록. 카드 1개 = 군집 1개:
    //   머리줄: 군집 ID | 단계 배지 | '중대급 7대 ×2'(제대·대수·제대가중치) | 전술 이름 (지휘관이 지정했으면 주황 + '(지정)')
    //   아래줄: 판정 근거 (reasons[0] 제대는 머리줄과 같아 빼고, 나머지를 ' · ' 로 이어 회색 글씨로)
    $("pa-clusters").innerHTML = data.clusters.map((c) => `
        <li class="cluster-item stage${c.level}">
            <div class="ci-head">
                <b>${esc(c.cluster_id)}</b>
                <span class="badge stage${c.level}">${STAGE_SHORT[c.level]}</span>
                <span>${esc(c.echelon.name)}급 ${c.echelon.n}대 ×${c.echelon.weight}</span>
                <span class="ci-tactic${c.tactic_source === "지휘관 지정" ? " manual" : ""}"
                      title="${esc(c.tactic_source)}">${esc(c.tactic_name)}${c.tactic_source === "지휘관 지정" ? " (지정)" : ""}</span>
            </div>
            <div class="ci-reasons">${c.reasons.slice(1).map(esc).join(" · ")}</div>
        </li>`).join("");                                                // 군집마다 단계·제대·전술 + 판정 근거 (reasons[0] 제대는 머리줄과 같아 생략)

    const sel = $("tp-cluster");                                         // 전술 선택의 군집 목록
    const keep = sel.value;                                              // 고르던 군집 유지
    sel.innerHTML = data.clusters.map((c) => `<option value="${esc(c.cluster_id)}">${esc(c.cluster_id)} (${esc(c.echelon.name)}급)</option>`).join("");  // 'C-1 (중대급)' 같은 선택지
    if (data.clusters.some((c) => c.cluster_id === keep)) sel.value = keep;  // 고르던 군집이 아직 있으면 그대로
    syncTacticSelect();                                                  // 전술 목록도 그 군집 상태로
}

function syncTacticSelect() {                                            // 전술 목록을 선택 군집의 현재 상태로 맞춤
    const c = data && data.clusters.find((x) => x.cluster_id === $("tp-cluster").value);  // 고른 군집 데이터
    if (!c) return;                                                      // 아직 데이터가 없으면 아무것도 안 함
    $("tp-tactic").value = c.tactic_source === "지휘관 지정" ? String(c.tactic) : "";  // 자동이면 '자동' 선택
}

async function applyTactic() {                                           // 전술 적용 → 서버 재계산
    const cid = $("tp-cluster").value;                                   // 고른 군집 ID
    const v = $("tp-tactic").value;                                      // 고른 전술 번호 ('' = 자동)
    const ok = await fetchResult(`/api/clusters/${encodeURIComponent(cid)}/tactic`, {  // PATCH /api/clusters/C-1/tactic
        method: "PATCH",                                                 // 기존 결과의 일부만 바꾸는 요청
        headers: { "Content-Type": "application/json" },                 // 본문이 JSON 이라고 알림
        body: JSON.stringify({ tactic: v === "" ? null : Number(v) }),     // '' = 자동으로 되돌림
    });                                                                  // 성공하면 fetchResult 가 화면을 새 결과로 다시 그림
    if (ok) $("tactic-pick").hidden = true;                              // 성공 시 펼침 영역 닫기
}

function openReport() {                                                  // 보고서 출력: 인쇄용 페이지를 새 탭으로
    const q = commanderStage != null ? `?stage=${commanderStage}` : "";  // 지휘관 조정 단계를 보고서에 전달
    window.open(`/report${q}`, "_blank");                                // 새 탭으로 /report 열기
}

function flashPanelA() {                                                 // 단계가 올라갔을 때 상황 패널을 잠깐 깜빡임
    const el = $("pa-panel");                                            // 상황 패널
    el.classList.add("flash");                                           // 깜빡임 시작 (CSS 애니메이션)
    setTimeout(() => el.classList.remove("flash"), 900);                 // 0.9초 뒤 끔
}
function confirmPanelA() {                                               // '확인' 버튼
    hideBanner();                                                        // 배너 닫기
    $("pa-panel").classList.remove("flash");                             // 깜빡임 멈춤
}
function showBanner(text) {                                              // 화면 맨 위 경보 배너 보이기
    $("alert-banner-text").textContent = text;                           // 문구
    $("alert-banner").hidden = false;                                    // 보이기
    document.body.classList.add("has-banner");                           // 배너 높이만큼 화면 내림
}
function hideBanner() {                                                  // 배너 숨기기
    $("alert-banner").hidden = true;                                     // 숨김
    document.body.classList.remove("has-banner");                        // 내렸던 화면 원위치
}

/* ===== (B) 선택 표적 상세 ===== */
function renderPanelB(t) {                                               // 오른쪽 가운데 패널: 고른 표적 1개의 상세
    $("pb-title").textContent = `${t.tracking_id} · ${modelName(t)}`;    // 'Tank-03 · T-90M'
    $("pb-status-badge").className = `badge ${t.is_unknown ? "unknown" : "known"}`;  // 미확인이면 보라, 아니면 파랑
    $("pb-status-badge").textContent = t.is_unknown ? "미확인·미검토" : "Known";      // 배지 글자
    $("pb-conf").innerHTML = `신뢰도 <b>${Math.round((t.confidence || 0) * 100)}%</b>`;  // 탐지 신뢰도

    $("pb-score").innerHTML = `${t.threat ?? "—"}<small> 위협도</small>`;    // 전차 위협도 점수
    $("pb-grade").innerHTML = t.threat == null ? "" : `<span class="grade ${GRADE_CLASS[t.grade]}">${esc(t.grade)}</span>`;  // 위협도 단계 배지 (점수 없으면 비움)
    $("pb-stage-badge").className = `badge stage${t.level}`;             // 소속 군집 단계 색
    $("pb-stage-badge").textContent = `${t.cluster_id} ${STAGE_SHORT[t.level]}`;  // 소속 군집 대응단계

    // 화력·기동력·방호력 막대 3줄. 막대 길이 = 점수 ÷ 150 (넘치면 100%), 오른쪽 글자 = '점수 × 적용된 전술 가중치'
    // 점수가 없는 표적(미확인 등)은 막대 대신 '제원 없음' 문구
    $("pb-bars").innerHTML = t.scores
        ? ["firepower", "mobility", "protection"].map((k) => `
        <div class="stat-row">
            <span class="stat-label">${STAT_LABEL[k]}</span>
            <span class="stat-track"><span class="stat-fill" style="width:${Math.min(t.scores[k] / BAR_MAX, 1) * 100}%"></span></span>
            <span class="stat-value">${t.scores[k]} × ${t.weights[k]}</span>
        </div>`).join("")                                                   // 점수 × 적용된 전술 가중치
        : `<p class="muted">제원 없음 — 위협도 산출 불가 (${esc(t.category)})</p>`;  // 점수 없음

    const tags = t.tags.filter((r) => !r.endsWith(" 소속"));               // 'C-1 소속'은 바로 위 단계 배지와 중복
    $("pb-reasons").innerHTML = tags.length                                 // 태그가 있으면
        ? tags.map((r) => `<span class="chip">${esc(r)}</span>`).join("")   // 칩으로 나열
        : `<span class="muted">해당 없음</span>`;                            // 없으면 안내 문구

    const p = t.position;                                                   // 추정 위치
    $("pb-info").textContent = `추정 거리 ${(p.distance_m / 1000).toFixed(1)} km · 방위 ${p.bearing_deg}° · 전술 ${t.tactic_name}`;  // m → km 변환해 표시
    $("pb-dict-link").style.display = t.model ? "" : "none";                // 기종 없으면 사전 링크 숨김 (#pb-dict-link 의 display 규칙이 hidden 보다 우선)
    $("pb-dict-link").href = `/dictionary?q=${encodeURIComponent(t.model || "")}`;  // 사전 페이지에서 기종명으로 검색
}

/* ===== (C) 미니맵: 관측 지점 기준 추정 위치 ===== */
function mapFail() {                                                        // 지도를 못 불러왔을 때
    $("map-fail").hidden = false;                                           // '지도를 불러올 수 없음'
}

function initMap() {                                                        // 페이지 시작 때 지도 한 번 만들기
    if (typeof L === "undefined") return mapFail();                         // Leaflet CDN 로딩 실패 (오프라인 등)
    map = L.map("minimap", { zoomControl: false });                         // #minimap 칸에 지도 생성 (+/- 버튼 없이)
    let tileOk = false;                                                     // 타일이 한 장이라도 왔는지
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" })  // OpenStreetMap 지도 그림
        .on("tileload", () => { tileOk = true; })                           // 한 장이라도 오면 성공으로 기록
        .on("tileerror", () => { if (!tileOk) mapFail(); })                  // 처음부터 실패하면 안내 표시
        .addTo(map);                                                        // 지도에 붙이기
    mapLayer = L.layerGroup().addTo(map);                                   // 마커·원을 담는 레이어 (다시 그릴 때 통째로 비움)
}

function renderMap() {                                                      // 분석 결과가 올 때마다 마커 다시 그림
    if (!map) return;                                                       // 지도가 없으면(로딩 실패) 건너뜀
    mapLayer.clearLayers();                                                 // 이전 마커·원 전부 지우기
    markers = {};                                                           // 마커 목록도 비움
    const obs = data.source.observer;                                       // 관측 지점 (카메라 위치)
    const points = [[obs.lat, obs.lon]];                                    // 화면 맞춤 범위

    data.clusters.forEach((c) => {                                          // 군집은 원으로 묶어 표시
        const pos = targets.filter((t) => t.cluster_id === c.cluster_id).map((t) => [t.position.lat, t.position.lon]);  // 이 군집 표적들의 [위도, 경도]
        if (!pos.length) return;                                            // 표적이 없으면 원도 안 그림
        const center = L.latLng(pos.reduce((s, p) => s + p[0], 0) / pos.length, pos.reduce((s, p) => s + p[1], 0) / pos.length);  // 평균 위치
        const radius = Math.max(...pos.map((p) => center.distanceTo(p))) + 120;  // 가장 먼 표적 + 여유 120m
        L.circle(center, { radius, color: stageColor(c.level), weight: 1.5, dashArray: "4 4", fillOpacity: 0.08 })  // 단계 색 점선 원
            .bindTooltip(`${esc(c.cluster_id)} · ${STAGE_SHORT[c.level]} · ${esc(c.echelon.name)}급`).addTo(mapLayer);  // 마우스 올리면 'C-1 · 2단계 · 중대급'
    });

    targets.forEach((t) => {                                                // 표적 마커 (색 = 군집 대응단계)
        const ll = [t.position.lat, t.position.lon];                        // 추정 위치
        points.push(ll);                                                    // 화면 맞춤 범위에 추가
        markers[t.tracking_id] = L.circleMarker(ll, { radius: 6, color: "#fff", weight: 1.5, fillColor: stageColor(t.level), fillOpacity: 1 })  // 흰 테두리 동그라미
            .bindTooltip(`${esc(t.tracking_id)} · ${esc(modelName(t))} (추정)`)  // 이름표
            .on("click", () => selectTarget(t.tracking_id))                 // 마커 클릭 = 표적 선택
            .addTo(mapLayer);                                               // 레이어에 붙이기
    });

    L.circleMarker([obs.lat, obs.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#1f2419", fillOpacity: 1 })  // 관측 지점 점
        .bindTooltip("관측 지점").addTo(mapLayer);                          // 관측 지점은 검은 점

    map.invalidateSize();                                                   // 패널 크기 변화 반영
    map.fitBounds(points, { padding: [20, 20], maxZoom: 15 });              // 전체가 보이게 확대·이동
}

init();                                                                     // 스크립트가 읽히면 바로 시작
