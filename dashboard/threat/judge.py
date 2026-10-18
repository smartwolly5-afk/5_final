"""트랙 → Known / Known_Variant / Unknown 판정과 전차 1대 위협도 (사전 DB tank_threat 값을 씀).

| 조건                                         | 상태          | 위협도                                    |
| s1 ≥ KNOWN_SCORE 그리고 margin ≥ KNOWN_MARGIN | Known         | 그 tank_id 의 f·m·p 를 전술 가중 평균     |
| 같은 계열 top_k 점수 합 ≥ FAMILY_SCORE        | Known_Variant | 그 계열 상위 25% T                        |
| 그 외                                        | Unknown       | 추정 계열 p75 → 유형 p75 → 주력전차 p75   |
계열 표본이 FAMILY_MIN_N 미만이면 계열 대신 유형(type_group) 값을 쓰고 근거에 남긴다.
"""
import json
import logging
from pathlib import Path

from . import config as C
from . import dictdb
from .core import tactic_weights

LABELS = json.loads(Path(__file__).with_name("label_map.json").read_text(encoding="utf-8"))["labels"]
log = logging.getLogger(__name__)


def resolve(label):
    """분류 라벨 → {"tank_id", "family", "name"} (계열은 사전 DB 기준). 매핑에 없으면 None + 경고."""
    m = LABELS.get(label)
    if m is None:
        log.warning("label_map.json 에 없는 분류 라벨 → Unknown 처리: %s", label)
        return None
    if "tank_id" in m:
        row = dictdb.tank(m["tank_id"])
        if row is None:
            log.warning("사전에 없는 tank_id: %s (라벨 %s)", m["tank_id"], label)
            return {"tank_id": None, "family": None, "name": None}
        return {"tank_id": row["tank_id"], "family": row["family_name"], "name": row["canonical_name"]}
    return {"tank_id": None, "family": m.get("family"), "name": None}


def judge(track):
    """트랙의 평균 top_k 로 판정 → {"status", "tank_id", "name", "family", "type_group", "evidence", "label_notes"}."""
    top = track["top_k"]
    res = [(k, resolve(k["label"])) for k in top]
    s1 = top[0]["score"] if top else 0.0
    margin = s1 - (top[1]["score"] if len(top) > 1 else 0.0)
    fam_sum = {}
    for k, r in res:
        if r and r["family"]:
            fam_sum[r["family"]] = fam_sum.get(r["family"], 0.0) + k["score"]
    family, fam_score = max(fam_sum.items(), key=lambda x: x[1], default=(None, 0.0))
    notes = [f"{k['label']}: 샘플 family {k['family_json']} ≠ 사전 {r['family']}"            # 라벨 임시값과 사전 불일치
             for k, r in res if r and r["family"] and k.get("family_json") and k["family_json"] != r["family"]]

    top1 = res[0][1] if res else None
    if top1 and top1["tank_id"] and s1 >= C.KNOWN_SCORE and margin >= C.KNOWN_MARGIN:
        row = dictdb.tank(top1["tank_id"])
        return {"status": "Known", "tank_id": row["tank_id"], "name": row["canonical_name"], "family": row["family_name"],
                "type_group": row["type_group"] or C.DEFAULT_TYPE_GROUP, "label_notes": notes,
                "evidence": f"분류 {row['canonical_name']} {s1:.2f} (2위와 차이 {margin:.2f}) → Known"}
    if family and fam_score >= C.FAMILY_SCORE:
        return {"status": "Known_Variant", "tank_id": None, "name": None, "family": family,
                "type_group": dictdb.family_type_group(family) or C.DEFAULT_TYPE_GROUP, "label_notes": notes,
                "evidence": f"{family} 계열 점수 합 {fam_score:.2f} (기종 1·2위 차이 {margin:.2f}) → 계열만 확정"}
    return {"status": "Unknown", "tank_id": None, "name": None, "family": family,
            "type_group": (dictdb.family_type_group(family) if family else None) or C.DEFAULT_TYPE_GROUP,
            "label_notes": notes, "evidence": f"분류 불확실 (1위 {s1:.2f}) → 미확인" + (f", 추정 계열 {family}" if family else "")}


def _group_p75(j, k):
    """Known_Variant·Unknown·제원 결측 Known 의 대체 위협도 → (T, p_p75 또는 None, 근거 문장)."""
    if j["family"]:
        st = dictdb.family_stats(j["family"], k)
        if st["n"] >= C.FAMILY_MIN_N:
            return st["t"], st["p"], f"{j['family']} 계열 상위25%"
        short = f"{j['family']} 계열 표본 {st['n']} < {C.FAMILY_MIN_N}"
    else:
        short = "계열 추정 불가"
    for tg in dict.fromkeys([j["type_group"], C.DEFAULT_TYPE_GROUP]):     # 유형 → 주력전차 순
        t = dictdb.type_p75(tg, k)
        if t is not None:
            return round(t, 1), None, f"{tg} 상위25% ({short})"
    return None, None, f"대체값 없음 ({short})"


def threat_of(j, tactic, is_commander=False, cope_cage=False):
    """판정 결과 + 전술 → {"threat", "threat_before_bonus", "scores", "weights", "tactic", "source", "cope_tag"}."""
    used, (wf, wm, wp) = tactic_weights(tactic, is_commander)
    k, wsum = int(used), wf + wm + wp
    weights = {"firepower": wf, "mobility": wm, "protection": wp}
    row = dictdb.tank(j["tank_id"]) if j["status"] == "Known" else None
    scores = None
    if row and row["computable"]:                                         # Known: 사전 f·m·p 로 직접 계산
        f, m, p = (row[a] * 100 for a in "fmp")
        before = round((wf * f + wm * m + wp * p) / wsum, 1)
        p_after = p * C.COPE_CAGE_PROTECTION_MULT if cope_cage else p
        after = round((wf * f + wm * m + wp * p_after) / wsum, 1)
        q = C.QUANT_WEIGHTS
        scores = {"firepower": round(f, 1), "mobility": round(m, 1), "protection": round(p_after, 1),
                  "total": round(f * q["firepower"] + m * q["mobility"] + p_after * q["protection"], 1)}
        source, cope_tag = f"사전 {row['canonical_name']}", (f"cope cage → 방호 ×{C.COPE_CAGE_PROTECTION_MULT:.2f}"
                                                             if cope_cage else None)
    else:                                                                 # 변형·미확인·제원 결측: 상위 25% 대체
        before, p_p75, source = _group_p75(j, k)
        if row:
            source = f"{row['canonical_name']} 제원 결측 → " + source
        after, cope_tag = before, None
        if cope_cage and before is not None and p_p75 is not None:        # T 가 스칼라라 P 만 떼어 보정
            after = round(before + wp / wsum * p_p75 * (C.COPE_CAGE_PROTECTION_MULT - 1), 1)
            cope_tag = f"cope cage → 방호 ×{C.COPE_CAGE_PROTECTION_MULT:.2f}"
        elif cope_cage:
            cope_tag = "cope cage 탐지 (방호 보정값 없음)"
    return {"threat": after, "threat_before_bonus": before, "scores": scores, "weights": weights,
            "tactic": used, "source": source, "cope_tag": cope_tag}
