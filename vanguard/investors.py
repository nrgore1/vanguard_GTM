"""Investor targets for the raise: config/investor_targets.yaml -> partners of kind 'investor'.

Each investor becomes (or refreshes) one partner under the YAML's property (Vireoka), with its rank, score,
factors, the reasons, the March 2026 conference considerations and the researched details. No outreach drafts are
created - first contact with an investor is personal - and nothing is approved or sent.

Re-importing is safe: research fields are refreshed, but the stage, a hand-entered contact email or contact name,
and any next step already set are left alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .registry import CONFIG_DIR, get_properties
from .store import now

DEFAULT_PATH = CONFIG_DIR / "investor_targets.yaml"
FACTOR_KEYS = ("thesis", "stage", "check", "geo", "research")
TYPE_LABEL = {"VC FUND": "VC fund", "ANGEL": "Angel", "FAMILY OFFICE": "Family office", "CORPORATE VC": "Corporate VC",
              "ACCELERATOR": "Accelerator", "VENTURE STUDIO": "Venture studio", "FUND OF FUNDS": "Fund of funds"}


def load(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("investors"), list):
        raise ValueError(f"{p}: expected a top-level 'investors' list")
    return data


def _types(e: dict) -> str:
    return " · ".join(TYPE_LABEL.get(t, t.title()) for t in e.get("types") or []) or "Investor"


def rationale(e: dict, total: int) -> str:
    r = e.get("research") or {}
    lines = [f"Rank #{e['rank']} of {total} for LiqMint Institutional (score {e['score']})."]
    prof = [x for x in (_types(e), e.get("check_size"), ", ".join(e.get("stages") or []),
                        ", ".join(e.get("sectors") or []), e.get("geography")) if x]
    lines.append("Profile: " + " · ".join(prof))
    if r.get("fit"):
        lines.append("Why: " + r["fit"])
    if r.get("thesis"):
        lines.append("Their thesis: " + r["thesis"])
    if r.get("concern"):
        lines.append("Likely concern: " + r["concern"])
    if r.get("hook"):
        lines.append("Opening hook: " + r["hook"])
    if e.get("signals"):
        lines.append("Signals: " + "; ".join(e["signals"]))
    if e.get("considerations"):
        lines.append("Key considerations:\n" + "\n".join(f"- {c}" for c in e["considerations"]))
    lines.append("Source: " + e.get("source", "investor_targets.yaml") +
                 (f" · research confidence {r['confidence']}" if r.get("confidence") else " · not researched yet"))
    return "\n".join(lines)


def how_to_find(e: dict) -> str | None:
    r = e.get("research") or {}
    parts = []
    for label, key in (("Title", "title"), ("Location", "location"), ("LinkedIn", "linkedin"),
                       ("Contact", "contact_route"), ("Typical check", "typical_check"), ("Leads rounds", "leads_rounds"),
                       ("Fund", "fund_size")):
        if r.get(key):
            parts.append(f"{label}: {r[key]}")
    if r.get("relevant_portfolio"):
        parts.append("Relevant portfolio: " + "; ".join(r["relevant_portfolio"]))
    if r.get("recent_deals"):
        parts.append("Recent deals: " + "; ".join(r["recent_deals"]))
    if r.get("sources"):
        parts.append("Sources: " + " ".join(r["sources"]))
    return " | ".join(parts) or None


def import_investors(ws, path: Path | str | None = None, user_id: int | None = None) -> dict:
    data = load(path)
    pid = data.get("property_id", "vireoka")
    if pid not in {p.id for p in get_properties(["all"])}:
        raise ValueError(f"unknown property id {pid}")
    items = data["investors"]
    report = {"property_id": pid, "created": 0, "updated": 0, "errors": [], "by_priority": {}}
    ts = now()
    for e in items:
        name = (e.get("name") or "").strip()
        if not name or "score" not in e or "rank" not in e:
            report["errors"].append(f"entry without name/score/rank: {e.get('name')!r}")
            continue
        r = e.get("research") or {}
        factors = {k: e.get("factors", {}).get(k) for k in FACTOR_KEYS}
        site = r.get("website")
        if site and not site.startswith("http"):
            site = "https://" + site.split()[0]
        fields = {
            "kind": "investor", "category": "investor", "source": "investor_research", "is_segment": 0,
            "partner_type": f"{_types(e)} · {e.get('firm') or 'no firm listed'}",
            "priority_score": int(e["score"]), "priority": e.get("priority"),
            "factors": json.dumps(factors), "rationale": rationale(e, len(items)), "how_to_find": how_to_find(e),
            "deal_structure": " · ".join(x for x in (e.get("check_size"), ", ".join(e.get("stages") or [])) if x) or None,
            "website": site, "updated_at": ts,
        }
        row = ws.one("SELECT id, contact_name, contact_email, next_step FROM partners WHERE property_id=? AND name=?",
                     (pid, name))
        if row:
            if not row["contact_name"]:
                fields["contact_name"] = name
            if r.get("published_email") and not row["contact_email"]:
                fields["contact_email"] = r["published_email"].strip().lower()
            ws.update("partners", "id", row["id"], fields)
            report["updated"] += 1
        else:
            fields |= {"property_id": pid, "name": name, "stage": "identified", "contact_name": name,
                       "contact_email": (r.get("published_email") or "").strip().lower() or None,
                       "next_step": ("Find a warm intro (LinkedIn, Known column), then a short plain-language note"
                                     if e.get("priority") == "P0" else None),
                       "owner_id": user_id, "created_by": user_id, "created_at": ts}
            ws.insert("partners", fields)
            report["created"] += 1
        report["by_priority"][e.get("priority") or "-"] = report["by_priority"].get(e.get("priority") or "-", 0) + 1
    ws.audit(user_id, "import-investors", "partner", None, {k: v for k, v in report.items() if k != "errors"})
    return report
