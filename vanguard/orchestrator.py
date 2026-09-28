"""Runs all selected properties in parallel, each through engines 1->4."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engines import run_property
from .lint_gate import LintGate
from .llm import LLM
from .registry import Property
from .store import Store

log = logging.getLogger("vanguard.orchestrator")
OUTPUT_DIR = Path(os.getenv("VANGUARD_OUTPUT", "output"))


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


async def run_portfolio(llm: LLM, properties: list[Property], store: Store, *,
                        concurrency: int | None = None, run_id: str | None = None) -> str:
    run_id = run_id or new_run_id()
    concurrency = concurrency or int(os.getenv("VANGUARD_CONCURRENCY", "4"))
    store.create_run(run_id, [p.id for p in properties])
    gate = LintGate()
    sem = asyncio.Semaphore(concurrency)
    out_dir = OUTPUT_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}

    async def one(p: Property):
        async with sem:
            try:
                pb = await run_property(llm, p, run_id, gate)
                store.save_playbook(pb)
                (out_dir / f"{p.id}.json").write_text(pb.model_dump_json(indent=2), encoding="utf-8")
                log.info("[%s] done: lint=%s tasks=%d", p.id, pb.lint_status, len(pb.daily_task_registry))
            except Exception as e:  # one property failing never stops the others
                log.exception("[%s] failed", p.id)
                errors[p.id] = f"{type(e).__name__}: {e}"

    await asyncio.gather(*(one(p) for p in properties))
    meter = getattr(llm, "meter", None)
    store.finish_run(run_id, errors, meter.summary() if meter else {"model": "mock", "cost_usd": 0.0})
    return run_id
