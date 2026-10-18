"""Unknown 레지스트리: 영상이 달라도 같은 미확인 기종으로 보이는 표적을 그룹으로 묶어 DB 에 쌓는다.

- 매칭: Unknown 트랙 임베딩과 open·confirmed 그룹 centroid 의 코사인 유사도 (numpy 전수 비교, 규모가 작음)
  ≥ GROUP_SIM_MIN 이면 그 그룹, 아니면 새 그룹. GROUP_SIM_REVIEW 이상 후보는 review_candidates 에 남긴다 (병합 제안용)
- 집계: 프레임 수가 아니라 고유 트랙 수·고유 영상 수. (video, tracking_id) 가 같으면 같은 행을 고친다 (재분석해도 중복 없음)
- centroid = 그룹 sighting 임베딩 평균. 누적 평균과 같은 값이고, 재분석·병합 뒤에도 sighting 에서 다시 계산해 어긋나지 않는다
- 순위 점수(priority) 는 config 의 PRIORITY_* · RECENT_* 로 계산 (목록을 볼 때마다 다시 계산: '최근' 기준이 날마다 바뀜)
DB 는 threat_db (MySQL, TANKLAB_DEMO=1 이면 SQLite).
ponytail: 요청마다 연결을 새로 연다 — 분석 1회에 미확인 몇 건이라 충분. 동시에 여러 분석을 돌리면 group_id 채번이 겹칠 수 있음(단일 서버 가정)
"""
import json
import logging
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import media
from .threat import config as C

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import threat_db as tdb  # noqa: E402

