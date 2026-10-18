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


# ───────── 2단계: 어댑터·경계값 일원화 ─────────
import copy  # noqa: E402
import json  # noqa: E402

import threat_db as tdb  # noqa: E402
from dashboard.threat import adapter, config as C  # noqa: E402
from dashboard.threat.pipeline import MOCK_V2, analyze  # noqa: E402

A, B = (json.loads(p.read_text(encoding="utf-8")) for p in MOCK_V2)
SCREEN_FIELDS = {"cluster_id", "level", "label", "score", "t_cluster", "echelon", "reasons", "tactic", "tactic_name",
                 "tactic_source", "track_ids", "floors", "S", "E", "N", "level_before_override"}


def test_adapter_roundtrip_has_screen_fields():
    for payload in (A, B):
        for c in analyze(payload)["clusters"]:
            assert SCREEN_FIELDS <= set(c)
            assert set(c["echelon"]) == {"n", "weight", "name"}
            assert c["reasons"][1].startswith("군집점수 ") and "→" in c["reasons"][1]   # 예전 문구 스타일
            assert c["_assess_input"]["vehicles"] and c["_assess_result"]["level"] == c["level"]


def test_cope_cage_T_reaches_t_cluster():
    c = analyze(B)["clusters"][0]
    unk = next(v for v in c["_assess_input"]["vehicles"] if v["track_id"] == "UNK-007")
    assert unk["T"] == 99.5 and c["t_cluster"] == 99.5          # 보정 전 97.8 이 아니라 cope cage 보정 후 값


def test_echelon_count_unknown_switch(monkeypatch):
    assert analyze(A)["clusters"][0]["N"] == 3                  # 전차 2 + 미확인 1
    monkeypatch.setattr(C, "ECHELON_COUNT_UNKNOWN", False)
    assert analyze(A)["clusters"][0]["N"] == 2                  # 예전 방식: 전차만


def test_frames_max_count():
    b = copy.deepcopy(B)                                        # 프레임마다 한 대씩만 보이게 → 동시에 보인 최대 1대
    for i, f in enumerate(b["frames"]):
        f["detections"] = [f["detections"][i % 2]]
    c = analyze(b)["clusters"][0]
    assert c["N"] == 1 and c["_assess_input"]["frames"]


def test_threat_coef_from_db_changes_boundary():
    assert adapter.load_coef() == {"lv1": 225, "lv2": 150, "lv3": 75, "floor_t": 75}   # DB 없음 → config 기본값
    assert analyze(A)["clusters"][0]["level"] == 3
    tdb.init_schema()
    tdb.execute("REPLACE INTO threat_coef (k, v, note) VALUES (%s, %s, %s)", ("lv2", 80, "테스트"))
    assert adapter.load_coef()["lv2"] == 80
    assert analyze(A)["clusters"][0]["level"] == 2              # S 88.9 ≥ 80 → 2단계


def test_sync_seed_defaults_match_config():
    import sync_threat_db
    d = {k: v for k, (v, _) in sync_threat_db.LEVEL_DEFAULTS.items()}
    assert d == {**{f"lv{lv}": th for th, lv in C.LEVEL_THRESHOLDS}, "floor_t": C.FLOOR_TANK_THREAT}


# ───────── 3단계: 판정 기록 (cluster_assessment) ─────────
def client():
    from app import app
    return app.test_client()


def test_analyze_saves_one_row_per_cluster_with_video_key():
    c = client()
    r = c.post("/api/analyze")
    assert r.status_code == 200 and r.json["alert"]["saved"] is True
    rows = tdb.query("SELECT cluster_id, level, input_json FROM cluster_assessment ORDER BY id")
    assert [x["cluster_id"] for x in rows] == ["mock_video_A.mp4:C-1", "mock_video_B.mp4:C-1"]
    assert json.loads(rows[0]["input_json"])["vehicles"][0]["T"] is not None     # 미리 계산된 T 가 입력에 저장됨
    assert r.json["clusters"][0]["cluster_id"] == "C-1" and "_assess_input" not in r.json["clusters"][0]


def test_saved_input_can_be_rejudged_by_apply_override():
    client().post("/api/analyze")
    res = rl.apply_override("mock_video_A.mp4:C-1", "core_target", "Tank-01", "tester", lookup=({}, {}, COEF))
    assert res["level"] == 2                                     # 핵심표적 → 최소 2단계 (같은 assess 로 재판정)


