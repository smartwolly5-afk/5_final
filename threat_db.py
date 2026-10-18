"""위협도 테이블 접근. 기본은 MySQL(db.get_connection), TANKLAB_DEMO=1 이면 SQLite 파일로 동작한다.

SQL은 MySQL 문법(%s 자리표시자, REPLACE INTO)으로 쓰고, SQLite에서는 자리표시자만 바꾼다.
REPLACE INTO 는 두 DB 모두 지원하므로 upsert 를 따로 나누지 않는다.
"""
import os
import re
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


def execute_all(steps):
    """[(sql, params, many), ...] 를 연결 하나에서 실행하고 마지막에 한 번만 커밋한다.
    중간에 실패하면 전부 취소 (DELETE 후 다시 넣는 작업이 반쯤 끝난 채로 남지 않게)."""
    conn = connect()
    try:
        cur = conn.cursor()
        for sql, params, many in steps:
            (cur.executemany if many else cur.execute)(_sql(sql), params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_ready = set()   # 테이블을 이미 만든 연결 대상 (MySQL 또는 SQLite 파일 경로)


def ensure_schema():
    """schema_threat.sql 을 연결 대상마다 한 번만 적용 (전부 CREATE TABLE IF NOT EXISTS 라 여러 번 돌려도 안전)."""
    target = os.getenv("TANKLAB_SQLITE", str(HERE / "tank_demo.sqlite3")) if demo() else "mysql"
    if target not in _ready:
        init_schema()
        _ready.add(target)


def init_schema():
    sql = (HERE / "schema_threat.sql").read_text(encoding="utf-8")
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    if demo():
        sql = sql.replace("BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    for stmt in filter(str.strip, re.split(r";[ \t]*(?:\n|$)", sql)):  # 줄 끝의 ';' 로만 나눔
        execute(stmt)
