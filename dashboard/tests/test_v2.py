"""v2 입력(프레임 단위 탐지) 테스트: 트랙 집계·판정·cope cage·Unknown 레지스트리·crop.
실행: 5_final 에서 python -m pytest dashboard/tests -q   (conftest.py 가 TANKLAB_DEMO=1 · 임시 SQLite 로 돌림)"""
import copy
import json
import math

import pytest
from PIL import Image

from dashboard import media
from dashboard import unknown_registry as reg
from dashboard.threat import config as C
from dashboard.threat import dictdb, judge, track
from dashboard.threat.pipeline import MOCK_DIR, MOCK_V2, analyze


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


A, B = (load(p) for p in MOCK_V2)
by_id = lambda r: {t["tracking_id"]: t for t in r["targets"]}  # noqa: E731


def record_all(result):
    """대시보드가 하는 것처럼 Unknown 표적을 레지스트리에 저장."""
    return {t["tracking_id"]: reg.record(result["source"]["video"], t, result["source"])
            for t in result["targets"] if t["status"] == "Unknown"}


# ───────── 샘플 기대 결과 (unknown_registry_prompt.md 1-1장 표) ─────────
def test_sample_statuses():
    a, b = by_id(analyze(A)), by_id(analyze(B))
    assert (a["Tank-01"]["status"], a["Tank-01"]["is_commander"]) == ("Known", True)
    assert a["Tank-01"]["tactic_name"] == "지휘통제"
    assert a["Tank-02"]["status"] == "Known_Variant" and a["Tank-02"]["family"] == "T-72" and a["Tank-02"]["has_cope_cage"]
    assert a["UNK-001"]["status"] == "Unknown"
    assert b["Tank-11"]["status"] == "Known"
    assert b["UNK-007"]["status"] == "Unknown" and b["UNK-007"]["has_cope_cage"]


def test_family_comes_from_dictionary_not_json():
    # 샘플 JSON 은 TANK_0230 을 T-72 로 적었지만 사전은 T-90 → 사전 우선
    a = by_id(analyze(A))
    assert a["Tank-01"]["family"] == dictdb.tank("TANK_0230")["family_name"] == "T-90"


def test_antenna_single_frame_false_positive_is_not_commander():
    t11 = by_id(analyze(B))["Tank-11"]
    assert t11["commander_evidence"]["n"] == 1 and not t11["is_commander"]


def test_commander_rule_needs_min_frames():
    one_frame = load(MOCK_DIR / "mock_video_A.json")             # 원래 1장짜리 샘플: 안테나 1/1 이지만 3프레임 미만
    assert not by_id(analyze(one_frame))["Tank-01"]["is_commander"]


def test_commander_override():
    r = analyze(A, commander_overrides={"Tank-01": False})
    t = by_id(r)["Tank-01"]
    assert not t["is_commander"] and "지휘전차 해제 (지휘관)" in t["tags"]
    assert r["clusters"][0]["tactic_name"] == "기동·직접전투"


# ───────── 판정 경계값 ─────────
def tk(*pairs):
    return {"top_k": [{"label": lb, "score": s, "family_json": None} for lb, s in pairs]}


@pytest.mark.parametrize("pairs, status", [
    ((("TANK_0231", C.KNOWN_SCORE), ("TANK_0226", C.KNOWN_SCORE - C.KNOWN_MARGIN)), "Known"),          # 경계값 그대로 → Known
    ((("TANK_0231", C.KNOWN_SCORE - 0.01), ("TANK_0226", 0.0)), "Unknown"),                           # 점수 부족, 계열 합도 부족
    ((("TANK_0231", 0.7), ("TANK_0226", 0.7 - C.KNOWN_MARGIN + 0.01)), "Known_Variant"),              # 1·2위 차이 부족 → 1위 계열(T-90)만 확정
    ((("TANK_0231", 0.5), ("TANK_0226", 0.45)), "Unknown"),                                           # 차이 부족, 계열 합도 각각 부족
    ((("TANK_0216", 0.35), ("TANK_0220", C.FAMILY_SCORE - 0.35)), "Known_Variant"),                   # 같은 계열 합 = 경계값
    ((("TANK_0216", 0.35), ("TANK_0220", C.FAMILY_SCORE - 0.36)), "Unknown"),                         # 합이 경계값 미만
    ((("NOT_IN_MAP", 0.99),), "Unknown"),                                                              # 매핑에 없는 라벨
])
def test_judge_boundaries(pairs, status):
    assert judge.judge(tk(*pairs))["status"] == status


