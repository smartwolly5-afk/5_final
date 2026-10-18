"""탐지 결과 → 대시보드 응답 JSON 조립. 화면(dashboard.js)은 이 응답만 쓴다.

입력 (POST /api/analyze 본문, 비우면 static/mock_frames 샘플 A → B):
  v2 (프레임 단위, 모델 출력 계약은 contract.md): {"source": {..., "frame_size"}, "frames": [{"frame_idx", "image_path", "detections"}]}
     → track.aggregate (트랙 집계) → judge.judge (Known/Known_Variant/Unknown) → judge.threat_of (사전 DB 위협도·cope cage)
  v1 (하위 호환, mock_detections.json): {"source": {"video", "captured_at", "source", "observer": {"lat", "lon", "heading_deg"}},
   "detections": [탐지 결과 (core.py 머리말 형식), ...]}

응답 AnalysisResult (/api/analyze, /api/threats, /api/clusters/<id>/tactic 공통):
  {"source":   입력 source 그대로,
   "counts":   {"total", "tank", "apc", "artillery", "infantry", "new"},       # 상단 카운터
   "alert":    {"level", "label", "prev_level", "banner", "message"},          # 상단 배너·상황 패널 (가장 심각한 군집 기준)
   "clusters": [Cluster, ...],                                                # 군집별 대응단계
   "targets":  [Target, ...]}                                                 # rank 순서 (전차·미확인), 그 뒤 순위 없는 표적
  Cluster = {"cluster_id", "level", "label", "score", "t_cluster", "echelon": {"n", "weight", "name"},
             "tactic", "tactic_name", "tactic_source": "시스템 추정"|"지휘관 지정", "reasons": [...], "track_ids": [...],
             "floors": [{"rule", "min_level", "reason", "text", "applied"}],          # 하한 규칙 (검사한 것 전부)
             "S", "E", "N", "score_level",                                           # 군집점수·제대가중치·대수·점수만으로 본 단계
             "level_before_override", "core_targets"}                                # 지휘관 조치(전술·지휘전차·핵심표적) 전 단계
  판정은 response_level.assess 하나 (adapter.py 가 변환). 내부 필드 _assess_input·_assess_result 는 기록 저장용 (API 로 안 나감)
  Target  = {"tracking_id", "category", "model", "confidence", "bbox", "is_commander", "is_unknown", "is_new",
             "cluster_id", "rank"|null, "threat"|null, "grade"|null,                    # 전차 1대 위협도와 단계
             "scores": {"firepower","mobility","protection","total"}|null, "weights": {...}|null,
             "tactic", "tactic_name", "level", "label",                                # level/label = 소속 군집 대응단계
             "tags": [...],                                                           # 근거 태그 (이 전차에 대한 것만)
             "position": {"bearing_deg","distance_m","lat","lon","estimated": true},
             # v2 에서 채움 (v1 은 status 만 Known/Unknown, 나머지 null·빈값)
             "status": "Known"|"Known_Variant"|"Unknown", "tank_id", "family", "type_group", "threat_source",   # 위협도를 어디서 가져왔는지
             "threat_before_bonus", "has_cope_cage", "cope_tag", "commander_evidence": {"n", "m", "on", "override"}|null,
             "parts": [{"cls", "conf", "bbox"}], "n_frames",
             "is_core",                                                               # 지휘관이 지정한 핵심표적 (랭킹 맨 위)
             "unknown_group_id", "crop_url"}                                          # 이 둘은 dashboard/__init__.py 가 채움
  source 에는 v2 일 때 "frame_image" (화면에 띄울 프레임, static 기준 경로), "frame_idx" 가 붙는다.
  alert 에는 "cluster_id" (가장 심각한 군집) 가 붙는다.
GET /api/threats/<id> 응답: {"target": Target, "cluster": 소속 Cluster}
"""
import json          # mock 파일 읽기
import math          # 위치 추정 삼각함수
from pathlib import Path

