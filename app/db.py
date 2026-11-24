# -*- coding: utf-8 -*-
"""PostgreSQL 连接层（唯一主库；不使用 SQLite）。

Mac 开发 / Linux 服务器共用同一个 DATABASE_URL；
连接池、行工厂、超时都在这里，业务代码不直接连库。
"""
import os
from contextlib import contextmanager

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://book:book@127.0.0.1:5432/bookworld'
)
POOL_MIN = int(os.environ.get('PG_POOL_MIN', '1'))
POOL_MAX = int(os.environ.get('PG_POOL_MAX', '10'))

_pool = None


def _require():
    try:
        import psycopg
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row
    except ImportError as e:
        raise RuntimeError(
            '缺少 PostgreSQL 依赖：pip install -r requirements-pg.txt'
        ) from e
    return psycopg, ConnectionPool, dict_row


def get_pool():
    global _pool
    if _pool is None:
        psycopg, ConnectionPool, dict_row = _require()
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=POOL_MIN,
            max_size=POOL_MAX,
            kwargs={
                'application_name': 'bookworld',
                'connect_timeout': 5,
                'row_factory': dict_row,
            },
            open=True,
        )
        _pool.wait(timeout=10)
    return _pool


@contextmanager
def get_conn():
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def fetch_all(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params or {}).fetchall()


def fetch_one(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params or {}).fetchone()


def execute(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params or {}).rowcount


def health():
    row = fetch_one('select now() as now, current_database() as db, version() as version')
    return row


def close():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
