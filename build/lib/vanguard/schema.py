"""Output contracts for each engine.

The final `Playbook` is a superset of the JSON schema in the Vanguard-GTM
prompt (section 4): same top-level keys, with the email automation widened to
the full 5-step sequence and tasks carrying priority / owner / dependencies as
required by Engine 4.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- Engine 1
class PricingTier(BaseModel):
    name: str
    price_usd_per_year: float = Field(ge=0)
    who_buys: str


class UnitEconomics(BaseModel):
    target_acv_usd: float = Field(gt=0, description="Blended annual value per paying unit")
    required_active_units: int = Field(gt=0, description="Paying units needed to hit the revenue target")
    pricing_tiers: list[PricingTier] = Field(min_length=1)
    funnel_assumptions: dict[str, float] = Field(
        description="Stage conversion rates as decimals, e.g. {'lead_to_meeting': 0.08}"
    )
    target_cac_usd: float = Field(gt=0)
    target_ltv_usd: float = Field(gt=0)
    months_to_target_estimate: int = Field(gt=0)
    key_risks: list[str] = Field(min_length=1)


class ICP(BaseModel):
    persona: str
    firmographics_or_demographics: str
    pain_triggers: list[str] = Field(min_length=1)
    budget_authority: str
    where_they_are: list[str] = Field(description="Specific communities, lists, events, platforms")


class MarketIntel(BaseModel):
    tier_1_icp: ICP
    tier_2_icp: ICP
    unit_economics: UnitEconomics
    primary_conversion_path: Literal["Self-serve", "High-Touch Sales", "Product-Led Growth"]
    us_market_narrative: str
    competitors: list[str] = Field(description="Named US incumbents / alternatives")
    differentiation: list[str]
    sources: list[str] = Field(default_factory=list, description="Public sources behind any market figures")

    def math_check(self, revenue_target: float) -> str | None:
        implied = self.unit_economics.target_acv_usd * self.unit_economics.required_active_units
        if implied < revenue_target * 0.98:
            return f"ACV x units = ${implied:,.0f}, below the ${revenue_target:,.0f} target"
        return None


# ---------------------------------------------------------------- Engine 2
PartnershipKind = Literal["design_partner", "co_sell", "distribution", "referral_affiliate", "integration"]


class Partnership(BaseModel):
    kind: PartnershipKind = Field(description=(
        "design_partner = an early customer that co-builds and validates the product under an agreed scope; "
        "co_sell = a B2B partner whose sales team sells alongside yours to shared accounts; "
        "distribution / referral_affiliate / integration = the other acquisition channels"))
    partner_type: str
    target_entities: list[str] = Field(min_length=1)
    mutual_value_exchange: str
    value_sharing_model: Literal["revenue_share", "co_marketing", "affiliate", "referral", "integration", "none_yet"]
    first_ask: str = Field(description="The concrete opening ask to the partner")
    success_metric: str


class PartnershipPlan(BaseModel):
    partnership_playbook: list[Partnership] = Field(min_length=3)

    @field_validator("partnership_playbook")
    @classmethod
    def needs_design_partner_and_co_sell(cls, v: list[Partnership]):
        kinds = {p.kind for p in v}
        missing = {"design_partner", "co_sell"} - kinds
        if missing:
            raise ValueError(f"playbook must include at least one of each: {sorted(missing)}")
        return v


# ---------------------------------------------------------------- Engine 2B (partner outreach)
class Factors(BaseModel):
    fit: int = Field(ge=1, le=5, description="How closely their customers match our ICP")
    reach: int = Field(ge=1, le=5, description="Audience/pipeline they can open")
    access: int = Field(ge=1, le=5, description="How reachable they are (warm path, public contact)")
    strategic: int = Field(ge=1, le=5, description="Long-term value: credibility, data, co-selling")
    speed: int = Field(ge=1, le=5, description="How fast a first result is realistic")


class OutreachStep(BaseModel):
    step: int = Field(ge=1, le=3)
    delay_days: int = Field(ge=0, le=60)
    subject: str = Field(min_length=3, max_length=140)
    body: str = Field(min_length=20, max_length=2500, description="Plain text, <=150 words; merge tags {{first_name}} {{company}} {{sender_name}}")


class PartnerRec(BaseModel):
    name: str = Field(description="A specific organisation, or a precise segment if unsure")
    is_segment: bool = Field(description="true when name describes a segment to research, not one organisation")
    category: str = Field(description="Category id from the property's partner playbook, or 'other'")
    kind: PartnershipKind
    why: str
    value_exchange: str
    deal_structure: str
    first_ask: str
    how_to_find_contact: str = Field(description="Role/title and channel to find the right person. Never invent emails or names.")
    factors: Factors
    messages: list[OutreachStep] = Field(min_length=2, max_length=3)

    @field_validator("messages")
    @classmethod
    def steps_in_order(cls, v: list[OutreachStep]):
        if [m.step for m in v] != list(range(1, len(v) + 1)):
            raise ValueError("messages must be steps 1..n in order")
        return v


class PartnerOutreachPlan(BaseModel):
    recommendations: list[PartnerRec] = Field(min_length=4, max_length=20)

    @field_validator("recommendations")
    @classmethod
    def covers_design_and_co_sell(cls, v: list[PartnerRec]):
        missing = {"design_partner", "co_sell"} - {r.kind for r in v}
        if missing:
            raise ValueError(f"recommendations must include at least one of each: {sorted(missing)}")
        return v


# ---------------------------------------------------------------- Engine 3
class EmailStepName(str, Enum):
    trigger_hook = "trigger_hook"
    pain_amplification = "pain_amplification"
    solution_proof = "solution_proof"
    social_validation = "social_validation"
    low_friction_cta = "low_friction_cta"


class EmailStep(BaseModel):
    step: int = Field(ge=1, le=5)
    name: EmailStepName
    delay_days: int = Field(ge=0)
    subject: str
    body: str = Field(description="Plain text; may use {{first_name}} {{company}} merge tags")


class EmailSequence(BaseModel):
    sequence_name: str
    trigger_event: str
    audience_filter: str = Field(description="Exact list/segment parameters")
    steps: list[EmailStep] = Field(min_length=5, max_length=5)

    @field_validator("steps")
    @classmethod
    def ordered(cls, v: list[EmailStep]):
        if [s.step for s in v] != [1, 2, 3, 4, 5]:
            raise ValueError("steps must be numbered 1..5 in order")
        return v


class SocialCampaign(BaseModel):
    channel: str
    content_pillar: str
    hook_concepts: list[str] = Field(min_length=2)
    cadence: str
    paid_or_organic: Literal["organic", "paid", "both"]
    audience_parameters: str
    funnel_metric_targets: dict[str, float]


class CampaignPlan(BaseModel):
    social_campaigns: list[SocialCampaign] = Field(min_length=1)
    email_sequences: list[EmailSequence] = Field(min_length=1)


# ---------------------------------------------------------------- Engine 4
class Task(BaseModel):
    day: int = Field(ge=1)
    task_id: str = Field(description="Unique within the property, e.g. LIQ-001")
    description: str
    category: Literal["Email", "Content", "Outreach", "Partnership", "Tech Integration", "Research", "Analytics"]
    priority: Literal["P0", "P1", "P2"]
    owner: Literal["Human", "Tool API"]
    tool: str | None = Field(default=None, description="If owner is Tool API: which tool (Notion, Smartlead, ...)")
    dependencies: list[str] = Field(default_factory=list)
    kpi: str


class TaskPlan(BaseModel):
    daily_task_registry: list[Task] = Field(min_length=10)


# ---------------------------------------------------------------- Assembled
class LintFinding(BaseModel):
    rule_id: str
    severity: Literal["block", "warn"]
    location: str
    excerpt: str
    message: str


class Playbook(BaseModel):
    property: str
    property_id: str
    run_id: str
    track: str = ""
    positioning_status: str
    revenue_roadmap: dict
    icp_matrix: dict
    market_intel: MarketIntel
    partnership_playbook: list[Partnership]
    campaign_blueprints: CampaignPlan
    daily_task_registry: list[Task]
    lint_findings: list[LintFinding] = Field(default_factory=list)
    lint_status: Literal["pass", "warn", "blocked"] = "pass"
    notes: list[str] = Field(default_factory=list)
    partner_outreach: list[dict] = Field(default_factory=list,
                                         description="Scored, prioritised PartnerRec dicts (+score, priority, lint)")
