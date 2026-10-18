"""탐지 결과 → 대시보드 응답 JSON 조립. 화면(dashboard.js)은 이 응답만 쓴다.

입력 (POST /api/analyze 본문, 비우면 mock_detections.json):
  {"source": {"video", "captured_at", "source", "observer": {"lat", "lon", "heading_deg"}},
   "detections": [탐지 결과 (core.py 머리말 형식), ...]}

응답 AnalysisResult (/api/analyze, /api/threats, /api/clusters/<id>/tactic 공통):
  {"source":   입력 source 그대로,
   "counts":   {"total", "tank", "apc", "artillery", "infantry", "new"},       # 상단 카운터
   "alert":    {"level", "label", "prev_level", "banner", "message"},          # 상단 배너·상황 패널 (가장 심각한 군집 기준)
   "clusters": [Cluster, ...],                                                # 군집별 대응단계
   "targets":  [Target, ...]}                                                 # rank 순서 (전차·미확인), 그 뒤 순위 없는 표적
  Cluster = {"cluster_id", "level", "label", "score", "t_cluster", "echelon": {"n", "weight", "name"},
             "tactic", "tactic_name", "tactic_source": "시스템 추정"|"지휘관 지정", "reasons": [...], "track_ids": [...]}
  Target  = {"tracking_id", "category", "model", "confidence", "bbox", "is_commander", "is_unknown", "is_new",
             "cluster_id", "rank"|null, "threat"|null, "grade"|null,                    # 전차 1대 위협도와 단계
             "scores": {"firepower","mobility","protection","total"}|null, "weights": {...}|null,
             "tactic", "tactic_name", "level", "label",                                # level/label = 소속 군집 대응단계
             "tags": [...],                                                           # 근거 태그 (이 전차에 대한 것만)
             "position": {"bearing_deg","distance_m","lat","lon","estimated": true}}
GET /api/threats/<id> 응답: {"target": Target, "cluster": 소속 Cluster}
"""
import json          # mock 파일 읽기
import math          # 위치 추정 삼각함수
from pathlib import Path

from . import config as C
from .core import (CATEGORIES, TACTIC_NAMES, Tactic, cluster_response_level, infer_tactic, is_unknown,
                   quant_score, spec_of, tactic_weights, tank_threat, threat_grade)

MOCK_FILE = Path(__file__).with_name("mock_detections.json")  # 이미지 분석 모델 대신 쓰는 탐지 결과
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


def _target_tags(row, scores):
    """근거 태그 = 이 전차의 위협도를 설명하는 사실만 (군집 판정 근거는 Cluster.reasons 로 따로 감)."""
    tags = []
    if row["is_commander"]:
        tags.append("지휘전차")                                                        # 지휘통제 가중치가 적용된 이유
    if row["is_unknown"]:
        tags.append("미확인 · 분석관 검토" if row["category"] == "미확인" else "제원 없음 · 분석관 검토")
    if row["is_new"]:
        tags.append("신규")                                                            # 직전 분석에 없던 표적
    if scores:                                                                        # 점수가 있는 전차만
        axes = {k: scores[k] for k in AXIS_LABELS}                                    # 화력·기동·방호
        hi, lo = max(axes, key=axes.get), min(axes, key=axes.get)                     # 가장 강한/약한 지수
        tags.append(f"강점 {AXIS_LABELS[hi]} {axes[hi]:g}")
        tags.append(f"약점 {AXIS_LABELS[lo]} {axes[lo]:g}")
        tags.append(f"{row['tactic_name']} 가중치")                                     # 어떤 전술 가중치로 계산했는지
    return tags


def analyze(payload, prev=None, tactic_overrides=None):
    """payload(입력 형식) → AnalysisResult.
    prev            = 직전 분석 결과 (신규 표적·단계 변화 비교용, 없으면 None)
    tactic_overrides = {cluster_id: 전술번호} — 화면 '전술 선택'으로 지휘관이 지정한 전술 (그 군집 전차 전부에 적용)"""
    dets = _validate(payload)                                                          # 입력 검증
    source = payload["source"]
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
                   "position": estimate_position(d, source["observer"])}
            if spec:                                                                   # 제원이 있는 전차만 점수 계산
                cmd = row["is_commander"] and not override                             # 지휘관이 전술을 지정하면 그 전술이 우선
                used, (wf, wm, wp) = tactic_weights(tactic, cmd)                       # 실제 적용된 전술·가중치
                row.update(threat=tank_threat(spec, tactic, cmd), scores=quant_score(spec),
                           weights={"firepower": wf, "mobility": wm, "protection": wp},
                           tactic=int(used), tactic_name=TACTIC_NAMES[used])
                row["grade"] = threat_grade(row["threat"])                             # 매우 높음/높음/보통/낮음
            row["tags"] = _target_tags(row, row["scores"])                             # 근거 태그
            rows.append(row)

        res = cluster_response_level({"detections": members, "threats": [r["threat"] for r in rows]})  # 군집 대응단계
        for r in rows:
            r.update(level=res["level"], label=res["label"])                           # 표적에 소속 군집 단계 기록
            r["tags"].append(f"{cid} 소속")                                              # 어느 군집인지
        clusters.append(dict(res, cluster_id=cid, tactic=int(tactic), tactic_name=TACTIC_NAMES[tactic],
                             tactic_source="지휘관 지정" if override else "시스템 추정",
                             track_ids=[r["tracking_id"] for r in rows]))
        targets += rows

    # 랭킹: 전차·미확인만. 위협도 높은 순, 점수 없는 미확인은 맨 뒤 (그 안에서는 군집 단계 순)
    ranked = sorted((t for t in targets if t["category"] in RANKED),
                    key=lambda t: (t["threat"] is None, -(t["threat"] or 0), t["level"]))
    for i, t in enumerate(ranked, 1):
        t["rank"] = i
    targets = ranked + [t for t in targets if t["rank"] is None]                       # 순위 없는 표적(기갑차·포병·인원)은 뒤에

    counts = {"total": len(targets), **{k: 0 for k in COUNT_KEYS.values()}, "new": sum(t["is_new"] for t in targets)}
    for t in targets:
        if t["category"] in COUNT_KEYS:
            counts[COUNT_KEYS[t["category"]]] += 1                                    # 분류별 개수

    top = min(clusters, key=lambda c: (c["level"], -c["score"]), default=None)        # 가장 심각한 군집
    level = top["level"] if top else 4
    alert = {"level": level, "label": C.LEVELS[level], "prev_level": prev["alert"]["level"] if prev else None,
             "banner": level == 1,                                                     # 1단계면 화면 상단 배너
             "message": (f"{top['cluster_id']} {top['echelon']['name']}급 {top['echelon']['n']}대 · {top['tactic_name']}"
                         f" · 군집점수 {top['score']:g}") if top else "탐지 표적 없음"}
    return {"source": source, "counts": counts, "alert": alert, "clusters": clusters, "targets": targets}
