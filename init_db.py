"""schema.sql을 MySQL에 적용합니다: python init_db.py"""
import re
from pathlib import Path

from db import get_connection


def statements():
    """schema.sql 의 SQL 문 목록. 줄 끝의 ';' 로만 나눈다 (문자열 안의 ';' 는 그대로)."""
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    return [s.strip() for s in re.split(r";[ \t]*(?:\n|$)", sql) if s.strip()]


def main():
    stmts = statements()
    conn = get_connection(with_db=False)
    try:
        with conn.cursor() as cur:
            for stmt in stmts:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    print(f"schema.sql 적용 완료 ({len(stmts)}개 구문)")


if __name__ == "__main__":
    main()