def test_family_sample_too_small_falls_back_to_type_group():
    j = judge.judge(tk(("TANK_0231", 0.22), ("TANK_0226", 0.19)))        # 추정 계열 T-90 (사전 표본 2 < 3)
    assert j["family"] == "T-90" and dictdb.family_stats("T-90", 1)["n"] < C.FAMILY_MIN_N
    th = judge.threat_of(j, 1)
    assert th["threat"] == round(dictdb.type_p75("주력전차", 1), 1)
    assert "주력전차 상위25%" in th["source"] and "표본 2" in th["source"]


# ───────── cope cage 보정 ─────────
def test_cope_cage_known_multiplies_protection():
    j = judge.judge(tk(("TANK_0222", 0.9)))
    row, (wf, wm, wp) = dictdb.tank("TANK_0222"), C.TACTIC_WEIGHTS[1]
    f, m, p = (row[a] * 100 for a in "fmp")
    th = judge.threat_of(j, 1, cope_cage=True)
    assert th["threat_before_bonus"] == round((wf * f + wm * m + wp * p) / (wf + wm + wp), 1)
    assert th["threat"] == round((wf * f + wm * m + wp * p * C.COPE_CAGE_PROTECTION_MULT) / (wf + wm + wp), 1)


def test_cope_cage_unknown_uses_family_p_p75():
    j = judge.judge(tk(("TANK_0226", 0.24), ("TANK_0231", 0.21)))        # 추정 계열 T-80 (표본 5)
    st, (wf, wm, wp) = dictdb.family_stats("T-80", 1), C.TACTIC_WEIGHTS[1]
    th = judge.threat_of(j, 1, cope_cage=True)
    assert th["threat_before_bonus"] == st["t"]
    assert th["threat"] == round(st["t"] + wp / (wf + wm + wp) * st["p"] * (C.COPE_CAGE_PROTECTION_MULT - 1), 1)


# ───────── 부품 연결 ─────────
def test_ioa_and_loose_part_attach():
    tank = {"tracking_id": "T", "category": "전차", "bbox_px": {"x": 0, "y": 0, "w": 100, "h": 100}}
    assert track.ioa({"x": 50, "y": 50, "w": 100, "h": 100}, tank["bbox_px"]) == 0.25
    inside = {"cls": "antenna", "conf": 0.9, "bbox_px": {"x": 10, "y": 10, "w": 20, "h": 40}}
    outside = {"cls": "antenna", "conf": 0.9, "bbox_px": {"x": 90, "y": 90, "w": 40, "h": 40}}
    assert track.attach_parts([tank], [inside, outside], {"w": 1920, "h": 1080}) == 1
    assert tank["parts"] == [inside]


# ───────── Unknown 레지스트리 ─────────
def test_two_videos_same_unknown_one_group():
    ga = record_all(analyze(A))["UNK-001"]
    gb = record_all(analyze(B))["UNK-007"]
    assert ga["new"] and not gb["new"] and ga["group_id"] == gb["group_id"]
    assert gb["similarity"] >= C.GROUP_SIM_MIN
    g = reg.detail(ga["group_id"])["group"]
    assert (g["n_tracks"], g["n_videos"]) == (2, 2)
    assert [x["group_id"] for x in reg.ranking()] == [ga["group_id"]]


def test_reanalysis_does_not_duplicate():
    for _ in range(2):
        record_all(analyze(A))
        record_all(analyze(B))
    d = reg.detail(reg.ranking()[0]["group_id"])
    assert (d["group"]["n_tracks"], d["group"]["n_videos"], len(d["sightings"])) == (2, 2, 2)
    assert len(d["crops"]) == 2 * C.CROP_KEEP


def test_different_embedding_makes_new_group():
    b2 = copy.deepcopy(B)
    for f in b2["frames"]:
        for d in f["detections"]:
            if d["tracking_id"] == "UNK-007":
                e = d["classification"]["embedding"]
                d["classification"]["embedding"] = [-v for v in e]           # 정반대 방향 → 유사도 -1
    ga = record_all(analyze(A))["UNK-001"]
    gb = record_all(analyze(b2))["UNK-007"]
    assert gb["new"] and gb["group_id"] != ga["group_id"]


