"""End-to-end tests. Each test's docstring starts with its ID from docs/TEST_CASES.md.

These drive the system the way you do - through the CLI, the HTTP API, the real
ClaudeLLM class (against a fake Anthropic client) and the Notion sync (against a
stateful fake Notion) - and spend nothing.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from vanguard import mock_fixtures
from vanguard.cost import BudgetExceeded, Meter, estimate
from vanguard.llm import ClaudeLLM
from vanguard.notion_sync import Notion
from vanguard.orchestrator import run_portfolio
from vanguard.registry import get_properties, load_properties
from vanguard.store import Store

from .fake_notion import FakeNotion

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def env(tmp_path, monkeypatch):
    e = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "NOTION_TOKEN")}
    e |= {"VANGUARD_DB": str(tmp_path / "v.db"), "VANGUARD_OUTPUT": str(tmp_path / "out"),
          "VANGUARD_NOTION_CONFIG": str(tmp_path / "notion.json"), "PYTHONPATH": str(ROOT)}
    monkeypatch.setattr("vanguard.orchestrator.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("vanguard.notion_sync.CONFIG_PATH", tmp_path / "notion.json")
    return e


def cli(env, *args, check=True, input_text=None):
    r = subprocess.run([sys.executable, "-m", "vanguard", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, input=input_text, timeout=120)
    if check and r.returncode != 0:
        raise AssertionError(f"vanguard {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    return r


class FakeAnthropic:
    """Stands in for AsyncAnthropic; returns fixture objects with realistic usage."""

    def __init__(self, bad_first: set[str] | None = None, pause_research: bool = False):
        self.calls: list[str] = []
        self.bad_first = set(bad_first or ())
        self.pause_research = pause_research
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        pid = next(l.split(":", 1)[1].strip() for l in prompt.splitlines() if l.startswith("PROPERTY_ID:"))
        usage = SimpleNamespace(input_tokens=2000, output_tokens=1000, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0, server_tool_use=None)
        if "tool_choice" not in kw:  # research call with web search
            self.calls.append("research")
            usage.server_tool_use = SimpleNamespace(web_search_requests=2)
            paused = self.pause_research and len(kw["messages"]) == 1
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"notes for {pid} (Source: X, 2026)")],
                                   usage=usage, stop_reason="pause_turn" if paused else "end_turn")
        name = kw["tool_choice"]["name"]
        self.calls.append(name)
        repaired = "LINT VIOLATIONS" in prompt
        data = mock_fixtures.build(name, pid, repaired=repaired)
        if name in self.bad_first:  # first answer violates the schema -> must be retried
            self.bad_first.discard(name)
            data = {"oops": True}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="tu_1", input=data)],
                               usage=usage, stop_reason="tool_use")


def claude_with(fake: FakeAnthropic, budget: float | None = 50.0, web_search=True) -> ClaudeLLM:
    llm = ClaudeLLM.__new__(ClaudeLLM)
    llm.client, llm.model, llm.max_tokens, llm.web_search = fake, "claude-sonnet-5", 16000, web_search
    llm.meter = Meter("claude-sonnet-5", budget_usd=budget)
    return llm


# ------------------------------------------------------------------ registry
def test_e2e_01_registry_matches_repo_refresh():
    """E2E-01: registry loads all 8 properties; confirmed ones cite their repo sources."""
    props = {p.id: p for p in load_properties()}
    assert len(props) == 8
    confirmed = {i for i, p in props.items() if p.positioning_status == "confirmed"}
    assert confirmed == {"liqmint", "liqmint-institutional", "vireoka", "oratoplus", "atmakosh"}
    for i in confirmed:
        assert props[i].sources, f"{i} is confirmed but lists no source docs"
    assert "Meridian Crest" in props["liqmint-institutional"].banned_terms
    assert "AtmaSphere" in props["vireoka"].banned_terms
    assert "$19.99" in " ".join(props["liqmint"].pricing_facts)
    # regression: liqmint/liqmint-institutional and jodibana/jodiusa once shared task-id prefixes,
    # which merged their tasks in Notion
    assert len({p.task_prefix for p in props.values()}) == 8


# ------------------------------------------------------------------ CLI
def test_e2e_02_cli_full_offline_cycle(env):
    """E2E-02: run -> status -> show -> approve -> export through the real CLI, all 8 properties."""
    out = cli(env, "run", "--dry-run").stdout
    assert "8 properties in parallel" in out and "status=completed" in out
    for pid in ("liqmint", "vireoka", "jodiusa", "atmakosh"):
        assert pid in out
    assert "NEEDS_POSITIONING_REVIEW" in out  # the three Track B drafts

    pb = json.loads(cli(env, "show", "liqmint-institutional").stdout)
    assert pb["property"] == "https://institutional.liqmint.com" and pb["track"] == "A"
    assert len(pb["campaign_blueprints"]["email_sequences"][0]["steps"]) == 5

    r = cli(env, "export", "atmakosh")
    assert "skipped" in r.stdout and "not approved" in r.stdout
    cli(env, "approve", "atmakosh", "--by", "narendra")
    r = cli(env, "export", "atmakosh")
    seq = next(Path(l.split("wrote ", 1)[1]) for l in r.stdout.splitlines() if "seq1.csv" in l)
    rows = list(csv.DictReader(seq.open(encoding="utf-8")))
    assert [r["step_name"] for r in rows] == ["trigger_hook", "pain_amplification", "solution_proof",
                                              "social_validation", "low_friction_cta"]
    tasks_csv = next(Path(l.split("wrote ", 1)[1]) for l in r.stdout.splitlines() if "tasks-" in l)
    assert len(list(csv.DictReader(tasks_csv.open(encoding="utf-8")))) == 8 * 30


def test_e2e_03_cli_subset_and_unknown_property(env):
    """E2E-03: --properties limits the run; an unknown id fails loudly without creating a run."""
    out = cli(env, "run", "--dry-run", "--properties", "oratoplus,jodibana").stdout
    assert "2 properties" in out and "oratoplus" in out and "liqmint " not in out
    r = cli(env, "run", "--dry-run", "--properties", "nope", check=False)
    assert r.returncode != 0 and "unknown property ids" in r.stderr


def test_e2e_04_cli_estimate_and_doctor_spend_nothing(env):
    """E2E-04: estimate is $0 for the local provider and prices Claude on request; doctor fails cleanly with no
    local model and no Notion token, and treats a missing Anthropic key as fine."""
    local = json.loads(cli(env, "estimate").stdout)
    assert local["provider"] == "local" and local["total_usd"] == 0 and local["worst_case_usd"] == 0
    est = json.loads(cli(env, "estimate", "--provider", "claude").stdout)
    assert est["properties"] == 8 and 0 < est["total_usd"] < 20
    cheap = json.loads(cli(env, "estimate", "--provider", "claude", "--model", "claude-haiku-4-5",
                           "--no-research").stdout)
    assert cheap["total_usd"] < est["total_usd"]
    env = env | {"VANGUARD_LOCAL_URL": "http://127.0.0.1:9"}           # nothing listens here
    r = cli(env, "doctor", check=False)
    assert r.returncode == 1 and "FAIL local model: local model server not reachable" in r.stdout
    assert "ANTHROPIC_API_KEY not set - fine" in r.stdout and "NOTION_TOKEN not set" in r.stdout


def test_e2e_05_paid_runs_off_by_default_then_confirmation(env):
    """E2E-05: Claude-only runs refuse at the default cap of 0; with a cap they show the estimate and still stop
    unless confirmed. A local run with no local model and fallback off stops before doing anything."""
    env = env | {"ANTHROPIC_API_KEY": "sk-test-not-used", "VANGUARD_LOCAL_URL": "http://127.0.0.1:9"}
    env.pop("VANGUARD_MAX_COST_USD", None)
    r = cli(env, "run", "--properties", "oratoplus", "--provider", "claude", check=False)
    assert r.returncode != 0 and "Paid API runs are OFF" in r.stderr and "nothing was spent" in r.stderr
    r = cli(env | {"VANGUARD_MAX_COST_USD": "5"}, "run", "--properties", "oratoplus", "--provider", "claude",
            check=False, input_text="n\n")
    assert "Estimated cost" in r.stdout and "Hard spend cap for this run: $5.00" in r.stdout and "cancelled" in r.stderr
    r = cli(env, "run", "--properties", "oratoplus", check=False)
    assert "Claude fallback: OFF" in r.stdout and "nothing was run or spent" in r.stderr
    doc = cli(env, "doctor", check=False).stdout
    assert "paid API runs: OFF ($0 mode)" in doc and "Notion API: free" in doc


def test_e2e_06_approval_blocked_copy_cannot_ship(env):
    """E2E-06: a playbook whose copy stays blocked can't be approved or exported."""
    from vanguard.llm import MockLLM

    class Stubborn(MockLLM):
        async def structured(self, system, prompt, model_cls, tool_name):
            return await super().structured(system, prompt.replace("LINT VIOLATIONS", "X"), model_cls, tool_name)

    store = Store(Path(env["VANGUARD_DB"]))
    rid = asyncio.run(run_portfolio(Stubborn(), get_properties(["vireoka"]), store))
    pb = store.playbook(rid, "vireoka")
    assert pb.lint_status == "blocked"
    assert any(f.rule_id == "property-banned-term" for f in pb.lint_findings)
    r = cli(env, "approve", "vireoka", "--by", "narendra", "--run", rid, check=False)
    assert r.returncode != 0 and "blocked by the lint gate" in r.stderr


