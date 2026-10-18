"""대응수준 엔진: 군집 1개(탐지 결과 JSON) → 대응수준 1~4단계.

판정 순서 (대응수준_산출_설명.docx 와 같은 번호)
  ① 전차별 T   Known=사전 T_k / Known_Variant=원형 기종 T_k / Unknown=유형별 상위 25% T_k
               (차량에 "T" 가 있으면 그 값을 그대로 씀 — 대시보드가 judge.threat_of 로 미리 계산한 T. tags·threat_source 도 같이 받음)
  ② 전술 k     지휘관 override > (지휘전차 10번, 그 외 시스템 추정 전술). 전차는 1~10번만
  ③ T_cluster  군집 내 전차 T의 최댓값
  ④ 대수 N     전차+기갑차+Unknown (포병·인원 제외, 프레임별 대수의 최댓값) → 제대가중치 E
  ⑤ S = T_cluster × E → 경계값(threat_coef lv1/lv2/lv3)으로 단계
  ⑥ 하한       Unknown·T≥floor_t → 최소 3단계, 핵심표적 → 최소 2단계
  ⑦ 우선순위   핵심표적 → 지휘전차 → T 내림차순

assess() 는 순수 함수(조회 데이터를 인자로 받음). DB 연동은 아래쪽 load_lookup / assess_and_save / apply_override.

입력 예:
{"cluster_id": "C-001", "system_tactic": 1, "tactic_override": null, "core_targets": ["trk-3"],
 "vehicles": [{"track_id": "trk-1", "status": "Known", "tank_id": "TANK_0216", "category": "전차",
               "is_command": false, "confidence": 0.91},
              {"track_id": "trk-9", "status": "Unknown", "category": "전차", "type_group": "주력전차"}],
 "frames": [["trk-1", "trk-9"], ["trk-1"]]}
"""
import hashlib
import json
import logging
from datetime import datetime

LEVELS = {1: ("즉시 보고", "적"), 2: ("우선 감시", "주황"), 3: ("지속 감시", "황"), 4: ("관심", "청")}
ECHELONS = [(16, 3, "대대"), (5, 2, "중대"), (1, 1, "소대")]  # (최소 대수, E, 제대명)
COMMAND_TACTIC = 10
log = logging.getLogger(__name__)


def echelon(n):
    return next(((e, name) for lo, e, name in ECHELONS if n >= lo), (0, "없음"))


def level_of(score, coef):
    for lv, key in ((1, "lv1"), (2, "lv2"), (3, "lv3")):
        if score >= coef[key]:
            return lv
    return 4


def _counts(r, count_unknown=True):
    """제대 대수 N 에 넣는 차량: 전차·기갑차, 그리고 분류가 포병·인원이 아닌 Unknown (④).
    count_unknown=False 면 전차·기갑차만 (예전 대시보드 방식, dashboard/threat/config.py ECHELON_COUNT_UNKNOWN)."""
    return r["category"] in ("전차", "기갑차") or (count_unknown and r["status"] == "Unknown"
                                                   and r["category"] not in ("포병", "인원"))


def _tactic(t):
    if not isinstance(t, int) or not 1 <= t <= 10:
        raise ValueError(f"전차 전술은 1~10번만 허용: {t!r}")
    return t


