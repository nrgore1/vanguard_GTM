"""Persistence for runs, playbooks, tasks, approvals and Notion page ids.

SQLite by default; PostgreSQL when VANGUARD_DATABASE_URL is set (see db.py)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .db import Database
from .schema import Playbook

DB_PATH = Path(os.getenv("VANGUARD_DB", "data/vanguard.db"))

DDL = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created_at TEXT, finished_at TEXT, status TEXT,
  property_ids TEXT, errors TEXT DEFAULT '{}', usage TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS playbooks (
  run_id TEXT, property_id TEXT, lint_status TEXT, body TEXT, created_at TEXT,
  approved_by TEXT, approved_at TEXT, notion_page_id TEXT,
  PRIMARY KEY (run_id, property_id)
);
CREATE TABLE IF NOT EXISTS tasks (
  run_id TEXT, property_id TEXT, task_id TEXT, day INTEGER, priority TEXT, owner TEXT,
  status TEXT DEFAULT 'Not started', body TEXT, notion_page_id TEXT,
  PRIMARY KEY (run_id, property_id, task_id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | None = None, url: str | None = None):
        self.db = Database(Path(path or DB_PATH), url)
        self.path = self.db.path
        with self.conn() as c:
            c.executescript(DDL)
            if "usage" not in self.columns(c, "runs"):  # databases created by v0.1
                c.execute("ALTER TABLE runs ADD COLUMN usage TEXT DEFAULT '{}'")

    @property
    def postgres(self) -> bool:
        return self.db.postgres

    def conn(self):
        return self.db.conn()

    def columns(self, c, table: str) -> set[str]:
        return self.db.columns(c, table)

    # runs --------------------------------------------------------------
    def create_run(self, run_id: str, property_ids: list[str]):
        with self.conn() as c:
            c.execute("INSERT INTO runs(id, created_at, status, property_ids) VALUES (?,?,?,?)",
                      (run_id, now(), "running", json.dumps(property_ids)))

    def finish_run(self, run_id: str, errors: dict[str, str], usage: dict | None = None):
        status = "completed" if not errors else ("failed" if len(errors) == len(self.run(run_id)["property_ids"]) else "partial")
        with self.conn() as c:
            c.execute("UPDATE runs SET finished_at=?, status=?, errors=?, usage=? WHERE id=?",
                      (now(), status, json.dumps(errors), json.dumps(usage or {}), run_id))

    def run(self, run_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["property_ids"] = json.loads(d["property_ids"])
        d["errors"] = json.loads(d["errors"] or "{}")
        d["usage"] = json.loads(d.get("usage") or "{}")
        return d

    def latest_run_id(self) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        return r["id"] if r else None

    # playbooks ---------------------------------------------------------
    def save_playbook(self, pb: Playbook):
        body = pb.model_dump_json()
        with self.conn() as c:
            # replace semantics (a re-saved playbook starts unapproved), portable to SQLite and PostgreSQL
            c.execute("DELETE FROM playbooks WHERE run_id=? AND property_id=?", (pb.run_id, pb.property_id))
            c.execute("INSERT INTO playbooks(run_id, property_id, lint_status, body, created_at) VALUES (?,?,?,?,?)",
                      (pb.run_id, pb.property_id, pb.lint_status, body, now()))
            c.execute("DELETE FROM tasks WHERE run_id=? AND property_id=?", (pb.run_id, pb.property_id))
            for t in pb.daily_task_registry:
                c.execute("INSERT INTO tasks(run_id, property_id, task_id, day, priority, owner, body) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (pb.run_id, pb.property_id, t.task_id, t.day, t.priority, t.owner, t.model_dump_json()))

    def playbooks(self, run_id: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM playbooks WHERE run_id=? ORDER BY property_id", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    def playbook(self, run_id: str, property_id: str) -> Playbook | None:
        with self.conn() as c:
            r = c.execute("SELECT body FROM playbooks WHERE run_id=? AND property_id=?", (run_id, property_id)).fetchone()
        return Playbook.model_validate_json(r["body"]) if r else None

    def approve(self, run_id: str, property_id: str, approver: str) -> bool:
        with self.conn() as c:
            cur = c.execute("UPDATE playbooks SET approved_by=?, approved_at=? WHERE run_id=? AND property_id=? "
                            "AND lint_status != 'blocked'", (approver, now(), run_id, property_id))
        return cur.rowcount == 1

    def set_playbook_notion(self, run_id: str, property_id: str, page_id: str):
        with self.conn() as c:
            c.execute("UPDATE playbooks SET notion_page_id=? WHERE run_id=? AND property_id=?", (page_id, run_id, property_id))

    # tasks -------------------------------------------------------------
    def tasks(self, run_id: str, property_id: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM tasks WHERE run_id=?", [run_id]
        if property_id:
            q += " AND property_id=?"
            args.append(property_id)
        with self.conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY property_id, day, task_id", args).fetchall()]

    def set_task_notion(self, run_id: str, property_id: str, task_id: str, page_id: str):
        with self.conn() as c:
            c.execute("UPDATE tasks SET notion_page_id=? WHERE run_id=? AND property_id=? AND task_id=?",
                      (page_id, run_id, property_id, task_id))
