"""위협도 테이블 접근. 기본은 MySQL(db.get_connection), TANKLAB_DEMO=1 이면 SQLite 파일로 동작한다.

SQL은 MySQL 문법(%s 자리표시자, REPLACE INTO)으로 쓰고, SQLite에서는 자리표시자만 바꾼다.
REPLACE INTO 는 두 DB 모두 지원하므로 upsert 를 따로 나누지 않는다.
"""
import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def demo():
    return os.getenv("TANKLAB_DEMO") == "1"


def connect():
    if demo():
        conn = sqlite3.connect(os.getenv("TANKLAB_SQLITE", str(HERE / "tank_demo.sqlite3")))
        conn.row_factory = sqlite3.Row
        return conn
    from db import get_connection
    return get_connection()


def _sql(q):
    return q.replace("%s", "?") if demo() else q


def query(sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(sql), params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def execute(sql, params=(), many=False):
    conn = connect()
    try:
        cur = conn.cursor()
        (cur.executemany if many else cur.execute)(_sql(sql), params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def init_schema():
    sql = (HERE / "schema_threat.sql").read_text(encoding="utf-8")
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    if demo():
        sql = sql.replace("BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    for stmt in filter(str.strip, sql.split(";")):
        execute(stmt)
