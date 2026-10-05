const THREAT_ORDER = { High: 0, Medium: 1, Low: 2 };

let targets = [];      // 위협도 순으로 정렬된 전체 목록
let visible = [];      // 필터 적용된 목록
let selectedId = null;

const $ = (id) => document.getElementById(id);

async function init() {
    const res = await fetch("/api/targets");
    targets = (await res.json())
        .sort((a, b) => THREAT_ORDER[a.threat] - THREAT_ORDER[b.threat] || b.confidence - a.confidence);
    targets.forEach((t, i) => (t.rank = i + 1));

    renderBoxes();
    applyFilter();

    $("threat-filter").addEventListener("change", applyFilter);
    $("detail-close").addEventListener("click", closeDetail);
    document.addEventListener("keydown", (e) => e.key === "Escape" && closeDetail());
}

/* ===== 영상 위 바운딩 박스 ===== */
function renderBoxes() {
    const video = $("video");
    targets.forEach((t) => {
        const box = document.createElement("div");
        box.className = `bbox ${t.threat}`;
        box.dataset.id = t.id;
        Object.assign(box.style, {
            left: `${t.bbox.x}%`, top: `${t.bbox.y}%`,
            width: `${t.bbox.w}%`, height: `${t.bbox.h}%`,
        });
        box.innerHTML = `<span class="bbox-label">${t.id}</span>`;
        box.addEventListener("click", () => openDetail(t.id));
        video.appendChild(box);
    });
}

/* ===== 위협도 순위 테이블 ===== */
function applyFilter() {
    const f = $("threat-filter").value;
    visible = f === "all" ? targets : targets.filter((t) => t.threat === f);
    renderTable();
}

function renderTable() {
    $("target-count").textContent = `(${visible.length})`;
    const body = $("rank-body");
    if (!visible.length) {
        body.innerHTML = `<tr><td colspan="8" class="empty"></td></tr>`;
        return;
    }
    body.innerHTML = visible.map((t) => `
        <tr data-id="${t.id}" class="${t.id === selectedId ? "selected" : ""}">
            <td><span class="medal ${t.rank <= 3 ? "r" + t.rank : "rn"}">${t.rank}</span></td>
            <td>${t.id}</td>
            <td><div class="thumb"></div></td>
            <td></td>
            <td></td>
            <td><span class="badge ${t.threat}">${t.threat}</span></td>
            <td>${t.confidence.toFixed(2)}</td>
            <td></td>
        </tr>`).join("");
    body.querySelectorAll("tr[data-id]").forEach((tr) =>
        tr.addEventListener("click", () => openDetail(tr.dataset.id)));
}

function highlight() {
    document.querySelectorAll("#rank-body tr").forEach((tr) =>
        tr.classList.toggle("selected", tr.dataset.id === selectedId));
    document.querySelectorAll(".bbox").forEach((b) =>
        b.classList.toggle("selected", b.dataset.id === selectedId));
}

/* ===== 상세 패널 (현재는 빈 창) ===== */
function openDetail(id) {
    selectedId = id;
    $("layout").classList.add("has-detail");
    $("detail").hidden = false;
    highlight();
}

function closeDetail() {
    selectedId = null;
    $("detail").hidden = true;
    $("layout").classList.remove("has-detail");
    highlight();
}

init();