def assess(cluster, tanks, unknown_t, coef, _with_before=True):
    """vehicles[] 에 "T" 키가 있으면 lookup 을 쓰지 않고 그 값을 쓴다 (없을 때만 tanks 에서 t[k-1]).
    tanks: tank_id → {name, type_group, computable, confidence, t: [T_1..T_10]}
    unknown_t: (type_group, k) → 상위 25% T.  coef: lv1, lv2, lv3, floor_t."""
    override = cluster.get("tactic_override")
    system = _tactic(cluster.get("system_tactic") or 1)
    if override is not None:
        _tactic(override)
    vehicles = cluster.get("vehicles", [])
    ids = {v["track_id"] for v in vehicles}
    core = [c for c in cluster.get("core_targets", []) if c in ids]

    rows = []
    for v in vehicles:
        k = override or (COMMAND_TACTIC if v.get("is_command") else system)
        status, cat = v.get("status", "Unknown"), v.get("category", "전차")
        row = {"track_id": v["track_id"], "status": status, "category": cat, "tactic": k,
               "is_command": bool(v.get("is_command")), "core_target": v["track_id"] in core,
               "detect_confidence": v.get("confidence"), "tank_id": v.get("tank_id"), "name": None,
               "T": None, "data_confidence": None, "tags": []}
        if "T" in v:                                       # 미리 계산된 T (대시보드: cope cage·계열 p75·지휘전차 반영)
            row.update(T=v["T"], name=v.get("name") or (tanks.get(v.get("tank_id")) or {}).get("name"),
                       data_confidence=v.get("data_confidence"), threat_source=v.get("threat_source"))
            row["tags"] += list(v.get("tags") or [])
        elif cat == "전차":
            info = tanks.get(v.get("tank_id")) if status in ("Known", "Known_Variant") else None
            if info and info["computable"]:
                row.update(name=info["name"], T=info["t"][k - 1], data_confidence=info["confidence"])
                if status == "Known_Variant":
                    row["tags"].append(f"{info['name']} 계열 추정")
            else:
                tg = (info or {}).get("type_group") or v.get("type_group") or "주력전차"
                row.update(T=unknown_t.get((tg, k)), data_confidence="대체")
                row["tags"].append("분석관 검토" if status == "Unknown" else "T 산출불가 → 유형 대체")
                row["tags"].append(f"{tg} 상위25% 대체")
                if info:
                    row["name"] = info["name"]
        elif status == "Unknown":
            row["tags"].append("분석관 검토")
        rows.append(row)

    counted = {r["track_id"] for r in rows if _counts(r, cluster.get("echelon_count_unknown", True))}
    frames = cluster.get("frames")
    if frames:
        n = max(sum(1 for t in f if t in counted) for f in frames)
    else:
        n = len(counted)
    e, ech = echelon(n)

    ts = [r["T"] for r in rows if r["T"] is not None]
    t_cluster = max(ts) if ts else 0.0
    score = round(t_cluster * e, 1)
    base = level_of(score, coef)

    floors = []
    unknowns = [r["track_id"] for r in rows if r["status"] == "Unknown" and r["category"] != "포병"]
    strong = [r for r in rows if r["T"] is not None and r["status"] != "Unknown" and r["T"] >= coef["floor_t"]]
    if unknowns:
        floors.append({"min_level": 3, "rule": "Unknown 포함", "reason": f"Unknown {len(unknowns)}대: {', '.join(unknowns)}"})
    if strong:
        top = max(strong, key=lambda r: r["T"])
        floors.append({"min_level": 3, "rule": f"T≥{coef['floor_t']:g} 전차 포함",
                       "reason": f"{len(strong)}대, 최고 {top['name']} {top['T']}"})
    if core:
        floors.append({"min_level": 2, "rule": "핵심표적 지정", "reason": ", ".join(core)})
    final = min([base] + [f["min_level"] for f in floors])

    rows.sort(key=lambda r: (not r["core_target"], not r["is_command"], -(r["T"] if r["T"] is not None else -1)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    name, color = LEVELS[final]
    out = {"cluster_id": cluster.get("cluster_id"), "level": final, "level_name": name, "color": color,
           "score_level": base, "S": score, "T_cluster": t_cluster, "E": e, "echelon": ech, "N": n,
           "tactic": override or system, "tactic_source": "지휘관 수정" if override else "시스템 추정",
           "floors_applied": [f for f in floors if f["min_level"] < base], "floors_checked": floors,
           "vehicles": rows}
    if _with_before:
        plain = dict(cluster, tactic_override=None, core_targets=[])
        out["level_before_override"] = assess(plain, tanks, unknown_t, coef, _with_before=False)["level"]
        out["level_after_override"] = final
    return out


# ───────────────────────────── DB 연동 ─────────────────────────────
COEF_KEYS = ("lv1", "lv2", "lv3", "floor_t")


def load_coef():
    """판정 경계값 lv1·lv2·lv3·floor_t. DB threat_coef 가 기준이고, 테이블이 없거나 값이 빠졌으면
    dashboard/threat/config.py 의 LEVEL_THRESHOLDS·FLOOR_TANK_THREAT 를 기본값으로 쓴다 (경계값 조회는 이 함수 하나)."""
    from dashboard.threat import config as C          # 함수 안에서 import (dashboard 패키지와 순환 import 방지)
    coef = {f"lv{lv}": th for th, lv in C.LEVEL_THRESHOLDS}
    coef["floor_t"] = C.FLOOR_TANK_THREAT
    try:
        import threat_db as tdb
        coef.update({r["k"]: r["v"] for r in tdb.query("SELECT k, v FROM threat_coef") if r["k"] in COEF_KEYS})
    except Exception as e:                            # DB 없음·테이블 없음 → 기본값
        log.warning("threat_coef 를 못 읽어 config 기본 경계값 사용: %s", e)
    return coef


def load_lookup():
    import threat_db as tdb
    tanks = {r["tank_id"]: {"name": r["canonical_name"], "type_group": r["type_group"], "computable": bool(r["computable"]),
                            "confidence": r["confidence"], "t": [r[f"t{i}"] for i in range(1, 11)]}
             for r in tdb.query("SELECT * FROM tank_threat")}
    unknown_t = {(r["type_group"], r["tactic_no"]): r["t_p75"] for r in tdb.query("SELECT * FROM type_threat_summary")}
    return tanks, unknown_t, load_coef()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")      # 시각을 직접 넣음 (SQLite 기본값은 UTC 라 MySQL 과 달라짐)


def cluster_key(video, cluster_id):
    """기록용 군집 ID '영상:군집' — 영상이 달라도 C-1 이 겹치지 않게. DB 컬럼(64자)보다 길면 앞부분 + 해시로 줄인다."""
    key = f"{video}:{cluster_id}"
    if len(key) <= 64:
        return key
    tail = f"~{hashlib.sha1(key.encode()).hexdigest()[:8]}:{cluster_id}"[-64:]
    return str(video)[:64 - len(tail)] + tail


def save_assessment(cluster, result):
    """판정 1건 기록 (cluster_assessment). cluster = assess 입력 그대로 → apply_override 가 이 입력으로 다시 판정한다."""
    import threat_db as tdb
    tdb.ensure_schema()
    return tdb.execute("INSERT INTO cluster_assessment (cluster_id, level, score, t_cluster, echelon_e, n_vehicles, tactic_no,"
                       " input_json, result_json, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                       (cluster.get("cluster_id"), result["level"], result["S"], result["T_cluster"], result["E"],
                        result["N"], result["tactic"], json.dumps(cluster, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False), _now()))


def record_override(cluster_id, actor, item, before, after, level_before, level_after):
    """지휘관 조치 1건 기록 (commander_override). item: tactic | core_target | commander | stage."""
    import threat_db as tdb
    tdb.ensure_schema()
    tdb.execute("INSERT INTO commander_override (cluster_id, actor, item, before_value, after_value, level_before,"
                " level_after, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (cluster_id, actor, item, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                 level_before, level_after, _now()))


def history(cluster_id):
    """그 군집의 판정·지휘관 조치 이력 (시간순). 각 항목: {"kind": "판정"|"조치", "at", ...}."""
    import threat_db as tdb
    tdb.ensure_schema()
    out = [{"kind": "판정", "at": str(r["created_at"])[:19], "level": r["level"], "score": r["score"],
            "tactic": r["tactic_no"], "id": r["id"]}
           for r in tdb.query("SELECT id, level, score, tactic_no, created_at FROM cluster_assessment WHERE cluster_id = %s",
                              (cluster_id,))]
    out += [{"kind": "조치", "at": str(r["created_at"])[:19], "actor": r["actor"], "item": r["item"],
             "before": json.loads(r["before_value"]) if r["before_value"] else None,
             "after": json.loads(r["after_value"]) if r["after_value"] else None,
             "level_before": r["level_before"], "level_after": r["level_after"], "id": r["id"]}
            for r in tdb.query("SELECT id, actor, item, before_value, after_value, level_before, level_after, created_at "
                               "FROM commander_override WHERE cluster_id = %s", (cluster_id,))]
    return sorted(out, key=lambda e: (e["at"], e["kind"] == "조치", e["id"]))   # 같은 시각이면 기록된 순서(판정 → 조치)


def assess_and_save(cluster, lookup=None):
    """판정 + 기록. 모든 차량에 T 가 있으면(대시보드 형식) 사전 lookup 없이 경계값만 읽는다."""
    if lookup is None:
        lookup = ({}, {}, load_coef()) if all("T" in v for v in cluster.get("vehicles", [])) else load_lookup()
    result = assess(cluster, *lookup)
    save_assessment(cluster, result)
    return result


def latest_cluster(cluster_id):
    import threat_db as tdb
    rows = tdb.query("SELECT input_json, level FROM cluster_assessment WHERE cluster_id = %s ORDER BY id DESC LIMIT 1",
                     (cluster_id,))
    return (json.loads(rows[0]["input_json"]), rows[0]["level"]) if rows else (None, None)


def apply_override(cluster_id, item, value, actor="unknown", remove=False, lookup=None):
    """item='tactic': value=전술 번호(None 이면 해제). item='core_target': value=track_id, remove=True 면 해제.
    그 군집만 재판정하고 commander_override 에 변경 전→후를 남긴다."""
    cluster, level_before = latest_cluster(cluster_id)
    if cluster is None:
        raise LookupError(cluster_id)
    if item == "tactic":
        before = cluster.get("tactic_override")
        if value is not None:
            _tactic(value)
        cluster["tactic_override"] = value
        after = value
    elif item == "core_target":
        before = list(cluster.get("core_targets", []))
        if value not in {v["track_id"] for v in cluster.get("vehicles", [])}:
            raise ValueError(f"군집에 없는 track_id: {value}")
        cluster["core_targets"] = [c for c in before if c != value] + ([] if remove else [value])
        after = cluster["core_targets"]
    else:
        raise ValueError(f"알 수 없는 항목: {item}")
    result = assess_and_save(cluster, lookup)
    record_override(cluster_id, actor, item, before, after, level_before, result["level"])
    return result
