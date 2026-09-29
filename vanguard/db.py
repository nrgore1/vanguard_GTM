"""Database connections: SQLite (default, tests, local) or PostgreSQL (set VANGUARD_DATABASE_URL).

All application SQL is written once, in the portable subset both engines accept, with `?`
placeholders. This module adapts the few places the engines differ:

- placeholders: `?` becomes `%s` for PostgreSQL (and a literal `%` becomes `%%`);
- DDL: `INTEGER PRIMARY KEY AUTOINCREMENT` becomes `BIGSERIAL PRIMARY KEY`, `REAL` becomes
  `DOUBLE PRECISION`, and tables the code orders by `rowid` get a `rowid BIGSERIAL` column;
- `PRAGMA ...` statements are skipped (PostgreSQL always enforces foreign keys);
- `lastrowid` comes from `INSERT ... RETURNING *`;
- `columns(table)` replaces `PRAGMA table_info`.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

# Tables whose queries use SQLite's implicit rowid; PostgreSQL gets an explicit column.
ROWID_TABLES = {"runs", "playbooks", "tasks"}


def database_url() -> str:
    return os.getenv("VANGUARD_DATABASE_URL", "").strip()


def is_postgres_url(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


# ---------------------------------------------------------------- SQL translation
_TOKEN = re.compile(r"'(?:[^']|'')*'|\?|%")


def to_pg_params(sql: str) -> str:
    """`?` -> `%s` and `%` -> `%%`, leaving quoted string literals alone except for `%`."""
    def sub(m: re.Match) -> str:
        tok = m.group(0)
        if tok == "?":
            return "%s"
        if tok == "%":
            return "%%"
        return tok.replace("%", "%%")          # a quoted literal
    return _TOKEN.sub(sub, sql)


def to_pg_ddl(sql: str) -> str:
    sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)

    def add_rowid(m: re.Match) -> str:
        return m.group(0) + ("\n  rowid BIGSERIAL," if m.group(1) in ROWID_TABLES else "")
    return re.sub(r"CREATE TABLE IF NOT EXISTS (\w+) \(", add_rowid, sql)


def split_script(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


# ---------------------------------------------------------------- PostgreSQL wrappers
class PgCursor:
    def __init__(self, cur, returned: dict | None = None):
        self._cur = cur
        self._returned = returned
        self.rowcount = cur.rowcount
        self.lastrowid = None
        if returned:
            self.lastrowid = returned.get("id", returned.get("rowid"))

    def fetchall(self) -> list[dict]:
        if self._returned is not None:
            return [self._returned]
        return self._cur.fetchall() if self._cur.description else []

    def fetchone(self) -> dict | None:
        if self._returned is not None:
            return self._returned
        return self._cur.fetchone() if self._cur.description else None

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    """Enough of the sqlite3.Connection interface for this codebase."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, args: Iterable[Any] = ()) -> PgCursor:
        stripped = sql.lstrip()
        if stripped[:6].upper() == "PRAGMA":
            return PgCursor(_NoResult())
        is_insert = stripped[:6].upper() == "INSERT" and "RETURNING" not in sql.upper()
        cur = self.raw.cursor()
        cur.execute(to_pg_params(sql + (" RETURNING *" if is_insert else "")), list(args))
        if is_insert:
            row = cur.fetchone() if cur.description else None
            c = PgCursor(cur, row or {})
            c.rowcount = cur.rowcount
            return c
        return PgCursor(cur)

    def executescript(self, script: str) -> None:
        for stmt in split_script(to_pg_ddl(script)):
            if stmt[:6].upper() != "PRAGMA":
                self.raw.execute(stmt)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


class _NoResult:
    rowcount = 0
    description = None


# ---------------------------------------------------------------- the one entry point
class Database:
    """Opens connections for a SQLite file or a PostgreSQL URL."""

    def __init__(self, path: Path | None, url: str | None = None):
        self.url = url if url is not None else database_url()
        self.postgres = is_postgres_url(self.url)
        self.path = Path(path) if path else None
        if not self.postgres:
            if self.url.startswith("sqlite:///"):
                self.path = Path(self.url[len("sqlite:///"):])
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def conn(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            raw = psycopg.connect(self.url, row_factory=dict_row)
            c = PgConnection(raw)
        else:
            c = sqlite3.connect(self.path)
            c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def columns(self, c, table: str) -> set[str]:
        if self.postgres:
            rows = c.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_name=?", (table,))
        else:
            rows = c.execute(f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    def describe(self) -> str:
        if self.postgres:
            return "PostgreSQL " + re.sub(r"//[^@/]*@", "//***@", self.url)
        return f"SQLite {self.path}"


# ---------------------------------------------------------------- SQLite -> current database
def copy_from_sqlite(src: Path, dest_store, replace: bool = False) -> dict[str, str]:
    """Copy every table of a SQLite database into dest_store's database (usually PostgreSQL).

    The destination schema is created first (web tables and fail-proof tables included). A table that
    already holds rows is skipped unless `replace` is true, so running it twice never duplicates data.
    Only columns present on both sides are copied; PostgreSQL id sequences are moved past the copied ids.
    """
    from .failproof import FailproofStore
    from .web.db import WebStore
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"no SQLite database at {src}")
    ws = WebStore(url=dest_store.db.url, path=dest_store.db.path) if not isinstance(dest_store, WebStore) else dest_store
    FailproofStore(ws)
    report: dict[str, str] = {}
    s = sqlite3.connect(src)
    s.row_factory = sqlite3.Row
    try:
        tables = [r["name"] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # parents before children so foreign keys hold
        order = ["users", "runs", "playbooks", "tasks", "campaigns", "campaign_results", "partners",
                 "partner_interactions", "outreach_messages"]
        tables = [t for t in order if t in tables] + [t for t in tables if t not in order]
        with ws.conn() as c:
            for t in tables:
                dest_cols = ws.columns(c, t)
                if not dest_cols:
                    report[t] = "skipped (no such table in destination)"
                    continue
                src_cols = [r["name"] for r in s.execute(f"PRAGMA table_info({t})")]
                cols = [col for col in src_cols if col in dest_cols]
                existing = c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                if existing and not replace:
                    report[t] = f"skipped ({existing} rows already there; use --replace to overwrite)"
                    continue
                if existing:
                    c.execute(f"DELETE FROM {t}")
                rows = s.execute(f"SELECT {','.join(cols)} FROM {t}").fetchall()
                sql = f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
                for r in rows:
                    c.execute(sql, tuple(r[col] for col in cols))
                if ws.postgres:
                    for seq_col in ("id", "rowid"):
                        if seq_col not in dest_cols:
                            continue
                        seq = c.execute(f"SELECT pg_get_serial_sequence('{t}', '{seq_col}') AS s").fetchone()["s"]
                        if seq:  # numeric serial column: move the sequence past the copied ids
                            c.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX({seq_col}) FROM {t}), 0) + 1, false)")
                report[t] = f"copied {len(rows)} rows"
    finally:
        s.close()
    return report