# ------------------------------------------------------------------ real ClaudeLLM path
def test_e2e_07_claude_path_all_properties_with_metering():
    """E2E-07: the real ClaudeLLM class drives all 8 pipelines; usage and cost are metered."""
    fake = FakeAnthropic()
    llm = claude_with(fake)
    store = Store(Path(os.environ.get("TMPDIR", "/tmp")) / f"e2e7-{time.time_ns()}.db")
    rid = asyncio.run(run_portfolio(llm, load_properties(), store, concurrency=8))
    run = store.run(rid)
    assert run["status"] == "completed" and len(store.playbooks(rid)) == 8
    assert fake.calls.count("research") == 8
    assert run["usage"]["calls"] == len(fake.calls) and run["usage"]["web_searches"] == 16
    assert run["usage"]["cost_usd"] == llm.meter.cost_usd > 0


def test_e2e_08_schema_violation_is_retried():
    """E2E-08: a malformed tool answer is sent back with the validation error and fixed."""
    fake = FakeAnthropic(bad_first={"submit_market_intel"})
    llm = claude_with(fake, web_search=False)
    store = Store(Path(os.environ.get("TMPDIR", "/tmp")) / f"e2e8-{time.time_ns()}.db")
    rid = asyncio.run(run_portfolio(llm, get_properties(["oratoplus"]), store))
    assert store.run(rid)["status"] == "completed"
    assert fake.calls.count("submit_market_intel") == 2