def test_save_failure_keeps_analysis(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("DB 꺼짐")
    monkeypatch.setattr(rl, "save_assessment", boom)
    r = client().post("/api/analyze")
    assert r.status_code == 200 and r.json["alert"]["saved"] is False and r.json["targets"]


def test_cluster_key_fits_column():
    k = rl.cluster_key("v" * 300 + ".mp4", "C-12")
    assert len(k) <= 64 and k.endswith(":C-12") and k != rl.cluster_key("w" * 300 + ".mp4", "C-12")


# ───────── 4단계: 지휘관 조치 이력 (commander_override) ─────────
def overrides(key="mock_video_A.mp4:C-1"):
    return tdb.query("SELECT actor, item, before_value, after_value, level_before, level_after "
                     "FROM commander_override WHERE cluster_id = %s ORDER BY id", (key,))


def test_tactic_commander_stage_actions_are_logged():
    c = client()
    c.post("/api/analyze")
    assert c.patch("/api/clusters/C-1/tactic", json={"tactic": 3}, headers={"X-User": "대대장"}).status_code == 200
    assert c.patch("/api/threats/Tank-01/commander", json={"is_commander": False}).status_code == 200
    r = c.post("/api/clusters/C-1/stage", json={"stage": 1})
    assert r.status_code == 200 and r.json["recorded"] is True and r.json["ai_level"] == 3
    rows = overrides()
    assert [x["item"] for x in rows] == ["tactic", "commander", "stage"]
    assert rows[0]["actor"] == "대대장" and rows[1]["actor"] == "commander"               # X-User → 기본 "commander"
    assert json.loads(rows[0]["after_value"]) == 3 and json.loads(rows[0]["before_value"]) is None
    assert json.loads(rows[2]["after_value"]) == 1 and (rows[2]["level_before"], rows[2]["level_after"]) == (3, 1)
    assert c.post("/api/clusters/C-1/stage", json={"stage": 7}).status_code == 400
    assert c.post("/api/clusters/NOPE/stage", json={"stage": 1}).status_code == 404


def test_stage_does_not_change_calculation():
    c = client()
    before = c.post("/api/analyze").json["clusters"][0]["level"]
    c.post("/api/clusters/C-1/stage", json={"stage": 1})
    assert c.get("/api/threats").json["clusters"][0]["level"] == before


def test_history_endpoint_in_time_order():
    c = client()
    c.post("/api/analyze")
    c.patch("/api/clusters/C-1/tactic", json={"tactic": 3})
    h = c.get("/api/clusters/C-1/history?video=mock_video_A.mp4").json["events"]
    assert [e["kind"] for e in h] == ["판정", "판정", "조치"]                  # 분석 판정 → 재판정 → 전술 조치 기록
    assert h[-1]["item"] == "tactic" and h[-1]["after"] == 3
    assert [e["kind"] for e in c.get("/api/clusters/C-1/history?video=mock_video_B.mp4").json["events"]] == ["판정"]


# ───────── 5단계: 핵심표적 ─────────
def test_core_target_min_level_2_and_back():
    c = client()
    base = c.post("/api/analyze").json
    assert base["clusters"][0]["level"] == 3
    r = c.patch("/api/threats/Tank-01/core-target", json={"core": True}).json
    cl = r["clusters"][0]
    assert cl["level"] == 2 and cl["level_before_override"] == 3 and cl["core_targets"] == ["Tank-01"]
    assert any("핵심표적" in x and "최소 2단계" in x for x in cl["reasons"])               # 상황 패널 근거
    first = r["targets"][0]
    assert first["tracking_id"] == "Tank-01" and first["is_core"] and first["rank"] == 1   # 핵심표적이 랭킹 맨 위
    assert "핵심표적 → 최소 2단계" in first["tags"]
    back = c.patch("/api/threats/Tank-01/core-target", json={"core": False}).json
    assert back["clusters"][0]["level"] == 3 and back["targets"][0]["tracking_id"] == "UNK-001"
    rows = overrides()
    assert [x["item"] for x in rows] == ["core_target", "core_target"]
    assert (rows[0]["level_before"], rows[0]["level_after"], rows[1]["level_after"]) == (3, 2, 3)
    assert c.patch("/api/threats/Tank-01/core-target", json={"core": "yes"}).status_code == 400
    assert c.patch("/api/threats/NOPE/core-target", json={"core": True}).status_code == 404
