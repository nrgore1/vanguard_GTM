"""Engine 2B - Partner Outreach: recommend, score, prioritise and draft outreach for each property.

Grounded in config/partner_playbooks.yaml (the expert layer). Three ways to produce a plan:
  * offline_plan(p)            - $0, no model: turns the playbook into prioritised recommendations + drafts
  * engine2b_partner_outreach  - a model (local or Claude) names specific organisations, using the playbook
  * MockLLM (dry runs)         - returns offline_plan(), so dry runs show real categories
Scoring is deterministic (weights in the YAML) so priorities are explainable and consistent.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from .lint_gate import LintGate
from .llm import LLM, dumps
from .registry import CONFIG_DIR, Property
from .schema import Factors, MarketIntel, OutreachStep, PartnerOutreachPlan, PartnerRec

log = logging.getLogger("vanguard.partners")


@lru_cache(maxsize=1)
def playbooks(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_DIR / "partner_playbooks.yaml").read_text(encoding="utf-8"))


def property_playbook(pid: str) -> dict:
    pb = playbooks()["properties"].get(pid)
    if not pb:
        raise KeyError(f"no partner playbook for {pid} in config/partner_playbooks.yaml")
    return pb


# ---------------------------------------------------------------- scoring
def score(f: Factors | dict) -> tuple[int, str]:
    cfg = playbooks()["scoring"]
    d = f.model_dump() if isinstance(f, Factors) else f
    w = cfg["weights"]
    raw = sum(w[k] * d[k] for k in w) / sum(w.values())          # 1..5
    s = round((raw - 1) / 4 * 100)                                # 0..100
    pri = "P0" if s >= cfg["p0_min"] else "P1" if s >= cfg["p1_min"] else "P2"
    return s, pri


# ---------------------------------------------------------------- message templates (by partnership kind)
_MIDDLE = {
    "design_partner": "We're looking for a small number of design partners to shape the product with us, and {{company}} "
                      "looks like a strong fit. What I'd propose: {offer}. There's no cost, and you'd have a direct say in "
                      "what we build.",
    "co_sell": "I think there's a natural way for our two teams to help each other: {offer}. Your clients get something "
               "useful, and we both reach people at the right moment.",
    "referral_affiliate": "The idea is simple: {offer}. It takes a few minutes to set up and there's nothing to pay.",
    "distribution": "I'd like to explore {offer} - built around what your audience actually needs, not an ad.",
    "integration": "I'd like to explore {offer}, so your users get this without leaving your product.",
}
_FOLLOW = {
    "design_partner": "To make it concrete: a pilot starts small - one scoped use case, a short weekly check-in, and you "
                      "decide whether it continues. Happy to send a one-page outline first if that's easier.",
    "co_sell": "To make it concrete, we could start with a short call to compare the clients we each serve and pick one "
               "simple way to refer or bundle. I can send a one-page outline first.",
    "referral_affiliate": "If it helps, I can send the one-page terms and a sample of how your business would be featured "
                          "- you can decide from there.",
    "distribution": "If it helps, I can send a one-page outline of what we'd bring and what it would ask of your team.",
    "integration": "If it helps, I can share a short technical outline so your team can judge the effort before any call.",
}


def draft_messages(p: Property, cat: dict, kind: str) -> list[OutreachStep]:
    line = property_playbook(p.id)["product_line"]
    delays = playbooks()["message_rules"]["default_delays_days"]
    subj = f"{{{{company}}}} + {p.name}: {'a small pilot idea' if kind == 'design_partner' else 'partnership idea'}"
    intro = (f"Hi {{{{first_name}}}},\n\nI'm {{{{sender_name}}}}, and I'm building {p.name} - {line}.\n\n"
             f"I'm reaching out because {cat['angle']}. " + _MIDDLE[kind].format(offer=cat["offer"]) +
             "\n\nWould a 20-minute call in the next two weeks be worth it?\n\nThanks,\n{{sender_name}}")
    follow = f"Hi {{{{first_name}}}},\n\nFollowing up briefly on my note about {p.name}. {_FOLLOW[kind]}\n\n{{{{sender_name}}}}"
    close = (f"Hi {{{{first_name}}}},\n\nI don't want to crowd your inbox, so this is my last note for now. If "
             f"{cat['offer']} becomes interesting later, just reply here and I'll pick it up.\n\nAll the best,\n{{{{sender_name}}}}")
    return [OutreachStep(step=1, delay_days=delays[0], subject=subj, body=intro),
            OutreachStep(step=2, delay_days=delays[1], subject=f"Re: {subj}", body=follow),
            OutreachStep(step=3, delay_days=delays[2], subject="Closing the loop", body=close)]


def offline_plan(p: Property) -> PartnerOutreachPlan:
    """$0 expert baseline: one recommendation per category (or per named example)."""
    recs = []
    for cat in property_playbook(p.id)["categories"]:
        names = cat.get("examples") or [cat["label"]]
        for name in names:
            recs.append(PartnerRec(
                name=name, is_segment=not cat.get("examples"), category=cat["id"], kind=cat["kind"],
                why=cat["why"], value_exchange=cat["value_exchange"], deal_structure=cat["deal_structure"],
                first_ask=cat["offer"][0].upper() + cat["offer"][1:],
                how_to_find_contact=cat["where_to_find"], factors=Factors(**cat["factors"]),
                messages=draft_messages(p, cat, cat["kind"])))
    return PartnerOutreachPlan(recommendations=recs)


# ---------------------------------------------------------------- model-driven engine
PARTNER_SYSTEM_ADDENDUM = """
PARTNER OUTREACH RULES:
- You are a partnerships expert. Recommend specific organisations where you are confident they exist and fit;
  otherwise give a precise segment to research (is_segment=true), e.g. "South Asian wedding planners in NJ/NY
  running 10+ events a year".