def test_group_crops_keep_top_n(monkeypatch):
    monkeypatch.setattr(C, "GROUP_CROP_MAX", 4)
    record_all(analyze(A))
    record_all(analyze(B))
    gid = reg.ranking()[0]["group_id"]
    crops = reg.detail(gid)["crops"]
    assert len(crops) == 4
    assert [c["quality"] for c in crops] == sorted((c["quality"] for c in crops), reverse=True)
    files = list((media.OUT / "unknown_crops" / gid).glob("*.jpg"))
    assert len(files) == 4                                                   # 밀려난 crop 은 파일도 삭제


def test_priority_formula():
    g = {"max_threat": 90.0, "n_tracks": 3, "n_videos": 2, "last_seen": "2000-01-01 00:00:00"}
    assert reg.priority(g) == round(90 * (1 + C.PRIORITY_FREQ_K * math.log(4)) * (1 + C.PRIORITY_VIDEO_K), 1)


def test_low_threat_group_saved_but_not_ranked(monkeypatch):
    monkeypatch.setattr(C, "UNKNOWN_RANK_MIN_THREAT", 1000)
    gid = record_all(analyze(A))["UNK-001"]["group_id"]
    assert reg.detail(gid) is not None and reg.ranking() == []


# ───────── crop ─────────
def test_crop_matches_reference_size(tmp_path):
    one = load(MOCK_DIR / "mock_video_A.json")                              # 원본 1장 + 정답 crop (패딩 10%)
    frame = one["frames"][0]
    for d in one["detections"] if "detections" in one else frame["detections"]:
        ref = MOCK_DIR / "crops" / f"mock_video_A_{d['tracking_id']}_{frame['frame_idx']:06d}.jpg"
        out = media.save_crop(frame["image_path"], d["bbox_px"], f"t/{d['tracking_id']}.jpg")
        got, want = Image.open(media.OUT / out).size, Image.open(ref).size
        assert abs(got[0] - want[0]) <= 2 and abs(got[1] - want[1]) <= 2


def test_crop_skips_missing_frame_and_path_outside_static():
    assert media.save_crop("mock_frames/없는파일.jpg", {"x": 0, "y": 0, "w": 10, "h": 10}, "x.jpg") is None
    assert media.frame_file("../app.py") is None


def test_edge_and_tiny_boxes_are_not_crop_candidates():
    size = {"w": 1920, "h": 1080}
    assert not track._crop_ok({"x": 0, "y": 100, "w": 200, "h": 200}, size)       # 왼쪽 가장자리에 잘림
    assert not track._crop_ok({"x": 100, "y": 100, "w": 30, "h": 200}, size)      # 너무 작음
    assert track._crop_ok({"x": 100, "y": 100, "w": 200, "h": 200}, size)


# ───────── API ─────────
def test_api_flow():
    from app import app
    c = app.test_client()
    r = c.post("/api/analyze")
    assert r.status_code == 200 and r.json["videos"] == ["mock_video_A.mp4", "mock_video_B.mp4"]
    gid = by_id(r.json)["UNK-001"]["unknown_group_id"]
    assert gid and by_id(r.json)["Tank-01"]["crop_url"].startswith("/static/track_crops/")
    assert "_track" not in r.json["targets"][0]
    b = c.get("/api/threats?video=mock_video_B.mp4").json
    assert by_id(b)["UNK-007"]["unknown_group_id"] == gid
    g = c.get(f"/api/unknowns/{gid}").json
    assert g["group"]["n_videos"] == 2 and all(x["url"] for x in g["crops"])
    assert c.get("/api/unknowns").json["groups"][0]["group_id"] == gid
    r = c.patch("/api/threats/Tank-11/commander", json={"is_commander": True})
    assert r.status_code == 200 and by_id(r.json)["Tank-11"]["is_commander"]
    assert by_id(r.json)["UNK-007"]["unknown_group_id"] == gid                 # 재계산해도 그룹 유지
    assert c.patch("/api/threats/Tank-11/commander", json={"is_commander": "yes"}).status_code == 400
    assert c.patch("/api/threats/NOPE/commander", json={"is_commander": True}).status_code == 404
    assert c.get("/api/unknowns/UNK-G9999").status_code == 404
    assert c.get("/unknowns").status_code == 200
