"""Notion backlog sync: two databases (Playbooks, Tasks) under one parent page.

Setup once:   vanguard notion-setup --parent-page <page id>
Then:         vanguard sync --run <run id>

Idempotent: re-syncing a run updates existing pages and never overwrites the
Status column (that belongs to whoever works the task in Notion).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx

from .schema import Playbook
from .store import Store

log = logging.getLogger("vanguard.notion")
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
CONFIG_PATH = Path(os.getenv("VANGUARD_NOTION_CONFIG", "data/notion.json"))


def _t(s: str) -> list[dict]:
    s = s or ""
    return [{"type": "text", "text": {"content": s[i:i + 2000]}} for i in range(0, max(len(s), 1), 2000)][:100]


def _sel(v: str) -> dict:
    return {"select": {"name": v.replace(",", " ")[:100]}}


TASK_SCHEMA = {
    "Task ID": {"title": {}},
    "Property": {"select": {}},
    "Day": {"number": {}},
    "Priority": {"select": {"options": [{"name": "P0", "color": "red"}, {"name": "P1", "color": "yellow"},
                                        {"name": "P2", "color": "gray"}]}},
    "Owner": {"select": {"options": [{"name": "Human", "color": "blue"}, {"name": "Tool API", "color": "purple"}]}},
    "Tool": {"rich_text": {}},
    "Category": {"select": {}},
    "Description": {"rich_text": {}},
    "Dependencies": {"rich_text": {}},
    "KPI": {"rich_text": {}},
    "Status": {"select": {"options": [{"name": "Not started"}, {"name": "In progress", "color": "blue"},
                                      {"name": "Done", "color": "green"}, {"name": "Blocked", "color": "red"}]}},
    "Run": {"rich_text": {}},
    "Playbook lint": {"select": {"options": [{"name": "pass", "color": "green"}, {"name": "warn", "color": "yellow"},
                                             {"name": "blocked", "color": "red"}]}},
}

PLAYBOOK_SCHEMA = {
    "Property": {"title": {}},
    "Property ID": {"rich_text": {}},
    "Track": {"select": {}},
    "Target ACV": {"rich_text": {}},
    "Units needed": {"number": {}},
    "Conversion path": {"select": {}},
    "Months to target": {"number": {}},
    "Lint": {"select": {"options": [{"name": "pass", "color": "green"}, {"name": "warn", "color": "yellow"},
                                    {"name": "blocked", "color": "red"}]}},
    "Positioning": {"select": {"options": [{"name": "confirmed", "color": "green"},
                                           {"name": "needs_review", "color": "orange"}]}},
    "Approved by": {"rich_text": {}},
    "Run": {"rich_text": {}},
}


class Notion:
    def __init__(self, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 min_interval: float = 0.34):
        token = token or os.environ["NOTION_TOKEN"]
        self.http = httpx.AsyncClient(
            base_url=API, timeout=30, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"})
        self.min_interval = min_interval  # Notion allows ~3 req/s per integration
        self._lock = asyncio.Lock()

    async def req(self, method: str, path: str, body: dict | None = None) -> dict:
        for attempt in range(6):
            async with self._lock:
                r = await self.http.request(method, path, json=body)
                await asyncio.sleep(self.min_interval)
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", 2 ** attempt))
                log.warning("Notion %s %s -> %s, retrying in %.1fs", method, path, r.status_code, wait)
                await asyncio.sleep(wait)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Notion {method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json()
        raise RuntimeError(f"Notion {method} {path}: retries exhausted")

    async def aclose(self):
        await self.http.aclose()

    # setup -------------------------------------------------------------
    async def setup(self, parent_page_id: str) -> dict:
        cfg = {}
        for key, title, schema in (("tasks_db", "Vanguard-GTM · Tasks", TASK_SCHEMA),
                                   ("playbooks_db", "Vanguard-GTM · Playbooks", PLAYBOOK_SCHEMA)):
            db = await self.req("POST", "/databases", {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": _t(title), "properties": schema})
            cfg[key] = db["id"]
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg

    # sync --------------------------------------------------------------
    async def _find(self, db: str, title_prop: str, title: str, run_id: str,
                    extra: list[dict] | None = None) -> str | None:
        res = await self.req("POST", f"/databases/{db}/query", {"filter": {"and": [
            {"property": title_prop, "title": {"equals": title}},
            {"property": "Run", "rich_text": {"equals": run_id}}, *(extra or [])]}, "page_size": 1})
        return res["results"][0]["id"] if res["results"] else None

    async def _upsert(self, db: str, title_prop: str, title: str, run_id: str, props: dict,
                      known_id: str | None, children: list[dict] | None = None,
                      create_only: dict | None = None, extra: list[dict] | None = None) -> str:
        page_id = known_id or await self._find(db, title_prop, title, run_id, extra)
        if page_id:
            await self.req("PATCH", f"/pages/{page_id}", {"properties": props})
            return page_id
        page = await self.req("POST", "/pages", {"parent": {"database_id": db},
                                                 "properties": {**props, **(create_only or {})},
                                                 "children": (children or [])[:100]})
        for i in range(100, len(children or []), 100):
            await self.req("PATCH", f"/blocks/{page['id']}/children", {"children": children[i:i + 100]})
        return page["id"]

    async def sync_run(self, store: Store, run_id: str, cfg: dict | None = None) -> dict:
        cfg = cfg or json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        counts = {"playbooks": 0, "tasks": 0}
        for row in store.playbooks(run_id):
            pb = Playbook.model_validate_json(row["body"])
            rr = pb.revenue_roadmap
            props = {
                "Property": {"title": _t(pb.property)},
                "Property ID": {"rich_text": _t(pb.property_id)},
                "Track": _sel(pb.track or "?"),
                "Target ACV": {"rich_text": _t(rr["target_acv"])},
                "Units needed": {"number": rr["required_active_units"]},
                "Conversion path": _sel(rr["primary_conversion_path"]),
                "Months to target": {"number": rr.get("months_to_target_estimate")},
                "Lint": _sel(pb.lint_status),
                "Positioning": _sel(pb.positioning_status),
                "Approved by": {"rich_text": _t(row.get("approved_by") or "")},
                "Run": {"rich_text": _t(run_id)},
            }
            pid = await self._upsert(cfg["playbooks_db"], "Property", pb.property, run_id, props,
                                     row.get("notion_page_id"), children=playbook_blocks(pb))
            store.set_playbook_notion(run_id, pb.property_id, pid)
            counts["playbooks"] += 1

            known = {t["task_id"]: t.get("notion_page_id") for t in store.tasks(run_id, pb.property_id)}
            for t in pb.daily_task_registry:
                tprops = {
                    "Task ID": {"title": _t(t.task_id)},
                    "Property": _sel(pb.property_id),
                    "Day": {"number": t.day},
                    "Priority": _sel(t.priority),
                    "Owner": _sel(t.owner),
                    "Tool": {"rich_text": _t(t.tool or "")},
                    "Category": _sel(t.category),
                    "Description": {"rich_text": _t(t.description)},
                    "Dependencies": {"rich_text": _t(", ".join(t.dependencies))},
                    "KPI": {"rich_text": _t(t.kpi)},
                    "Run": {"rich_text": _t(run_id)},
                    "Playbook lint": _sel(pb.lint_status),
                }
                tid = await self._upsert(cfg["tasks_db"], "Task ID", t.task_id, run_id, tprops,
                                         known.get(t.task_id), create_only={"Status": _sel("Not started")},
                                         extra=[{"property": "Property", "select": {"equals": pb.property_id}}])
                store.set_task_notion(run_id, pb.property_id, t.task_id, tid)
                counts["tasks"] += 1
        return counts


def playbook_blocks(pb: Playbook) -> list[dict]:
    def h(level: int, s: str):
        k = f"heading_{level}"
        return {"object": "block", "type": k, k: {"rich_text": _t(s)}}

    def p(s: str):
        return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _t(s)}}

    def li(s: str):
        return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _t(s)}}

    blocks = [h(2, "Revenue roadmap")] + [li(f"{k}: {v}") for k, v in pb.revenue_roadmap.items()]
    if pb.notes:
        blocks += [h(2, "Notes")] + [li(n) for n in pb.notes]
    if pb.lint_findings:
        blocks += [h(2, f"Lint findings ({pb.lint_status})")] + [
            li(f"[{f.severity}] {f.rule_id} @ {f.location}: {f.excerpt}") for f in pb.lint_findings[:40]]
    blocks.append(h(2, "Partnerships"))
    for pt in pb.partnership_playbook:
        blocks.append(li(f"[{pt.kind}] {pt.partner_type} - {', '.join(pt.target_entities)} | {pt.value_sharing_model} | "
                         f"first ask: {pt.first_ask}"))
    for seq in pb.campaign_blueprints.email_sequences:
        blocks += [h(2, f"Email: {seq.sequence_name}"), p(f"Trigger: {seq.trigger_event} | Audience: {seq.audience_filter}")]
        for st in seq.steps:
            blocks += [h(3, f"{st.step}. {st.name.value} (+{st.delay_days}d) - {st.subject}"), p(st.body)]
    for sc in pb.campaign_blueprints.social_campaigns:
        blocks += [h(2, f"Social: {sc.channel} - {sc.content_pillar}"), p(f"{sc.cadence} | {sc.audience_parameters}")]
        blocks += [li(x) for x in sc.hook_concepts]
    raw = pb.model_dump_json(indent=1)
    blocks.append(h(2, "Raw playbook JSON"))
    blocks += [{"object": "block", "type": "code",
                "code": {"language": "json", "rich_text": _t(raw[i:i + 2000])}} for i in range(0, len(raw), 2000)]
    return blocks
