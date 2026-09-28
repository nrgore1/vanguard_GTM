"""Local, free LLMs (Ollama / any OpenAI-compatible server) with Claude as an optional paid fallback.

    VANGUARD_PROVIDER=local   (default) local model first; Claude only as fallback, and only if
                              VANGUARD_MAX_COST_USD > 0 and ANTHROPIC_API_KEY is set
    VANGUARD_PROVIDER=claude  Claude only (paid; needs the cap > 0)

Local models run on your own machine: no per-token cost, no data leaves it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .llm import inline_schema

log = logging.getLogger("vanguard.providers")
T = TypeVar("T", bound=BaseModel)

DEFAULT_LOCAL_MODEL = "qwen3.6:27b"
_THINK = re.compile(r"<think>.*?</think>", re.S)


class LocalUnavailable(RuntimeError):
    """The local model server can't be reached or never produced valid output."""


def _env_float(name: str, default: str) -> float:
    return float(os.getenv(name, default) or default)


def extract_json(text: str) -> dict:
    """Strip reasoning blocks / code fences / chatter and parse the outermost JSON object."""
    text = _THINK.sub("", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


@dataclass
class LocalMeter:
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, tin: int, tout: int) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += tin or 0
            self.output_tokens += tout or 0

    cost_usd = 0.0  # it runs on your hardware

    def summary(self) -> dict:
        return {"provider": "local", "model": self.model, "calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "web_searches": 0, "cost_usd": 0.0, "failures": self.failures}


class LocalLLM:
    """Structured output from a local model, constrained by the same JSON Schema Claude gets."""

    def __init__(self, model: str | None = None, base_url: str | None = None, api: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.model = model or os.getenv("VANGUARD_LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
        self.api = (api or os.getenv("VANGUARD_LOCAL_API", "ollama")).lower()          # ollama | openai
        default_url = "http://localhost:11434" if self.api == "ollama" else "http://localhost:1234/v1"
        self.base_url = (base_url or os.getenv("VANGUARD_LOCAL_URL", default_url)).rstrip("/")
        self.num_ctx = int(os.getenv("VANGUARD_LOCAL_CTX", "32768"))
        self.think = os.getenv("VANGUARD_LOCAL_THINK", "0") == "1"
        self._transport = transport
        self.http = httpx.AsyncClient(timeout=_env_float("VANGUARD_LOCAL_TIMEOUT", "900"), transport=transport)
        # one GPU serves one generation at a time well; pipelines still run in parallel and queue here
        self._sem = asyncio.Semaphore(int(os.getenv("VANGUARD_LOCAL_CONCURRENCY", "1")))
        self.meter = LocalMeter(self.model)
        self.web_search = False

    # ----------------------------------------------------------------- health
    async def check(self) -> tuple[bool, str]:
        try:  # own short-lived client, so check() can run in a separate event loop from the run itself
            async with httpx.AsyncClient(timeout=10, transport=self._transport) as c:
                if self.api == "ollama":
                    r = await c.get(f"{self.base_url}/api/tags")
                    names = [m.get("name", "") for m in r.json().get("models", [])]
                else:
                    r = await c.get(f"{self.base_url}/models")
                    names = [m.get("id", "") for m in r.json().get("data", [])]
        except (httpx.HTTPError, ValueError) as e:
            return False, f"local model server not reachable at {self.base_url} ({type(e).__name__})"
        want = self.model if ":" in self.model else f"{self.model}:latest"
        if not any(n == self.model or n == want for n in names):
            hint = f"run `ollama pull {self.model}`" if self.api == "ollama" else "load it in your server"
            return False, f"server is up but model '{self.model}' isn't installed - {hint} (installed: {names[:6]})"
        return True, f"{self.model} ready at {self.base_url}"

    # ----------------------------------------------------------------- calls
    async def _chat(self, messages: list[dict], schema: dict | None) -> str:
        async with self._sem:
            if self.api == "ollama":
                body = {"model": self.model, "messages": messages, "stream": False, "think": self.think,
                        "options": {"num_ctx": self.num_ctx, "temperature": 0.4}}
                if schema:
                    body["format"] = schema               # Ollama structured outputs (JSON Schema)
                r = await self.http.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                d = r.json()
                self.meter.record(d.get("prompt_eval_count", 0), d.get("eval_count", 0))
                return d["message"]["content"]
            body = {"model": self.model, "messages": messages, "temperature": 0.4}
            if schema:
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "result", "schema": schema, "strict": False}}
            r = await self.http.post(f"{self.base_url}/chat/completions", json=body)
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            self.meter.record(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
            return d["choices"][0]["message"]["content"]

    async def structured(self, system: str, prompt: str, model_cls: type[T], tool_name: str, attempts: int = 3) -> T:
        schema = inline_schema(model_cls)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{prompt}\n\nReply with ONE JSON object only (no prose) that validates "
                                        f"against this JSON Schema for {model_cls.__name__}:\n{json.dumps(schema)}"},
        ]
        last: Exception | None = None
        for i in range(attempts):
            try:
                content = await self._chat(messages, schema)
            except httpx.HTTPError as e:
                self.meter.failures += 1
                raise LocalUnavailable(f"{self.model} at {self.base_url}: {type(e).__name__}: {e}") from e
            try:
                return model_cls.model_validate(extract_json(content))
            except (ValidationError, ValueError) as e:
                last = e
                log.warning("[local] %s invalid output (attempt %d/%d)", tool_name, i + 1, attempts)
                messages += [{"role": "assistant", "content": content[:20000]},
                             {"role": "user", "content": f"That output failed validation. Fix every error and "
                                                         f"return the complete JSON object again:\n{str(e)[:4000]}"}]
        self.meter.failures += 1
        raise LocalUnavailable(f"{tool_name}: {self.model} never produced valid output") from last

    async def research(self, system: str, prompt: str) -> str:
        return ""  # local models have no web access; Engine 1 works from the registry facts


