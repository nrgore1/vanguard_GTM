from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class Property(BaseModel):
    id: str
    url: str
    name: str
    track: str
    task_prefix: str = Field(pattern=r"^[A-Z]{2,5}$")
    motion: str
    lint_profile: str
    positioning_status: str
    positioning: str
    not_this: str = ""
    capability_facts: list[str] = Field(default_factory=list)
    pricing_facts: list[str] = Field(default_factory=list)
    banned_terms: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    icp_seeds: list[str] = Field(default_factory=list)
    partner_seeds: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    known_pipeline_context: str = ""
    revenue_target_usd: float = 2_000_000
    campaign_days: int = 30
    market: str = "US"

    def brief(self) -> str:
        lines = [
            f"PROPERTY: {self.name} ({self.url}) - Track {self.track}, motion: {self.motion}",
            f"MARKET: {self.market}. REVENUE TARGET: ${self.revenue_target_usd:,.0f} ARR.",
            f"POSITIONING ({self.positioning_status}): {self.positioning.strip()}",
        ]
        if self.not_this:
            lines.append(f"WHAT IT IS NOT: {self.not_this.strip()}")
        if self.capability_facts:
            lines.append("CAPABILITY FACTS (use exactly, no embellishment):\n- " + "\n- ".join(self.capability_facts))
        if self.pricing_facts:
            lines.append("PRICING FACTS:\n- " + "\n- ".join(self.pricing_facts))
        if self.banned_terms:
            lines.append("NEVER USE IN COPY: " + ", ".join(self.banned_terms))
        if self.icp_seeds:
            lines.append("ICP SEEDS:\n- " + "\n- ".join(self.icp_seeds))
        if self.partner_seeds:
            lines.append("PARTNER SEEDS: " + ", ".join(self.partner_seeds))
        if self.channels:
            lines.append("CHANNELS: " + ", ".join(self.channels))
        if self.known_pipeline_context:
            lines.append(f"PIPELINE CONTEXT (private, never cite in copy): {self.known_pipeline_context.strip()}")
        return "\n".join(lines)


def load_properties(path: Path | None = None) -> list[Property]:
    data: dict[str, Any] = yaml.safe_load((path or CONFIG_DIR / "properties.yaml").read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    out = []
    for raw in data["properties"]:
        merged = {**{
            "revenue_target_usd": defaults.get("revenue_target_usd", 2_000_000),
            "campaign_days": defaults.get("campaign_days", 30),
            "market": defaults.get("market", "US"),
        }, **raw}
        out.append(Property(**merged))
    for attr in ("id", "task_prefix"):
        vals = [getattr(p, attr) for p in out]
        if len(vals) != len(set(vals)):
            raise ValueError(f"duplicate {attr} values in registry - each property needs its own")
    return out


def get_properties(ids: list[str] | None = None) -> list[Property]:
    props = load_properties()
    if not ids or ids == ["all"]:
        return props
    by_id = {p.id: p for p in props}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"unknown property ids: {missing}. Known: {sorted(by_id)}")
    return [by_id[i] for i in ids]
