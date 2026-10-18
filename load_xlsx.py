"""tank_dictionary_v2.xlsx → tank_specs 테이블 전체 교체: python load_xlsx.py [엑셀 경로]"""
import re
import sys
from pathlib import Path

import openpyxl

import init_db
from config import data_file
from db import get_connection

DEFAULT_XLSX = data_file("tank_dictionary_v2.xlsx")
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
    name_i, var_i, fam_i = (header.index(c) for c in ("canonical_name", "variant_name", "family_name"))
    for r in data:  # canonical_name 은 NOT NULL → 비었으면 변형명(없으면 계열명)으로 채우고 알림
        if r[name_i] is None and (r[var_i] or r[fam_i]):
            r[name_i] = r[var_i] or r[fam_i]
            print(f"  {r[0]} canonical_name 비어 있음 → '{r[name_i]}' 로 채움 (엑셀 확인 필요)")
    no_name = [r[0] for r in data if r[name_i] is None]
    if no_name:
        sys.exit(f"canonical_name 이 빈 행이 있어 중단 (DB는 그대로): {', '.join(no_name)}")

    spec_idx = [i for i, c in enumerate(header) if c not in NOT_SPEC]
    for row in data:
        n = sum(row[i] is not None for i in spec_idx)
        row += [n, round(n / len(spec_idx) * 100, 1)]
    header += ["spec_count", "spec_coverage_%"]

    # 새 테이블(tank_specs_new)에 다 넣은 뒤에 바꿔치기한다. 중간에 실패하면 기존 tank_specs 는 그대로 남는다
    init_db.main()  # DB·tank_specs 가 없으면 생성 (RENAME 대상이 항상 있게)
    create = next(s for s in init_db.statements() if "CREATE TABLE IF NOT EXISTS tank_specs" in s)
    create = create.replace("CREATE TABLE IF NOT EXISTS tank_specs", "CREATE TABLE tank_specs_new")  # 스키마 변경도 반영
    cols = ", ".join(f"`{c}`" for c in header).replace("%", "%%")  # pymysql 자리표시자 이스케이프
    marks = ", ".join(["%s"] * len(header))
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS tank_specs_new, tank_specs_old")
            cur.execute(create)
            cur.executemany(f"INSERT INTO tank_specs_new ({cols}) VALUES ({marks})", data)
            conn.commit()
            cur.execute("RENAME TABLE tank_specs TO tank_specs_old, tank_specs_new TO tank_specs")  # 한 번에 교체
            cur.execute("DROP TABLE tank_specs_old")
    except Exception:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS tank_specs_new")  # 실패한 임시 테이블 정리 (기존 tank_specs 는 그대로)
        raise
    finally:
        conn.close()
    print(f"{len(data)}행 적재 완료 ({path.name})")


if __name__ == "__main__":
    main()
