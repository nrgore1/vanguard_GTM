"""Fail-proof layer: Engine 0 (forensic premortem), Engine 5 (readiness gates),
Engine 6 (tripwire monitor) and the focus lock.

The plan lives in config/failproof.yaml; the evidence (gate results, tripwire
readings, premortems) lives in the SQLite store. Nothing here sends, publishes or
spends: premortems use whatever LLM the caller passes (MockLLM for $0).
"""
from __future__ import annotations

import json
import operator
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .registry import CONFIG_DIR, Property, load_properties

_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
        "==": operator.eq, "!=": operator.ne}
_RULE = re.compile(r"^\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")

TripStatus = Literal["not_yet_due", "green", "amber", "tripped"]
GateStatus = Literal["open", "passed", "failed"]


# ---------------------------------------------------------------- config models
def parse_rule(rule: str) -> tuple[str, float]:
    m = _RULE.match(rule)
    if not m:
        raise ValueError(f"trips_if must look like '< 2' or '>= 0.5', got {rule!r}")
    return m.group(1), float(m.group(2))


class Check(BaseModel):
    week: int = Field(ge=1)
    trips_if: str

    @field_validator("trips_if")
    @classmethod
    def valid_rule(cls, v: str) -> str:
        parse_rule(v)
        return v


class Tripwire(BaseModel):
    id: str
    failure_mode: str
    signal: str
    unit: str = "count"
    checks: list[Check] = Field(default_factory=list)
    every_week_from: int | None = Field(default=None, ge=1, description="Recurring weekly check from this week")
    trips_if: str | None = Field(default=None, description="Rule for recurring checks")
    basis: Literal["premortem", "prd", "proposed"] = "proposed"
    action: str

    @model_validator(mode="after")
    def has_a_schedule(self):
        if self.every_week_from is None and not self.checks:
            raise ValueError(f"{self.id}: needs checks or every_week_from")
        if self.every_week_from is not None:
            if not self.trips_if:
                raise ValueError(f"{self.id}: recurring tripwires need trips_if")
            parse_rule(self.trips_if)
        return self


class FailureMode(BaseModel):
    id: str
    name: str
    cause: str
    assumption: str
    first_warning: str


class Gate(BaseModel):
    id: str
    name: str
    verify: str
    walk_away_if: str
    deadline_week: int = Field(ge=1)
    blocks: list[str] = Field(default_factory=list)


class PropertyFailproof(BaseModel):
    owner: str | None = None
    focus: Literal["primary", "founder", "delegated"]
    one_sentence: str
    failure_modes: list[FailureMode] = Field(min_length=1)
    gates: list[Gate] = Field(min_length=1)
    tripwires: list[Tripwire] = Field(min_length=1)

    @model_validator(mode="after")
    def references_resolve(self):
        fm = {f.id for f in self.failure_modes}
        bad = [t.id for t in self.tripwires if t.failure_mode not in fm]
        if bad:
            raise ValueError(f"tripwires point at unknown failure modes: {bad}")
        for kind, ids in (("gate", [g.id for g in self.gates]), ("tripwire", [t.id for t in self.tripwires])):
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {kind} ids: {ids}")
        return self


class Program(BaseModel):
    start: date
    weeks: int = Field(default=26, ge=1)
    meta_tripwire: dict = Field(default_factory=lambda: {"week": 10, "max_tripped": 3})

    @field_validator("start")
    @classmethod
    def monday(cls, v: date) -> date:
        if v.weekday() != 0:
            raise ValueError("program.start must be a Monday (week 1 starts on it)")
        return v


class Focus(BaseModel):
    founder: list[str]
    primary: str
    founder_name: str = ""


