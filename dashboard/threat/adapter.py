"""대시보드 표적 행 ↔ response_level.assess 입력·출력 변환. 군집 대응단계 판정 엔진은 response_level.assess 하나다.

- 전차 1대 위협도 T 는 대시보드(judge.threat_of · core.tank_threat)가 계산해 "T" 로 넘긴다 → cope cage 보정·계열 p75·지휘전차 가중치가 판정에 그대로 쓰임
- 결과는 화면(dashboard.js)이 쓰는 Cluster 형식(level, label, score, t_cluster, echelon, reasons)으로 되돌린다
- 경계값은 response_level.load_coef() (DB threat_coef 우선, 없으면 config 기본값)
"""
import sys
from pathlib import Path

from . import config as C
from .core import infer_tactic, is_unknown

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import response_level as rl  # noqa: E402

RULE_KO = {"Unknown 포함": "미확인 포함", "핵심표적 지정": "핵심표적 지정"}   # 하한 규칙 이름 → 화면 문구


def load_coef():
    """판정 경계값 (lv1·lv2·lv3·floor_t)."""
    return rl.load_coef()


def to_assess_input(cluster_id, rows, members, frames, tactic, tactic_source, core_targets):
    """대시보드 군집 1개 → assess 입력.
    rows = pipeline 이 만든 표적 행 (threat 계산 끝난 것), members = 그 군집 탐지, frames = 프레임별 tracking_id 목록 (v1 은 None)
    tactic_source 가 '지휘관 지정' 이면 tactic 은 지휘관 전술(override), 아니면 시스템 추정 전술."""
    override = int(tactic) if tactic_source == "지휘관 지정" else None
    ids = {r["tracking_id"] for r in rows}
    out = {"cluster_id": cluster_id,
           "system_tactic": int(infer_tactic(members)),                       # 지휘관이 바꾸기 전 시스템 추정
           "tactic_override": override,
           "core_targets": [t for t in core_targets if t in ids],
           "echelon_count_unknown": C.ECHELON_COUNT_UNKNOWN,
           "vehicles": [{"track_id": r["tracking_id"], "status": r["status"], "category": r["category"],
                         "tank_id": r.get("tank_id"), "type_group": r.get("type_group"), "name": r.get("model"),
                         "is_command": bool(r["is_commander"]), "confidence": r.get("confidence"),
                         "T": r["threat"], "threat_source": r.get("threat_source"), "tags": []} for r in rows]}
    if frames:                                                                  # v2: 프레임별로 동시에 보인 대수의 최댓값
        out["frames"] = [[t for t in f if t in ids] for f in frames]
    return out


def floor_text(f):
    """하한 규칙 1개 → 화면 문장. 예: '미확인 포함 → 최소 3단계 (미확인 1대: UNK-001)'."""
    rule = RULE_KO.get(f["rule"], f["rule"])
    return f"{rule} → 최소 {f['min_level']}단계 ({f['reason'].replace('Unknown', '미확인')})"


def from_assess_output(result):
    """assess 결과 → 화면 Cluster 형식. 화면 필수 필드 + S·E·N·level_before_override·하한 규칙 목록."""
    n, e, s, t, base = result["N"], result["E"], result["S"], result["T_cluster"], result["score_level"]
    applied = result["floors_applied"]
    reasons = [f"{result['echelon']}급 {n}대 ×{e}" if n else "전투차량 없음",                     # 근거 1: 제대
               f"군집점수 {s:g} = 최고 위협도 {t:g} × {e} → {base}단계"]                          # 근거 2: 점수 판정
    reasons += [floor_text(f) for f in applied]                                                  # 근거 3~: 적용된 하한
    return {"level": result["level"], "label": C.LEVELS[result["level"]], "score": s, "t_cluster": t,
            "echelon": {"n": n, "weight": e, "name": result["echelon"]}, "reasons": reasons,
            "floors": [dict(f, text=floor_text(f), applied=f in applied) for f in result["floors_checked"]],
            "score_level": base, "level_before_override": result.get("level_before_override", result["level"]),
            "S": s, "E": e, "N": n, "core_targets": result.get("core_targets", [])}


def assess_cluster(cluster_id, rows, members, frames, tactic, tactic_source, core_targets, coef):
    """대시보드 군집 판정 = to_assess_input → response_level.assess → from_assess_output.
    기록 저장(dashboard/__init__.py)을 위해 assess 입력·결과를 내부 필드 _assess_input·_assess_result 로 붙인다."""
    inp = to_assess_input(cluster_id, rows, members, frames, tactic, tactic_source, core_targets)
    res = rl.assess(inp, {}, {}, coef)                                          # T 를 모두 넘기므로 lookup 은 비워도 됨
    return dict(from_assess_output(dict(res, core_targets=inp["core_targets"])), _assess_input=inp, _assess_result=res)


def cluster_response_level(cluster, coef=None):
    """예전 호출 형식 호환: {"detections": [탐지...], "threats": [i번째 탐지의 위협도...]} → Cluster 형식.
    threats 는 detections 와 같은 순서 (모자라면 그 탐지는 점수 없음)."""
    dets, threats = cluster["detections"], cluster.get("threats", [])
    rows = [{"tracking_id": d.get("tracking_id") or f"#{i}", "status": "Unknown" if is_unknown(d) else "Known",
             "category": d.get("category"), "model": d.get("model"), "is_commander": d.get("is_commander", False),
             "confidence": d.get("confidence"), "threat": threats[i] if i < len(threats) else None}
            for i, d in enumerate(dets)]
    out = assess_cluster("C", rows, dets, None, infer_tactic(dets), "시스템 추정", [], coef or load_coef())
    return {k: v for k, v in out.items() if not k.startswith("_")}
