"""The four sequential engines, run per property."""
from __future__ import annotations

import logging

from .lint_gate import LintGate, copy_fields
from .llm import LLM, dumps
from .registry import Property
from .schema import CampaignPlan, MarketIntel, PartnershipPlan, Playbook, TaskPlan

log = logging.getLogger("vanguard.engines")

SYSTEM = """You are Vanguard-GTM, the go-to-market and revenue orchestration agent for Vireoka's portfolio.
Your benchmark for each property is a credible path to $2,000,000 ARR in the US market, built from explicit
unit economics (ACV x paying units), CAC/LTV, strategic integration with design partners, B2B co-selling partners,
distribution partnerships and outbound/inbound funnels.

Operating rules:
1. No fluff. Name exact audiences (titles, firm sizes, communities, list filters), exact copy, measurable funnel metrics.
2. Distinct market realities. Institutional fintech (LiqMint, Vireoka, Atmakosh): compliance, security, capital efficiency,
   long sales cycles, evidence-led. Consumer (WeddingOS, Jodibana, JodiUSA): viral loops, emotional resonance, community trust.
3. Execution-ready. Everything must be pipeable into Notion task databases and email dispatchers.
4. CLAIM DISCIPLINE (hard rule, copy is machine-checked and blocked on violation):
   - Every property is pre-commercial. Never claim customers, users, partners, traction, revenue or production deployments.
   - Never write testimonials or quotes attributed to people. The 'social_validation' email step must use attributed
     third-party evidence (regulation, analyst/industry data, public incidents) - never customer proof.
   - Every number in outward-facing copy must name its public source in the same sentence, e.g. "(Source: BIS, 2025)".
     If you are not sure a figure is real, do not use a figure.
   - Frame product capabilities as architectural design intent, not guarantees or certifications.
   - Use the property's POSITIONING and CAPABILITY FACTS verbatim in substance; respect WHAT IT IS NOT.
   - PIPELINE CONTEXT is private background; never mention those organisations or people in copy.
5. Be honest in the economics. If $2M ARR needs an implausible number of units or a long timeline, say so in key_risks
   and months_to_target_estimate rather than bending assumptions.
"""


def _header(p: Property, engine: str) -> str:
    return f"PROPERTY_ID: {p.id}\nENGINE: {engine}\n\n{p.brief()}\n"


async def engine1_market(llm: LLM, p: Property) -> MarketIntel:
    research = await llm.research(
        SYSTEM,
        _header(p, "research") + "\nResearch the current US market for this property: named competitors and their "
        "pricing, market-size figures from public sources, and recent regulatory or industry triggers. "
        "Return concise notes with a source for every figure.",
    )
    prompt = _header(p, "1 - Market Intelligence & ICP Engineering") + f"""
{('RESEARCH NOTES (cite these sources where used):' + chr(10) + research) if research else ''}

Produce the market intelligence object:
- tier_1_icp and tier_2_icp with firmographics/demographics, pain triggers, budget authority, and where they can be reached.
- unit_economics: pricing tiers, blended target ACV, required_active_units so that ACV x units >= ${p.revenue_target_usd:,.0f},
  stage conversion rates as decimals, target CAC and LTV, honest months-to-target, key risks.
- primary_conversion_path, the US market narrative, named US competitors, differentiation, and sources list.
"""
    return await llm.structured(SYSTEM, prompt, MarketIntel, "submit_market_intel")


async def engine2_partners(llm: LLM, p: Property, intel: MarketIntel) -> PartnershipPlan:
    prompt = _header(p, "2 - Strategic Partnerships") + f"""
ENGINE 1 OUTPUT:
{dumps(intel)}

Design 3-6 partnerships. The set MUST include:
- at least one kind="design_partner": an early customer organisation to co-build and validate the product with - define the
  scoped pilot, what they get (influence on roadmap, preferential pricing), what you get (usage data, a reference only if
  they agree), and the exit criteria that convert it to a paid contract;
- at least one kind="co_sell": a B2B partner whose sales team would sell alongside yours into shared accounts - define the
  joint target accounts, deal registration / referral fee or margin split, and enablement needed;
- the rest: zero-marginal-cost distribution, referral/affiliate or integration partners.
For each: kind, partner type, named target entities (real organisations that plausibly fit; never claim a relationship
exists), mutual value exchange, value-sharing model, the concrete first ask, and a success metric.
"""
    return await llm.structured(SYSTEM, prompt, PartnershipPlan, "submit_partnership_plan")


