"""Offline fixtures for --dry-run and tests. Placeholder content, NOT strategy.

The first campaign draft for some properties deliberately contains
lint violations so the repair loop is exercised end to end.
"""
from __future__ import annotations

ACV = {"liqmint": 240, "liqmint-institutional": 175000, "vireoka": 90000, "atmakosh": 60000,
       "weddingos": 600, "jodibana": 240, "jodiusa": 300, "oratoplus": 1200}


def _icp(tag: str) -> dict:
    return {"persona": f"[mock] {tag} persona", "firmographics_or_demographics": "[mock]",
            "pain_triggers": ["[mock] trigger"], "budget_authority": "[mock]", "where_they_are": ["[mock] channel"]}


def market(pid: str) -> dict:
    acv = ACV.get(pid, 1000)
    units = -(-2_000_000 // acv)
    return {
        "tier_1_icp": _icp("tier 1"), "tier_2_icp": _icp("tier 2"),
        "unit_economics": {
            "target_acv_usd": acv, "required_active_units": units,
            "pricing_tiers": [{"name": "Core", "price_usd_per_year": acv, "who_buys": "[mock]"}],
            "funnel_assumptions": {"lead_to_meeting": 0.05, "meeting_to_close": 0.2},
            "target_cac_usd": acv * 0.3, "target_ltv_usd": acv * 3, "months_to_target_estimate": 24,
            "key_risks": ["[mock] risk"]},
        "primary_conversion_path": "High-Touch Sales" if acv >= 10000 else "Product-Led Growth",
        "us_market_narrative": f"[mock] narrative for {pid}.",
        "competitors": ["[mock] Competitor"], "differentiation": ["[mock] differentiation"], "sources": [],
    }


def partners(pid: str) -> dict:
    kinds = ["design_partner", "co_sell", "distribution"]
    return {"partnership_playbook": [
        {"kind": kinds[i - 1], "partner_type": f"[mock] type {i}", "target_entities": [f"[mock] Entity {i}"], "mutual_value_exchange": "[mock]",
         "value_sharing_model": "co_marketing", "first_ask": "[mock] ask", "success_metric": "[mock] metric"}
        for i in (1, 2, 3)]}


BAD_COPY = {
    "liqmint": "Trusted by leading banks. Earn stablecoin yield with LiqMint.",
    "atmakosh": "Fines reach 7% of global turnover.",          # unattributed figure
    "vireoka": "See how AtmaSphere audits every decision.",     # property-banned term
    "weddingos": "Join 10,000 happy couples planning with us.",
    "jodibana": "We guarantee a match in 90 days.",
}
STEPS = ["trigger_hook", "pain_amplification", "solution_proof", "social_validation", "low_friction_cta"]


def campaigns(pid: str, repaired: bool) -> dict:
    hook0 = BAD_COPY.get(pid) if not repaired and pid in BAD_COPY else f"[mock] hook A for {pid}"
    return {
        "social_campaigns": [{
            "channel": "linkedin", "content_pillar": "[mock] pillar", "hook_concepts": [hook0, "[mock] hook B", "[mock] hook C"],
            "cadence": "3x/week", "paid_or_organic": "organic", "audience_parameters": "[mock]",
            "funnel_metric_targets": {"ctr": 0.012}}],
        "email_sequences": [{
            "sequence_name": f"{pid}-tier1", "trigger_event": "[mock] trigger", "audience_filter": "[mock] filter",
            "steps": [{"step": i + 1, "name": n, "delay_days": 0 if i == 0 else 3,
                       "subject": f"[mock] {n}", "body": f"Hi {{{{first_name}}}}, [mock] {n} body."}
                      for i, n in enumerate(STEPS)]}],
    }


def tasks(pid: str) -> dict:
    from .registry import load_properties
    prefix = next((p.task_prefix for p in load_properties() if p.id == pid), pid[:3].upper())
    cats = ["Research", "Content", "Email", "Outreach", "Partnership", "Tech Integration", "Analytics"]
    out = []
    for i in range(1, 31):
        tid = f"{prefix}-{i:03d}"
        out.append({"day": i, "task_id": tid, "description": f"[mock] day {i} task", "category": cats[i % len(cats)],
                    "priority": "P0" if i <= 5 else ("P1" if i <= 20 else "P2"),
                    "owner": "Tool API" if i % 3 == 0 else "Human", "tool": "Notion" if i % 3 == 0 else None,
                    "dependencies": [f"{prefix}-{i - 1:03d}"] if i > 1 else [], "kpi": "[mock] kpi"})
    return {"daily_task_registry": out}


def partner_outreach(pid: str) -> dict:
    """Dry runs use the $0 expert plan built from config/partner_playbooks.yaml."""
    from .partners import offline_plan
    from .registry import get_properties
    return offline_plan(get_properties([pid])[0]).model_dump(mode="json")


def build(tool_name: str, pid: str, repaired: bool = False) -> dict:
    return {
        "submit_partner_outreach": lambda: partner_outreach(pid),
        "submit_market_intel": lambda: market(pid),
        "submit_partnership_plan": lambda: partners(pid),
        "submit_campaign_plan": lambda: campaigns(pid, repaired),
        "submit_task_plan": lambda: tasks(pid),
    }[tool_name]()
