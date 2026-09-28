"""Unit tests for the fail-proof layer (config, tripwire maths, gate enforcement, focus lock, premortem)."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
import yaml

from vanguard.failproof import (FailproofConfig, FailproofStore, Tripwire, apply_to_playbook, classify_task,
                                evaluate_tripwire, focus_issues, load_failproof, parse_rule, run_premortem,
                                tracker, week_friday, week_of)
from vanguard.llm import MockLLM
from vanguard.registry import CONFIG_DIR, get_properties
from vanguard.schema import Task
from vanguard.store import Store


@pytest.fixture
def cfg():
    return load_failproof()


@pytest.fixture
def fs(tmp_path):
    return FailproofStore(Store(tmp_path / "v.db"))


def test_config_covers_every_property_and_founder_focus(cfg):
    assert set(cfg.properties) == {p.id for p in get_properties(["all"])}
    assert cfg.focus.primary == "liqmint-institutional"
    assert {cfg.properties[p].focus for p in cfg.focus.founder} <= {"primary", "founder"}
    # the institutional premortem is the full seven causes
    assert len(cfg.properties["liqmint-institutional"].failure_modes) == 7


def test_program_calendar(cfg):
    assert cfg.program.start == date(2026, 9, 28)
    assert week_friday(cfg.program, 1) == date(2026, 10, 2)
    assert week_friday(cfg.program, 10) == date(2026, 12, 4)
    assert week_of(cfg.program, date(2026, 12, 4)) == 10


def test_rules_are_validated():
    assert parse_rule("< 2") == ("<", 2.0)
    assert parse_rule(">= 3.5") == (">=", 3.5)
    with pytest.raises(ValueError):
        parse_rule("fewer than two")
    with pytest.raises(ValueError):
        Tripwire(id="X", failure_mode="FM-1", signal="s", action="a")  # no schedule


def test_config_rejects_unknown_task_class_and_bad_start():
    raw = yaml.safe_load((CONFIG_DIR / "failproof.yaml").read_text(encoding="utf-8"))
    raw["properties"]["vireoka"]["gates"][0]["blocks"] = ["not_a_class"]
    with pytest.raises(ValueError, match="unknown task class"):
        FailproofConfig.model_validate(raw)
    raw = yaml.safe_load((CONFIG_DIR / "failproof.yaml").read_text(encoding="utf-8"))
    raw["program"]["start"] = "2026-09-29"  # a Tuesday
    with pytest.raises(ValueError, match="Monday"):
        FailproofConfig.model_validate(raw)


def test_tripwire_states(cfg):
    tw = next(t for t in cfg.properties["liqmint-institutional"].tripwires if t.id == "TW-1")  # W6 <1, W10 <2
    prog = cfg.program
    assert evaluate_tripwire(tw, prog, [], date(2026, 10, 30))["status"] == "not_yet_due"
    assert evaluate_tripwire(tw, prog, [], date(2026, 11, 6))["status"] == "amber"  # due, no evidence
    one = [{"value": 1, "reading_date": "2026-11-05"}]
    r = evaluate_tripwire(tw, prog, one, date(2026, 11, 6))
    assert r["status"] == "green" and r["next_check"] == "2026-12-04"
    assert evaluate_tripwire(tw, prog, one, date(2026, 12, 4))["status"] == "tripped"  # still 1 at W10
    two = one + [{"value": 2, "reading_date": "2026-12-03"}]
    assert evaluate_tripwire(tw, prog, two, date(2026, 12, 4))["status"] == "green"


def test_recurring_tripwire_needs_a_reading_each_week(cfg):
    tw = next(t for t in cfg.properties["liqmint-institutional"].tripwires if t.id == "TW-4")  # hours > 8
    prog = cfg.program
    rows = [{"value": 4, "reading_date": "2026-10-01"}]
    assert evaluate_tripwire(tw, prog, rows, date(2026, 10, 2))["status"] == "green"
    # week 2 has no reading of its own: the week-1 value does not carry over
    assert evaluate_tripwire(tw, prog, rows, date(2026, 10, 9))["status"] == "amber"
    rows.append({"value": 12, "reading_date": "2026-10-08"})
    assert evaluate_tripwire(tw, prog, rows, date(2026, 10, 9))["status"] == "tripped"


def _task(tid, desc, deps=()):
    return Task(day=1, task_id=tid, description=desc, category="Outreach", priority="P0", owner="Human",
                dependencies=list(deps), kpi="done")


def test_open_gates_remove_blocked_tasks(cfg, fs):
    from types import SimpleNamespace
    pb = SimpleNamespace(property_id="liqmint-institutional", notes=[], daily_task_registry=[
        _task("LQI-001", "Book Mirai governance walkthrough"),
        _task("LQI-002", "Send pitch deck to 20 seed investors"),
        _task("LQI-003", "Follow up on investor replies", ["LQI-002", "LQI-001"])])
    removed = apply_to_playbook(pb, cfg, fs)
    assert removed == ["LQI-002", "LQI-003"]
    assert [t.task_id for t in pb.daily_task_registry] == ["LQI-001"]
    assert any("GATE_BLOCKED: LQI-002" in n for n in pb.notes)
    # once every gate blocking investor outreach has passed, the same plan survives
    for g in ("G1", "G2", "G3", "G4", "G5"):
        fs.set_gate("liqmint-institutional", g, "passed", by="test")
    pb2 = SimpleNamespace(property_id="liqmint-institutional", notes=[], daily_task_registry=[
        _task("LQI-002", "Send pitch deck to 20 seed investors")])
    assert apply_to_playbook(pb2, cfg, fs) == []


def test_classifier_and_focus_lock(cfg):
    assert "investor_outreach" in classify_task("Email VC partners", cfg)
    assert "cold_investor_outreach" in classify_task("Send cold connection requests to VCs", cfg)
    assert "paid_acquisition" in classify_task("Launch paid social campaign on Instagram", cfg)
    assert classify_task("Record a demo of the evidence pack", cfg) == []
    assert focus_issues(cfg, "weddingos")          # delegated, no owner yet
    assert focus_issues(cfg, "liqmint-institutional") == []


def test_tracker_halts_at_three_tripped(cfg, fs):
    for tw, v, d in (("TW-3", 4, "2026-10-15"), ("TW-6", 0, "2026-10-15"), ("TW-5", 0, "2026-10-22")):
        fs.record("liqmint-institutional", tw, v, date.fromisoformat(d))
    t = tracker(cfg, fs, date(2026, 10, 23), ["liqmint-institutional"])
    p = t["properties"][0]
    assert p["tripped"] == 3 and p["halt"] and t["week"] == 4


def test_offline_premortem_is_complete(cfg):
    p = get_properties(["liqmint-institutional"])[0]
    pm = asyncio.run(run_premortem(MockLLM(), p, cfg.properties[p.id]))
    assert [c.rank for c in pm.causes] == list(range(1, 8))
    assert len(pm.tripwires) >= 7 and pm.verdict.most_likely == "No evidence to underwrite"
