import os
from datetime import datetime, timedelta

import pytest

# Tests wipe their database, so they never use DATABASE_URL and refuse any database not named *_test.
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@/bpops_test?host=/tmp")
if not TEST_DB.split("?")[0].rstrip("/").endswith("_test"):
    raise SystemExit(f"TEST_DATABASE_URL must point at a database whose name ends in _test, got {TEST_DB}")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ.setdefault("OWNER_EMAILS", "owner@example.test")

import config  # noqa: E402
import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    with db.conn() as c:
        c.execute("drop schema public cascade; create schema public;")
    db.migrate()
    yield
    db.close()


@pytest.fixture(autouse=True)
def clean():
    tables = [r["tablename"] for r in db.query("select tablename from pg_tables where schemaname = 'public'")]
    with db.conn() as c:
        c.execute("truncate " + ", ".join(tables) + " restart identity cascade")
    db.migrate()  # re-seed roster + settings
    yield


NOW = datetime(2026, 10, 16, 15, 0, tzinfo=config.TZ)  # a Friday


def ago(days: float = 0, hours: float = 0) -> datetime:
    return NOW - timedelta(days=days, hours=hours)


def iso(t: datetime) -> str:
    return t.isoformat()
