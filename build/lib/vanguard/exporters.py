"""Dispatcher-ready exports. Nothing is sent from here - files only.

Email sequences export only for playbooks that are lint-clean (not blocked)
AND approved by a human (`vanguard approve`).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .schema import Playbook
from .store import Store


class NotApproved(Exception):
    pass


def export_sequences(store: Store, run_id: str, property_id: str, out_dir: Path) -> list[Path]:
    row = next((r for r in store.playbooks(run_id) if r["property_id"] == property_id), None)
    if not row:
        raise KeyError(f"no playbook for {property_id} in run {run_id}")
    if row["lint_status"] == "blocked":
        raise NotApproved(f"{property_id}: lint gate blocked - fix copy before export")
    if not row["approved_by"]:
        raise NotApproved(f"{property_id}: not approved - run `vanguard approve {property_id} --run {run_id}`")
    pb = Playbook.model_validate_json(row["body"])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, seq in enumerate(pb.campaign_blueprints.email_sequences, 1):
        # Smartlead / Instantly both import sequences as step rows (step, delay, subject, body)
        path = out_dir / f"{property_id}-seq{i}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sequence", "step", "step_name", "delay_days", "subject", "body", "audience_filter", "trigger"])
            for st in seq.steps:
                w.writerow([seq.sequence_name, st.step, st.name.value, st.delay_days, st.subject, st.body,
                            seq.audience_filter, seq.trigger_event])
        written.append(path)
    return written


def export_tasks(store: Store, run_id: str, out_dir: Path, fmt: str = "csv") -> Path:
    """Backlog export for Linear/Jira/Airtable import (Notion is synced via API instead)."""
    rows = [json.loads(t["body"]) | {"property_id": t["property_id"], "run_id": run_id} for t in store.tasks(run_id)]
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path = out_dir / f"tasks-{run_id}.json"
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return path
    path = out_dir / f"tasks-{run_id}.csv"
    cols = ["property_id", "task_id", "day", "priority", "owner", "tool", "category", "description", "dependencies", "kpi"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r | {"dependencies": ";".join(r["dependencies"])})
    return path
