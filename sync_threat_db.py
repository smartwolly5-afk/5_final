"""사전 → 위협도 테이블 전체 재계산: python sync_threat_db.py [--dict 사전.xlsx]

1. schema_threat.sql 적용 (CREATE IF NOT EXISTS)
2. 계수 테이블이 비어 있으면 위협도_컬럼_산출.xlsx 계수·전술가중치 시트에서 1회 seed (이후 DB가 원본)
3. 사전(MySQL tank_specs, 데모 모드면 tank_dictionary_v2.xlsx)을 threat_calc 로 계산
4. tank_threat, type_threat_summary 에 REPLACE
계수를 바꾼 뒤 다시 돌리면 전체가 재계산된다.
"""
import argparse
from pathlib import Path

import openpyxl
import pandas as pd

import threat_db as tdb
from threat_calc import coefs_from_sheets, compute

ROOT = Path(__file__).resolve().parent.parent
COEF_XLSX = ROOT / "위협도_컬럼_산출.xlsx"
DICT_XLSX = ROOT / "tank_dictionary_v2.xlsx"
# 대응수준 경계값 (엑셀에는 없음). 68/136/204 비교 실험은 이 값만 바꾸면 된다
LEVEL_DEFAULTS = {"lv1": (225, "S ≥ lv1 → 1단계 즉시 보고"), "lv2": (150, "S ≥ lv2 → 2단계 우선 감시"),
                  "lv3": (75, "S ≥ lv3 → 3단계 지속 감시"), "floor_t": (75, "T ≥ floor_t 전차 포함 → 최소 3단계")}
TYPES = ["주력전차", "중전차", "중형전차", "경전차", "순항전차", "보병전차", "초중전차", "미상"]


def seed(path=COEF_XLSX):
    if tdb.query("SELECT COUNT(*) AS n FROM threat_coef")[0]["n"]:
        return False
    wb = openpyxl.load_workbook(path)
    k, w = wb["계수"], wb["전술가중치"]
    coefs, weights = coefs_from_sheets(k, w)
    rows = [(key, coefs[key], k[cell].value and str(k[cell].value)) for key, cell in
            [("cal", "A2"), ("len", "A3"), ("pw", "A4"), ("h", "A5"), ("hmin", "A26"), ("hmax", "A27")]]
    rows += [(key, v, note) for key, (v, note) in LEVEL_DEFAULTS.items()]
    tdb.execute("REPLACE INTO threat_coef (k, v, note) VALUES (%s, %s, %s)", rows, many=True)
    tdb.execute("REPLACE INTO ammo_coef (ammo, coef) VALUES (%s, %s)", list(coefs["ammo"].items()), many=True)
    tdb.execute("REPLACE INTO gen_coef (gen, coef) VALUES (%s, %s)", list(coefs["gen"].items()), many=True)
    tactics = [(i, w[f"B{i + 1}"].value, *weights[i - 1], 1) for i in range(1, 11)]
    tactics.append((11, "전투근무지원", 0, None, None, 0))  # 화력 0 → 전차에는 적용하지 않음 (기동·방호 가중치는 설문 원본 확인 필요)
    tdb.execute("REPLACE INTO tactic_weight (tactic_no, name, w_f, w_m, w_p, tank_allowed) VALUES (%s,%s,%s,%s,%s,%s)",
                tactics, many=True)
    return True


def load_coefs():
    c = {r["k"]: r["v"] for r in tdb.query("SELECT k, v FROM threat_coef")}
    c["ammo"] = {r["ammo"]: r["coef"] for r in tdb.query("SELECT ammo, coef FROM ammo_coef")}
    c["gen"] = {r["gen"]: r["coef"] for r in tdb.query("SELECT gen, coef FROM gen_coef")}
    weights = [(r["w_f"], r["w_m"], r["w_p"]) for r in
               tdb.query("SELECT w_f, w_m, w_p FROM tactic_weight WHERE tank_allowed = 1 ORDER BY tactic_no")]
    return c, weights


def load_dictionary(path=None):
    if path or tdb.demo():
        return pd.read_excel(path or DICT_XLSX)
    return pd.DataFrame(tdb.query("SELECT * FROM tank_specs"))


def sync(dict_path=None):
    tdb.init_schema()
    seeded = seed()
    coefs, weights = load_coefs()
    X = compute(load_dictionary(dict_path), coefs, weights)

    def v(x):
        return None if pd.isna(x) else (x.item() if hasattr(x, "item") else x)

    cols = ["tank_id", "canonical_name", "family_name", "유형", "산출가능", "신뢰도", "구경", "구경장", "탄종", "세대",
            "출력대중량비", "장갑", "높이", "구경_src", "구경장_src", "탄종_src", "세대_src", "출력대중량비_src", "장갑_src",
            "높이_src", "장갑 규칙", "ERA", "ERA_src", "F", "M", "P"] + [f"T_{i}" for i in range(1, 11)]
    rows = [tuple(v(x) for x in r) for r in X[cols].itertuples(index=False)]
    tdb.execute("DELETE FROM tank_threat")
    tdb.execute(
        "REPLACE INTO tank_threat (tank_id, canonical_name, family_name, type_group, computable, confidence, cal_mm, cal_len,"
        " ammo, gen, pw, armor, height, cal_src, len_src, ammo_src, gen_src, pw_src, armor_src, height_src, armor_rule,"
        " era_ref, era_src, f, m, p, t1, t2, t3, t4, t5, t6, t7, t8, t9, t10)"
        f" VALUES ({', '.join(['%s'] * len(cols))})", rows, many=True)

    ok = X[X.산출가능]
    summary = []
    for k in range(1, 11):
        g = ok.groupby("유형")[f"T_{k}"]
        for t in TYPES:
            if t in g.groups:
                # PERCENTILE(…, 0.75) 와 같은 선형 보간 (pandas 기본)
                summary.append((t, k, int(g.count()[t]), round(g.median()[t], 2), round(g.quantile(0.75)[t], 2)))
    tdb.execute("DELETE FROM type_threat_summary")
    tdb.execute("REPLACE INTO type_threat_summary (type_group, tactic_no, n, t_median, t_p75) VALUES (%s,%s,%s,%s,%s)",
                summary, many=True)
    return {"seeded": seeded, "tanks": len(rows), "computable": int(len(ok)), "summary_rows": len(summary)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dict", help="사전 xlsx 경로 (기본: MySQL tank_specs, 데모 모드는 tank_dictionary_v2.xlsx)")
    r = sync(ap.parse_args().dict)
    print(f"{'SQLite(데모)' if tdb.demo() else 'MySQL'}: 계수 seed {'완료' if r['seeded'] else '생략(이미 있음)'}, "
          f"tank_threat {r['tanks']}행 (산출가능 {r['computable']}), type_threat_summary {r['summary_rows']}행")
