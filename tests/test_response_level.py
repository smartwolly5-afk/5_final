"""대응수준 엔진 테스트: 임시 SQLite(데모 모드)에 sync_threat_db 를 실제로 돌린 값으로 검증한다.
실행: 5_final 에서 python -m pytest tests -q
"""
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    old = {k: os.environ.get(k) for k in ("TANKLAB_DEMO", "TANKLAB_SQLITE")}
    os.environ["TANKLAB_DEMO"] = "1"
    os.environ["TANKLAB_SQLITE"] = str(tmp_path_factory.mktemp("db") / "test.sqlite3")
    import response_level as rl
    import sync_threat_db
    sync_threat_db.sync()
    yield rl, rl.load_lookup()
    for k, v in old.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def tid(lookup, name):
    return next(k for k, v in lookup[0].items() if v["name"] == name)


def tanks(lookup, name, n, start=0, **kw):
    return [dict(track_id=f"{name}-{start + i}", status="Known", tank_id=tid(lookup, name), category="전차", **kw)
            for i in range(n)]


def run(db, vehicles, **kw):
    rl, lookup = db
    return rl.assess(dict(cluster_id="T", vehicles=vehicles, **kw), *lookup)


def T(db, name, k=1):
    return db[1][0][tid(db[1], name)]["t"][k - 1]


# ── 시나리오 (설명서 10장 예시와 같은 값) ──
def test_t72_battalion(db):
    r = run(db, tanks(db[1], "T-72", 20))
    assert (r["N"], r["E"], r["echelon"]) == (20, 3, "대대")
    assert r["S"] == round(T(db, "T-72") * 3, 1) == 230.4
    assert r["level"] == 1 and r["floors_applied"] == []


def test_t72_company_with_t90(db):
    r = run(db, tanks(db[1], "T-72", 10) + tanks(db[1], "T-90", 1))
    assert r["T_cluster"] == T(db, "T-90") == 89.9  # 중앙값이 아니라 최댓값
    assert (r["E"], r["S"], r["level"]) == (2, 179.8, 2)


def test_t62_platoon_no_floor(db):
    r = run(db, tanks(db[1], "T-62", 4))
    assert (r["S"], r["level"]) == (T(db, "T-62"), 4) and r["floors_checked"] == []


def test_t62_platoon_with_unknown(db):
    v = tanks(db[1], "T-62", 3) + [dict(track_id="unk-1", status="Unknown", category="전차")]
    r = run(db, v)
    assert r["N"] == 4 and r["E"] == 1
    assert r["T_cluster"] == db[1][1][("주력전차", 1)]  # Unknown = 주력전차 상위 25%
    assert r["level"] == 3
    assert any(f["rule"] == "Unknown 포함" for f in r["floors_checked"])
    assert "분석관 검토" in next(x for x in r["vehicles"] if x["track_id"] == "unk-1")["tags"]


def test_t55_platoon_core_target(db):
    v = tanks(db[1], "T-55", 4)
    r = run(db, v, core_targets=["T-55-2"])
    assert r["score_level"] == 4 and r["level"] == 2
    assert r["vehicles"][0]["track_id"] == "T-55-2"  # 핵심표적이 1순위
    assert (r["level_before_override"], r["level_after_override"]) == (4, 2)


def test_tactic_change_1_to_4(db):
    v = tanks(db[1], "T-72", 20)
    r1, r4 = run(db, v), run(db, v, tactic_override=4)
    assert r1["T_cluster"] == T(db, "T-72", 1) and r4["T_cluster"] == T(db, "T-72", 4)
    assert r4["tactic"] == 4 and r4["tactic_source"] == "지휘관 수정"
    assert r4["level_before_override"] == r1["level"]
    assert (r1["S"], r1["level"], r4["S"], r4["level"]) == (230.4, 1, 234.6, 1)  # 4번: T는 오르지만 단계 동일
    r10 = run(db, v, tactic_override=10)  # 10번(지휘통제): T-72 74.5 → 223.5 → 2단계로 내려감
    assert (r10["S"], r10["level"]) == (223.5, 2)


def test_command_tank_uses_tactic_10_and_ranks_first(db):
    v = tanks(db[1], "T-72", 3) + tanks(db[1], "T-62", 1, is_command=True)
    r = run(db, v)
    cmd = r["vehicles"][0]
    assert cmd["is_command"] and cmd["tactic"] == 10 and cmd["T"] == T(db, "T-62", 10)