class FallbackLLM:
    """Local first. On outage or repeated invalid output, hand that one call to Claude - if paid runs are on."""

    def __init__(self, primary: LocalLLM, backup_factory=None):
        self.primary = primary
        self._backup_factory = backup_factory
        self._backup = None
        self.fallback_calls = 0
        self.research_with_claude = os.getenv("VANGUARD_RESEARCH_WITH_CLAUDE", "0") == "1"
        self.model = primary.model
        self.web_search = self.research_with_claude and self.backup_enabled

    @property
    def backup_enabled(self) -> bool:
        return (_env_float("VANGUARD_MAX_COST_USD", "0") > 0 and bool(os.getenv("ANTHROPIC_API_KEY"))
                and self._backup_factory is not None)

    @property
    def backup(self):
        if self._backup is None and self.backup_enabled:
            self._backup = self._backup_factory()
        return self._backup

    async def structured(self, system, prompt, model_cls, tool_name):
        try:
            return await self.primary.structured(system, prompt, model_cls, tool_name)
        except LocalUnavailable as e:
            if not self.backup_enabled:
                raise LocalUnavailable(f"{e}. Claude fallback is OFF (VANGUARD_MAX_COST_USD=0 or no "
                                       f"ANTHROPIC_API_KEY), so nothing was spent") from e
            self.fallback_calls += 1
            log.warning("[fallback] %s -> Claude (%s)", tool_name, e)
            return await self.backup.structured(system, prompt, model_cls, tool_name)

    async def research(self, system, prompt):
        if self.research_with_claude and self.backup_enabled:
            return await self.backup.research(system, prompt)
        return ""

    @property
    def meter(self):
        return self

    def summary(self) -> dict:
        p = self.primary.meter.summary()
        b = self._backup.meter.summary() if self._backup else None
        return {
            "provider": "local+claude" if b and b.get("calls") else "local",
            "model": p["model"] + (f" -> {b['model']} (fallback)" if b and b.get("calls") else ""),
            "calls": p["calls"] + (b["calls"] if b else 0),
            "input_tokens": p["input_tokens"] + (b["input_tokens"] if b else 0),
            "output_tokens": p["output_tokens"] + (b["output_tokens"] if b else 0),
            "web_searches": b["web_searches"] if b else 0,
            "cost_usd": b["cost_usd"] if b else 0.0,
            "local_calls": p["calls"], "local_failures": p["failures"], "fallback_calls": self.fallback_calls,
        }

    @property
    def cost_usd(self) -> float:
        return self.summary()["cost_usd"]