def test_e2e_09_research_resumes_after_pause_turn():
    """E2E-09: a paused web-search turn is resumed instead of truncating the research."""
    fake = FakeAnthropic(pause_research=True)
    llm = claude_with(fake)
    notes = asyncio.run(llm.research("sys", "PROPERTY_ID: atmakosh\nresearch"))
    assert fake.calls.count("research") == 2 and notes.count("notes for atmakosh") == 2


def test_e2e_10_spend_cap_stops_the_run():
    """E2E-10: once the spend cap is reached no further API calls are made; the run is marked failed."""
    fake = FakeAnthropic()
    llm = claude_with(fake, budget=0.05)  # each fake call costs $0.014
    store = Store(Path(os.environ.get("TMPDIR", "/tmp")) / f"e2e10-{time.time_ns()}.db")
    rid = asyncio.run(run_portfolio(llm, load_properties(), store, concurrency=1))
    run = store.run(rid)
    assert run["status"] in ("failed", "partial")
    assert any("BudgetExceeded" in e for e in run["errors"].values())
    assert llm.meter.cost_usd < 0.05 + 0.02  # at most one call past the line (the one that crossed it)


def test_e2e_11_cost_maths():
    """E2E-11: meter and estimate arithmetic."""
    m = Meter("claude-sonnet-5")
    m.record(SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=1_000_000,
                             cache_creation_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=10)))
    assert m.cost_usd == pytest.approx(2.0 + 1.0 + 0.2 + 0.1)
    with pytest.raises(BudgetExceeded):
        Meter("claude-sonnet-5", budget_usd=0).check_budget()
    assert estimate(8, "unknown-model", True)["total_usd"] >= estimate(8, "claude-opus-5-5", True)["total_usd"]


# ------------------------------------------------------------------ Notion
def _run_offline(env, ids=("all",)) -> tuple[Store, str]:
    from vanguard.llm import MockLLM
    store = Store(Path(env["VANGUARD_DB"]))
    rid = asyncio.run(run_portfolio(MockLLM(), get_properties(list(ids)), store))
    return store, rid


def test_e2e_12_notion_setup_sync_resync(env):
    """E2E-12: setup creates both databases; sync creates 8 playbooks + 240 tasks; re-sync updates in place
    and never overwrites a Status someone changed in Notion."""
    fake = FakeNotion()
    store, rid = _run_offline(env)

    async def go():
        n = Notion(token="secret_x", transport=fake.transport(), min_interval=0)
        cfg = await n.setup("parent-page")
        first = await n.sync_run(store, rid, cfg)
        task_page = next(p for p in fake.rows(cfg["tasks_db"]) if p["Task ID"] == "ATM-001")
        fake.pages[task_page["_id"]]["properties"]["Status"] = {"select": {"name": "Done"}}
        second = await n.sync_run(store, rid, cfg)
        await n.aclose()
        return cfg, first, second

    cfg, first, second = asyncio.run(go())
    assert json.loads(Path(env["VANGUARD_NOTION_CONFIG"]).read_text(encoding="utf-8")) == cfg
    assert first == second == {"playbooks": 8, "tasks": 240}
    assert len(fake.rows(cfg["playbooks_db"])) == 8 and len(fake.rows(cfg["tasks_db"])) == 240
    assert next(p for p in fake.rows(cfg["tasks_db"]) if p["Task ID"] == "ATM-001")["Status"] == "Done"
    pb_rows = {r["Property ID"]: r for r in fake.rows(cfg["playbooks_db"])}
    assert pb_rows["jodiusa"]["Positioning"] == "needs_review" and pb_rows["liqmint"]["Track"] == "A"
    assert all(len(c) >= 10 for c in fake.children.values() if c)  # playbook bodies written


