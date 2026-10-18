"""엔진 통합 테스트: 대시보드와 /api/threat 가 같은 판정 엔진(response_level.assess)·같은 기록 테이블을 쓰는지.
실행: 5_final 에서 python -m pytest dashboard/tests -q   (conftest.py 가 TANKLAB_DEMO=1 · 임시 SQLite 로 돌림)"""
import response_level as rl

COEF = {"lv1": 225, "lv2": 150, "lv3": 75, "floor_t": 75}


def veh(tid, T, status="Known", cat="전차", **kw):
    return dict(track_id=tid, status=status, category=cat, T=T, **kw)


# ───────── 1단계: assess() 에 미리 계산된 T ─────────
def test_assess_uses_given_T_without_lookup():
    # lookup(tanks)이 비어 있어도 T 를 그대로 쓴다 (tank_id 가 사전에 없어도 됨)
    r = rl.assess({"cluster_id": "x", "vehicles": [veh("a", 99.5, tank_id="NOPE", threat_source="T-80 계열 상위25%",
                                                       tags=["cope cage → 방호 ×1.10"])]}, {}, {}, COEF)
    v = r["vehicles"][0]
    assert r["T_cluster"] == 99.5 and v["T"] == 99.5 and v["threat_source"] == "T-80 계열 상위25%"
    assert "cope cage → 방호 ×1.10" in v["tags"]


def test_assess_T_none_counts_as_no_score():
    r = rl.assess({"cluster_id": "x", "vehicles": [veh("a", None, status="Unknown")]}, {}, {}, COEF)
    assert r["T_cluster"] == 0.0 and r["level"] == 3          # 점수 없음 → 4단계지만 Unknown 하한 → 3


def test_assess_without_T_still_uses_lookup():
    tanks = {"TK": {"name": "가상", "type_group": "주력전차", "computable": True, "confidence": "상", "t": [80.0] * 10}}
    r = rl.assess({"cluster_id": "x", "vehicles": [{"track_id": "a", "status": "Known", "tank_id": "TK", "category": "전차"}]},
                  tanks, {}, COEF)
    assert r["T_cluster"] == 80.0
