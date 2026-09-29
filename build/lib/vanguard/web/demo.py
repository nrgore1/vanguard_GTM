"""Clearly-labelled demo data so the UI can be explored before real campaigns exist.

Everything created here is named "[DEMO] ..." or belongs to a run id starting with "demo-", and
`vanguard demo-data --purge` removes all of it. The figures are synthetic and must never be reported.
"""
from __future__ import annotations

import asyncio
import random
from datetime import date, timedelta

from ..llm import MockLLM
from ..orchestrator import new_run_id, run_portfolio
from ..registry import load_properties
from ..store import now
from .db import WebStore

STAGES = ["identified", "contacted", "in_conversation", "pilot", "signed"]


def load_demo(ws: WebStore) -> str:
    rng = random.Random(42)
    users = [u["id"] for u in ws.q("SELECT id FROM users WHERE active=1 ORDER BY id")] or [None]
    rid = "demo-" + new_run_id()
    asyncio.run(run_portfolio(MockLLM(), load_properties(), ws, run_id=rid))
    today, n_c, n_p, n_r = date.today(), 0, 0, 0
    for i, p in enumerate(load_properties()):
        acv = {"liqmint": 240, "liqmint-institutional": 175_000, "vireoka": 90_000, "weddingos": 600,
               "jodibana": 240, "jodiusa": 300, "oratoplus": 300, "atmakosh": 12_000}.get(p.id, 1_000)
        enterprise = acv >= 10_000
        for kind, channel, label in (("email", "email", "outbound to tier-1 ICP"),
                                     ("social", p.channels[0] if p.channels else "linkedin", "organic content"),
                                     ("partner", "partner", "co-sell pilot")):
            status = rng.choice(["active", "active", "scheduled", "draft", "paused"])
            cid = ws.insert("campaigns", {
                "property_id": p.id, "name": f"[DEMO] {p.name} - {label}", "kind": kind, "channel": channel,
                "status": status, "start_date": (today - timedelta(days=56)).isoformat(),
                "end_date": (today + timedelta(days=30)).isoformat(), "budget_usd": rng.choice([0, 250, 500, 1000]),
                "goal_metric": "meetings" if p.track == "A" else "signups", "goal_value": rng.choice([20, 50, 200]),
                "description": "Synthetic demo campaign - delete with `vanguard demo-data --purge`.",
                "owner_id": users[(i + n_c) % len(users)], "source_run_id": rid, "created_by": users[0],
                "created_at": now(), "updated_at": now()})
            n_c += 1
            if status in ("active", "paused"):
                sent = rng.randint(80, 300)
                for w in range(8):
                    grow = 1 + w * 0.15
                    s_ = int(sent * grow) if kind == "email" else 0
                    conv = (1 if rng.random() < 0.12 else 0) if enterprise else rng.randint(0, 12)
                    ws.insert("campaign_results", {
                        "campaign_id": cid, "date": (today - timedelta(days=56 - 7 * w)).isoformat(),
                        "sent": s_, "opens": int(s_ * rng.uniform(.35, .55)), "clicks": int(s_ * rng.uniform(.03, .08)),
                        "replies": int(s_ * rng.uniform(.02, .06)), "meetings": rng.randint(0, 4),
                        "signups": 0 if enterprise else rng.randint(0, 25), "conversions": conv,
                        "revenue_usd": round(conv * acv / 12, 2),  # new MRR booked
                        "spend_usd": rng.choice([0, 25, 60]), "notes": "[DEMO]", "created_by": users[0],
                        "created_at": now()})
                    n_r += 1
        for kind, label in (("design_partner", "design-partner candidate"), ("co_sell", "co-selling partner"),
                            ("distribution", "distribution partner")):
            stage = rng.choice(STAGES)
            pid = ws.insert("partners", {
                "property_id": p.id, "name": f"[DEMO] {p.name} {label}", "kind": kind, "stage": stage,
                "partner_type": label, "contact_name": "Demo Contact", "value_sharing_model":
                {"design_partner": "none_yet", "co_sell": "revenue_share", "distribution": "co_marketing"}[kind],
                "mutual_value": "Synthetic demo partner.", "first_ask": "30-minute scoping call",
                "next_step": "Send one-page pilot scope", "next_step_date": (today + timedelta(days=rng.randint(1, 14))).isoformat(),
                "owner_id": users[n_p % len(users)], "source_run_id": rid, "created_by": users[0],
                "created_at": now(), "updated_at": now()})
            n_p += 1
            for k in range(STAGES.index(stage)):
                ws.insert("partner_interactions", {
                    "partner_id": pid, "date": (today - timedelta(days=40 - 9 * k)).isoformat(),
                    "type": ["email", "call", "meeting", "proposal"][k % 4],
                    "summary": f"[DEMO] {['Intro email', 'Discovery call', 'Scoping meeting', 'Pilot proposal'][k % 4]}",
                    "outcome": rng.choice(["positive", "neutral"]), "created_by": users[k % len(users)],
                    "created_at": now()})
    # partner outreach: expert recommendations for every property + a Jodibana walk-through (sent, replied, signed)
    from ..lint_gate import LintGate
    from ..partners import finalize, offline_plan
    gate = LintGate()
    for p in load_properties():
        for r in finalize(gate, p, offline_plan(p)):
            r = dict(r) | {"name": f"[DEMO] {r['name']}"}
            ws.upsert_recommendation(p.id, r, rid, users[0])
    seg = ws.one("SELECT id FROM partners WHERE property_id='jodibana' AND name LIKE '[DEMO] South Asian wedding planners%'")
    photo = ws.one("SELECT id FROM partners WHERE property_id='jodibana' AND name LIKE '[DEMO] Wedding photographers%'")
    demo_targets = [(seg["id"], "[DEMO] Example Planner Studio", "Asha Rao", "asha@example.com", "signed"),
                    (seg["id"], "[DEMO] Sample Events & Decor", "Vikram Das", "vikram@example.org", "replied"),
                    (photo["id"], "[DEMO] Placeholder Photo Co", "Neha Iyer", "neha@example.net", "sent"),
                    (photo["id"], "[DEMO] Test Frames Studio", "Rohan Mehta", "rohan@example.com", "approved")]
    for seg_id, name, contact, mail, state in demo_targets:
        tid = ws.add_target(seg_id, {"name": name, "contact_name": contact, "contact_email": mail}, users[0])
        ws.update("partners", "id", tid, {"source_run_id": rid})
        msgs = ws.q("SELECT id, step FROM outreach_messages WHERE partner_id=? ORDER BY step", (tid,))
        sent_at = (today - timedelta(days=12)).isoformat() + "T15:00:00+00:00"
        if state == "approved":
            for m in msgs:
                ws.update("outreach_messages", "id", m["id"], {"status": "approved", "approved_by": "Admin", "approved_at": now()})
            continue
        ws.update("outreach_messages", "id", msgs[0]["id"], {"status": "sent", "sent_at": sent_at, "approved_by": "Admin",
                                                             "to_email": mail, "message_id": f"<demo-{tid}@vanguard.local>"})
        ws.update("partners", "id", tid, {"stage": "contacted"})
        if state in ("replied", "signed"):
            from ..outreach import record_reply
            record_reply(ws, tid, "[DEMO] Sounds good - happy to talk about a referral arrangement next week.",
                         when=today - timedelta(days=9), actor=users[-1])
        if state == "signed":
            ws.update("partners", "id", tid, {"agreement_status": "signed", "stage": "signed",
                                              "agreement_signed_date": (today - timedelta(days=2)).isoformat(),
                                              "agreement_notes": "[DEMO] two-way referral, 12 months"})
    # spread the demo run's tasks across users and mark early ones done
    for t in ws.q("SELECT rowid AS id, day FROM tasks WHERE run_id=?", (rid,)):
        status = "Done" if t["day"] <= 6 else ("In progress" if t["day"] <= 10 else "Not started")
        ws.update("tasks", "rowid", t["id"], {"assignee_id": users[t["id"] % len(users)], "status": status})
    return f"loaded demo data: run {rid}, {n_c} campaigns, {n_r} weekly results, {n_p} partners (all marked [DEMO])"


def purge_demo(ws: WebStore) -> str:
    with ws.conn() as c:
        c.execute("PRAGMA foreign_keys=ON")
        n1 = c.execute("DELETE FROM campaigns WHERE name LIKE '[DEMO]%'").rowcount
        n2 = c.execute("DELETE FROM partners WHERE name LIKE '[DEMO]%' OR source_run_id LIKE 'demo-%'").rowcount
        for t in ("tasks", "playbooks", "runs"):
            c.execute(f"DELETE FROM {t} WHERE {'id' if t == 'runs' else 'run_id'} LIKE 'demo-%'")
    return f"removed {n1} demo campaigns and {n2} demo partners (with their results and interactions) and demo runs"
