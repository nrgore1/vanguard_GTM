"""Tables for the web app: users, campaigns + results, partners + interactions, targets, audit log.

Lives in the same database as runs/playbooks/tasks (store.py) so the agent and the UI share one database
(SQLite by default, PostgreSQL when VANGUARD_DATABASE_URL is set).
"""
from __future__ import annotations

import json
from typing import Any

from ..store import Store, now

WEB_DDL = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','user')), password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT, last_login TEXT
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, property_id TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'email', channel TEXT, status TEXT NOT NULL DEFAULT 'draft',
  start_date TEXT, end_date TEXT, budget_usd REAL DEFAULT 0, goal_metric TEXT, goal_value REAL,
  description TEXT, content TEXT, owner_id INTEGER, source_run_id TEXT,
  created_by INTEGER, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS campaign_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  date TEXT NOT NULL, sent INTEGER DEFAULT 0, opens INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0, meetings INTEGER DEFAULT 0, signups INTEGER DEFAULT 0, conversions INTEGER DEFAULT 0,
  revenue_usd REAL DEFAULT 0, spend_usd REAL DEFAULT 0, notes TEXT, created_by INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS partners (
  id INTEGER PRIMARY KEY AUTOINCREMENT, property_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'identified', partner_type TEXT, contact_name TEXT, contact_email TEXT,
  value_sharing_model TEXT, mutual_value TEXT, first_ask TEXT, next_step TEXT, next_step_date TEXT,
  owner_id INTEGER, source_run_id TEXT, created_by INTEGER, created_at TEXT, updated_at TEXT,
  UNIQUE (property_id, name)
);
CREATE TABLE IF NOT EXISTS partner_interactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
  date TEXT NOT NULL, type TEXT NOT NULL, summary TEXT NOT NULL, outcome TEXT DEFAULT 'none', next_step TEXT,
  created_by INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS targets (
  property_id TEXT PRIMARY KEY, arr_target_usd REAL NOT NULL DEFAULT 2000000,
  monthly_conversions_target INTEGER DEFAULT 0, notes TEXT, updated_by INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS outreach_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
  step INTEGER NOT NULL, delay_days INTEGER NOT NULL DEFAULT 0, subject TEXT NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', lint_status TEXT DEFAULT 'pass', lint_findings TEXT,
  approved_by TEXT, approved_at TEXT, sent_at TEXT, message_id TEXT, to_email TEXT, error TEXT,
  replied_at TEXT, source_run_id TEXT, created_by INTEGER, created_at TEXT, updated_at TEXT,
  UNIQUE (partner_id, step)
);
CREATE TABLE IF NOT EXISTS email_suppression (
  email TEXT PRIMARY KEY, reason TEXT NOT NULL, at TEXT
);
CREATE TABLE IF NOT EXISTS inbound_emails (
  message_id TEXT PRIMARY KEY, partner_id INTEGER, outreach_id INTEGER, from_addr TEXT, subject TEXT,
  received_at TEXT, classification TEXT
);
CREATE TABLE IF NOT EXISTS notification_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, transport TEXT, to_addr TEXT, subject TEXT, kind TEXT
);
CREATE TABLE IF NOT EXISTS linkedin_connections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, profile_url TEXT NOT NULL, first_name TEXT, last_name TEXT,
  email TEXT, company TEXT, company_norm TEXT, position TEXT, connected_on TEXT, imported_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS intro_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
  connection_id INTEGER NOT NULL REFERENCES linkedin_connections(id) ON DELETE CASCADE,
  path TEXT NOT NULL DEFAULT 'bridge', reason TEXT, score INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'suggested',
  channel TEXT NOT NULL DEFAULT 'linkedin', subject TEXT, body TEXT, blurb TEXT, lint_status TEXT DEFAULT 'pass',
  lint_findings TEXT, approved_by TEXT, approved_at TEXT, sent_at TEXT, to_email TEXT, outcome TEXT, error TEXT,
  created_by INTEGER, created_at TEXT, updated_at TEXT, UNIQUE (partner_id, connection_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user_id INTEGER, action TEXT, entity TEXT, entity_id TEXT,
  detail TEXT
);
"""

MIGRATIONS = {
    "tasks": [("assignee_id", "INTEGER"), ("due_date", "TEXT"), ("updated_at", "TEXT"), ("notes", "TEXT")],
    "partners": [("category", "TEXT"), ("is_segment", "INTEGER DEFAULT 0"), ("priority_score", "INTEGER"),
                 ("priority", "TEXT"), ("factors", "TEXT"), ("rationale", "TEXT"), ("deal_structure", "TEXT"),
                 ("how_to_find", "TEXT"), ("website", "TEXT"), ("source", "TEXT DEFAULT 'manual'"),
                 ("agreement_status", "TEXT DEFAULT 'none'"), ("agreement_signed_date", "TEXT"),
                 ("agreement_notes", "TEXT"), ("parent_id", "INTEGER"), ("email_consent", "TEXT DEFAULT 'none'"),
                 ("campaign_id", "INTEGER")],
    "linkedin_connections": [("msg_count", "INTEGER DEFAULT 0"), ("last_message_at", "TEXT"),
                             ("endorsements", "INTEGER DEFAULT 0"), ("strength", "DOUBLE PRECISION DEFAULT 0"),
                             ("tags", "TEXT")],
    "outreach_messages": [("transport", "TEXT"), ("pm_message_id", "TEXT"), ("delivered_at", "TEXT"),
                          ("opened_at", "TEXT")],
}
AGREEMENT_STATUSES = ["none", "proposed", "negotiating", "signed", "declined"]

CAMPAIGN_FIELDS = ["property_id", "name", "kind", "channel", "status", "start_date", "end_date", "budget_usd",
                   "goal_metric", "goal_value", "description", "content", "owner_id"]
RESULT_FIELDS = ["date", "sent", "opens", "clicks", "replies", "meetings", "signups", "conversions",
                 "revenue_usd", "spend_usd", "notes"]
PARTNER_FIELDS = ["property_id", "name", "kind", "stage", "partner_type", "contact_name", "contact_email",
                  "value_sharing_model", "mutual_value", "first_ask", "next_step", "next_step_date", "owner_id",
                  "website", "category", "agreement_status", "agreement_signed_date", "agreement_notes", "email_consent"]
INTERACTION_FIELDS = ["date", "type", "summary", "outcome", "next_step"]
METRICS = ["sent", "opens", "clicks", "replies", "meetings", "signups", "conversions", "revenue_usd", "spend_usd"]


class WebStore(Store):
    def __init__(self, path=None, url=None):
        super().__init__(path, url)
        with self.conn() as c:
            c.executescript(WEB_DDL)
            for table, new_cols in MIGRATIONS.items():
                cols = self.columns(c, table)
                for col, ddl in new_cols:
                    if col not in cols:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    # generic helpers -----------------------------------------------------
    def q(self, sql: str, args: tuple | list = ()) -> list[dict]:
        with self.conn() as c:
            c.execute("PRAGMA foreign_keys=ON")
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def insert(self, table: str, data: dict) -> int:
        cols = list(data)
        with self.conn() as c:
            cur = c.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [data[k] for k in cols])
            return cur.lastrowid

    def update(self, table: str, key: str, key_val: Any, data: dict) -> int:
        if not data:
            return 0
        with self.conn() as c:
            cur = c.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in data)} WHERE {key}=?",
                            [*data.values(), key_val])
            return cur.rowcount

    def delete(self, table: str, key: str, key_val: Any) -> int:
        with self.conn() as c:
            c.execute("PRAGMA foreign_keys=ON")
            return c.execute(f"DELETE FROM {table} WHERE {key}=?", (key_val,)).rowcount

    def audit(self, user_id: int | None, action: str, entity: str, entity_id: Any, detail: Any = None):
        self.insert("audit_log", {"at": now(), "user_id": user_id, "action": action, "entity": entity,
                                  "entity_id": str(entity_id), "detail": json.dumps(detail) if detail else None})

    # users ---------------------------------------------------------------
    def create_user(self, email: str, name: str, role: str, password_hash: str) -> int:
        return self.insert("users", {"email": email.lower().strip(), "name": name, "role": role,
                                     "password_hash": password_hash, "created_at": now()})

    def user_by_email(self, email: str) -> dict | None:
        return self.one("SELECT * FROM users WHERE email=?", (email.lower().strip(),))

    def user(self, uid: int) -> dict | None:
        return self.one("SELECT * FROM users WHERE id=?", (uid,))

    # agent -> UI import ----------------------------------------------------
    def import_from_run(self, run_id: str, property_ids: list[str] | None, user_id: int) -> dict:
        """Turn a run's playbooks into draft campaigns and identified partners (idempotent per run)."""
        counts = {"campaigns": 0, "partners": 0, "messages": 0, "skipped": 0}
        for row in self.playbooks(run_id):
            if property_ids and row["property_id"] not in property_ids:
                continue
            if row["lint_status"] == "blocked":
                counts["skipped"] += 1
                continue
            pb = json.loads(row["body"])
            pid, ts = row["property_id"], now()
            existing = {r["name"] for r in self.q("SELECT name FROM campaigns WHERE property_id=? AND source_run_id=?",
                                                  (pid, run_id))}
            for seq in pb["campaign_blueprints"]["email_sequences"]:
                name = f"{seq['sequence_name']} (email)"
                if name in existing:
                    continue
                self.insert("campaigns", {
                    "property_id": pid, "name": name, "kind": "email", "channel": "email", "status": "draft",
                    "goal_metric": "meetings", "description": f"Trigger: {seq['trigger_event']}\nAudience: {seq['audience_filter']}",
                    "content": json.dumps(seq["steps"]), "source_run_id": run_id, "created_by": user_id,
                    "created_at": ts, "updated_at": ts})
                counts["campaigns"] += 1
            for sc in pb["campaign_blueprints"]["social_campaigns"]:
                name = f"{sc['content_pillar']} ({sc['channel']})"
                if name in existing:
                    continue
                self.insert("campaigns", {
                    "property_id": pid, "name": name, "kind": "social", "channel": sc["channel"], "status": "draft",
                    "goal_metric": "signups", "description": f"{sc['cadence']} · {sc['paid_or_organic']} · {sc['audience_parameters']}",
                    "content": json.dumps(sc["hook_concepts"]), "source_run_id": run_id, "created_by": user_id,
                    "created_at": ts, "updated_at": ts})
                counts["campaigns"] += 1
            for rec in pb.get("partner_outreach", []):
                created = self.upsert_recommendation(pid, rec, run_id, user_id)
                counts["partners"] += created["partner_created"]
                counts["messages"] = counts.get("messages", 0) + created["messages"]
            for p in pb["partnership_playbook"]:
                for entity in p["target_entities"]:
                    if self.one("SELECT id FROM partners WHERE property_id=? AND name=?", (pid, entity)):
                        continue
                    self.insert("partners", {
                        "property_id": pid, "name": entity, "kind": p.get("kind", "distribution"),
                        "stage": "identified", "partner_type": p["partner_type"],
                        "value_sharing_model": p["value_sharing_model"], "mutual_value": p["mutual_value_exchange"],
                        "first_ask": p["first_ask"], "next_step": p["first_ask"], "source_run_id": run_id,
                        "created_by": user_id, "created_at": ts, "updated_at": ts})
                    counts["partners"] += 1
        self.audit(user_id, "import", "run", run_id, counts)
        return counts

    def upsert_recommendation(self, pid: str, rec: dict, run_id: str | None, user_id: int | None) -> dict:
        """Create/refresh an agent-recommended partner and its draft outreach sequence (never touches sent mail)."""
        ts = now()
        fields = {"category": rec.get("category"), "is_segment": int(bool(rec.get("is_segment"))),
                  "priority_score": rec.get("score"), "priority": rec.get("priority"),
                  "factors": json.dumps(rec.get("factors", {})), "rationale": rec.get("why"),
                  "deal_structure": rec.get("deal_structure"), "how_to_find": rec.get("how_to_find_contact"),
                  "mutual_value": rec.get("value_exchange"), "first_ask": rec.get("first_ask"),
                  "value_sharing_model": rec.get("deal_structure"), "updated_at": ts}
        row = self.one("SELECT id FROM partners WHERE property_id=? AND name=?", (pid, rec["name"]))
        created = 0
        if row:
            part_id = row["id"]
            self.update("partners", "id", part_id, fields)
        else:
            part_id = self.insert("partners", fields | {
                "property_id": pid, "name": rec["name"], "kind": rec["kind"], "stage": "identified",
                "partner_type": rec.get("category"), "next_step": rec.get("first_ask"), "source": "agent",
                "source_run_id": run_id, "created_by": user_id, "created_at": ts})
            created = 1
        n = 0
        findings_by_step: dict[int, list] = {}
        for f in rec.get("lint_findings", []):
            step = int(f["location"].split("step")[1].split(".")[0]) if "step" in f["location"] else 1
            findings_by_step.setdefault(step, []).append(f)
        for m in rec.get("messages", []):
            ex = self.one("SELECT id, status FROM outreach_messages WHERE partner_id=? AND step=?", (part_id, m["step"]))
            fs = findings_by_step.get(m["step"], [])
            lint = "blocked" if any(f["severity"] == "block" for f in fs) else ("warn" if fs else "pass")
            data = {"subject": m["subject"], "body": m["body"], "delay_days": m["delay_days"], "lint_status": lint,
                    "lint_findings": json.dumps(fs), "updated_at": ts}
            if ex is None:
                self.insert("outreach_messages", data | {"partner_id": part_id, "step": m["step"], "status": "draft",
                                                         "source_run_id": run_id, "created_by": user_id, "created_at": ts})
                n += 1
            elif ex["status"] == "draft":
                self.update("outreach_messages", "id", ex["id"], data)
        return {"partner_id": part_id, "partner_created": created, "messages": n}

    def add_target(self, segment_id: int, data: dict, user_id: int | None) -> int:
        """Add a named organisation under a recommended segment; it inherits kind, scores and draft sequence."""
        seg = self.one("SELECT * FROM partners WHERE id=?", (segment_id,))
        if not seg:
            raise KeyError(segment_id)
        ts = now()
        inherit = {k: seg[k] for k in ("property_id", "kind", "category", "priority_score", "priority", "factors",
                                        "rationale", "deal_structure", "value_sharing_model", "mutual_value", "first_ask",
                                        "partner_type", "how_to_find")}
        pid = self.insert("partners", inherit | {k: v for k, v in data.items() if v not in (None, "")} | {
            "stage": "identified", "is_segment": 0, "parent_id": segment_id, "source": "agent-segment",
            "next_step": seg["first_ask"], "owner_id": user_id, "created_by": user_id, "created_at": ts, "updated_at": ts})
        for m in self.q("SELECT step, delay_days, subject, body, lint_status, lint_findings FROM outreach_messages "
                        "WHERE partner_id=? ORDER BY step", (segment_id,)):
            self.insert("outreach_messages", dict(m) | {"partner_id": pid, "status": "draft", "created_by": user_id,
                                                          "created_at": ts, "updated_at": ts})
        return pid

    # dashboard -------------------------------------------------------------
    def dashboard(self, property_ids: list[str], latest_run: str | None) -> dict:
        from datetime import date as _d, timedelta as _td
        totals_sql = ", ".join(f"COALESCE(SUM(r.{m}),0) AS {m}" for m in METRICS)
        since30 = (_d.today() - _td(days=30)).isoformat()
        out_props = []
        for pid in property_ids:
            t = self.one("SELECT * FROM targets WHERE property_id=?", (pid,)) or {"arr_target_usd": 2_000_000,
                                                                               "monthly_conversions_target": 0}
            funnel = self.one(f"SELECT {totals_sql} FROM campaign_results r JOIN campaigns c ON c.id=r.campaign_id "
                              f"WHERE c.property_id=?", (pid,))
            last30 = self.one("SELECT COALESCE(SUM(r.revenue_usd),0) AS rev FROM campaign_results r JOIN campaigns c "
                              "ON c.id=r.campaign_id WHERE c.property_id=? AND r.date >= ?", (pid, since30))
            camp = self.one("SELECT COUNT(*) AS total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active "
                            "FROM campaigns WHERE property_id=?",
                            (pid,))
            stages = {r["stage"]: r["n"] for r in self.q(
                "SELECT stage, COUNT(*) AS n FROM partners WHERE property_id=? GROUP BY stage", (pid,))}
            tasks = self.one("SELECT COUNT(*) AS total, SUM(CASE WHEN status='Done' THEN 1 ELSE 0 END) AS done FROM tasks WHERE property_id=? "
                             "AND (run_id=? OR run_id='manual')", (pid, latest_run or ""))
            pb = self.one("SELECT lint_status, approved_by FROM playbooks WHERE run_id=? AND property_id=?",
                          (latest_run or "", pid))
            agr = {r["agreement_status"] or "none": r["n"] for r in self.q(
                "SELECT agreement_status, COUNT(*) AS n FROM partners WHERE property_id=? GROUP BY agreement_status", (pid,))}
            outreach = self.one(
                "SELECT SUM(CASE WHEN m.status='draft' THEN 1 ELSE 0 END) AS drafts, "
                "SUM(CASE WHEN m.status='approved' THEN 1 ELSE 0 END) AS approved, "
                "SUM(CASE WHEN m.sent_at IS NOT NULL THEN 1 ELSE 0 END) AS sent, "
                "SUM(CASE WHEN m.status='replied' THEN 1 ELSE 0 END) AS replied "
                "FROM outreach_messages m JOIN partners p ON p.id=m.partner_id WHERE p.property_id=?", (pid,))
            out_props.append({
                "property_id": pid, "arr_target_usd": t["arr_target_usd"],
                "monthly_conversions_target": t["monthly_conversions_target"],
                "revenue_to_date_usd": funnel["revenue_usd"], "arr_run_rate_usd": last30["rev"] * 12,
                "funnel": {m: funnel[m] for m in METRICS},
                "campaigns": {"total": camp["total"] or 0, "active": camp["active"] or 0},
                "partners": stages, "tasks": {"total": tasks["total"] or 0, "done": tasks["done"] or 0},
                "playbook": pb,
                "agreements": {k: agr.get(k, 0) for k in AGREEMENT_STATUSES},
                "outreach": {k: (outreach[k] or 0) for k in ("drafts", "approved", "sent", "replied")},
            })
        return {"properties": out_props, "weekly": self._weekly_series(), "latest_run": latest_run}

    def _weekly_series(self) -> list[dict]:
        """Results bucketed by week (Monday-based, like SQLite's %W), computed in Python so any database works."""
        from datetime import date as _d
        buckets: dict[str, dict] = {}
        for r in self.q("SELECT r.date, SUM(r.revenue_usd) AS revenue_usd, SUM(r.conversions) AS conversions, "
                        "SUM(r.meetings) AS meetings, SUM(r.signups) AS signups FROM campaign_results r "
                        "GROUP BY r.date ORDER BY r.date"):
            d = _d.fromisoformat(str(r["date"])[:10])
            week = f"{d.year}-W{int(d.strftime('%W')):02d}"
            b = buckets.setdefault(week, {"week": week, "start": r["date"], "revenue_usd": 0, "conversions": 0,
                                          "meetings": 0, "signups": 0})
            for k in ("revenue_usd", "conversions", "meetings", "signups"):
                b[k] += r[k] or 0
        return sorted(buckets.values(), key=lambda b: b["start"])
