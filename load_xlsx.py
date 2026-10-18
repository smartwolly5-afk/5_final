"""tank_dictionary_v2.xlsx → tank_specs 테이블 전체 교체: python load_xlsx.py [엑셀 경로]"""
import re
import sys
from pathlib import Path

import openpyxl

import init_db
from db import get_connection

DEFAULT_XLSX = Path(__file__).resolve().parent.parent / "tank_dictionary_v2.xlsx"
NUMERIC = {"crew", "combat_weight_t", "length_m", "width_m", "height_m", "main_gun_caliber_mm",
           "effective_range_m", "engine_power_hp", "power_to_weight_hp_t", "max_road_speed_kmh",
           "range_km", "source_count"}
# 충족률 계산에서 빼는 식별·출처 컬럼 (항상 채워져 있어 의미 없음)
NOT_SPEC = {"tank_id", "canonical_name", "family_name", "variant_name", "sources", "source_count"}


def clean(col, v, tank_id):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if col in NUMERIC and not isinstance(v, (int, float)):
        if re.fullmatch(r"-?\d+(\.\d+)?", str(v).strip()):
            return float(v)
        print(f"  {tank_id} {col}={v!r} → 숫자 아님, NULL 처리")
        return None
    return v.strip() if isinstance(v, str) else v


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    rows = openpyxl.load_workbook(path, read_only=True).active.iter_rows(values_only=True)
    header = list(next(rows))
    data = [[clean(c, v, r[0]) for c, v in zip(header, r)] for r in rows if r[0]]

    spec_idx = [i for i, c in enumerate(header) if c not in NOT_SPEC]
    for row in data:
        n = sum(row[i] is not None for i in spec_idx)
        row += [n, round(n / len(spec_idx) * 100, 1)]
    header += ["spec_count", "spec_coverage_%"]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS tank_specs")
        conn.commit()
    finally:
        conn.close()
    init_db.main()  # schema.sql 로 테이블 재생성

    cols = ", ".join(f"`{c}`" for c in header).replace("%", "%%")  # pymysql 자리표시자 이스케이프
    marks = ", ".join(["%s"] * len(header))
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(f"INSERT INTO tank_specs ({cols}) VALUES ({marks})", data)
        conn.commit()
    finally:
        conn.close()
    print(f"{len(data)}행 적재 완료 ({path.name})")


if __name__ == "__main__":
    main()
