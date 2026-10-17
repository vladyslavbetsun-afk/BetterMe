"""SQLite (Option A) or Postgres (Option B) storage, same DDL (spec §12).

Only this module and config.py know which backend is in use. Rows come back as
plain dicts; JSON columns are decoded on read and encoded on write.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DDL = [
    """create table if not exists decay_runs(id integer primary key, run_at timestamp, country text, date text,
      date_compared text, rows_returned int, units_used int, status text, error text)""",
    """create table if not exists decay_signals(run_id int, keyword text, url text, volume int, kd int, was int, now int,
      traffic_prev int, traffic_now int, kind text, aio_appeared bool, aio_citation_lost bool, swapped_to text,
      primary key(run_id, keyword, url))""",
    """create table if not exists decay_items(url text primary key, slug text, first_seen_run int, last_seen_run int,
      confirmations int,
      state text check (state in ('watch','confirmed','proposed','carded','in_progress','updated','recovered','partial',
        'not_recovered','excluded','noseo')),
      level text, level_override text, override_reason text, why text, checklist json, priority real,
      main_keyword text, lost_top3_count int, traffic_lost int, worst_now int,
      notion_url text, jira_key text, excluded_reason text, updated_on_new text)""",
    """create table if not exists page_audits(url text, run_id int, http_status int, final_url text, updated_on text,
      title text, h1 text, word_count int, has_key_takeaways bool, faq_count int, question_h2_count int,
      question_h2_answered int, table_count int, images_missing_alt int, internal_links_out int, claim_flags json,
      median_competitor_words int, competitor_check text, screen_verdict text, screen_categories json,
      primary key(url, run_id))""",
    """create table if not exists decay_followups(url text, label text, due_date text, checked_at text, results json,
      outcome text, primary key(url, label))""",
    """create table if not exists decay_cards(url text, iso_week text, notion_url text, created_at text, payload json,
      primary key(url, iso_week))""",
    """create table if not exists decay_suggestions(url text primary key, first_suggested text, source text)""",
    """create table if not exists settings(key text primary key, value json)""",
    # Additions beyond §12, documented in docs/decisions.md D-07.
    """create table if not exists decay_run_items(run_id int, url text, payload json, primary key(run_id, url))""",
    """create table if not exists screen_cache(url text, rules_version text, verdict json, primary key(url, rules_version))""",
]

JSON_COLUMNS = {"checklist", "claim_flags", "screen_categories", "results", "payload", "value", "verdict"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Storage:
    placeholder = "?"

    def __init__(self, conn):
        self.conn = conn

    # -- plumbing ---------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql if self.placeholder == "?" else sql.replace("?", self.placeholder)

    @staticmethod
    def _encode(params):
        out = []
        for p in params:
            if isinstance(p, (dict, list)):
                out.append(json.dumps(p, ensure_ascii=False))
            else:
                out.append(p)
        return out

    @staticmethod
    def _decode(row: dict) -> dict:
        for k, v in row.items():
            if k in JSON_COLUMNS and isinstance(v, str):
                try:
                    row[k] = json.loads(v)
                except ValueError:
                    pass
        return row

    def execute(self, sql: str, params=()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), self._encode(params))
        return cur

    def query(self, sql: str, params=()) -> list[dict]:
        cur = self.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [self._decode(dict(zip(cols, r))) for r in cur.fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def commit(self):
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def init(self):
        for stmt in DDL:
            self.execute(stmt)
        self.commit()

    def upsert(self, table: str, row: dict, keys: list[str]):
        cols = list(row)
        updates = [c for c in cols if c not in keys]
        sql = f"insert into {table}({', '.join(cols)}) values ({', '.join('?' for _ in cols)})"
        if updates:
            sql += f" on conflict({', '.join(keys)}) do update set " + ", ".join(f"{c}=excluded.{c}" for c in updates)
        else:
            sql += f" on conflict({', '.join(keys)}) do nothing"
        self.execute(sql, [row[c] for c in cols])

    # -- settings ---------------------------------------------------------
    def load_settings(self) -> dict:
        return {r["key"]: r["value"] for r in self.query("select key, value from settings")}

    def set_setting(self, key: str, value):
        self.upsert("settings", {"key": key, "value": json.dumps(value)}, ["key"])
        self.commit()

    # -- runs -------------------------------------------------------------
    def new_run(self, country: str, date: str, date_compared: str) -> int:
        row = self.one("select coalesce(max(id), 0) + 1 as id from decay_runs")
        run_id = int(row["id"])
        self.execute(
            "insert into decay_runs(id, run_at, country, date, date_compared, rows_returned, units_used, status, error)"
            " values (?, ?, ?, ?, ?, 0, 0, 'running', null)",
            [run_id, now_iso(), country, date, date_compared],
        )
        self.commit()
        return run_id

    def finish_run(self, run_id: int, status: str, rows_returned: int = 0, units_used: int = 0, error: str | None = None):
        self.execute(
            "update decay_runs set status=?, rows_returned=?, units_used=?, error=? where id=?",
            [status, rows_returned, units_used, error, run_id],
        )
        self.commit()

    def run(self, run_id: int) -> dict | None:
        return self.one("select * from decay_runs where id=?", [run_id])

    def latest_run(self, status: str | None = None) -> dict | None:
        if status:
            return self.one("select * from decay_runs where status=? order by id desc limit 1", [status])
        return self.one("select * from decay_runs order by id desc limit 1")

    def previous_ok_run(self, run_id: int, country: str) -> dict | None:
        return self.one(
            "select * from decay_runs where id < ? and country=? and status='ok' order by id desc limit 1",
            [run_id, country],
        )

    # -- items ------------------------------------------------------------
    def item(self, url: str) -> dict | None:
        return self.one("select * from decay_items where url=?", [url])

    def items(self, where: str = "1=1", params=()) -> list[dict]:
        return self.query(f"select * from decay_items where {where} order by priority desc", params)

    def save_item(self, item: dict):
        self.upsert("decay_items", item, ["url"])

    def latest_audit(self, url: str, before_run: int | None = None) -> dict | None:
        if before_run is None:
            return self.one("select * from page_audits where url=? order by run_id desc limit 1", [url])
        return self.one(
            "select * from page_audits where url=? and run_id < ? order by run_id desc limit 1", [url, before_run]
        )


def connect(cfg) -> Storage:
    if cfg.database_url:
        return PostgresStorage.connect(cfg.database_url)
    conn = sqlite3.connect(str(cfg.db_path))
    store = Storage(conn)
    store.init()
    return store


class PostgresStorage(Storage):
    """Option B. Same DDL; psycopg 3 is imported lazily so Option A needs no driver."""

    placeholder = "%s"

    @classmethod
    def connect(cls, url: str) -> "PostgresStorage":
        import psycopg  # noqa: WPS433

        store = cls(psycopg.connect(url))
        store.init()
        return store
