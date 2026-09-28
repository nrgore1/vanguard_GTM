import asyncio
import json

import httpx
import pytest

from vanguard.exporters import NotApproved, export_sequences, export_tasks
from vanguard.lint_gate import LintGate
from vanguard.llm import MockLLM, inline_schema
from vanguard.notion_sync import Notion
from vanguard.orchestrator import run_portfolio
from vanguard.registry import get_properties, load_properties
from vanguard.schema import CampaignPlan, MarketIntel
from vanguard.store import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("vanguard.orchestrator.OUTPUT_DIR", tmp_path / "out")
    return Store(tmp_path / "v.db")


def run(store, ids=("all",), llm=None, **kw):
    return asyncio.run(run_portfolio(llm or MockLLM(), get_properties(list(ids)), store, **kw))


# registry ----------------------------------------------------------------
def test_registry_has_all_eight():
    ids = {p.id for p in load_properties()}
    assert ids == {"liqmint", "liqmint-institutional", "vireoka", "weddingos", "jodibana", "jodiusa",
                   "oratoplus", "atmakosh"}


def test_unknown_property_rejected():
    with pytest.raises(KeyError):
        get_properties(["nope"])


# lint gate ---------------------------------------------------------------
@pytest.mark.parametrize("text,profile,rule", [
    ("Trusted by leading banks worldwide.", "institutional", "no-customer-claims"),
    ("Earn stablecoin yield on idle treasury.", "institutional", "liqmint-not-yield"),
    ("LiqMint supports Canton today.", "institutional", "canton-claim"),
    ("Settlement failures cost $3bn a year.", "institutional", "unattributed-figure"),
    ("Join 10,000 happy couples.", "consumer", "no-fabricated-social-proof"),
    ("We guarantee a match in 90 days.", "consumer", "no-guaranteed-match"),
])
def test_lint_blocks(text, profile, rule):
    ids = {f.rule_id for f in LintGate().check_text(text, "x", profile)}
    assert rule in ids


@pytest.mark.parametrize("text,profile", [
    ("Settlement failures cost $3bn a year (Source: BIS, 2025).", "institutional"),
    ("LiqMint is fully capable of supporting Canton integration.", "institutional"),
    ("Plan every event of a multi-day wedding in one place.", "consumer"),
])
def test_lint_allows(text, profile):
    assert not [f for f in LintGate().check_text(text, "x", profile) if f.severity == "block"]


# schema ------------------------------------------------------------------
def test_tool_schema_has_no_refs():
    for cls in (MarketIntel, CampaignPlan):
        assert "$ref" not in json.dumps(inline_schema(cls))


def test_email_sequence_needs_five_ordered_steps():
    from vanguard import mock_fixtures
    bad = mock_fixtures.campaigns("x", True)
    bad["email_sequences"][0]["steps"] = bad["email_sequences"][0]["steps"][:4]
    with pytest.raises(Exception):
        CampaignPlan.model_validate(bad)


# orchestration -----------------------------------------------------------
def test_parallel_run_all_properties(store):
    llm = MockLLM(delay=0.05)
    rid = run(store, llm=llm, concurrency=8)
    rows = store.playbooks(rid)
    assert len(rows) == 8 and store.run(rid)["status"] == "completed"
    assert all(r["lint_status"] != "blocked" for r in rows)
    # 4 engines x 8 properties + one repair pass for each property with seeded bad copy
    assert llm.calls.count("submit_campaign_plan") == 8 + 5
    assert len(store.tasks(rid)) == 8 * 30


def test_repair_loop_records_passes(store):
    rid = run(store, ["liqmint", "jodiusa"])
    assert "lint repair passes: 1" in store.playbook(rid, "liqmint").notes
    assert "lint repair passes: 0" in store.playbook(rid, "jodiusa").notes


def test_needs_review_flag(store):
    rid = run(store, ["weddingos", "liqmint"])
    assert any(n.startswith("NEEDS_POSITIONING_REVIEW") for n in store.playbook(rid, "weddingos").notes)
    assert not any(n.startswith("NEEDS_POSITIONING_REVIEW") for n in store.playbook(rid, "liqmint").notes)


def test_one_failure_does_not_stop_others(store):
    class Flaky(MockLLM):
        async def structured(self, system, prompt, model_cls, tool_name):
            if "PROPERTY_ID: oratoplus" in prompt:
                raise RuntimeError("boom")
            return await super().structured(system, prompt, model_cls, tool_name)

    rid = run(store, ["oratoplus", "atmakosh"], llm=Flaky())
    r = store.run(rid)
    assert r["status"] == "partial" and "oratoplus" in r["errors"]
    assert store.playbook(rid, "atmakosh") is not None


def test_persistent_block_stays_blocked(store):
    class Stubborn(MockLLM):
        async def structured(self, system, prompt, model_cls, tool_name):
            return await super().structured(system, prompt.replace("LINT VIOLATIONS", "X"), model_cls, tool_name)

    rid = run(store, ["liqmint"], llm=Stubborn())
    assert store.playbook(rid, "liqmint").lint_status == "blocked"
    assert not store.approve(rid, "liqmint", "narendra")


# exports / approval gate -------------------------------------------------
def test_export_requires_approval(store, tmp_path):
    rid = run(store, ["atmakosh"])
    with pytest.raises(NotApproved):
        export_sequences(store, rid, "atmakosh", tmp_path)
    assert store.approve(rid, "atmakosh", "narendra")
    files = export_sequences(store, rid, "atmakosh", tmp_path)
    assert files and files[0].read_text(encoding="utf-8").count("\n") == 6  # header + 5 steps
    assert export_tasks(store, rid, tmp_path).exists()


# notion ------------------------------------------------------------------
def test_notion_sync_is_idempotent(store):
    rid = run(store, ["vireoka"])
    pages: dict[str, dict] = {}
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        body = json.loads(req.content or b"{}")
        if req.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        if req.method == "POST" and req.url.path == "/v1/pages":
            pid = f"page-{len(pages)}"
            pages[pid] = body
            assert len(body.get("children", [])) <= 100
            return httpx.Response(200, json={"id": pid})
        if req.method == "PATCH" and req.url.path.startswith("/v1/pages/"):
            assert "Status" not in body["properties"]  # never clobber human status
            return httpx.Response(200, json={"id": req.url.path.split("/")[-1]})
        return httpx.Response(200, json={"id": "x"})

    async def go():
        n = Notion(token="t", transport=httpx.MockTransport(handler), min_interval=0)
        cfg = {"tasks_db": "T", "playbooks_db": "P"}
        first = await n.sync_run(store, rid, cfg)
        created = len(pages)
        second = await n.sync_run(store, rid, cfg)
        await n.aclose()
        return first, created, second

    first, created, second = asyncio.run(go())
    assert first == {"playbooks": 1, "tasks": 30} and created == 31
    assert second == first and len(pages) == created  # second pass only PATCHes
    assert sum(1 for m, _ in calls if m == "PATCH" and "/pages/" in _) == 31
