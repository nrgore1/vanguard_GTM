"""Claude client: structured output via forced tool use, with optional web research."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("vanguard.llm")
T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    async def structured(self, system: str, prompt: str, model_cls: type[T], tool_name: str) -> T: ...
    async def research(self, system: str, prompt: str) -> str: ...


def inline_schema(model_cls: type[BaseModel]) -> dict:
    """Pydantic schema with $refs inlined (tool input_schema stays self-contained)."""
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


class ClaudeLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 16000, web_search: bool | None = None):
        from anthropic import AsyncAnthropic

        from .cost import Meter

        self.client = AsyncAnthropic(max_retries=4)
        self.model = model or os.getenv("VANGUARD_MODEL", "claude-sonnet-5")
        self.max_tokens = max_tokens
        self.web_search = web_search if web_search is not None else os.getenv("VANGUARD_WEB_SEARCH", "1") == "1"
        # Paid mode is OFF unless you set a positive cap: the default of 0 refuses every API call.
        self.meter = Meter(self.model, budget_usd=float(os.getenv("VANGUARD_MAX_COST_USD", "0") or 0))

    async def _create(self, **kw):
        self.meter.check_budget()           # refuse new calls once the spend cap is hit
        resp = await self.client.messages.create(**kw)
        self.meter.record(resp.usage)
        return resp

    async def structured(self, system: str, prompt: str, model_cls: type[T], tool_name: str, attempts: int = 3) -> T:
        tool = {
            "name": tool_name,
            "description": f"Submit the {model_cls.__name__} result. All fields are required unless marked optional.",
            "input_schema": inline_schema(model_cls),
        }
        messages: list[dict] = [{"role": "user", "content": prompt}]
        last_err: Exception | None = None
        for i in range(attempts):
            resp = await self._create(
                model=self.model, max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages, tools=[tool], tool_choice={"type": "tool", "name": tool_name},
            )
            block = next(b for b in resp.content if b.type == "tool_use")
            try:
                return model_cls.model_validate(block.input)
            except ValidationError as e:  # feed the validation error back once or twice
                last_err = e
                log.warning("%s validation failed (attempt %d): %s", tool_name, i + 1, e.error_count())
                messages += [
                    {"role": "assistant", "content": resp.content},
                    {"role": "user", "content": [{
                        "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                        "content": f"Schema validation failed. Fix and resubmit the complete object:\n{e}",
                    }]},
                ]
        raise RuntimeError(f"{tool_name}: output never validated") from last_err

    async def research(self, system: str, prompt: str) -> str:
        if not self.web_search:
            return ""
        messages: list[dict] = [{"role": "user", "content": prompt}]
        text: list[str] = []
        for _ in range(3):  # server tools may pause a long turn; resume it
            resp = await self._create(
                model=self.model, max_tokens=6000, system=system, messages=messages,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            )
            text += [b.text for b in resp.content if b.type == "text"]
            if resp.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
        return "\n".join(text)


class MockLLM:
    """Deterministic offline stand-in used by tests and `--dry-run`."""

    def __init__(self, fixtures: dict[str, Any] | None = None, delay: float = 0.0):
        from . import mock_fixtures
        self.fixtures = fixtures or mock_fixtures
        self.delay = delay
        self.calls: list[str] = []

    async def structured(self, system: str, prompt: str, model_cls: type[T], tool_name: str) -> T:
        self.calls.append(tool_name)
        await asyncio.sleep(self.delay)
        pid = _extract(prompt, "PROPERTY_ID:")
        repairing = "LINT VIOLATIONS" in prompt
        return model_cls.model_validate(self.fixtures.build(tool_name, pid, repaired=repairing))

    async def research(self, system: str, prompt: str) -> str:
        return ""


def _extract(prompt: str, key: str) -> str:
    for line in prompt.splitlines():
        if line.startswith(key):
            return line.split(":", 1)[1].strip()
    return "unknown"


def make_llm(dry_run: bool, web_search: bool | None = None, provider: str | None = None) -> LLM:
    """dry run -> MockLLM; provider "claude" -> Claude only (paid); default "local" -> local model with
    Claude as a fallback that only activates when VANGUARD_MAX_COST_USD > 0."""
    if dry_run:
        return MockLLM()
    provider = (provider or os.getenv("VANGUARD_PROVIDER", "local")).lower()
    if provider == "claude":
        return ClaudeLLM(web_search=web_search)
    if provider != "local":
        raise ValueError(f"VANGUARD_PROVIDER must be 'local' or 'claude', not {provider!r}")
    from .providers import FallbackLLM, LocalLLM
    return FallbackLLM(LocalLLM(), backup_factory=lambda: ClaudeLLM(web_search=web_search))


def dumps(obj: BaseModel) -> str:
    return json.dumps(obj.model_dump(mode="json"), indent=1)