async def engine3_campaigns(llm: LLM, p: Property, intel: MarketIntel, partners: PartnershipPlan,
                            violations: str | None = None, previous: CampaignPlan | None = None) -> CampaignPlan:
    prompt = _header(p, "3 - Campaign & Funnel Architecture") + f"""
ENGINE 1 OUTPUT:
{dumps(intel)}

ENGINE 2 OUTPUT:
{dumps(partners)}

Design:
- 1-3 social campaigns on this property's channels: pillar, at least 3 hook concepts written as ready-to-post opening lines,
  cadence, paid/organic, exact audience parameters, funnel metric targets.
- 1-2 five-step email sequences, one per ICP tier, steps in this order: trigger_hook, pain_amplification, solution_proof,
  social_validation, low_friction_cta. Write full subject and body copy (under 120 words each), merge tags {{{{first_name}}}}
  and {{{{company}}}} where useful, delay_days between steps.
"""
    if violations and previous:
        prompt += f"""
LINT VIOLATIONS in your previous draft - rewrite ONLY what is needed to clear every one, keep everything else:
{violations}

PREVIOUS DRAFT:
{dumps(previous)}
"""
    return await llm.structured(SYSTEM, prompt, CampaignPlan, "submit_campaign_plan")


async def engine4_tasks(llm: LLM, p: Property, intel: MarketIntel, partners: PartnershipPlan,
                        campaigns: CampaignPlan) -> TaskPlan:
    prefix = p.task_prefix
    prompt = _header(p, "4 - Task Tracking & Workflow Orchestration") + f"""
ENGINE 1-3 OUTPUTS:
{dumps(intel)}
{dumps(partners)}
{dumps(campaigns)}

Translate the plan into a {p.campaign_days}-day daily task registry (25-60 tasks). Rules:
- task_id format {prefix}-001, {prefix}-002, ... unique; dependencies reference only these ids.
- priority P0 (blocks launch or revenue), P1, P2. owner "Human" or "Tool API" (name the tool: Notion, Smartlead, Instantly,
  SendGrid, LinkedIn, Buffer, GA4 ...). Any task that SENDS email or PUBLISHES content needs a preceding Human approval task.
- Every task has a measurable KPI. Days 1-{p.campaign_days} only.
"""
    return await llm.structured(SYSTEM, prompt, TaskPlan, "submit_task_plan")


def _fmt(findings) -> str:
    return "\n".join(f"- [{f.rule_id}] at {f.location}: \"{f.excerpt}\" -> {f.message}" for f in findings)


async def run_property(llm: LLM, p: Property, run_id: str, gate: LintGate, max_repairs: int = 2) -> Playbook:
    log.info("[%s] engine 1", p.id)
    intel = await engine1_market(llm, p)
    log.info("[%s] engine 2", p.id)
    partners = await engine2_partners(llm, p, intel)
    log.info("[%s] engine 2B (partner outreach)", p.id)
    from .partners import plan_partners
    partner_outreach = await plan_partners(llm, p, intel, gate)
    log.info("[%s] engine 3", p.id)
    campaigns = await engine3_campaigns(llm, p, intel, partners)

    findings = gate.check_items(copy_fields(intel, campaigns), p.lint_profile, p.banned_terms)
    repairs = 0
    while repairs < max_repairs and any(f.severity == "block" and not f.location.startswith("market_intel")
                                        for f in findings):
        repairs += 1
        log.info("[%s] lint repair pass %d (%d findings)", p.id, repairs, len(findings))
        campaigns = await engine3_campaigns(llm, p, intel, partners, violations=_fmt(findings), previous=campaigns)
        findings = gate.check_items(copy_fields(intel, campaigns), p.lint_profile, p.banned_terms)

    log.info("[%s] engine 4", p.id)
    tasks = await engine4_tasks(llm, p, intel, partners, campaigns)

    pb = assemble(p, run_id, intel, partners, campaigns, tasks, findings, [f"lint repair passes: {repairs}"])
    pb.partner_outreach = partner_outreach
    return pb