def test_variant_and_artillery_and_frames(db):
    v = [dict(track_id="v1", status="Known_Variant", tank_id=tid(db[1], "T-72"), category="전차"),
         dict(track_id="a1", status="Known", category="포병"), dict(track_id="b1", status="Known", category="기갑차")]
    r = run(db, v, frames=[["v1", "a1"], ["v1", "a1", "b1"]])
    assert r["N"] == 2  # 포병 제외, 프레임별 최댓값
    assert "T-72 계열 추정" in next(x for x in r["vehicles"] if x["track_id"] == "v1")["tags"]


def test_tactic_11_rejected(db):
    with pytest.raises(ValueError):
        run(db, tanks(db[1], "T-72", 1), tactic_override=11)


def test_override_flow_saves_history(db):
    rl, lookup = db
    import threat_db as tdb
    rl.assess_and_save(dict(cluster_id="C-hist", vehicles=tanks(lookup, "T-55", 4)), lookup)
    r = rl.apply_override("C-hist", "core_target", "T-55-0", actor="tester", lookup=lookup)
    assert r["level"] == 2
    r = rl.apply_override("C-hist", "tactic", 4, actor="tester", lookup=lookup)
    assert r["tactic"] == 4
    hist = tdb.query("SELECT item, level_before, level_after, actor FROM commander_override WHERE cluster_id = %s ORDER BY id",
                     ("C-hist",))
    assert [(h["item"], h["level_before"], h["level_after"]) for h in hist] == [("core_target", 4, 2), ("tactic", 2, 2)]


def test_api_roundtrip(db):
    from flask import Flask
    from threat_api import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    c = app.test_client()
    body = dict(cluster_id="C-api", vehicles=tanks(db[1], "T-72", 20))
    assert c.post("/api/threat/assess", json=body).json["level"] == 1
    assert c.patch("/api/threat/cluster/C-api/tactic", json={"tactic": 10}).json["tactic"] == 10
    assert c.patch("/api/threat/cluster/C-api/tactic", json={"tactic": 11}).status_code == 400
    assert c.patch("/api/threat/cluster/none/tactic", json={"tactic": 1}).status_code == 404
    t = c.get(f"/api/threat/tank/{tid(db[1], 'M1A1 Abrams')}").json
    assert [t[f"t{i}"] for i in range(1, 11)] == [100.0] * 10


# ── 단조성: 랜덤 군집 1,000개 ──
def _random_cluster(rnd, pool):
    v = [dict(track_id=f"x{i}", status="Known", tank_id=rnd.choice(pool), category="전차") for i in range(rnd.randint(1, 20))]
    for i in range(rnd.randint(0, 2)):
        v.append(dict(track_id=f"u{i}", status="Unknown", category="전차"))
    for i in range(rnd.randint(0, 3)):
        v.append(dict(track_id=f"b{i}", status="Known", category="기갑차"))
    return dict(cluster_id="R", vehicles=v, system_tactic=rnd.randint(1, 10))


def test_monotonic(db):
    rl, (tk, unk, coef) = db
    pool = [k for k, v in tk.items() if v["computable"]]
    rnd = random.Random(42)
    for _ in range(1000):
        c = _random_cluster(rnd, pool)
        lv = rl.assess(c, tk, unk, coef)["level"]
        # 1대 추가 → 단계가 내려가지 않음(숫자가 커지지 않음)
        add = dict(c, vehicles=c["vehicles"] + [dict(track_id="new", status="Known", tank_id=rnd.choice(pool), category="전차")])
        assert rl.assess(add, tk, unk, coef)["level"] <= lv
        # 1대를 같은 전술 기준 T가 더 높은 기종으로 교체 → 단계가 내려가지 않음
        k = c["system_tactic"]
        i = rnd.randrange(len(c["vehicles"]))
        old = c["vehicles"][i]
        if old["status"] == "Known" and old["category"] == "전차":
            stronger = [p for p in pool if tk[p]["t"][k - 1] >= tk[old["tank_id"]]["t"][k - 1]]
            v2 = list(c["vehicles"])
            v2[i] = dict(old, tank_id=rnd.choice(stronger))
            assert rl.assess(dict(c, vehicles=v2), tk, unk, coef)["level"] <= lv