- Never invent email addresses, phone numbers or named individuals. how_to_find_contact names the ROLE and channel.
- Never claim an existing relationship, customers, users or results. Outreach copy is a first approach.
- Score factors honestly (1-5). Big, famous organisations are usually low 'access' and low 'speed'.
- Each partner gets a 3-step email sequence (intro, follow-up after ~4 days, polite close after ~9 days),
  each under 150 words, specific to that partner, merge tags {{first_name}} {{company}} {{sender_name}}.
"""


def _playbook_brief(pid: str) -> str:
    pb = property_playbook(pid)
    lines = [f"PRODUCT LINE: {pb['product_line']}", "PARTNER CATEGORIES (expert playbook):"]
    for c in pb["categories"]:
        lines.append(f"- [{c['id']}] {c['label']} | kind={c['kind']} | why: {c['why']} | value: {c['value_exchange']} | "
                     f"deal: {c['deal_structure']} | find: {c['where_to_find']} | typical factors: {c['factors']}"
                     + (f" | example targets to consider: {', '.join(c['examples'])}" if c.get("examples") else ""))
    return "\n".join(lines)


async def engine2b_partner_outreach(llm: LLM, p: Property, intel: MarketIntel | None,
                                    violations: str | None = None, previous: PartnerOutreachPlan | None = None
                                    ) -> PartnerOutreachPlan:
    from .engines import SYSTEM, _header
    prompt = _header(p, "2B - Partner Outreach") + "\n" + _playbook_brief(p.id) + "\n"
    if intel:
        prompt += f"\nENGINE 1 OUTPUT (ICP & economics):\n{dumps(intel)}\n"
    prompt += """
Recommend 8-12 partners across the playbook categories. Include at least two design_partner and two co_sell
recommendations. Prefer categories with high fit and access for the first 30 days. For each, fill every field and
write the 3-step email sequence."""
    if violations and previous:
        prompt += f"\n\nLINT VIOLATIONS in your previous draft - fix only these, keep the rest:\n{violations}\n\nPREVIOUS:\n{dumps(previous)}"
    return await llm.structured(SYSTEM + PARTNER_SYSTEM_ADDENDUM, prompt, PartnerOutreachPlan, "submit_partner_outreach")


def lint_rec(gate: LintGate, p: Property, rec: PartnerRec) -> list:
    items = [(f"outreach.step{m.step}.subject", m.subject) for m in rec.messages] + \
            [(f"outreach.step{m.step}.body", m.body) for m in rec.messages]
    return gate.check_items(items, p.lint_profile, p.banned_terms)


def finalize(gate: LintGate, p: Property, plan: PartnerOutreachPlan) -> list[dict]:
    """Score, lint and rank; returns dicts ready to store on the Playbook / import into the web app."""
    out = []
    for rec in plan.recommendations:
        s, pri = score(rec.factors)
        findings = lint_rec(gate, p, rec)
        out.append(rec.model_dump(mode="json") | {
            "score": s, "priority": pri, "lint_status": LintGate.status(findings),
            "lint_findings": [f.model_dump() for f in findings]})
    out.sort(key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


async def plan_partners(llm: LLM | None, p: Property, intel: MarketIntel | None, gate: LintGate,
                        max_repairs: int = 1) -> list[dict]:
    """Model plan with one lint-repair pass; falls back to the offline expert plan if there is no model."""
    if llm is None:
        return finalize(gate, p, offline_plan(p))
    plan = await engine2b_partner_outreach(llm, p, intel)
    for _ in range(max_repairs):
        bad = [(r, lint_rec(gate, p, r)) for r in plan.recommendations]
        blocking = [(r, f) for r, f in bad if any(x.severity == "block" for x in f)]
        if not blocking:
            break
        v = "\n".join(f"- {r.name} [{x.rule_id}] {x.location}: \"{x.excerpt}\"" for r, fs in blocking for x in fs)
        plan = await engine2b_partner_outreach(llm, p, intel, violations=v, previous=plan)
    return finalize(gate, p, plan)