from . import adapter as AD
from . import config as C
from . import judge as J
from . import track as TR
from .core import (CATEGORIES, TACTIC_NAMES, Tactic, infer_tactic, is_unknown, quant_score, spec_of, tactic_weights,
                   tank_threat, threat_grade)

MOCK_FILE = Path(__file__).with_name("mock_detections.json")  # v1 탐지 결과 (하위 호환 테스트용)
MOCK_DIR = Path(__file__).resolve().parents[2] / "static" / "mock_frames"
MOCK_V2 = [MOCK_DIR / "mock_video_A_5f.json", MOCK_DIR / "mock_video_B_5f.json"]  # 기본 mock: 영상 A → B (5프레임)
RANKED = ("전차", "미확인")                                    # 랭킹 표에 올리는 분류
COUNT_KEYS = {"전차": "tank", "기갑차": "apc", "포병": "artillery", "인원": "infantry"}  # 카운터 키
AXIS_LABELS = {"firepower": "화력", "mobility": "기동력", "protection": "방호력"}       # 근거 태그용 이름


def load_mock(path=MOCK_FILE):
    """mock 입력기: 탐지 결과 JSON 파일을 읽는다. 모델이 붙으면 같은 형식의 dict 를 analyze() 에 넘기면 된다."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def estimate_position(det, observer):
    """관측 지점 기준 방위·거리 → 위경도.
    ponytail: mock 추정 — 방위는 bbox 가로 위치×시야각, 거리는 bbox 높이 반비례. 거리측정·카메라 보정이 생기면 교체."""
    b = det["bbox"]                                                                   # 화면 % 좌표
    bearing = (observer.get("heading_deg", 0)                                         # 카메라가 보는 방위
               + (b["x"] + b["w"] / 2 - 50) / 100 * C.CAMERA_FOV_DEG) % 360           # + 화면 중심에서 벗어난 만큼
    dist = C.DISTANCE_K * 10 / max(b["h"], 1)                                         # 박스가 클수록 가까움 (m)
    lat = observer["lat"] + dist * math.cos(math.radians(bearing)) / 111_320          # 북쪽 이동 (위도 1도 ≈ 111.32km)
    lon = observer["lon"] + dist * math.sin(math.radians(bearing)) / (111_320 * math.cos(math.radians(observer["lat"])))  # 동쪽 이동
    return {"bearing_deg": round(bearing, 1), "distance_m": round(dist), "lat": round(lat, 6), "lon": round(lon, 6),
            "estimated": True}                                                        # 화면에 '추정 위치'로 표시


def _num(d, k):
    """d[k] 가 숫자인지 (True/False 는 숫자로 치지 않음)."""
    return isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)


def _validate(payload):
    """입력 검증 (외부에서 들어오는 값이라 필수). 문제가 있으면 ValueError → API 400."""
    dets = payload.get("detections") if isinstance(payload, dict) else None
    if not isinstance(dets, list):
        raise ValueError("detections 리스트 필요")
    seen = set()                                                                       # tracking_id 중복 검사
    for d in dets:
        if not isinstance(d, dict) or not d.get("tracking_id"):
            raise ValueError("각 탐지에 tracking_id 필요")
        if d["tracking_id"] in seen:
            raise ValueError(f"tracking_id 중복: {d['tracking_id']}")
        seen.add(d["tracking_id"])
        if d.get("category") not in CATEGORIES:
            raise ValueError(f"{d['tracking_id']}: category 는 {'/'.join(CATEGORIES)} 중 하나")
        if not all(_num(d.get("bbox") or {}, k) for k in "xywh"):
            raise ValueError(f"{d['tracking_id']}: bbox x,y,w,h 숫자 필요")
        if d.get("confidence") is not None and not (_num(d, "confidence") and 0 <= d["confidence"] <= 1):
            raise ValueError(f"{d['tracking_id']}: confidence 는 0~1 숫자 또는 null")  # 화면이 toFixed() 로 표시
    obs = (payload.get("source") or {}).get("observer") or {}
    if not all(_num(obs, k) for k in ("lat", "lon")):
        raise ValueError("source.observer.lat/lon 필요")
    if obs.get("heading_deg") is not None and not _num(obs, "heading_deg"):
        raise ValueError("source.observer.heading_deg 는 숫자")                       # 위치 추정 계산에 씀
    return dets


def _commander_tag(row):
    ev = row["commander_evidence"]
    if ev and ev["override"] is not None:                                              # 지휘관이 화면에서 바꿈
        return "지휘전차 (지휘관 지정)" if row["is_commander"] else "지휘전차 해제 (지휘관)"
    if ev and ev["on"]:
        return f"안테나 탐지 {ev['n']}/{ev['m']}프레임 → 지휘전차 추정"
    return "지휘전차" if row["is_commander"] else None


def _target_tags(row, scores):
    """근거 태그 = 이 전차의 위협도를 설명하는 사실만 (군집 판정 근거는 Cluster.reasons 로 따로 감)."""
    tags = ["핵심표적 → 최소 2단계"] if row["is_core"] else []                     # 지휘관 지정 (군집 하한 규칙)
    cmd = _commander_tag(row)
    if cmd:
        tags.append(cmd)                                                               # 지휘통제 가중치가 적용된 이유
    if row["threat_source"] and row["status"] != "Known":
        tags.append(row["threat_source"])                                              # 'T-72 계열 상위25%' 등
    if row["cope_tag"]:
        tags.append(row["cope_tag"])                                                   # 'cope cage → 방호 ×1.10' 
    if row["is_unknown"]:
        tags.append("제원 없음 · 분석관 검토" if row["category"] == "전차" and row["threat_source"] is None
                    else "미확인 · 분석관 검토")                                    # v2 미확인은 대체값이 있어도 검토 대상
    if row["is_new"]:
        tags.append("신규")                                                            # 직전 분석에 없던 표적
    if scores:                                                                        # 점수가 있는 전차만
        axes = {k: scores[k] for k in AXIS_LABELS}                                    # 화력·기동·방호
        hi, lo = max(axes, key=axes.get), min(axes, key=axes.get)                     # 가장 강한/약한 지수
        tags.append(f"강점 {AXIS_LABELS[hi]} {axes[hi]:g}")
        tags.append(f"약점 {AXIS_LABELS[lo]} {axes[lo]:g}")
        tags.append(f"{row['tactic_name']} 가중치")                                     # 어떤 전술 가중치로 계산했는지
    return tags


def _v2_detections(payload, commander_overrides):
    """v2 입력 → (트랙 단위 탐지 목록 (v1 탐지 형식 + status, _v2), 화면 프레임, 프레임별 tracking_id 목록). 전차·미확인만 판정."""
    tracks, shown = TR.aggregate(payload)
    frame_ids = [[d["tracking_id"] for d in f["detections"]] for f in payload["frames"]]   # 제대 대수: 프레임별 최댓값
    dets = []
    for t in tracks:
        j = J.judge(t) if t["category"] in RANKED else None
        ov = commander_overrides.get(t["tracking_id"])                              # 지휘관 지정·해제 (없으면 None)
        model = None
        if j and j["status"] == "Known":
            model = j["name"]
        elif j and j["status"] == "Known_Variant":
            model = f"{j['family']} 계열"
        dets.append({"tracking_id": t["tracking_id"], "category": t["category"], "model": model,
                     "confidence": t["confidence"], "bbox": t["bbox"], "cluster_id": t["cluster_id"],
                     "is_commander": t["commander"]["on"] if ov is None else ov,
                     "status": j["status"] if j else None,
                     "_v2": {"track": t, "judge": j, "commander": dict(t["commander"], override=ov)}})
    return dets, shown, frame_ids


def analyze(payload, prev=None, tactic_overrides=None, commander_overrides=None, core_targets=None, coef=None):
    """payload(입력 형식) → AnalysisResult.
    prev            = 직전 분석 결과 (신규 표적·단계 변화 비교용, 없으면 None)
    tactic_overrides = {cluster_id: 전술번호} — 화면 '전술 선택'으로 지휘관이 지정한 전술 (그 군집 전차 전부에 적용)
    commander_overrides = {tracking_id: bool} — 지휘관이 지휘전차를 지정·해제 (v2 만)
    core_targets     = {tracking_id, ...} — 지휘관이 지정한 핵심표적 (그 군집 최소 2단계, 랭킹 맨 위)
    coef             = 판정 경계값 (없으면 response_level.load_coef: DB threat_coef → config 기본값)
    v2 표적에는 레지스트리 저장용 내부 필드 "_track" 이 붙는다 (API 로 내보내기 전에 dashboard/__init__.py 가 뗌)."""
    if TR.is_v2(payload):
        dets, shown, frame_ids = _v2_detections(payload, commander_overrides or {})
        source = dict(payload["source"], frame_image=shown.get("image_path"), frame_idx=shown["frame_idx"])
    else:
        dets, source, frame_ids = _validate(payload), payload["source"], None        # 입력 검증 (v1 은 프레임 정보 없음)
    coef = coef or AD.load_coef()
    core = set(core_targets or ())
    prev_ids = {t["tracking_id"] for t in prev["targets"]} if prev else None           # 직전 표적 ID 목록
    overrides = tactic_overrides or {}

    groups = {}                                                                        # cluster_id → 탐지 목록
    for d in dets:
        groups.setdefault(d.get("cluster_id") or "C-1", []).append(d)                   # 군집 ID 없으면 C-1

    for cid, t in overrides.items():                                                   # 지정 전술 검증
        if cid not in groups:
            raise LookupError(f"군집 없음: {cid}")
        if t not in C.TACTIC_WEIGHTS:
            raise ValueError(f"가중치 없는 전술 번호: {t} (1~10만 가능)")

    clusters, targets = [], []
    for cid, members in groups.items():                                                # 군집마다
        override = overrides.get(cid)                                                  # 지휘관 지정 전술 (없으면 None)
        tactic = Tactic(override) if override else infer_tactic(members)               # 지정이 없으면 시스템 추정
        rows = []
        for d in members:                                                              # 군집 안 표적마다
            spec = spec_of(d)                                                          # 전차 제원 (없으면 None)
            row = {"tracking_id": d["tracking_id"], "category": d["category"], "model": d.get("model"),
                   "confidence": d.get("confidence"), "bbox": d["bbox"], "is_commander": bool(d.get("is_commander")),
                   "is_unknown": is_unknown(d), "is_new": prev_ids is not None and d["tracking_id"] not in prev_ids,
                   "cluster_id": cid, "rank": None, "threat": None, "grade": None, "scores": None, "weights": None,
                   "tactic": int(tactic), "tactic_name": TACTIC_NAMES[tactic],
                   "position": estimate_position(d, source["observer"]),
                   "status": d.get("status") or ("Unknown" if is_unknown(d) else "Known"),
                   "tank_id": None, "family": None, "type_group": None, "threat_source": None, "threat_before_bonus": None, "cope_tag": None,
                   "has_cope_cage": False, "commander_evidence": None, "parts": [], "n_frames": 1,
                   "is_core": d["tracking_id"] in core, "unknown_group_id": None, "crop_url": None}
            v2 = d.get("_v2")
            if v2:                                                                     # v2: 트랙 집계·판정 결과
                t, j = v2["track"], v2["judge"]
                row.update(has_cope_cage=t["cope_cage"]["on"], commander_evidence=v2["commander"],
                           parts=t["parts"], n_frames=t["n_frames"], _track=t)
                if j:
                    row.update(tank_id=j["tank_id"], family=j["family"], type_group=j["type_group"])
            if v2 and v2["judge"]:                                                     # 사전 DB 위협도 (판정 상태별)
                cmd = row["is_commander"] and not override
                th = J.threat_of(v2["judge"], tactic, cmd, row["has_cope_cage"])
                row.update(threat=th["threat"], threat_before_bonus=th["threat_before_bonus"], scores=th["scores"],
                           weights=th["weights"], threat_source=th["source"], cope_tag=th["cope_tag"],
                           tactic=int(th["tactic"]), tactic_name=TACTIC_NAMES[th["tactic"]])
                row["grade"] = threat_grade(row["threat"])
            elif spec:                                                                   # 제원이 있는 전차만 점수 계산
                cmd = row["is_commander"] and not override                             # 지휘관이 전술을 지정하면 그 전술이 우선
                used, (wf, wm, wp) = tactic_weights(tactic, cmd)                       # 실제 적용된 전술·가중치
                row.update(threat=tank_threat(spec, tactic, cmd), scores=quant_score(spec),
                           weights={"firepower": wf, "mobility": wm, "protection": wp},
                           tactic=int(used), tactic_name=TACTIC_NAMES[used])
                row["grade"] = threat_grade(row["threat"])                             # 매우 높음/높음/보통/낮음
            row["tags"] = _target_tags(row, row["scores"])                             # 근거 태그
            rows.append(row)

        res = AD.assess_cluster(cid, rows, members, frame_ids, tactic, "지휘관 지정" if override else "시스템 추정",
                                core, coef)                                    # 군집 대응단계 (response_level.assess)
        for r in rows:
            r.update(level=res["level"], label=res["label"])                           # 표적에 소속 군집 단계 기록
            r["tags"].append(f"{cid} 소속")                                              # 어느 군집인지
        clusters.append(dict(res, cluster_id=cid, tactic=int(tactic), tactic_name=TACTIC_NAMES[tactic],
                             tactic_source="지휘관 지정" if override else "시스템 추정",
                             track_ids=[r["tracking_id"] for r in rows]))
        targets += rows

    # 랭킹: 전차·미확인만. 핵심표적 → 위협도 높은 순, 점수 없는 미확인은 맨 뒤 (그 안에서는 군집 단계 순)
    # 지휘전차는 태그로만 표시하고 순서에는 넣지 않는다 (response_level 의 군집 안 순서와 다름 — 팀 결정 필요)
    ranked = sorted((t for t in targets if t["category"] in RANKED),
                    key=lambda t: (not t["is_core"], t["threat"] is None, -(t["threat"] or 0), t["level"]))
    for i, t in enumerate(ranked, 1):
        t["rank"] = i
    targets = ranked + [t for t in targets if t["rank"] is None]                       # 순위 없는 표적(기갑차·포병·인원)은 뒤에

    counts = {"total": len(targets), **{k: 0 for k in COUNT_KEYS.values()}, "new": sum(t["is_new"] for t in targets)}
    for t in targets:
        if t["category"] in COUNT_KEYS:
            counts[COUNT_KEYS[t["category"]]] += 1                                    # 분류별 개수

    top = min(clusters, key=lambda c: (c["level"], -c["score"]), default=None)        # 가장 심각한 군집
    level = top["level"] if top else 4
    if tactic_overrides or commander_overrides or core:                               # 지휘관 조치 전 단계 = 조치 없이 다시 계산
        before = {c["cluster_id"]: c["level"] for c in analyze(payload, prev, coef=coef)["clusters"]}
        for c in clusters:
            c["level_before_override"] = before.get(c["cluster_id"], c["level"])
    alert = {"level": level, "label": C.LEVELS[level], "prev_level": prev["alert"]["level"] if prev else None,
             "cluster_id": top["cluster_id"] if top else None,
             "banner": level == 1,                                                     # 1단계면 화면 상단 배너
             "message": (f"{top['cluster_id']} {top['echelon']['name']}급 {top['echelon']['n']}대 · {top['tactic_name']}"
                         f" · 군집점수 {top['score']:g}") if top else "탐지 표적 없음"}
    return {"source": source, "counts": counts, "alert": alert, "clusters": clusters, "targets": targets}
