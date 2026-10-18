"""위협도·대응수준 API (blueprint). 판정 로직은 response_level.py, 계산은 threat_calc.py."""
from flask import Blueprint, jsonify, request

import response_level as rl
import threat_db as tdb

bp = Blueprint("threat", __name__, url_prefix="/api/threat")


def _actor():
    return request.headers.get("X-User") or (request.get_json(silent=True) or {}).get("actor") or "unknown"


@bp.errorhandler(ValueError)
def _bad(e):
    return jsonify(error=str(e)), 400


@bp.errorhandler(LookupError)
def _missing(e):
    return jsonify(error=f"군집 없음: {e}"), 404


@bp.post("/assess")
def assess():
    cluster = request.get_json(force=True)
    if not cluster.get("cluster_id"):
        raise ValueError("cluster_id 필요")
    return jsonify(rl.assess_and_save(cluster))


@bp.patch("/cluster/<cluster_id>/tactic")
def tactic(cluster_id):
    body = request.get_json(force=True)  # {"tactic": 4} 또는 {"tactic": null} (해제)
    return jsonify(rl.apply_override(cluster_id, "tactic", body.get("tactic"), _actor()))


@bp.patch("/cluster/<cluster_id>/core-target")
def core_target(cluster_id):
    body = request.get_json(force=True)  # {"track_id": "trk-3", "remove": false}
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
