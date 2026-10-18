"""사전 위협도 조회: DB tank_threat(369종)·type_threat_summary 를 읽는다. 대시보드 v2 판정(judge.py)이 쓴다.

- 보통은 threat_db (MySQL, TANKLAB_DEMO=1 이면 SQLite) 에서 읽는다.
- 그 DB 에 tank_threat 가 없으면(사전 DB 없는 데모 환경) demo_seed.json 을 쓴다.
  seed 다시 만들기 (사전 DB 가 있는 PC 에서): python -m dashboard.threat.dictdb --seed
- 계열(family) 상위 25% 는 tank_threat 의 같은 계열 행으로 바로 계산한다.
  ponytail: 프로세스 메모리 캐시 — 369행이라 통째로 읽어 둔다. sync_threat_db 로 값을 바꾸면 서버를 다시 켜야 반영
"""
import json
import logging
import sys
from pathlib import Path

import numpy as np

from . import config as C

ROOT = Path(__file__).resolve().parents[2]
SEED = Path(__file__).with_name("demo_seed.json")
SEED_FAMILIES = ("T-72", "T-80", "T-90", "T-14 Armata")   # 샘플에 나오는 계열 (seed 에 담는 범위)
COLS = "tank_id, canonical_name, family_name, type_group, computable, f, m, p, " + ", ".join(f"t{k}" for k in range(1, 11))
log = logging.getLogger(__name__)
_cache = {}


def _from_db():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import threat_db as tdb
    return {"tanks": tdb.query(f"SELECT {COLS} FROM tank_threat"),
            "types": tdb.query("SELECT type_group, tactic_no, n, t_p75 FROM type_threat_summary")}


def data():
    """{"tanks": [tank_threat 행], "types": [type_threat_summary 행], "source": "db"|"seed"}."""
    if not _cache:
        try:
            d = _from_db()
            if not d["tanks"]:
                raise LookupError("tank_threat 비어 있음")
            d["source"] = "db"
        except Exception as e:                               # DB 가 없거나 sync 전이면 seed
            log.warning("사전 위협도 DB 를 못 읽어 demo_seed.json 사용: %s", e)
            d = dict(json.loads(SEED.read_text(encoding="utf-8")), source="seed")
        _cache.update(d, by_id={r["tank_id"]: r for r in d["tanks"]})
    return _cache


def reset():
    """캐시 비우기 (테스트·seed 교체용)."""
    _cache.clear()


def tank(tank_id):
    """tank_id → tank_threat 행 (없으면 None)."""
    return data()["by_id"].get(tank_id)


def p75(values):
    return round(float(np.percentile(values, C.THREAT_PERCENTILE)), 1) if values else None


def family_stats(family, tactic):
    """계열 안 계산 가능한 기종들의 상위 25% → {"n", "t", "f", "m", "p"} (f·m·p 는 100 기준). 표본이 없으면 n=0."""
    rows = [r for r in data()["tanks"] if r["family_name"] == family and r["computable"] and r[f"t{tactic}"] is not None]
    if not rows:
        return {"n": 0, "t": None, "f": None, "m": None, "p": None}
    return {"n": len(rows), "t": p75([r[f"t{tactic}"] for r in rows]),
            **{a: p75([r[a] * 100 for r in rows]) for a in "fmp"}}


def family_type_group(family):
    """계열에서 가장 많은 유형 (예: T-72 → 주력전차)."""
    groups = [r["type_group"] for r in data()["tanks"] if r["family_name"] == family and r["type_group"]]
    return max(set(groups), key=groups.count) if groups else None


def type_p75(type_group, tactic):
    """유형별 상위 25% T (type_threat_summary.t_p75)."""
    return next((r["t_p75"] for r in data()["types"] if r["type_group"] == type_group and r["tactic_no"] == tactic), None)


def make_seed():
    d = _from_db()
    tanks = [r for r in d["tanks"] if r["family_name"] in SEED_FAMILIES]
    types = [r for r in d["types"] if r["type_group"] == C.DEFAULT_TYPE_GROUP]
    SEED.write_text(json.dumps({"_note": "사전 DB 없는 데모용 (python -m dashboard.threat.dictdb --seed 로 생성)",
                                "tanks": tanks, "types": types}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"demo_seed.json: 전차 {len(tanks)}종, 유형 요약 {len(types)}행")


if __name__ == "__main__" and "--seed" in sys.argv:
    make_seed()