def test_e2e_13_notion_lookup_after_local_db_loss(env):
    """E2E-13: if the local page-id cache is lost, sync finds existing pages by query instead of duplicating."""
    fake = FakeNotion()
    store, rid = _run_offline(env, ["oratoplus"])

    async def go():
        n = Notion(token="secret_x", transport=fake.transport(), min_interval=0)
        cfg = await n.setup("parent")
        await n.sync_run(store, rid, cfg)
        with store.conn() as c:  # simulate losing the cached Notion ids
            c.execute("UPDATE tasks SET notion_page_id=NULL"); c.execute("UPDATE playbooks SET notion_page_id=NULL")
        await n.sync_run(store, rid, cfg)
        await n.aclose()
        return cfg

    cfg = asyncio.run(go())
    assert len(fake.rows(cfg["tasks_db"])) == 30 and len(fake.rows(cfg["playbooks_db"])) == 1


def test_e2e_14_notion_rate_limit_retry(env):
    """E2E-14: 429 responses are retried and the sync still completes."""
    fake = FakeNotion(fail_first_n_with_429=3)
    store, rid = _run_offline(env, ["jodiusa"])

    async def go():
        n = Notion(token="secret_x", transport=fake.transport(), min_interval=0)
        cfg = await n.setup("parent")
        res = await n.sync_run(store, rid, cfg)
        await n.aclose()
        return res

    assert asyncio.run(go()) == {"playbooks": 1, "tasks": 30}


def test_e2e_15_notion_bad_token_fails_clearly(env):
    """E2E-15: a rejected token surfaces Notion's error message."""
    import httpx
    t = httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "API token is invalid."}))

    async def go():
        n = Notion(token="bad", transport=t, min_interval=0)
        try:
            await n.setup("parent")
        finally:
            await n.aclose()

    with pytest.raises(RuntimeError, match="401.*API token is invalid"):
        asyncio.run(go())


# ------------------------------------------------------------------ HTTP API
def test_e2e_16_api_full_cycle(env, monkeypatch):
    """E2E-16: HTTP API - auth, start a run, poll, fetch playbook, approve, Notion sync."""
    monkeypatch.setenv("VANGUARD_API_TOKEN", "tok")
    from fastapi.testclient import TestClient
    import vanguard.api as api
    from vanguard.notion_sync import PLAYBOOK_SCHEMA, TASK_SCHEMA
    monkeypatch.setattr(api, "store", Store(Path(env["VANGUARD_DB"])))
    fake = FakeNotion()
    fake.databases["T"] = {"properties": TASK_SCHEMA}
    fake.databases["P"] = {"properties": PLAYBOOK_SCHEMA}
    Path(env["VANGUARD_NOTION_CONFIG"]).write_text(json.dumps({"tasks_db": "T", "playbooks_db": "P"}), encoding="utf-8")
    monkeypatch.setattr("vanguard.notion_sync.Notion.__init__", lambda self, *a, **k: _init(self, fake))
    h = {"Authorization": "Bearer tok"}
    c = TestClient(api.app)

    assert c.get("/health").json() == {"ok": True}
    assert c.get("/properties").status_code == 401
    assert len(c.get("/properties", headers=h).json()) == 8
    assert c.post("/runs", json={"properties": ["bogus"]}, headers=h).status_code == 400

    rid = c.post("/runs", json={"properties": ["atmakosh", "weddingos"], "dry_run": True}, headers=h).json()["run_id"]
    run = c.get(f"/runs/{rid}", headers=h).json()
    assert run["status"] == "completed" and {p["property_id"] for p in run["playbooks"]} == {"atmakosh", "weddingos"}
    pb = c.get(f"/runs/{rid}/playbooks/weddingos", headers=h).json()
    assert pb["positioning_status"] == "needs_review"
    assert c.post(f"/runs/{rid}/playbooks/atmakosh/approve", json={"approved_by": "narendra"}, headers=h).json() == {"approved": True}
    assert c.post(f"/runs/{rid}/sync", headers=h).json() == {"playbooks": 2, "tasks": 60}
    assert any(r["Approved by"] == "narendra" for r in fake.rows("P"))


def _init(self, fake):
    import asyncio as _a
    import httpx
    self.http = httpx.AsyncClient(base_url="https://api.notion.com/v1", transport=fake.transport(),
                                  headers={"Authorization": "Bearer secret_x", "Notion-Version": "2022-06-28",
                                           "Content-Type": "application/json"})
    self.min_interval = 0
    self._lock = _a.Lock()


# ------------------------------------------------------------------ optional live smoke tests
live = pytest.mark.skipif(os.getenv("VANGUARD_LIVE") != "1", reason="set VANGUARD_LIVE=1 to spend real (small) money")