log = logging.getLogger(__name__)
ensure_schema = tdb.ensure_schema   # 레지스트리 테이블이 없으면 만든다 (threat_db 한 곳에서 관리)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _when(captured_at):
    """source.captured_at ('2024-03-15' 또는 '2024-03-15 10:20:00') → DATETIME 문자열. 못 읽으면 지금."""
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(str(captured_at)[:n], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return _now()


def _unit(v):
    a = np.asarray(v, dtype=float)
    n = np.linalg.norm(a)
    return a / n if n else a


def priority(g, today=None):
    """순위 점수 = max_threat × (1 + K_f·log(1+트랙수)) × (1 + K_v·(영상수−1)), 최근 RECENT_DAYS 안이면 × RECENT_BOOST."""
    p = (g["max_threat"] or 0) * (1 + C.PRIORITY_FREQ_K * math.log(1 + (g["n_tracks"] or 0))) \
        * (1 + C.PRIORITY_VIDEO_K * max((g["n_videos"] or 1) - 1, 0))
    last = g.get("last_seen")
    if last and datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S") >= (today or datetime.now()) - timedelta(days=C.RECENT_DAYS):
        p *= C.RECENT_BOOST
    return round(p, 1)


def _group(gid):
    rows = tdb.query("SELECT * FROM unknown_group WHERE group_id = %s", (gid,))
    return rows[0] if rows else None


def _live(gid):
    """병합된 그룹이면 병합 대상 그룹으로 따라간다."""
    seen = set()
    g = _group(gid)
    while g and g["status"] == "merged" and g["merged_into"] and g["group_id"] not in seen:
        seen.add(g["group_id"])
        g = _group(g["merged_into"])
    return g


def _new_group_id():
    n = tdb.query("SELECT COUNT(*) AS n FROM unknown_group")[0]["n"]
    return f"UNK-G{n + 1:04d}"


def _match(emb):
    """open·confirmed 그룹과 코사인 유사도 → (최고 그룹 id 또는 None, 유사도, 검토 후보 목록)."""
    groups = [g for g in tdb.query("SELECT group_id, centroid FROM unknown_group WHERE status IN ('open', 'confirmed')")
              if g["centroid"]]
    if not groups:
        return None, None, []
    mat = np.array([_unit(json.loads(g["centroid"])) for g in groups])
    sims = mat @ _unit(emb)
    order = np.argsort(-sims)
    best = order[0]
    if sims[best] >= C.GROUP_SIM_MIN:
        return groups[best]["group_id"], round(float(sims[best]), 4), []
    review = [{"group_id": groups[i]["group_id"], "similarity": round(float(sims[i]), 4)}
              for i in order if sims[i] >= C.GROUP_SIM_REVIEW]
    return None, None, review


def _refresh(gid, today=None):
    """sighting 으로 그룹 집계를 다시 계산 (트랙 수·영상 수·최고 위협도·centroid·처음/마지막 출현·순위 점수)."""
    rows = tdb.query("SELECT video, threat, embedding, captured_at FROM unknown_sighting WHERE group_id = %s", (gid,))
    if not rows:
        return
    embs = [_unit(json.loads(r["embedding"])) for r in rows if r["embedding"]]
    centroid = json.dumps([round(float(v), 6) for v in _unit(np.mean(embs, axis=0))]) if embs else None
    seen = sorted(str(r["captured_at"])[:19] for r in rows if r["captured_at"])
    g = {"n_tracks": len(rows), "n_videos": len({r["video"] for r in rows}),
         "max_threat": max((r["threat"] for r in rows if r["threat"] is not None), default=None),
         "last_seen": seen[-1] if seen else None}
    tdb.execute("UPDATE unknown_group SET n_tracks = %s, n_videos = %s, max_threat = %s, centroid = %s, first_seen = %s, "
                "last_seen = %s, priority = %s, updated_at = %s WHERE group_id = %s",
                (g["n_tracks"], g["n_videos"], g["max_threat"], centroid, seen[0] if seen else None, g["last_seen"],
                 priority(g, today), _now(), gid))


def _prune(gid):
    """그룹 crop 은 품질 상위 GROUP_CROP_MAX 장만 남기고 나머지는 파일·행 삭제."""
    rows = tdb.query("SELECT id, path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id", (gid,))
    for r in rows[C.GROUP_CROP_MAX:]:
        f = media.OUT / r["path"]
        if f.is_file():
            f.unlink()
        tdb.execute("DELETE FROM unknown_crop WHERE id = %s", (r["id"],))


def _save_crops(gid, sighting_id, video, target):
    """트랙의 대표 crop (최대 CROP_KEEP 장) 을 그룹 폴더에 저장. 같은 경로는 다시 저장하지 않는다."""
    for c in target["_track"]["crops"]:
        dest = f"unknown_crops/{gid}/{media.safe(video)}_{media.safe(target['tracking_id'])}_{c['frame_idx']}.jpg"
        if tdb.query("SELECT id FROM unknown_crop WHERE path = %s", (dest,)):
            continue
        if media.save_crop(c["image_path"], c["bbox_px"], dest):
            tdb.execute("INSERT INTO unknown_crop (sighting_id, group_id, path, quality, frame_idx, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (sighting_id, gid, dest, c["quality"], c["frame_idx"], _now()))
    _prune(gid)


def record(video, target, source, today=None):
    """Unknown 표적 1건(트랙) 저장 → {"group_id", "similarity", "new"} . 임베딩이 없으면 매칭을 건너뛰고 None."""
    t = target["_track"]
    if not t.get("embedding"):
        log.warning("임베딩 없음 → 레지스트리 매칭 건너뜀: %s %s", video, target["tracking_id"])
        return None
    ensure_schema()
    pos = target["position"]
    vals = {"cluster_id": target["cluster_id"], "top_k_json": json.dumps(t["top_k"], ensure_ascii=False),
            "embedding": json.dumps([round(v, 6) for v in t["embedding"]]), "threat": target["threat"],
            "lat": pos["lat"], "lon": pos["lon"], "captured_at": _when(source.get("captured_at"))}
    old = tdb.query("SELECT id, group_id, similarity FROM unknown_sighting WHERE video = %s AND tracking_id = %s",
                    (video, target["tracking_id"]))
    if old:                                                        # 같은 영상 재분석: 그 행만 고친다 (그룹은 유지)
        g = _live(old[0]["group_id"])
        gid, sim, new = g["group_id"], old[0]["similarity"], False
        tdb.execute("UPDATE unknown_sighting SET group_id = %s, " + ", ".join(f"{k} = %s" for k in vals) + " WHERE id = %s",
                    (gid, *vals.values(), old[0]["id"]))
        sighting_id = old[0]["id"]
    else:
        gid, sim, review = _match(t["embedding"])
        new = gid is None
        if new:                                                    # 새 그룹
            gid = _new_group_id()
            tdb.execute("INSERT INTO unknown_group (group_id, status, family_guess, type_group, review_candidates, updated_at) "
                        "VALUES (%s, 'open', %s, %s, %s, %s)",
                        (gid, target["family"], target.get("type_group"), json.dumps(review) if review else None, _now()))
        sighting_id = tdb.execute("INSERT INTO unknown_sighting (group_id, video, tracking_id, similarity, created_at, "
                                  + ", ".join(vals) + ") VALUES (" + ", ".join(["%s"] * (5 + len(vals))) + ")",
                                  (gid, video, target["tracking_id"], sim, _now(), *vals.values()))
    g = _group(gid)
    if target["threat"] is not None and (g["max_threat"] is None or target["threat"] >= g["max_threat"]):
        tdb.execute("UPDATE unknown_group SET threat_source = %s WHERE group_id = %s", (target["threat_source"], gid))
    tdb.execute("UPDATE unknown_group SET has_cope_cage = %s, commander_seen = %s, family_guess = COALESCE(family_guess, %s) "
                "WHERE group_id = %s", (int(bool(g["has_cope_cage"]) or target["has_cope_cage"]),
                                        int(bool(g["commander_seen"]) or target["is_commander"]), target["family"], gid))
    _refresh(gid, today)
    _save_crops(gid, sighting_id, video, target)
    return {"group_id": gid, "similarity": sim, "new": new}


def lookup(video, tracking_id):
    """이미 저장된 표적의 그룹 id (재분석·전술 변경 때 다시 저장하지 않고 붙이기). 없으면 None."""
    ensure_schema()
    rows = tdb.query("SELECT group_id FROM unknown_sighting WHERE video = %s AND tracking_id = %s", (video, tracking_id))
    g = _live(rows[0]["group_id"]) if rows else None
    return g["group_id"] if g else None


def _cover(gid):
    rows = tdb.query("SELECT path FROM unknown_crop WHERE group_id = %s ORDER BY quality DESC, id LIMIT 1", (gid,))
    return rows[0]["path"] if rows else None


def ranking(limit=C.UNKNOWN_RANK_TOP, today=None):
    """open 그룹 순위 (위협도 UNKNOWN_RANK_MIN_THREAT 미만은 저장만 하고 제외)."""
    ensure_schema()
    groups = tdb.query("SELECT * FROM unknown_group WHERE status = 'open' AND max_threat >= %s",
                       (C.UNKNOWN_RANK_MIN_THREAT,))
    for g in groups:
        g["priority"] = priority(g, today)
    groups.sort(key=lambda g: -g["priority"])
    return [_public(g, rank=i, cover=_cover(g["group_id"])) for i, g in enumerate(groups[:limit], 1)]


def detail(gid):
    """그룹 상세: 그룹 + 출현 기록(위치 포함) + crop. 없으면 None."""
    ensure_schema()
    g = _group(gid)
    if g is None:
        return None
    sightings = tdb.query("SELECT id, video, tracking_id, cluster_id, similarity, threat, lat, lon, captured_at "
                          "FROM unknown_sighting WHERE group_id = %s ORDER BY captured_at, id", (gid,))
    crops = tdb.query("SELECT c.path, c.quality, c.frame_idx, s.video, s.tracking_id FROM unknown_crop c "
                      "LEFT JOIN unknown_sighting s ON s.id = c.sighting_id WHERE c.group_id = %s ORDER BY c.quality DESC, c.id",
                      (gid,))
    for s in sightings:
        s["captured_at"] = str(s["captured_at"])[:19] if s["captured_at"] else None
    return {"group": _public(g, cover=_cover(gid)), "sightings": sightings, "crops": crops}


def _public(g, **extra):
    """API 로 내보낼 그룹 (centroid 는 빼고, 날짜는 문자열)."""
    out = {k: v for k, v in g.items() if k != "centroid"}
    for k in ("first_seen", "last_seen", "updated_at"):
        out[k] = str(out[k])[:19] if out.get(k) else None
    out["review_candidates"] = json.loads(g["review_candidates"]) if g.get("review_candidates") else []
    out["has_cope_cage"], out["commander_seen"] = bool(g["has_cope_cage"]), bool(g["commander_seen"])
    return dict(out, **extra)
