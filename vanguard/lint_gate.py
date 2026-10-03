"""Claim-discipline gate for all outward-facing copy."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .registry import CONFIG_DIR
from .schema import CampaignPlan, LintFinding, MarketIntel

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Rule:
    id: str
    severity: str
    pattern: re.Pattern
    message: str


class LintGate:
    def __init__(self, path: Path | None = None):
        cfg = yaml.safe_load((path or CONFIG_DIR / "lint_gate.yaml").read_text(encoding="utf-8"))
        self.profiles: dict[str, list[Rule]] = {
            name: [Rule(r["id"], r["severity"], re.compile(r["pattern"], re.I), r["message"]) for r in rules]
            for name, rules in cfg["profiles"].items()
        }
        a = cfg.get("attribution", {})
        self.attr_profiles = set(a.get("enabled_profiles", []))
        self.attr_number = re.compile(a["number_pattern"], re.I) if a else None
        self.attr_source = re.compile(a["source_pattern"]) if a else None  # case-sensitive on purpose
        self.attr_severity = a.get("severity", "block")
        self.attr_exempt = re.compile(a["exempt_pattern"]) if a.get("exempt_pattern") else None

    # ------------------------------------------------------------------
    def check_text(self, text: str, location: str, profile: str,
                   banned_terms: Iterable[str] = ()) -> list[LintFinding]:
        out: list[LintFinding] = []
        for term in banned_terms:
            for m in re.finditer(r"\b" + re.escape(term) + r"\b", text, re.I):
                out.append(LintFinding(rule_id="property-banned-term", severity="block", location=location,
                                       excerpt=_window(text, m.start(), m.end()),
                                       message=f"'{term}' must not appear in this property's public copy."))
        for rule in self.profiles.get(profile, []):
            for m in rule.pattern.finditer(text):
                out.append(LintFinding(rule_id=rule.id, severity=rule.severity, location=location,
                                       excerpt=_window(text, m.start(), m.end()), message=rule.message))
        if profile in self.attr_profiles and self.attr_number:
            for sentence in _SENTENCE.split(text):
                if self.attr_exempt and self.attr_exempt.search(sentence):
                    continue
                if self.attr_number.search(sentence) and not self.attr_source.search(sentence):
                    out.append(LintFinding(
                        rule_id="unattributed-figure", severity=self.attr_severity, location=location,
                        excerpt=sentence.strip()[:160],
                        message="Quantitative claim in copy needs a named public source in the same sentence."))
        return out

    def check_items(self, items: Iterable[tuple[str, str]], profile: str,
                    banned_terms: Iterable[str] = ()) -> list[LintFinding]:
        findings: list[LintFinding] = []
        banned = list(banned_terms)
        for loc, text in items:
            if text:
                findings.extend(self.check_text(text, loc, profile, banned))
        return findings

    @staticmethod
    def status(findings: list[LintFinding]) -> str:
        if any(f.severity == "block" for f in findings):
            return "blocked"
        return "warn" if findings else "pass"


def copy_fields(intel: MarketIntel | None, campaigns: CampaignPlan | None) -> list[tuple[str, str]]:
    """Every outward-facing string, with a stable location path."""
    items: list[tuple[str, str]] = []
    if intel:
        items.append(("market_intel.us_market_narrative", intel.us_market_narrative))
        items += [(f"market_intel.differentiation[{i}]", d) for i, d in enumerate(intel.differentiation)]
    if campaigns:
        for ci, c in enumerate(campaigns.social_campaigns):
            items += [(f"social[{ci}:{c.channel}].hook[{hi}]", h) for hi, h in enumerate(c.hook_concepts)]
        for si, seq in enumerate(campaigns.email_sequences):
            for st in seq.steps:
                items.append((f"email[{si}].step{st.step}.subject", st.subject))
                items.append((f"email[{si}].step{st.step}.body", st.body))
    return items


def _window(text: str, s: int, e: int, pad: int = 50) -> str:
    return ("…" if s > pad else "") + text[max(0, s - pad): e + pad].replace("\n", " ") + ("…" if e + pad < len(text) else "")