@live
def test_e2e_live_01_one_property_on_haiku(tmp_path, monkeypatch):
    """E2E-L1: one real property end to end on Haiku without web research, capped at $0.50."""
    monkeypatch.setenv("VANGUARD_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("VANGUARD_MAX_COST_USD", "0.50")
    monkeypatch.setattr("vanguard.orchestrator.OUTPUT_DIR", tmp_path)
    llm = ClaudeLLM(web_search=False)
    store = Store(tmp_path / "live.db")
    rid = asyncio.run(run_portfolio(llm, get_properties(["oratoplus"]), store))
    assert store.run(rid)["status"] == "completed", store.run(rid)["errors"]
    pb = store.playbook(rid, "oratoplus")
    assert len(pb.daily_task_registry) >= 10 and pb.lint_status in ("pass", "warn", "blocked")
    print("live spend:", llm.meter.summary())


@live
@pytest.mark.skipif(not os.getenv("NOTION_TEST_PARENT_PAGE"), reason="needs NOTION_TEST_PARENT_PAGE")
def test_e2e_live_02_notion_roundtrip(tmp_path, monkeypatch):
    """E2E-L2: create databases under a scratch Notion page and sync an offline run ($0; Notion API is free)."""
    monkeypatch.setattr("vanguard.notion_sync.CONFIG_PATH", tmp_path / "notion.json")
    store, rid = _run_offline({"VANGUARD_DB": str(tmp_path / "v.db")}, ["jodiusa"])

    async def go():
        n = Notion()
        cfg = await n.setup(os.environ["NOTION_TEST_PARENT_PAGE"])
        res = await n.sync_run(store, rid, cfg)
        await n.aclose()
        return res

    assert asyncio.run(go()) == {"playbooks": 1, "tasks": 30}


# ------------------------------------------------------------------ $0 manual path
def _chat_reply(pid: str, repaired: bool) -> str:
    """What a Claude chat reply looks like: prose + a fenced JSON object."""
    body = {"market_intel": mock_fixtures.market(pid),
            "partnership_playbook": mock_fixtures.partners(pid)["partnership_playbook"],
            "campaign_blueprints": mock_fixtures.campaigns(pid, repaired),
            "daily_task_registry": mock_fixtures.tasks(pid)["daily_task_registry"]}
    return "Here is the playbook:\n```json\n" + json.dumps(body) + "\n```\n"


def test_e2e_17_prompt_then_import_clean(env, tmp_path):
    """E2E-17: `prompt` writes a self-contained prompt; `import` validates, lints and stores the reply at $0."""
    out = tmp_path / "ora.txt"
    cli(env, "prompt", "oratoplus", "--out", str(out))
    text = out.read_text(encoding="utf-8")
    assert "PROPERTY_ID: oratoplus" in text and "ORA-001" in text and '"daily_task_registry"' in text
    reply = tmp_path / "reply.json"
    reply.write_text(_chat_reply("oratoplus", repaired=True), encoding="utf-8")
    r = cli(env, "import", "oratoplus", str(reply)).stdout
    assert "lint=pass" in r and "tasks=30" in r
    status = cli(env, "status").stdout
    assert "Spend: $0.00" in status and "model=manual" in status


def test_e2e_18_import_catches_bad_copy(env, tmp_path):
    """E2E-18: copy pasted from a chat still goes through the lint gate - a yield claim is blocked."""
    reply = tmp_path / "reply.json"
    reply.write_text(_chat_reply("liqmint", repaired=False), encoding="utf-8")
    r = cli(env, "import", "liqmint", str(reply)).stdout
    assert "lint=blocked" in r and "liqmint-not-yield" in r and "no-customer-claims" in r
    r = cli(env, "approve", "liqmint", "--by", "narendra", check=False)
    assert r.returncode != 0


def test_e2e_19_partnerships_require_design_partner_and_co_sell():
    """E2E-19: Engine 2 output without a design partner or a co-selling partner is rejected (and retried)."""
    from pydantic import ValidationError
    from vanguard.schema import PartnershipPlan
    plan = mock_fixtures.partners("oratoplus")
    PartnershipPlan.model_validate(plan)
    for drop in ("design_partner", "co_sell"):
        bad = {"partnership_playbook": [dict(p, kind="distribution") if p["kind"] == drop else p
                                        for p in plan["partnership_playbook"]]}
        with pytest.raises(ValidationError, match=drop):
            PartnershipPlan.model_validate(bad)


def test_e2e_20_prompt_all_import_all(env, tmp_path):
    """E2E-20: $0 path for the whole portfolio - 8 prompts out, replies in (one missing, one malformed)."""
    d = tmp_path / "prompts"
    assert "wrote 8 prompts" in cli(env, "prompt", "all", "--out", str(d)).stdout
    assert len(list(d.glob("*.prompt.txt"))) == 8
    assert "weddingos.jodibana.com" in (d / "weddingos.prompt.txt").read_text(encoding="utf-8")
    for p in load_properties():
        if p.id == "jodibana":
            continue                                             # reply not back yet
        body = _chat_reply(p.id, repaired=True)
        if p.id == "jodiusa":
            body = body.replace('"design_partner"', '"distribution"')  # a reply missing the design partner
        (d / f"{p.id}.json").write_text(body, encoding="utf-8")
    r = cli(env, "import", "all", str(d)).stdout
    assert r.count("imported ") == 6 and "FAILED jodiusa" in r and "design_partner" in r
    assert "no reply yet for: jodibana" in r
    assert "status=partial" in cli(env, "status").stdout


def test_e2e_21_claude_client_refuses_when_cap_is_zero(monkeypatch):
    """E2E-21: the real ClaudeLLM makes no API call at all when VANGUARD_MAX_COST_USD is unset (the $0 default)."""
    monkeypatch.delenv("VANGUARD_MAX_COST_USD", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = ClaudeLLM()
    fake = FakeAnthropic()
    llm.client = fake
    with pytest.raises(BudgetExceeded, match="paid API runs are off"):
        asyncio.run(llm.research("s", "PROPERTY_ID: oratoplus"))
    assert fake.calls == []


# ------------------------------------------------------------------ local models (Ollama / OpenAI-compatible)
from vanguard.providers import FallbackLLM, LocalLLM, LocalUnavailable  # noqa: E402

TITLE_TO_TOOL = {"MarketIntel": "submit_market_intel", "PartnershipPlan": "submit_partnership_plan",
                 "PartnerOutreachPlan": "submit_partner_outreach",
                 "CampaignPlan": "submit_campaign_plan", "TaskPlan": "submit_task_plan"}


class FakeOllama:
    """Ollama /api/tags + /api/chat (and OpenAI-compatible /v1/models + /v1/chat/completions)."""

    def __init__(self, models=("qwen3.6:27b",), down=False, invalid_first=0, always_invalid=False):
        import httpx
        self.httpx = httpx
        self.models, self.down = list(models), down
        self.invalid_left, self.always_invalid = invalid_first, always_invalid
        self.chats: list[dict] = []
        self.in_flight = self.max_in_flight = 0

    def transport(self):
        return self.httpx.MockTransport(self.handle)

    async def handle(self, req):
        httpx = self.httpx
        if self.down:
            raise httpx.ConnectError("connection refused")
        path = req.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        body = json.loads(req.content)
        self.chats.append(body)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.001)
        self.in_flight -= 1
        schema = body.get("format") or body["response_format"]["json_schema"]["schema"]
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        pid = next(l.split(":", 1)[1].strip() for l in user.splitlines() if l.startswith("PROPERTY_ID:"))
        data = mock_fixtures.build(TITLE_TO_TOOL[schema["title"]], pid, repaired="LINT VIOLATIONS" in user)
        if self.always_invalid or self.invalid_left > 0:
            self.invalid_left -= 1
            content = "<think>hmm</think>Sure! {\"not\": \"valid\"}"
        else:  # reasoning block + code fence around the JSON, as local models often produce
            content = "<think>planning...</think>\n```json\n" + json.dumps(data) + "\n```"
        if path == "/api/chat":
            return httpx.Response(200, json={"message": {"role": "assistant", "content": content},
                                             "prompt_eval_count": 900, "eval_count": 700})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 700}})


