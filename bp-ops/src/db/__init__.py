"""Postgres access: a small connection pool, boot-time migrations and query helpers."""

import atexit
import json
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config

HERE = Path(__file__).parent
_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row},
                               open=True)
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


atexit.register(close)


@contextmanager
def conn():
    with pool().connection() as c:
        yield c


def query(sql: str, params=None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def one(sql: str, params=None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def scalar(sql: str, params=None):
    row = one(sql, params)
    return next(iter(row.values())) if row else None


def execute(sql: str, params=None) -> int:
    with conn() as c:
        return c.execute(sql, params).rowcount


def migrate() -> list[str]:
    """Run every migration, then every seed file, in name order. All files are idempotent."""
    done = []
    with conn() as c:
        c.execute("select pg_advisory_lock(424242)")
        try:
            for folder in ("migrations", "seed"):
                for f in sorted((HERE / folder).glob("*.sql")):
                    c.execute(f.read_text())
                    done.append(f"{folder}/{f.name}")
        finally:
            c.execute("select pg_advisory_unlock(424242)")
    return done


# --- settings ----------------------------------------------------------------------

def get_setting(key: str, default=None):
    row = one("select value from settings where key = %s", (key,))
    return default if row is None else row["value"]


def set_setting(key: str, value) -> None:
    execute("insert into settings (key, value) values (%s, %s) "
            "on conflict (key) do update set value = excluded.value", (key, Jsonb(value)))


def flag(key: str) -> bool:
    return bool(get_setting(key, False))


def audit(actor: str | None, action: str, target: str | None = None, detail: dict | None = None) -> None:
    execute("insert into audit_log (actor, action, target, detail) values (%s, %s, %s, %s)",
            (actor, action, target, Jsonb(detail or {})))


def jsonb(v):
    return Jsonb(v)


def dumps(v) -> str:
    return json.dumps(v, default=str)
