"""외부 연동용 대응수준 API (/api/threat/*). 판정·기록 로직은 response_level.py 한 곳에 있다.

용도: 외부 시스템이 군집 JSON 을 보내 대응단계(1~4) 판정을 받는 주소.
화면과의 관계: 대시보드(dashboard/__init__.py)와 **같은 엔진**(response_level.assess)·**같은 경계값**(load_coef: DB threat_coef → config)·
  **같은 기록 테이블**(cluster_assessment, commander_override)을 쓴다. 대시보드 군집은 cluster_id 가 '영상:군집' (예: mock_video_A.mp4:C-1).

POST /api/threat/assess 는 두 형식을 받는다
  1) 사전 lookup 형식 — 차량마다 tank_id, 전술별 T 는 DB tank_threat 에서 찾음
     {"cluster_id": "C-001", "system_tactic": 1, "core_targets": [],
      "vehicles": [{"track_id": "trk-1", "status": "Known", "tank_id": "TANK_0216", "category": "전차"}],
      "frames": [["trk-1"]]}
  2) 미리 계산된 T 형식 — 대시보드가 저장하는 형식 (cope cage·계열 p75·지휘전차 반영된 T)
     {"cluster_id": "ext:C-1", "system_tactic": 10, "vehicles": [
        {"track_id": "UNK-007", "status": "Unknown", "category": "미확인", "T": 99.5, "threat_source": "T-80 계열 상위25%"}]}
  응답: {"level": 3, "level_name": "지속 감시", "S": 99.5, "T_cluster": 99.5, "E": 1, "N": 2, "echelon": "소대",
         "floors_applied": [...], "floors_checked": [...], "vehicles": [...], "level_before_override": 3, ...}
PATCH /cluster/<id>/tactic, /cluster/<id>/core-target 는 마지막 판정 입력으로 다시 판정하고 commander_override 에 남긴다.
  주의: 형식 2) 는 T 가 고정이라 전술을 바꿔도 T 는 다시 계산되지 않는다 (전술에 따른 T 재계산은 대시보드 PATCH /api/clusters/<id>/tactic).
"""
from flask import Blueprint, jsonify, request

import response_level as rl
import threat_db as tdb

bp = Blueprint("threat", __name__, url_prefix="/api/threat")


def _body():
    """요청 본문 JSON 객체. 배열·문자열이면 400 (아래 ValueError 처리기)."""
    body = request.get_json(force=True)
    if not isinstance(body, dict):
        raise ValueError("본문은 JSON 객체여야 함")
    return body


def _actor(default="unknown"):
    """조치한 사람: 요청 헤더 X-User → 본문 actor → default (대시보드는 "commander"). 대시보드 라우트도 이 함수를 쓴다."""
    body = request.get_json(silent=True)
    return request.headers.get("X-User") or (body.get("actor") if isinstance(body, dict) else None) or default


@bp.errorhandler(ValueError)
def _bad(e):
    return jsonify(error=str(e)), 400


@bp.errorhandler(LookupError)
def _missing(e):
    return jsonify(error=f"군집 없음: {e}"), 404


@bp.post("/assess")
def assess():
    cluster = _body()
    if not cluster.get("cluster_id"):
        raise ValueError("cluster_id 필요")
    return jsonify(rl.assess_and_save(cluster))


@bp.patch("/cluster/<cluster_id>/tactic")
def tactic(cluster_id):
    body = _body()  # {"tactic": 4} 또는 {"tactic": null} (해제)
    return jsonify(rl.apply_override(cluster_id, "tactic", body.get("tactic"), _actor()))


@bp.patch("/cluster/<cluster_id>/core-target")
def core_target(cluster_id):
    body = _body()  # {"track_id": "trk-3", "remove": false}
    return jsonify(rl.apply_override(cluster_id, "core_target", body.get("track_id"), _actor(),
                                     remove=bool(body.get("remove"))))


@bp.get("/tank/<tank_id>")
def tank(tank_id):
    rows = tdb.query("SELECT * FROM tank_threat WHERE tank_id = %s", (tank_id,))
    if not rows:
        return jsonify(error=f"전차 ID 없음: {tank_id}"), 404
    r = rows[0]
    r["updated_at"] = str(r.get("updated_at"))
    return jsonify(r)