def _local(fake: FakeOllama, api="ollama") -> LocalLLM:
    url = "http://localhost:11434" if api == "ollama" else "http://localhost:1234/v1"
    return LocalLLM(model="qwen3.6:27b", base_url=url, api=api, transport=fake.transport())


def _store(tag: str) -> Store:
    return Store(Path(os.environ.get("TMPDIR", "/tmp")) / f"{tag}-{time.time_ns()}.db")


def test_e2e_22_local_model_runs_whole_portfolio_at_zero_cost(monkeypatch):
    """E2E-22: all 8 pipelines on a local model; $0 metered; calls queue one at a time on the GPU."""
    monkeypatch.delenv("VANGUARD_MAX_COST_USD", raising=False)
    fake = FakeOllama()
    llm = FallbackLLM(_local(fake), backup_factory=lambda: pytest.fail("Claude must not be built"))
    store = _store("e2e22")
    rid = asyncio.run(run_portfolio(llm, load_properties(), store, concurrency=8))
    run = store.run(rid)
    assert run["status"] == "completed" and len(store.playbooks(rid)) == 8
    u = run["usage"]
    assert u["provider"] == "local" and u["cost_usd"] == 0.0 and u["fallback_calls"] == 0
    assert u["local_calls"] == len(fake.chats) == 8 * 5 + 5          # 5 engine calls (1,2,2B,3,4) + 5 lint repairs
    assert fake.max_in_flight == 1                                      # VANGUARD_LOCAL_CONCURRENCY default
    assert all(c["format"]["title"] in TITLE_TO_TOOL and c["options"]["num_ctx"] == 32768 for c in fake.chats)