class FailproofConfig(BaseModel):
    program: Program
    focus: Focus
    task_classes: dict[str, str]
    properties: dict[str, PropertyFailproof]

    @model_validator(mode="after")
    def consistent(self):
        for pid, pf in self.properties.items():
            for g in pf.gates:
                unknown = [b for b in g.blocks if b not in self.task_classes]
                if unknown:
                    raise ValueError(f"{pid} {g.id}: unknown task class {unknown}")
            for t in pf.tripwires:
                weeks = [c.week for c in t.checks] + ([t.every_week_from] if t.every_week_from else [])
                if any(w > self.program.weeks for w in weeks):
                    raise ValueError(f"{pid} {t.id}: check week past program.weeks")
            if pid in self.focus.founder and pf.focus == "delegated":
                raise ValueError(f"{pid} is on the founder's list but marked delegated")
        if self.focus.primary not in self.focus.founder:
            raise ValueError("focus.primary must be one of focus.founder")
        return self

    def compiled_classes(self) -> dict[str, re.Pattern]:
        return {k: re.compile(v, re.I) for k, v in self.task_classes.items()}


def load_failproof(path: Path | None = None, registry: list[Property] | None = None) -> FailproofConfig:
    cfg = FailproofConfig.model_validate(
        yaml.safe_load((path or CONFIG_DIR / "failproof.yaml").read_text(encoding="utf-8")))
    reg_ids = {p.id for p in (registry if registry is not None else load_properties())}
    missing, extra = reg_ids - set(cfg.properties), set(cfg.properties) - reg_ids
    if missing or extra:
        raise ValueError(f"failproof.yaml must cover every registry property: missing {sorted(missing)}, "
                         f"unknown {sorted(extra)}")
    return cfg


# ---------------------------------------------------------------- calendar
def week_friday(program: Program, week: int) -> date:
    return program.start + timedelta(days=7 * (week - 1) + 4)


def week_of(program: Program, d: date) -> int:
    return (d - program.start).days // 7 + 1


def today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------- store
DDL = """
CREATE TABLE IF NOT EXISTS tripwire_readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, property_id TEXT, tripwire_id TEXT, value REAL,
  reading_date TEXT, note TEXT DEFAULT '', recorded_by TEXT DEFAULT '', recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS gate_status (
  property_id TEXT, gate_id TEXT, status TEXT, note TEXT DEFAULT '', updated_by TEXT DEFAULT '',
  updated_at TEXT, PRIMARY KEY (property_id, gate_id)
);
CREATE TABLE IF NOT EXISTS premortems (
  id INTEGER PRIMARY KEY AUTOINCREMENT, property_id TEXT, created_at TEXT, plan TEXT, body TEXT
);
"""


