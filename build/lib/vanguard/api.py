"""HTTP API (for n8n/cron/the dashboard). Bearer-token protected."""
from __future__ import annotations

import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import __version__
from .llm import make_llm
from .orchestrator import new_run_id, run_portfolio
from .registry import get_properties, load_properties
from .store import Store

app = FastAPI(title="Vanguard-GTM", version=__version__)
store = Store()


def auth(authorization: str = Header(default="")):
    token = os.getenv("VANGUARD_API_TOKEN")
    if not token:
        raise HTTPException(503, "VANGUARD_API_TOKEN not configured")
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "bad token")


class RunRequest(BaseModel):
    properties: list[str] = ["all"]
    dry_run: bool = False
    concurrency: int | None = None
    sync_notion: bool = False


class Approval(BaseModel):
    approved_by: str


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/properties", dependencies=[Depends(auth)])
def properties():
    return [p.model_dump(include={"id", "url", "name", "track", "motion", "positioning_status"}) for p in load_properties()]


@app.post("/runs", dependencies=[Depends(auth)], status_code=202)
async def start_run(req: RunRequest, bg: BackgroundTasks):
    try:
        props = get_properties(req.properties)
    except KeyError as e:
        raise HTTPException(400, str(e))
    rid = new_run_id()

    async def job():
        await run_portfolio(make_llm(req.dry_run), props, store, concurrency=req.concurrency, run_id=rid)
        if req.sync_notion:
            from .notion_sync import Notion
            n = Notion()
            try:
                await n.sync_run(store, rid)
            finally:
                await n.aclose()

    bg.add_task(job)
    return {"run_id": rid, "properties": [p.id for p in props]}


@app.get("/runs/{run_id}", dependencies=[Depends(auth)])
def get_run(run_id: str):
    run = store.run(run_id)
    if not run:
        raise HTTPException(404)
    run["playbooks"] = [{k: r[k] for k in ("property_id", "lint_status", "approved_by", "notion_page_id")}
                        for r in store.playbooks(run_id)]
    return run


@app.get("/runs/{run_id}/playbooks/{property_id}", dependencies=[Depends(auth)])
def get_playbook(run_id: str, property_id: str):
    pb = store.playbook(run_id, property_id)
    if not pb:
        raise HTTPException(404)
    return pb.model_dump(mode="json")


@app.post("/runs/{run_id}/playbooks/{property_id}/approve", dependencies=[Depends(auth)])
def approve(run_id: str, property_id: str, body: Approval):
    if not store.approve(run_id, property_id, body.approved_by):
        raise HTTPException(409, "missing, or blocked by lint gate")
    return {"approved": True}


@app.get("/failproof", dependencies=[Depends(auth)])
def failproof(as_of: str | None = None):
    """Tripwire + gate tracker for cron/n8n; `halt` is true for any property with 3+ tripped tripwires."""
    from datetime import date
    from .failproof import FailproofStore, load_failproof, today, tracker
    return tracker(load_failproof(), FailproofStore(store), date.fromisoformat(as_of) if as_of else today())


@app.post("/runs/{run_id}/sync", dependencies=[Depends(auth)])
async def sync(run_id: str):
    from .notion_sync import Notion
    n = Notion()
    try:
        return await n.sync_run(store, run_id)
    finally:
        await n.aclose()