def test_e2e_23_local_invalid_output_is_retried():
    """E2E-23: a reply that fails validation is sent back with the error; <think> blocks and code fences are
    stripped from the good reply."""
    fake = FakeOllama(invalid_first=1)
    from vanguard.schema import MarketIntel
    out = asyncio.run(_local(fake).structured("sys", "PROPERTY_ID: atmakosh\nx", MarketIntel, "submit_market_intel"))
    assert out.unit_economics.required_active_units > 0 and len(fake.chats) == 2
    assert "failed validation" in fake.chats[1]["messages"][-1]["content"]


def test_e2e_24_local_down_and_fallback_off_spends_nothing(monkeypatch):
    """E2E-24: local server down, cap 0 -> properties fail with a clear message and Claude is never called."""
    monkeypatch.delenv("VANGUARD_MAX_COST_USD", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude_fake = FakeAnthropic()
    llm = FallbackLLM(_local(FakeOllama(down=True)), backup_factory=lambda: claude_with(claude_fake))
    store = _store("e2e24")
    rid = asyncio.run(run_portfolio(llm, get_properties(["oratoplus", "jodiusa"]), store))
    run = store.run(rid)
    assert run["status"] == "failed" and all("Claude fallback is OFF" in e for e in run["errors"].values())
    assert claude_fake.calls == [] and run["usage"]["cost_usd"] == 0.0


def test_e2e_25_fallback_to_claude_when_local_fails(monkeypatch):
    """E2E-25: cap > 0 and a key set -> calls the local model can't serve go to Claude, are metered and capped."""
    monkeypatch.setenv("VANGUARD_MAX_COST_USD", "5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude_fake = FakeAnthropic()
    llm = FallbackLLM(_local(FakeOllama(always_invalid=True)),
                      backup_factory=lambda: claude_with(claude_fake, budget=5.0, web_search=False))
    store = _store("e2e25")
    rid = asyncio.run(run_portfolio(llm, get_properties(["atmakosh"]), store))
    run = store.run(rid)
    assert run["status"] == "completed"
    u = run["usage"]
    assert u["provider"] == "local+claude" and u["fallback_calls"] == 5 + 1   # every engine call + 1 lint repair
    assert u["local_failures"] == u["fallback_calls"] and 0 < u["cost_usd"] < 5
    assert "claude-sonnet-5 (fallback)" in u["model"]


def test_e2e_26_openai_compatible_servers():
    """E2E-26: LM Studio / llama.cpp / vLLM mode sends an OpenAI-style request with a json_schema response_format."""
    fake = FakeOllama()
    llm = _local(fake, api="openai")
    assert asyncio.run(llm.check())[0]
    from vanguard.schema import PartnershipPlan
    plan = asyncio.run(llm.structured("s", "PROPERTY_ID: vireoka\nx", PartnershipPlan, "submit_partnership_plan"))
    assert {p.kind for p in plan.partnership_playbook} >= {"design_partner", "co_sell"}
    req = fake.chats[0]
    assert req["response_format"]["type"] == "json_schema" and req["messages"][0]["role"] == "system"


def test_e2e_27_model_not_pulled_gives_the_fix():
    """E2E-27: server up but model missing -> check() says exactly which `ollama pull` to run."""
    ok, msg = asyncio.run(_local(FakeOllama(models=("llama3.1:8b",))).check())
    assert not ok and "ollama pull qwen3.6:27b" in msg and "llama3.1:8b" in msg
    ok, msg = asyncio.run(_local(FakeOllama(down=True)).check())
    assert not ok and "not reachable" in msg


@pytest.mark.skipif(os.getenv("VANGUARD_LIVE_LOCAL") != "1", reason="set VANGUARD_LIVE_LOCAL=1 with Ollama running")
def test_e2e_live_03_real_local_model(tmp_path, monkeypatch):
    """E2E-L3: one property end to end on your real local model (Ollama or OpenAI-compatible). $0."""
    monkeypatch.setattr("vanguard.orchestrator.OUTPUT_DIR", tmp_path)
    monkeypatch.delenv("VANGUARD_MAX_COST_USD", raising=False)   # no Claude fallback: prove local alone works
    llm = FallbackLLM(LocalLLM())
    ok, msg = asyncio.run(llm.primary.check())
    assert ok, msg
    store = Store(tmp_path / "live-local.db")
    rid = asyncio.run(run_portfolio(llm, get_properties(["oratoplus"]), store))
    run = store.run(rid)
    assert run["status"] == "completed", run["errors"]
    assert run["usage"]["cost_usd"] == 0.0
    print("local run:", run["usage"], "lint:", store.playbook(rid, "oratoplus").lint_status)


def test_e2e_28_runs_on_a_non_utf8_windows_style_locale(tmp_path):
    """E2E-28: with a non-UTF-8 default encoding (like Windows cp1252), config files load, demo data, partner
    recommendations and a dry run all work, and no source file reads or writes text without encoding="utf-8"."""
    import re as _re
    for f in (ROOT / "vanguard").rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if _re.search(r"\.(read_text|write_text)\(", line) or _re.search(r"\.open\(\"[wra]", line):
                assert "encoding=" in line, f"{f.name}:{n} needs encoding=\"utf-8\": {line.strip()}"
    env = {k: v for k, v in os.environ.items() if k not in ("LANG", "LC_ALL", "LC_CTYPE", "PYTHONUTF8", "PYTHONIOENCODING")}
    env |= {"LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0", "PYTHONPATH": str(ROOT),
            "VANGUARD_DB": str(tmp_path / "v.db"), "VANGUARD_OUTPUT": str(tmp_path / "out")}
    for args in (["demo-data"], ["partners", "recommend", "jodibana"], ["run", "--dry-run", "--properties", "oratoplus"],
                 ["outreach", "status"]):
        r = subprocess.run([sys.executable, "-m", "vanguard", *args], cwd=ROOT, env=env, capture_output=True)
        assert r.returncode == 0, (args, r.stderr.decode("utf-8", "replace")[-800:])


# ------------------------------------------------------------------ fail-proof layer
def test_e2e_failproof_cli_flow(env):
    """E2E-29: record readings, set gates and print the tracker from the CLI; 3 tripped tripwires exit 2 (HALT)."""
    cli(env, "record", "liqmint-institutional", "TW-3", "8", "--date", "2026-10-15", "--by", "test")
    out = cli(env, "tripwires", "--property", "liqmint-institutional", "--as-of", "2026-10-16").stdout
    assert "| TW-3 |" in out and "GREEN" in out and "G1 Buyer reality" in out
    assert cli(env, "gate", "liqmint-institutional", "G2", "pass", check=False).returncode != 0  # --by required
    cli(env, "gate", "liqmint-institutional", "G2", "pass", "--by", "Narendra")
    r = cli(env, "gate", "liqmint-institutional", "G1", "fail", "--by", "Narendra")
    assert "WALK-AWAY CONDITION" in r.stdout
    # readings count toward a check only if dated on or before that check's Friday
    for tw, v, d in (("TW-3", 4, "2026-10-16"), ("TW-6", 0, "2026-10-16"), ("TW-5", 0, "2026-10-22")):
        cli(env, "record", "liqmint-institutional", tw, str(v), "--date", d)
    r = cli(env, "tripwires", "--property", "liqmint-institutional", "--as-of", "2026-10-23", check=False)
    assert r.returncode == 2 and "HALT" in r.stdout
    data = json.loads(cli(env, "tripwires", "--json", "--as-of", "2026-10-23", check=False).stdout)
    assert {p["property_id"] for p in data["properties"]} == {p.id for p in load_properties()}
    assert cli(env, "record", "liqmint-institutional", "TW-99", "1", check=False).returncode != 0


def test_e2e_run_drops_gate_blocked_tasks(env, tmp_path, monkeypatch):
    """E2E-30: a run whose task plan includes investor outreach loses those tasks while gates are open, with a
    GATE_BLOCKED note, and delegated properties with no owner carry a FOCUS_LOCK note."""
    real = mock_fixtures.tasks

    def with_investor_task(pid):
        d = real(pid)
        d["daily_task_registry"][4]["description"] = "Email 20 seed investors the pitch deck"
        return d

    monkeypatch.setattr(mock_fixtures, "tasks", with_investor_task)
    from vanguard.failproof import load_failproof
    unowned = load_failproof()
    unowned.properties["weddingos"].owner = None
    monkeypatch.setattr("vanguard.orchestrator.load_failproof", lambda **_: unowned)
    from vanguard.llm import MockLLM
    store = Store(tmp_path / "v.db")
    rid = asyncio.run(run_portfolio(MockLLM(), get_properties(["liqmint-institutional", "weddingos"]), store))
    pb = store.playbook(rid, "liqmint-institutional")
    ids = [t.task_id for t in pb.daily_task_registry]
    assert "LQI-005" not in ids and "LQI-006" in ids
    assert "LQI-005" not in next(t for t in pb.daily_task_registry if t.task_id == "LQI-006").dependencies
    assert any(n.startswith("GATE_BLOCKED: LQI-005") for n in pb.notes)
    assert any(n.startswith("FOCUS_LOCK") for n in store.playbook(rid, "weddingos").notes)


def test_e2e_premortem_dry_run(env, tmp_path):
    """E2E-31: `vanguard premortem --dry-run` writes a 7-cause autopsy with verdict, adversary and tripwires, $0."""
    out = tmp_path / "pm.md"
    plan = tmp_path / "plan.md"
    plan.write_text("Raise $3M from stablecoin VCs via LinkedIn in 6 months.", encoding="utf-8")
    cli(env, "premortem", "liqmint-institutional", "--dry-run", "--plan", str(plan), "--out", str(out))
    md = out.read_text(encoding="utf-8")
    assert md.count("### #") == 7 and "## Verdict" in md and "## Adversary" in md and "## Tripwires" in md
