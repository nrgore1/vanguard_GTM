"""Load researched, real partner organisations (config/partner_targets.yaml) as named targets.

Each target is added under its property's category segment (created from the $0 expert playbook if
missing), inherits that segment's kind, scores and 3-step draft sequence, and is marked source='research'.
For categories the playbook lists by name (e.g. Fireblocks, KPMG), research enriches that existing entry.
Idempotent: re-running refreshes research fields but never touches stage, outreach status, agreements,
or a contact email someone already entered by hand. Nothing is approved or sent.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import yaml

from .registry import CONFIG_DIR, get_properties
from .store import now

DEFAULT_PATH = CONFIG_DIR / "partner_targets.yaml"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SHIFT = {"P0": 6, "P1": 0, "P2": -8}          # nudge the segment score by the researcher's priority hint
BANDS = {"P0": (75, 100), "P1": (55, 74), "P2": (0, 54)}   # partners.score(): P0 >= 75, P1 >= 55


def load(path: Path | str | None = None) -> dict:
    data = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    return data.get("properties", {})


def _templates(ws, prop) -> dict[str, dict]:
    """category -> the partner whose drafts a new target copies: the category's segment, or (for categories the
    playbook lists by name, e.g. custodians) its highest-scored named example. Creates the $0 plan if missing."""
    q = ("SELECT p.* FROM partners p WHERE p.property_id=? AND p.category IS NOT NULL "
         "AND EXISTS (SELECT 1 FROM outreach_messages m WHERE m.partner_id=p.id) "
         "ORDER BY p.is_segment DESC, (p.parent_id IS NULL) DESC, COALESCE(p.priority_score,0) DESC")
    rows = ws.q(q, (prop.id,))
    from .partners import property_playbook
    wanted = {c["id"] for c in property_playbook(prop.id)["categories"]}
    missing = wanted - {r["category"] for r in rows}
    if missing:  # first import, or categories added to the playbook since the last one
        from .lint_gate import LintGate
        from .partners import plan_partners
        for r in asyncio.run(plan_partners(None, prop, None, LintGate())):
            if r.get("category") in missing:
                ws.upsert_recommendation(prop.id, r, None, None)
        rows = ws.q(q, (prop.id,))
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["category"], r)
    return out


def _existing(ws, pid: str, category: str, name: str) -> dict | None:
    """Same organisation already present: exact name, or a playbook example whose name the research name contains
    (e.g. 'KPMG' vs 'KPMG US - Digital Assets Advisory')."""
    row = ws.one("SELECT * FROM partners WHERE property_id=? AND lower(name)=lower(?)", (pid, name))
    if row:
        return row
    low = name.lower()
    for r in ws.q("SELECT * FROM partners WHERE property_id=? AND category=? AND is_segment=0", (pid, category)):
        n = r["name"].lower()
        if len(n) >= 2 and re.search(rf"(^|[^a-z]){re.escape(n)}([^a-z]|$)", low):
            return r
    return None


def _fields(t: dict, seg: dict) -> dict:
    hint = t.get("priority_hint") if t.get("priority_hint") in SHIFT else seg.get("priority") or "P2"
    score = int(seg.get("priority_score") or 50) + SHIFT[hint]
    lo, hi = BANDS[hint]                         # keep score and priority consistent with the scoring rule
    score = max(lo, min(hi, score))
    src = f"\nSource: {t['evidence_url']}" if t.get("evidence_url") else ""
    conf = f" (research confidence: {t.get('confidence', 'medium')})"
    contact = [f"Contact: {t['contact_url']}"] if t.get("contact_url") else []
    if t.get("how_to_reach"):
        contact.append(f"Route: {t['how_to_reach']}")
    for c in t.get("contacts") or []:            # publicly named role holders, each with its source
        conf_c = f", {c['confidence']}" if c.get("confidence") else ""
        contact.append(f"Person: {c['name']} - {c['title']} ({c.get('source', 'no source')}{conf_c})")
    if t.get("location"):
        contact.append(f"Location: {t['location']}")
    hook = f"\nTimely hook: {t['recent_hook']}" + (f" ({t['recent_hook_url']})" if t.get("recent_hook_url") else "") \
        if t.get("recent_hook") else ""
    return {"rationale": (t.get("why") or seg.get("rationale") or "") + src + hook + conf,
            "how_to_find": " | ".join(contact) or seg.get("how_to_find"),
            "priority": hint, "priority_score": score, "website": t.get("website")}


def import_targets(ws, path: Path | str | None = None, user_id: int | None = None,
                   property_ids: list[str] | None = None) -> dict:
    """Returns {"properties": {pid: {"created": n, "updated": n}}, "errors": [...], "without_email": n}."""
    data = load(path)
    report: dict = {"properties": {}, "errors": [], "without_email": 0}
    known = {p.id: p for p in get_properties(["all"])}
    for pid, items in data.items():
        if property_ids and pid not in property_ids:
            continue
        if pid not in known:
            report["errors"].append(f"{pid}: unknown property id")
            continue
        segs = _templates(ws, known[pid])
        stats = {"created": 0, "updated": 0}
        for t in items or []:
            name = (t.get("name") or "").strip()
            seg = segs.get(t.get("category"))
            if len(name) < 2:
                report["errors"].append(f"{pid}: target without a name")
                continue
            if not seg:
                report["errors"].append(f"{pid}/{name}: no segment for category '{t.get('category')}'")
                continue
            email = (t.get("contact_email") or "").strip().lower() or None
            if email and not EMAIL.match(email):
                report["errors"].append(f"{pid}/{name}: invalid contact_email '{email}' - ignored")
                email = None
            if email:                                   # only a named person's own address is used (v0.15.1)
                from .addresses import classify
                if classify(email, (t.get("contacts") or [{}])[0].get("name")) != "named":
                    report.setdefault("general_inboxes_skipped", []).append(f"{name}: {email}")
                    email = None
            if not email:
                report["without_email"] += 1
            f = _fields(t, seg)
            row = _existing(ws, pid, t["category"], name)
            if row and row["is_segment"]:
                report["errors"].append(f"{pid}/{name}: name clashes with a segment - skipped")
                continue
            if row:
                upd = f | {"updated_at": now(), "source": "research"}
                if email and not row["contact_email"]:
                    upd["contact_email"] = email
                lead = (t.get("contacts") or [{}])[0].get("name")
                if lead and not row.get("contact_name"):   # never overwrite a name someone entered
                    upd["contact_name"] = lead
                ws.update("partners", "id", row["id"], upd)
                stats["updated"] += 1
            else:
                lead = (t.get("contacts") or [{}])[0].get("name")
                new = ws.add_target(seg["id"], {"name": name, "contact_email": email, "contact_name": lead} | f, user_id)
                ws.update("partners", "id", new, {"source": "research", "priority": f["priority"],
                                                   "priority_score": f["priority_score"],
                                                   "parent_id": seg["id"] if seg["is_segment"] else None})
                stats["created"] += 1
        report["properties"][pid] = stats
    return report