class FailproofStore:
    """Thin layer over the main Store's SQLite file."""

    def __init__(self, store):
        self.store = store
        with store.conn() as c:
            c.executescript(DDL)

    def record(self, property_id: str, tripwire_id: str, value: float, reading_date: date,
               note: str = "", by: str = "") -> None:
        with self.store.conn() as c:
            c.execute("INSERT INTO tripwire_readings(property_id, tripwire_id, value, reading_date, note, recorded_by, "
                      "recorded_at) VALUES (?,?,?,?,?,?,?)",
                      (property_id, tripwire_id, float(value), reading_date.isoformat(), note, by,
                       datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def readings(self, property_id: str, tripwire_id: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM tripwire_readings WHERE property_id=?", [property_id]
        if tripwire_id:
            q += " AND tripwire_id=?"
            args.append(tripwire_id)
        with self.store.conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY reading_date, id", args).fetchall()]

    def set_gate(self, property_id: str, gate_id: str, status: GateStatus, note: str = "", by: str = "") -> None:
        with self.store.conn() as c:
            c.execute("INSERT OR REPLACE INTO gate_status(property_id, gate_id, status, note, updated_by, updated_at) "
                      "VALUES (?,?,?,?,?,?)", (property_id, gate_id, status, note, by,
                                                datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def gates(self, property_id: str) -> dict[str, dict]:
        with self.store.conn() as c:
            rows = c.execute("SELECT * FROM gate_status WHERE property_id=?", (property_id,)).fetchall()
        return {r["gate_id"]: dict(r) for r in rows}

    def save_premortem(self, property_id: str, plan: str, body: dict) -> int:
        with self.store.conn() as c:
            cur = c.execute("INSERT INTO premortems(property_id, created_at, plan, body) VALUES (?,?,?,?)",
                            (property_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), plan,
                             json.dumps(body)))
            return cur.lastrowid

    def latest_premortem(self, property_id: str) -> dict | None:
        with self.store.conn() as c:
            r = c.execute("SELECT * FROM premortems WHERE property_id=? ORDER BY id DESC LIMIT 1",
                          (property_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["body"] = json.loads(d["body"])
        return d


# ---------------------------------------------------------------- Engine 6: tripwires
def _latest(readings: list[dict], on_or_before: date, not_before: date | None = None) -> dict | None:
    pick = None
    for r in readings:
        d = date.fromisoformat(r["reading_date"])
        if d <= on_or_before and (not_before is None or d >= not_before):
            pick = r
    return pick


def evaluate_tripwire(tw: Tripwire, program: Program, readings: list[dict], as_of: date) -> dict:
    """Status of one tripwire as of a date.

    tripped     - any due check's reading breaks its rule
    amber       - a due check has no reading (missing evidence is never green)
    green       - every due check has a reading inside its rule
    not_yet_due - no check has come due
    """
    due: list[dict] = []
    schedule: list[tuple[int, str, bool]] = [(c.week, c.trips_if, False) for c in tw.checks]
    if tw.every_week_from:
        schedule += [(w, tw.trips_if, True) for w in range(tw.every_week_from, program.weeks + 1)]
    for week, rule, recurring in sorted(schedule):
        friday = week_friday(program, week)
        if friday > as_of:
            continue
        window_start = friday - timedelta(days=6) if recurring else None
        r = _latest(readings, friday, window_start)
        op, thr = parse_rule(rule)
        if r is None:
            due.append({"week": week, "date": friday.isoformat(), "rule": rule, "value": None, "result": "missing"})
        else:
            hit = _OPS[op](r["value"], thr)
            due.append({"week": week, "date": friday.isoformat(), "rule": rule, "value": r["value"],
                        "result": "tripped" if hit else "ok"})
    upcoming = [w for w, _, _ in sorted(schedule) if week_friday(program, w) > as_of]
    if not due:
        status: TripStatus = "not_yet_due"
    elif any(d["result"] == "tripped" for d in due):
        status = "tripped"
    elif any(d["result"] == "missing" for d in due):
        status = "amber"
    else:
        status = "green"
    latest = readings[-1] if readings else None
    return {
        "id": tw.id, "failure_mode": tw.failure_mode, "signal": tw.signal, "unit": tw.unit, "basis": tw.basis,
        "action": tw.action, "status": status,
        "latest_value": latest["value"] if latest else None,
        "latest_date": latest["reading_date"] if latest else None,
        "next_check": week_friday(program, upcoming[0]).isoformat() if upcoming else None,
        "next_check_week": upcoming[0] if upcoming else None,
        "schedule": _schedule_text(tw),
        "due_checks": due[-6:],   # recent history is enough for the tracker
    }


def _schedule_text(tw: Tripwire) -> str:
    parts = [f"W{c.week}: trips if {c.trips_if}" for c in tw.checks]
    if tw.every_week_from:
        parts.append(f"every Friday from W{tw.every_week_from}: trips if {tw.trips_if}")
    return "; ".join(parts)


# ---------------------------------------------------------------- Engine 5: gates
def gate_report(cfg: FailproofConfig, property_id: str, fstore: FailproofStore, as_of: date) -> list[dict]:
    pf = cfg.properties[property_id]
    stored = fstore.gates(property_id)
    out = []
    for g in pf.gates:
        s = stored.get(g.id, {})
        status = s.get("status", "open")
        deadline = week_friday(cfg.program, g.deadline_week)
        out.append({"id": g.id, "name": g.name, "verify": g.verify, "walk_away_if": g.walk_away_if,
                    "deadline": deadline.isoformat(), "deadline_week": g.deadline_week, "blocks": g.blocks,
                    "status": status, "overdue": status == "open" and deadline < as_of,
                    "note": s.get("note", ""), "updated_by": s.get("updated_by", "")})
    return out


def blocked_classes(cfg: FailproofConfig, property_id: str, fstore: FailproofStore) -> dict[str, list[str]]:
    """Task class -> ids of the open (or failed) gates that block it."""
    stored = fstore.gates(property_id)
    out: dict[str, list[str]] = {}
    for g in cfg.properties[property_id].gates:
        if stored.get(g.id, {}).get("status") != "passed":
            for cls in g.blocks:
                out.setdefault(cls, []).append(g.id)
    return out


def classify_task(text: str, cfg: FailproofConfig) -> list[str]:
    return [name for name, pat in cfg.compiled_classes().items() if pat.search(text)]


# ---------------------------------------------------------------- focus lock
def focus_issues(cfg: FailproofConfig, property_id: str) -> list[str]:
    pf = cfg.properties[property_id]
    issues = []
    if pf.focus == "delegated" and not (pf.owner or "").strip():
        issues.append("FOCUS_LOCK: delegated property has no named owner - assign one in config/failproof.yaml")
    if pf.focus == "delegated" and cfg.focus.founder_name and pf.owner == cfg.focus.founder_name:
        issues.append("FOCUS_LOCK: delegated property is owned by the founder - hand it to a delegate")
    return issues


# ---------------------------------------------------------------- applied to a playbook
def apply_to_playbook(pb, cfg: FailproofConfig, fstore: FailproofStore) -> list[str]:
    """Remove tasks that an open gate blocks, fix their dependants, and add notes. Returns the removed ids."""
    blocked = blocked_classes(cfg, pb.property_id, fstore)
    removed: list[str] = []
    kept = []
    for t in pb.daily_task_registry:
        hits = [c for c in classify_task(f"{t.description} {t.kpi}", cfg) if c in blocked]
        if hits:
            removed.append(t.task_id)
            gates = sorted({g for c in hits for g in blocked[c]})
            pb.notes.append(f"GATE_BLOCKED: {t.task_id} removed ({', '.join(hits)} blocked by open gates {', '.join(gates)})")
        else:
            kept.append(t)
    for t in kept:
        t.dependencies = [d for d in t.dependencies if d not in removed]
    pb.daily_task_registry = kept
    pb.notes.extend(focus_issues(cfg, pb.property_id))
    return removed


# ---------------------------------------------------------------- tracker
def tracker(cfg: FailproofConfig, fstore: FailproofStore, as_of: date | None = None,
            property_ids: list[str] | None = None) -> dict:
    as_of = as_of or today()
    props = []
    for pid, pf in cfg.properties.items():
        if property_ids and pid not in property_ids:
            continue
        tws = [evaluate_tripwire(t, cfg.program, fstore.readings(pid, t.id), as_of) for t in pf.tripwires]
        gates = gate_report(cfg, pid, fstore, as_of)
        tripped = sum(1 for t in tws if t["status"] == "tripped")
        halt = tripped >= int(cfg.program.meta_tripwire["max_tripped"])
        props.append({
            "property_id": pid, "owner": pf.owner, "focus": pf.focus, "one_sentence": pf.one_sentence,
            "tripwires": tws, "gates": gates, "tripped": tripped,
            "amber": sum(1 for t in tws if t["status"] == "amber"),
            "gates_passed": sum(1 for g in gates if g["status"] == "passed"),
            "gates_overdue": sum(1 for g in gates if g["overdue"]),
            "halt": halt, "focus_issues": focus_issues(cfg, pid),
            "blocked_classes": blocked_classes(cfg, pid, fstore),
            "failure_modes": [f.model_dump() for f in pf.failure_modes],
        })
    return {"as_of": as_of.isoformat(), "week": week_of(cfg.program, as_of),
            "program_start": cfg.program.start.isoformat(), "properties": props}


_ICON = {"not_yet_due": "not yet due", "green": "GREEN", "amber": "AMBER", "tripped": "TRIPPED"}


def tracker_markdown(t: dict) -> str:
    lines = [f"# Tripwire tracker - as of {t['as_of']} (week {t['week']})", ""]
    for p in t["properties"]:
        head = f"## {p['property_id']} - owner: {p['owner'] or 'UNASSIGNED'} ({p['focus']})"
        lines += [head, "", f"> {p['one_sentence']}", ""]
        if p["halt"]:
            lines += ["**HALT: 3 or more tripwires tripped - stop and rerun the walk-away gates.**", ""]
        for issue in p["focus_issues"]:
            lines.append(f"- {issue}")
        lines += ["| ID | Signal | Schedule | Latest | Next check | Status | Action if tripped |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for w in p["tripwires"]:
            latest = "-" if w["latest_value"] is None else f"{w['latest_value']:g} {w['unit']} ({w['latest_date']})"
            lines.append(f"| {w['id']} | {w['signal']} | {w['schedule']} | {latest} | {w['next_check'] or '-'} | "
                         f"{_ICON[w['status']]} | {w['action']} |")
        lines += ["", "| Gate | Verify | Deadline | Status | Walk away if |", "| --- | --- | --- | --- | --- |"]
        for g in p["gates"]:
            st = g["status"].upper() + (" (OVERDUE)" if g["overdue"] else "")
            lines.append(f"| {g['id']} {g['name']} | {g['verify']} | W{g['deadline_week']} {g['deadline']} | {st} | "
                         f"{g['walk_away_if']} |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- Engine 0: premortem
class CauseOfDeath(BaseModel):
    rank: int = Field(ge=1, le=7)
    name: str
    what_killed_it: str
    month_by_month: list[str] = Field(min_length=3, max_length=7)
    enabling_assumption: str
    first_warning_sign: str
    traces_to: str = Field(description="The stated fact from the plan or registry this cause traces back to")


class Verdict(BaseModel):
    most_likely: str
    most_dangerous: str
    why_they_differ: str
    hidden_assumption: str
    fatal_flaw: bool
    fatal_flaw_statement: str = ""


class Adversary(BaseModel):
    who: str
    attack_points: list[str] = Field(min_length=2)
    launch_week_moves: list[str] = Field(min_length=1)
    unseen_move: str


class ProposedTripwire(BaseModel):
    cause_rank: int = Field(ge=1, le=7)
    signal: str
    check_week: int = Field(ge=1)
    trips_if: str

    @field_validator("trips_if")
    @classmethod
    def valid_rule(cls, v: str) -> str:
        parse_rule(v)
        return v


class Premortem(BaseModel):
    horizon_months: int = Field(default=6, ge=1, le=24)
    causes: list[CauseOfDeath] = Field(min_length=7, max_length=7)
    verdict: Verdict
    adversary: Adversary
    tripwires: list[ProposedTripwire] = Field(min_length=7)

    @field_validator("causes")
    @classmethod
    def ranked(cls, v: list[CauseOfDeath]):
        if sorted(c.rank for c in v) != list(range(1, 8)):
            raise ValueError("causes must be ranked 1..7")
        return sorted(v, key=lambda c: c.rank)


PREMORTEM_SYSTEM = """You are Vanguard-GTM acting as a forensic failure analyst (Engine 0).
Assume the plan below was executed and FAILED COMPLETELY at the horizon. Write the autopsy.
Rules:
- Exactly 7 causes of death, ranked by likelihood. For each: what killed it, how it unfolded month by month,
  the assumption that allowed it, the first warning sign, and traces_to = the specific stated fact it comes from.
- Every cause traces to a detail in the plan or the property facts. No generic advice. Never reassure.
- Verdict: name the most likely and the most dangerous cause and why they differ; name the hidden assumption
  the owner does not realise is an assumption; set fatal_flaw true and say so plainly if the plan cannot work as written.
- Adversary: the party who gains most from failure - where they attack, what they do launch week, the unseen move.
- One tripwire per cause: a measurable signal, the week to check it, and a numeric rule such as "< 2".
"""


def premortem_prompt(p: Property, pf: PropertyFailproof, plan: str) -> str:
    known = "\n".join(f"- {f.id} {f.name}: {f.cause} (assumption: {f.assumption})" for f in pf.failure_modes)
    return (f"PROPERTY_ID: {p.id}\nENGINE: 0 - Forensic Premortem\n\n{p.brief()}\n\n"
            f"ONE SENTENCE: {pf.one_sentence}\nOWNER: {pf.owner or 'UNASSIGNED'} ({pf.focus})\n\n"
            f"FAILURE MODES ALREADY ON FILE (confirm, re-rank or replace):\n{known}\n\n"
            f"THE PLAN BEING TESTED:\n{plan.strip() or '(no plan text given - test the property registry entry)'}\n")


def offline_premortem(pf: PropertyFailproof) -> dict:
    """A $0 premortem assembled from the failure modes on file (used by --dry-run and tests)."""
    fms = (pf.failure_modes * 7)[:7]
    causes = []
    for i, f in enumerate(fms, 1):
        causes.append({"rank": i, "name": f.name, "what_killed_it": f.cause,
                       "month_by_month": [f"Month 1: {f.first_warning}", "Months 2-4: the pattern repeats unchecked",
                                          "Months 5-6: the failure becomes visible to buyers and investors"],
                       "enabling_assumption": f.assumption, "first_warning_sign": f.first_warning,
                       "traces_to": f"failproof.yaml {f.id}"})
    t_by_fm = {t.failure_mode: t for t in pf.tripwires}
    tws = []
    for c, f in zip(causes, fms):
        t = t_by_fm.get(f.id) or pf.tripwires[0]
        week = t.checks[0].week if t.checks else t.every_week_from
        rule = t.checks[0].trips_if if t.checks else t.trips_if
        tws.append({"cause_rank": c["rank"], "signal": t.signal, "check_week": week, "trips_if": rule})
    first, worst = pf.failure_modes[0], pf.failure_modes[-1]
    return {
        "horizon_months": 6, "causes": causes,
        "verdict": {"most_likely": first.name, "most_dangerous": worst.name,
                    "why_they_differ": "[offline] The likely failure stalls the plan; the dangerous one damages the "
                                       "company beyond the plan. Run a live premortem for the full reasoning.",
                    "hidden_assumption": first.assumption, "fatal_flaw": False,
                    "fatal_flaw_statement": ""},
        "adversary": {"who": "[offline] the competitor who wants the same first customers",
                      "attack_points": [f.name for f in pf.failure_modes[:2]],
                      "launch_week_moves": ["[offline] reach the same design partners first"],
                      "unseen_move": "[offline] run a live premortem to generate this"},
        "tripwires": tws,
    }


async def run_premortem(llm, p: Property, pf: PropertyFailproof, plan: str = "") -> Premortem:
    from .llm import MockLLM
    if isinstance(llm, MockLLM):
        llm.calls.append("submit_premortem")
        return Premortem.model_validate(offline_premortem(pf))
    return await llm.structured(PREMORTEM_SYSTEM, premortem_prompt(p, pf, plan), Premortem, "submit_premortem")


def premortem_markdown(property_id: str, pm: Premortem) -> str:
    lines = [f"# Premortem - {property_id} (failed at {pm.horizon_months} months)", "", "## Causes of death, ranked", ""]
    for c in pm.causes:
        lines += [f"### #{c.rank} {c.name}", "", f"**What killed it.** {c.what_killed_it}", ""]
        lines += [f"- {m}" for m in c.month_by_month]
        lines += ["", f"**Assumption that allowed it.** {c.enabling_assumption}",
                  f"**First warning sign.** {c.first_warning_sign}", f"*Traces to: {c.traces_to}*", ""]
    v = pm.verdict
    lines += ["## Verdict", "", f"- **Most likely:** {v.most_likely}", f"- **Most dangerous:** {v.most_dangerous}",
              f"- **Why they differ:** {v.why_they_differ}", f"- **Hidden assumption:** {v.hidden_assumption}",
              f"- **Fatal flaw:** {'YES - ' + v.fatal_flaw_statement if v.fatal_flaw else 'none named'}", "",
              "## Adversary", "", f"**Who:** {pm.adversary.who}", ""]
    lines += [f"- Attack: {a}" for a in pm.adversary.attack_points]
    lines += [f"- Launch week: {m}" for m in pm.adversary.launch_week_moves]
    lines += [f"- Unseen move: {pm.adversary.unseen_move}", "", "## Tripwires", "",
              "| Cause | Signal | Check week | Trips if |", "| --- | --- | --- | --- |"]
    lines += [f"| #{t.cause_rank} | {t.signal} | W{t.check_week} | {t.trips_if} |" for t in pm.tripwires]
    return "\n".join(lines) + "\n"
