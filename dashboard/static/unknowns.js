// 미확인 레지스트리 화면 (/unknowns). 데이터는 /api/unknowns, /api/unknowns/<id> 에서 받고 계산하지 않는다.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));  // API 값은 외부 입력
const STATUS = { open: "검토 대기", confirmed: "확정", merged: "병합됨", dismissed: "기각" };
let map = null, layer = null, selected = null;

async function getJSON(url) {
    const res = await fetch(url);
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || res.status);
    return body;
}

async function init() {
    if (typeof L !== "undefined") {
        map = L.map("ud-map", { zoomControl: false });
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" })
            .on("tileerror", () => { $("map-fail").hidden = false; }).addTo(map);
        layer = L.layerGroup().addTo(map);
    } else {
        $("map-fail").hidden = false;
    }
    let groups = [];
    try {
        groups = (await getJSON("/api/unknowns")).groups;
    } catch (err) {
        $("unk-body").innerHTML = `<tr><td colspan="7" class="empty">목록을 불러오지 못했습니다: ${esc(err.message)}</td></tr>`;
        return;
    }
    if (!groups.length) {
        $("unk-body").innerHTML = `<tr><td colspan="7" class="empty">아직 저장된 미확인 그룹이 없습니다. 대시보드에서 분석을 실행하세요.</td></tr>`;
        return;
    }
    // 그룹 1개 = 행 1개. 칸: 순위 | 그룹 ID | 추정 계열 | 최고 위협도(근거) | 트랙 수 | 영상 수 | 최근 출현 날짜
    $("unk-body").innerHTML = groups.map((g) => `
        <tr data-id="${esc(g.group_id)}">
            <td class="rank-num">${g.rank}</td>
            <td>${esc(g.group_id)}</td>
            <td>${esc(g.family_guess || "모름")}</td>
            <td title="${esc(g.threat_source)}"><b>${g.max_threat ?? "—"}</b></td>
            <td>${g.n_tracks}</td>
            <td>${g.n_videos}</td>
            <td>${esc((g.last_seen || "").slice(0, 10))}</td>
        </tr>`).join("");
    document.querySelectorAll("#unk-body tr[data-id]").forEach((tr) => tr.addEventListener("click", () => show(tr.dataset.id)));
    show(groups[0].group_id);                                        // 1위 자동 선택
}

async function show(id) {
    selected = id;
    document.querySelectorAll("#unk-body tr").forEach((tr) => tr.classList.toggle("selected", tr.dataset.id === id));
    let d;
    try {
        d = await getJSON(`/api/unknowns/${encodeURIComponent(id)}`);
    } catch (err) {
        $("unk-empty").textContent = `그룹을 불러오지 못했습니다: ${err.message}`;
        return;
    }
    if (selected !== id) return;                                     // 기다리는 사이 다른 그룹을 골랐으면 버림
    const g = d.group;
    $("unk-empty").hidden = true;
    $("unk-body-detail").hidden = false;
    $("ud-title").textContent = g.group_id;
    $("ud-status").textContent = STATUS[g.status] || g.status;
    $("ud-chips").innerHTML = [g.threat_source, g.has_cope_cage && "cope cage 탐지", g.commander_seen && "지휘전차와 함께 출현"]
        .filter(Boolean).map((c) => `<span class="chip">${esc(c)}</span>`).join("");
    const review = g.review_candidates.map((r) => `${esc(r.group_id)} (유사도 ${r.similarity})`).join(", ");
    $("ud-facts").innerHTML = [
        ["최고 위협도", g.max_threat ?? "—"], ["추정 계열", esc(g.family_guess || "모름")],
        ["출현", `트랙 ${g.n_tracks} · 영상 ${g.n_videos}`],
        ["처음 · 마지막", `${esc((g.first_seen || "").slice(0, 10))} · ${esc((g.last_seen || "").slice(0, 10))}`],
        ["순위 점수", g.priority], ...(review ? [["병합 후보", review]] : []),
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

    $("ud-crop-count").textContent = `${d.crops.length}장`;
    // crop 1장 = 칸 1개: 이미지 + '영상 · 표적 · 프레임' 설명 (품질 높은 순)
    $("ud-gallery").innerHTML = d.crops.map((c) => `
        <figure>
            <img src="${esc(c.url)}" alt="${esc(`${c.video} ${c.tracking_id} 프레임 ${c.frame_idx}`)}" loading="lazy">
            <figcaption>${esc((c.video || "").replace(/\.[^.]+$/, ""))} · ${esc(c.tracking_id)} · #${c.frame_idx}</figcaption>
        </figure>`).join("") || `<p class="muted">저장된 crop 이 없습니다 (원본 프레임 없음).</p>`;

    if (!map) return;
    layer.clearLayers();
    const pts = d.sightings.filter((s) => s.lat != null).map((s) => {
        L.circleMarker([s.lat, s.lon], { radius: 7, color: "#fff", weight: 1.5, fillColor: getComputedStyle(document.documentElement).getPropertyValue("--purple").trim(), fillOpacity: 1 })
            .bindTooltip(`${esc(s.video)} · ${esc(s.tracking_id)} · ${esc((s.captured_at || "").slice(0, 10))}`).addTo(layer);
        return [s.lat, s.lon];
    });
    map.invalidateSize();
    if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
}

init();
