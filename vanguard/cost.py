"""Token/usage accounting, a hard spend cap, and a pre-run estimate.

Prices are USD per million tokens (Claude API list prices, checked 2026-09-27
at https://platform.claude.com/docs/en/about-claude/pricing). Override with
VANGUARD_PRICE_INPUT / VANGUARD_PRICE_OUTPUT if they change.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

PRICES = {  # model: (input $/MTok, output $/MTok)
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
CACHE_READ_MULT = 0.1      # cache reads bill at 10% of input
CACHE_WRITE_MULT = 1.25    # 5-minute cache writes bill at 125% of input
WEB_SEARCH_USD = 0.01      # $10 per 1,000 searches

# Typical per-property token volumes observed for this pipeline's shape
# (prompts grow as each engine receives the previous engines' output).
TYPICAL = {
    "research": {"in": 30_000, "out": 3_000, "searches": 6},
    "engine1": {"in": 4_000, "out": 4_000},
    "engine2": {"in": 7_000, "out": 3_000},
    "engine3": {"in": 10_000, "out": 6_000},
    "repair": {"in": 16_000, "out": 6_000},
    "engine4": {"in": 17_000, "out": 12_000},
}


class BudgetExceeded(RuntimeError):
    pass


def price_for(model: str) -> tuple[float, float]:
    pin, pout = os.getenv("VANGUARD_PRICE_INPUT"), os.getenv("VANGUARD_PRICE_OUTPUT")
    if pin and pout:
        return float(pin), float(pout)
    for key, p in PRICES.items():
        if model.startswith(key):
            return p
    return PRICES["claude-opus-5-5"]  # unknown model: assume the dearest, never under-estimate


@dataclass
class Meter:
    model: str
    budget_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, usage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
            stu = getattr(usage, "server_tool_use", None)
            self.web_searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0

    @property
    def cost_usd(self) -> float:
        pin, pout = price_for(self.model)
        return round(
            self.input_tokens / 1e6 * pin
            + self.cache_read_tokens / 1e6 * pin * CACHE_READ_MULT
            + self.cache_write_tokens / 1e6 * pin * CACHE_WRITE_MULT
            + self.output_tokens / 1e6 * pout
            + self.web_searches * WEB_SEARCH_USD, 4)

    def check_budget(self) -> None:
        if self.budget_usd is not None and self.budget_usd <= 0:
            raise BudgetExceeded("paid API runs are off (VANGUARD_MAX_COST_USD is 0). Use --dry-run or the $0 "
                                 "prompt/import path, or set a positive cap to allow paid runs")
        if self.budget_usd is not None and self.cost_usd >= self.budget_usd:
            raise BudgetExceeded(f"spend cap ${self.budget_usd:.2f} reached (spent ${self.cost_usd:.2f}); "
                                 "raise VANGUARD_MAX_COST_USD to continue")

    def summary(self) -> dict:
        return {"model": self.model, "calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cache_read_tokens": self.cache_read_tokens,
                "web_searches": self.web_searches, "cost_usd": self.cost_usd}


def estimate(n_properties: int, model: str, web_search: bool, repair_rate: float = 0.5) -> dict:
    """Rough pre-run cost; the Meter reports the real figure afterwards."""
    pin, pout = price_for(model)
    per = 0.0
    for stage, t in TYPICAL.items():
        if stage == "research" and not web_search:
            continue
        weight = repair_rate if stage == "repair" else 1.0
        per += weight * (t["in"] / 1e6 * pin + t["out"] / 1e6 * pout + t.get("searches", 0) * WEB_SEARCH_USD)
    return {"model": model, "properties": n_properties, "web_search": web_search,
            "per_property_usd": round(per, 2), "total_usd": round(per * n_properties, 2),
            "note": "estimate; actual spend is metered per run and shown by `vanguard status`"}