def assemble(p: Property, run_id: str, intel: MarketIntel, partners: PartnershipPlan, campaigns: CampaignPlan,
             tasks: TaskPlan, findings, notes: list[str]) -> Playbook:
    """Build the final Playbook and attach consistency notes. Shared by live runs and `vanguard import`."""
    notes = list(notes)
    if p.positioning_status != "confirmed":
        notes.append("NEEDS_POSITIONING_REVIEW: positioning in config/properties.yaml is a draft")
    if (msg := intel.math_check(p.revenue_target_usd)):
        notes.append(f"ECONOMICS_GAP: {msg}")
    ids = {t.task_id for t in tasks.daily_task_registry}
    if len(ids) != len(tasks.daily_task_registry):
        notes.append("TASKS: duplicate task ids")
    dangling = sorted({d for t in tasks.daily_task_registry for d in t.dependencies if d not in ids})
    if dangling:
        notes.append(f"TASKS: dependencies reference unknown ids {dangling}")
    late = [t.task_id for t in tasks.daily_task_registry if t.day > p.campaign_days]
    if late:
        notes.append(f"TASKS: scheduled past day {p.campaign_days}: {late}")

    ue = intel.unit_economics
    return Playbook(
        property=p.url, property_id=p.id, run_id=run_id, track=p.track, positioning_status=p.positioning_status,
        revenue_roadmap={
            "target_acv": f"${ue.target_acv_usd:,.0f}",
            "required_active_units": ue.required_active_units,
            "primary_conversion_path": intel.primary_conversion_path,
            "target_cac": f"${ue.target_cac_usd:,.0f}",
            "target_ltv": f"${ue.target_ltv_usd:,.0f}",
            "months_to_target_estimate": ue.months_to_target_estimate,
        },
        icp_matrix={"tier_1_icp": intel.tier_1_icp.model_dump(), "tier_2_icp": intel.tier_2_icp.model_dump()},
        market_intel=intel,
        partnership_playbook=partners.partnership_playbook,
        campaign_blueprints=campaigns,
        daily_task_registry=tasks.daily_task_registry,
        lint_findings=findings,
        lint_status=LintGate.status(findings),
        notes=notes,
    )


MANUAL_INSTRUCTIONS = """You are producing a go-to-market playbook for the property below. Return ONE JSON object
with exactly these four keys, each matching its JSON Schema:
  "market_intel"          -> MarketIntel schema
  "partnership_playbook"  -> PartnershipPlan schema (object with key partnership_playbook)
  "campaign_blueprints"   -> CampaignPlan schema
  "daily_task_registry"   -> TaskPlan schema (object with key daily_task_registry)
Work through the four engines in order (market -> partnerships -> campaigns -> tasks), each building on the last.
Task ids use the prefix {prefix}-001, {prefix}-002, ... Return only the JSON."""


def manual_prompt(p: Property) -> str:
    """A self-contained prompt for producing a playbook in a Claude chat (covered by a Claude subscription)."""
    from .llm import inline_schema
    schemas = {k: inline_schema(c) for k, c in (("market_intel", MarketIntel), ("partnership_playbook", PartnershipPlan),
                                                ("campaign_blueprints", CampaignPlan), ("daily_task_registry", TaskPlan))}
    import json
    return "\n\n".join([SYSTEM, MANUAL_INSTRUCTIONS.format(prefix=p.task_prefix), _header(p, "all four"),
                        "JSON SCHEMAS:\n" + json.dumps(schemas, indent=1)])


def import_playbook(p: Property, run_id: str, data: dict, gate: LintGate) -> Playbook:
    """Validate a playbook produced elsewhere (e.g. pasted from a Claude chat) and run it through the lint gate."""
    intel = MarketIntel.model_validate(data["market_intel"])
    pp = data["partnership_playbook"]
    partners = PartnershipPlan.model_validate(pp if isinstance(pp, dict) else {"partnership_playbook": pp})
    campaigns = CampaignPlan.model_validate(data["campaign_blueprints"])
    tr = data["daily_task_registry"]
    tasks = TaskPlan.model_validate(tr if isinstance(tr, dict) else {"daily_task_registry": tr})
    findings = gate.check_items(copy_fields(intel, campaigns), p.lint_profile, p.banned_terms)
    return assemble(p, run_id, intel, partners, campaigns, tasks, findings, ["imported (manual / Claude chat)"])
