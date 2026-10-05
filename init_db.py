"""schema.sql을 MySQL에 적용합니다: python init_db.py"""
from pathlib import Path

from db import get_connection


def main():
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    conn = get_connection(with_db=False)
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    print(f"schema.sql 적용 완료 ({len(statements)}개 구문)")


if __name__ == "__main__":
    main()
