"""위협도 대시보드 테스트 (계산 + API). 실행: 5_final 에서 python -m pytest tests dashboard/tests -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 5_final 폴더 (dashboard 패키지가 있는 곳)

from dashboard.threat import (Tactic, analyze, classify_echelon, cluster_response_level, infer_tactic,  # noqa: E402
                              load_mock, quant_score, tank_threat, threat_grade)
from dashboard.threat.core import SPECS  # noqa: E402


def det(cat="전차", model="T-72B3", cmd=False, i=0):
    return {"tracking_id": f"{cat}-{i}", "category": cat, "model": model, "is_commander": cmd,
            "confidence": 0.9, "bbox": {"x": 10, "y": 10, "w": 10, "h": 10}}


def many(n, cat="전차", model="T-72B3"):
    return [det(cat, model, i=i) for i in range(n)]


@pytest.mark.parametrize("n, weight, name", [(0, 0, "없음"), (1, 1, "소대"), (4, 1, "소대"), (5, 2, "중대"),
                                             (15, 2, "중대"), (16, 3, "대대")])
def test_echelon_boundaries(n, weight, name):
    e = classify_echelon(many(n))
    assert (e["n"], e["weight"], e["name"]) == (n, weight, name)


def test_echelon_counts_apc_but_not_artillery_infantry_unknown():
    dets = many(3) + many(2, "기갑차", "BMP-2") + many(5, "포병", "2S19") + many(5, "인원", None) + many(5, "미확인", None)
    assert classify_echelon(dets)["n"] == 5


def test_infer_tactic():
    assert infer_tactic(many(3)) is Tactic.MANEUVER
    assert infer_tactic(many(3) + [det(cmd=True, i=9)]) is Tactic.COMMAND
    assert infer_tactic([det("기갑차", "BMP-2", cmd=True)]) is Tactic.MANEUVER  # 전차만 본다


def test_quant_base_is_100():
    assert quant_score(SPECS["M1A1"]) == {"firepower": 100, "mobility": 100, "protection": 100, "total": 100}


def test_quant_simplified_formula():
    # 화력 = 125×48^0.5 ÷ 120×44^0.5, 방호 = 평균(550/600, 650/700) × (2.44/2.23)^0.5, 기동 = 23.5/26.3
    assert quant_score(SPECS["T-90M"]) == {"firepower": 108.8, "mobility": 89.4, "protection": 96.5, "total": 100.5}


def test_quant_ignores_extension_fields():
    spec = dict(SPECS["T-72M1"], thermal="gen3", fcs="hunter_killer", stabilizer="2axis", armor="steel", era="relikt")
    assert quant_score(spec) == quant_score(SPECS["T-72M1"])


def test_commander_changes_weights_only():
    spec = SPECS["T-90M"]
    assert tank_threat(spec, Tactic.MANEUVER, True) == tank_threat(spec, Tactic.COMMAND, False)
    assert tank_threat(spec, Tactic.MANEUVER, True) != tank_threat(spec, Tactic.MANEUVER, False)


def test_unweighted_tactic_rejected():
    with pytest.raises(ValueError):
        tank_threat(SPECS["T-90M"], Tactic.SUSTAINMENT)  # 11번은 화력 0 → 가중치 없음


def test_levels_by_score():
    for threat, n, level in [(74.9, 1, 4), (75, 1, 3), (74.9, 5, 3), (75, 5, 2), (75, 16, 1), (74.9, 16, 2)]:
        assert cluster_response_level({"detections": many(n), "threats": [threat]})["level"] == level


def test_floor_unknown():
    r = cluster_response_level({"detections": many(1) + [det("미확인", None, i=9)], "threats": [40]})
    assert r["score"] == 40 and r["level"] == 3
    assert any("미확인" in x for x in r["reasons"])


def test_floor_unlisted_model_counts_as_unknown():
    r = cluster_response_level({"detections": [det(model="T-14")], "threats": []})
    assert r["level"] == 3


def test_floor_strong_tank():
    # 무게 0(전투차량 없음)이면 점수 0이지만 75 이상 전차가 있으면 4단계 불가
    r = cluster_response_level({"detections": [], "threats": [80]})
    assert r["score"] == 0 and r["level"] == 3
    assert cluster_response_level({"detections": [], "threats": [74.9]})["level"] == 4


def test_commander_does_not_raise_level():
    base = cluster_response_level({"detections": many(4), "threats": [70]})
    cmd = cluster_response_level({"detections": many(3) + [det(cmd=True, i=9)], "threats": [70]})
    assert base["level"] == cmd["level"] == 4


def test_analyze_mock():
    r = analyze(load_mock())
    ranked = [t for t in r["targets"] if t["rank"]]
    assert [t["rank"] for t in ranked] == list(range(1, len(ranked) + 1))
    assert all(t["category"] in ("전차", "미확인") for t in ranked)
    assert r["counts"]["total"] == len(r["targets"]) and r["counts"]["new"] == 0
    again = analyze(load_mock(), prev={**r, "targets": r["targets"][1:]})
    assert again["counts"]["new"] == 1


def test_analyze_rejects_bad_input():
    with pytest.raises(ValueError):
        analyze({"detections": [{"tracking_id": "x", "category": "비행기"}]})


@pytest.mark.parametrize("score, grade", [(None, None), (0, "낮음"), (39.9, "낮음"), (40, "보통"), (69.9, "보통"),
                                          (70, "높음"), (99.9, "높음"), (100, "매우 높음")])
def test_threat_grade_boundaries(score, grade):
    assert threat_grade(score) == grade


def test_ranking_by_tank_threat_unknown_last():
    r = analyze(load_mock())
    ranked = [t for t in r["targets"] if t["rank"]]
    scores = [t["threat"] for t in ranked if t["threat"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert ranked[-1]["threat"] is None  # 미확인은 맨 뒤


def test_tags_are_per_target_and_cluster_reasons_separate():
    r = analyze(load_mock())
    t03 = next(t for t in r["targets"] if t["tracking_id"] == "Tank-03")
    assert "지휘전차" in t03["tags"] and "C-1 소속" in t03["tags"]
    assert not any("군집점수" in x for x in t03["tags"])                 # 군집 판정 근거는 표적 태그에 없음
    assert any("군집점수" in x for x in r["clusters"][0]["reasons"])


def test_tactic_override_applies_to_whole_cluster():
    base = analyze(load_mock())
    over = analyze(load_mock(), tactic_overrides={"C-1": 5})            # 장거리화력 (화력 가중치 0.72)
    c1 = next(c for c in over["clusters"] if c["cluster_id"] == "C-1")
    assert (c1["tactic"], c1["tactic_source"]) == (5, "지휘관 지정")
    t03 = next(t for t in over["targets"] if t["tracking_id"] == "Tank-03")
    assert t03["tactic"] == 5                                           # 지휘전차도 지정 전술을 따름
    assert t03["threat"] != next(t for t in base["targets"] if t["tracking_id"] == "Tank-03")["threat"]
    c2 = next(c for c in over["clusters"] if c["cluster_id"] == "C-2")
    assert c2["tactic_source"] == "시스템 추정"                           # 다른 군집은 그대로


def test_tactic_override_rejects_bad_values():
    with pytest.raises(LookupError):
        analyze(load_mock(), tactic_overrides={"C-9": 1})
    with pytest.raises(ValueError):
        analyze(load_mock(), tactic_overrides={"C-1": 11})


def test_api_tactic_and_report():
    from app import app
    c = app.test_client()
    assert c.post("/api/analyze").status_code == 200
    r = c.patch("/api/clusters/C-1/tactic", json={"tactic": 3})
    assert r.status_code == 200 and r.json["clusters"][0]["tactic_name"] == "대전차"
    assert c.patch("/api/clusters/C-1/tactic", json={"tactic": 11}).status_code == 400
    assert c.patch("/api/clusters/NOPE/tactic", json={"tactic": 1}).status_code == 404
    r = c.patch("/api/clusters/C-1/tactic", json={"tactic": None})        # 자동으로 되돌림
    assert r.json["clusters"][0]["tactic_source"] == "시스템 추정"
    page = c.get("/report?stage=1").get_data(as_text=True)
    assert "위협도 분석 보고서" in page and "지휘관 결정 1단계" in page
