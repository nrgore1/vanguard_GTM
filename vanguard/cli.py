"""vanguard - command line entry point."""
from __future__ import annotations

import argparse
import os
import asyncio
import json
import logging
import sys
from pathlib import Path

from .exporters import NotApproved, export_sequences, export_tasks
from .cost import estimate
from .llm import make_llm
from .orchestrator import OUTPUT_DIR, run_portfolio
from .registry import get_properties
from .store import Store


def _run_id(store: Store, given: str | None) -> str:
    rid = given or store.latest_run_id()
    if not rid:
        sys.exit("no runs yet - start one with `vanguard run`")
    return rid


def _preflight(a, llm, n_props: int) -> None:
    """Decide what this run may spend, tell the user, and stop early when it can't run for $0."""
    from .providers import FallbackLLM
    if isinstance(llm, FallbackLLM):
        ok, msg = asyncio.run(llm.primary.check())
        cap = float(os.getenv("VANGUARD_MAX_COST_USD", "0") or 0)
        fb = f"ON, capped at ${cap:.2f} - used only for calls the local model fails" if llm.backup_enabled else "OFF"
        print(f"Primary: local model {llm.primary.model} ($0) - {msg}\nClaude fallback: {fb}")
        if not ok and not llm.backup_enabled:
            sys.exit(f"Local model not ready and Claude fallback is off, so nothing was run or spent.\n  {msg}\n"
                     "  See docs/SETUP_NOTION_AND_KEYS.md Part 3 (install Ollama + pull a model), "
                     "or use `vanguard run --dry-run`.")
        if not ok:
            est = estimate(n_props, os.getenv("VANGUARD_MODEL", "claude-sonnet-5"), llm.web_search)
            print(f"Local model unavailable: every call will go to Claude (~${est['total_usd']:.2f}, cap ${cap:.2f}).")
        if llm.backup_enabled and not a.yes and input("Proceed? [y/N] ").strip().lower() != "y":
            sys.exit("cancelled")
        return
    est = estimate(n_props, llm.model, llm.web_search)
    cap = llm.meter.budget_usd or 0
    print(f"Provider: Claude only. Estimated cost: ~${est['total_usd']:.2f} on {llm.model} "
          f"(web research {'on' if llm.web_search else 'off'})")
    if cap <= 0:
        sys.exit("Paid API runs are OFF (VANGUARD_MAX_COST_USD=0), so nothing was spent.\n"
                 "  $0 options: VANGUARD_PROVIDER=local (a model on your machine), `vanguard run --dry-run`, or "
                 "`vanguard prompt all --out prompts/` + `vanguard import all prompts/`.\n"
                 "  To allow paid runs, set VANGUARD_MAX_COST_USD to a cap, e.g. 5.")
    print(f"Hard spend cap for this run: ${cap:.2f}")
    if not a.yes and input("Proceed? [y/N] ").strip().lower() != "y":
        sys.exit("cancelled")


def cmd_run(a, store: Store):
    props = get_properties(a.properties.split(","))
    llm = make_llm(a.dry_run, web_search=False if a.no_research else None, provider=a.provider)
    if not a.dry_run:
        _preflight(a, llm, len(props))
    print(f"Running {len(props)} properties in parallel (concurrency {a.concurrency or 'default'})"
          f"{' [DRY RUN - mock LLM, $0]' if a.dry_run else ''}")
    rid = asyncio.run(run_portfolio(llm, props, store, concurrency=a.concurrency))
    cmd_status(argparse.Namespace(run=rid), store)
    if a.sync:
        cmd_sync(argparse.Namespace(run=rid), store)


def cmd_status(a, store: Store):
    rid = _run_id(store, a.run)
    run = store.run(rid)
    u = run.get("usage") or {}
    print(f"\nRun {rid}  status={run['status']}  started={run['created_at']}  finished={run['finished_at']}")
    if u:
        print(f"Spend: ${u.get('cost_usd', 0):.2f}  model={u.get('model')}  calls={u.get('calls', 0)}  "
              f"tokens in/out={u.get('input_tokens', 0):,}/{u.get('output_tokens', 0):,}  searches={u.get('web_searches', 0)}"
              + (f"  local calls={u['local_calls']} fallbacks to Claude={u['fallback_calls']}" if "local_calls" in u else ""))
    print(f"{'property':24} {'lint':8} {'ACV':>12} {'units':>7} {'months':>7} {'tasks':>6}  approved  notes")
    for row in store.playbooks(rid):
        pb = json.loads(row["body"])
        rr = pb["revenue_roadmap"]
        flags = [n.split(":")[0] for n in pb["notes"] if ":" in n and not n.startswith("lint repair")]
        print(f"{row['property_id']:24} {row['lint_status']:8} {rr['target_acv']:>12} {rr['required_active_units']:>7} "
              f"{rr['months_to_target_estimate']:>7} {len(pb['daily_task_registry']):>6}  "
              f"{(row['approved_by'] or '-'):8}  {', '.join(flags)}")
    for pid, err in run["errors"].items():
        print(f"{pid:24} FAILED   {err}")


def cmd_show(a, store: Store):
    rid = _run_id(store, a.run)
    pb = store.playbook(rid, a.property)
    if not pb:
        sys.exit(f"no playbook for {a.property} in {rid}")
    print(pb.model_dump_json(indent=2))


def cmd_approve(a, store: Store):
    rid = _run_id(store, a.run)
    if store.approve(rid, a.property, a.by):
        print(f"approved {a.property} in {rid} by {a.by}")
    else:
        sys.exit(f"cannot approve {a.property}: missing, or blocked by the lint gate")


def cmd_export(a, store: Store):
    rid = _run_id(store, a.run)
    out = Path(a.out or OUTPUT_DIR / rid / "exports")
    pids = [r["property_id"] for r in store.playbooks(rid)] if a.property == "all" else [a.property]
    for pid in pids:
        try:
            for p in export_sequences(store, rid, pid, out):
                print(f"wrote {p}")
        except NotApproved as e:
            print(f"skipped: {e}")
    print(f"wrote {export_tasks(store, rid, out, a.format)}")


def cmd_notion_setup(a, store: Store):
    from .notion_sync import CONFIG_PATH, Notion

    async def go():
        n = Notion()
        try:
            return await n.setup(a.parent_page)
        finally:
            await n.aclose()
    cfg = asyncio.run(go())
    print(f"created Notion databases {cfg} -> {CONFIG_PATH}")


def cmd_sync(a, store: Store):
    from .notion_sync import Notion
    rid = _run_id(store, a.run)

    async def go():
        n = Notion()
        try:
            return await n.sync_run(store, rid)
        finally:
            await n.aclose()
    print(f"Notion sync {rid}: {asyncio.run(go())}")


def cmd_estimate(a, store: Store):
    props = get_properties(a.properties.split(","))
    provider = (a.provider or os.getenv("VANGUARD_PROVIDER", "local")).lower()
    model = a.model or os.getenv("VANGUARD_MODEL", "claude-sonnet-5")
    web = not a.no_research and os.getenv("VANGUARD_WEB_SEARCH", "1") == "1"
    claude = estimate(len(props), model, web)
    if provider == "local":
        research = web and os.getenv("VANGUARD_RESEARCH_WITH_CLAUDE", "0") == "1"
        out = {"provider": "local", "local_model": os.getenv("VANGUARD_LOCAL_MODEL", "qwen3.6:27b"),
               "properties": len(props), "total_usd": 0.0,
               "worst_case_usd": min(float(os.getenv("VANGUARD_MAX_COST_USD", "0") or 0), claude["total_usd"]),
               "claude_estimate_if_every_call_fell_back_usd": claude["total_usd"],
               "web_research": "via Claude (paid)" if research else "off (local models have no web access)",
               "note": "local runs cost $0; worst case is bounded by VANGUARD_MAX_COST_USD (0 = fallback off)"}
    else:
        out = claude | {"provider": "claude"}
    print(json.dumps(out, indent=2))


def cmd_doctor(a, store: Store):
    """Check configuration without spending anything."""
    import os
    import httpx
    from .notion_sync import CONFIG_PATH, NOTION_VERSION
    ok = True

    def line(good: bool, msg: str):
        nonlocal ok
        ok &= good
        print(("  OK   " if good else "  FAIL ") + msg)

    def info(msg: str):
        print("  INFO " + msg)

    print("Vanguard-GTM doctor")
    provider = os.getenv("VANGUARD_PROVIDER", "local").lower()
    info(f"provider: {provider}")
    if provider == "local":
        from .providers import LocalLLM
        good, msg = asyncio.run(LocalLLM().check())
        line(good, f"local model: {msg}")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        if provider == "claude":
            line(False, "ANTHROPIC_API_KEY not set (required when VANGUARD_PROVIDER=claude)")
        else:
            info("ANTHROPIC_API_KEY not set - fine: Claude is only the optional paid fallback")
    else:
        r = httpx.get("https://api.anthropic.com/v1/models", timeout=20,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        line(r.status_code == 200, f"Anthropic key accepted (HTTP {r.status_code}; listing models is free)")
    tok = os.getenv("NOTION_TOKEN", "")
    if not tok:
        line(False, "NOTION_TOKEN not set")
    else:
        r = httpx.get("https://api.notion.com/v1/users/me", timeout=20,
                      headers={"Authorization": f"Bearer {tok}", "Notion-Version": NOTION_VERSION})
        line(r.status_code == 200, f"Notion token accepted (HTTP {r.status_code})")
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, dbid in cfg.items():
                r = httpx.get(f"https://api.notion.com/v1/databases/{dbid}", timeout=20,
                              headers={"Authorization": f"Bearer {tok}", "Notion-Version": NOTION_VERSION})
                line(r.status_code == 200, f"{k} reachable (HTTP {r.status_code})")
        else:
            line(False, f"{CONFIG_PATH} missing - run `vanguard notion-setup --parent-page <id>`")
    cap = float(os.getenv("VANGUARD_MAX_COST_USD", "0") or 0)
    info(f"paid API runs: {'ON, capped at $%.2f per run' % cap if cap > 0 else 'OFF ($0 mode)'}  "
         f"(Claude model {os.getenv('VANGUARD_MODEL', 'claude-sonnet-5')}"
         f"{', fallback only' if provider == 'local' else ''})")
    info("Notion API: free")
    from .outreach import EmailConfig
    ecfg = EmailConfig.from_env()
    info(f"email mode: {ecfg.mode}")
    for pr in ecfg.problems():
        line(False, pr)
    if ecfg.postmark_token:
        from .postmark import PostmarkError, check_streams
        try:
            chk = check_streams(ecfg)
            line(chk["ok"], f"Postmark token accepted; streams {', '.join(chk['streams']) or 'none'}"
                 + "".join(f"; missing {m}" for m in chk["missing"]) + "".join(f"; {w}" for w in chk["not_transactional"]))
        except (PostmarkError, httpx.HTTPError) as ex:
            line(False, f"Postmark: {ex}")
        info(f"Postmark monthly cap {ecfg.postmark_monthly_cap} (free plan = 100/month); cold first touch "
             f"{'ALLOWED via Postmark' if ecfg.postmark_allow_cold else 'via your SMTP mailbox' if ecfg.smtp_ready else 'held (no SMTP)'}")
    sys.exit(0 if ok else 1)


def cmd_prompt(a, store: Store):
    """`prompt <id> [--out FILE]` or `prompt all --out DIR` (one <id>.prompt.txt per property)."""
    from .engines import manual_prompt
    props = get_properties([a.property])
    if a.property == "all":
        if not a.out:
            sys.exit("`prompt all` needs --out DIR")
        d = Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        for p in props:
            (d / f"{p.id}.prompt.txt").write_text(manual_prompt(p), encoding="utf-8")
        print(f"wrote {len(props)} prompts to {d}/. Paste each into its own Claude chat (they can run in parallel),\n"
              f"save each JSON reply as {d}/<id>.json, then run `vanguard import all {d}`")
        return
    text = manual_prompt(props[0])
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out} ({len(text):,} chars). Paste it into a Claude chat, save the JSON reply, "
              f"then run `vanguard import {a.property} <reply.json>`")
    else:
        print(text)


def _read_reply(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    start, end = raw.find("{"), raw.rfind("}")  # tolerate ```json fences or text around the object
    return json.loads(raw[start:end + 1])


def cmd_import(a, store: Store):
    """`import <id> <reply.json>` or `import all <DIR>` (reads <id>.json per property into one run)."""
    from pydantic import ValidationError
    from .engines import import_playbook
    from .lint_gate import LintGate
    from .orchestrator import new_run_id
    src = Path(a.file)
    if a.property == "all":
        jobs = [(p, src / f"{p.id}.json") for p in get_properties(["all"])]
        missing = [p.id for p, f in jobs if not f.exists()]
        jobs = [(p, f) for p, f in jobs if f.exists()]
        if not jobs:
            sys.exit(f"no <id>.json replies found in {src}")
    else:
        jobs, missing = [(get_properties([a.property])[0], src)], []
    rid = a.run or new_run_id()
    if not store.run(rid):
        store.create_run(rid, [p.id for p, _ in jobs])
    from .failproof import FailproofStore, apply_to_playbook, load_failproof
    gate, errors = LintGate(), {}
    fp_cfg, fp_store = load_failproof(), FailproofStore(store)
    for p, f in jobs:
        try:
            pb = import_playbook(p, rid, _read_reply(f), gate)
        except (ValidationError, ValueError, KeyError) as e:
            errors[p.id] = f"{type(e).__name__}: {str(e)[:300]}"
            print(f"FAILED {p.id}: {errors[p.id]}")
            continue
        for tid in apply_to_playbook(pb, fp_cfg, fp_store):
            print(f"  gate-blocked task removed: {tid}")
        store.save_playbook(pb)
        print(f"imported {p.id} into run {rid}: lint={pb.lint_status}, tasks={len(pb.daily_task_registry)}")
        for fd in pb.lint_findings:
            print(f"  [{fd.severity}] {fd.rule_id} @ {fd.location}: {fd.excerpt}")
    store.finish_run(rid, errors, {"model": "manual", "cost_usd": 0.0})
    if missing:
        print(f"no reply yet for: {', '.join(missing)}")


def cmd_partners(a, store: Store):
    from .lint_gate import LintGate
    from .partners import plan_partners
    from .web.db import WebStore
    ws = WebStore(store.path)
    if a.action == "import":
        from .targets import DEFAULT_PATH, import_targets
        res = import_targets(ws, a.property or DEFAULT_PATH)
        for pid, st in res["properties"].items():
            print(f"  {pid:24} {st['created']:3} added  {st['updated']:3} refreshed")
        for e in res["errors"]:
            print(f"  problem: {e}")
        total = sum(st["created"] for st in res["properties"].values())
        print(f"{total} researched organisations added as partners, each with 3 draft emails awaiting approval. "
              f"{res['without_email']} have no public inbox - use their contact page, or add a contact email.")
        return
    if not a.property:
        sys.exit("usage: vanguard partners recommend <property|a,b|all>")
    llm = make_llm(False, provider=a.provider) if a.model else None
    if llm is not None:
        from .providers import FallbackLLM
        if isinstance(llm, FallbackLLM):
            ok, msg = asyncio.run(llm.primary.check())
            if not ok and not llm.backup_enabled:
                sys.exit(f"{msg}\n  Drop --model to use the $0 expert playbook, or start your local model.")
    for p in get_properties(a.property.split(",")):
        recs = asyncio.run(plan_partners(llm, p, None, LintGate()))
        made = sum(ws.upsert_recommendation(p.id, r, None, None)["partner_created"] for r in recs)
        print(f"\n{p.name}: {len(recs)} recommendations ({made} new partners, drafts created for new ones)")
        print(f"  {'#':>2} {'pri':3} {'score':>5}  {'kind':18} partner")
        for r in recs:
            flag = "" if r["lint_status"] == "pass" else f"  [lint {r['lint_status']}]"
            print(f"  {r['rank']:>2} {r['priority']:3} {r['score']:>5}  {r['kind']:18} {r['name']}"
                  f"{' (segment - find named targets)' if r['is_segment'] else ''}{flag}")


def cmd_campaign(a, store: Store):
    """Campaigns and the partners whose outreach counts towards them."""
    from .campaign_link import attach_partners, campaign_outreach, detach_partner, outreach_totals_by_campaign
    from .web.db import WebStore
    ws = WebStore(store.path)

    def resolve(cid: int, refs: list[str]) -> list[int]:
        c = ws.one("SELECT property_id FROM campaigns WHERE id=?", (cid,))
        if not c:
            sys.exit(f"no campaign {cid}")
        ids = []
        for r in refs:
            if r.isdigit():
                ids.append(int(r)); continue
            row = ws.one("SELECT id FROM partners WHERE property_id=? AND lower(name)=lower(?)", (c["property_id"], r))
            if not row:
                sys.exit(f"no partner named '{r}' in {c['property_id']}")
            ids.append(row["id"])
        return ids

    if a.action == "list":
        q, args = "SELECT id, property_id, name, status FROM campaigns", []
        if a.property:
            q += " WHERE property_id=?"; args.append(a.property)
        rows = ws.q(q + " ORDER BY property_id, id", args)
        auto = outreach_totals_by_campaign(ws, [r["id"] for r in rows])
        for r in rows:
            o = auto[r["id"]]
            print(f"  {r['id']:>4}  {r['property_id']:24} {r['status']:10} {r['name']}  "
                  f"[{o['targets']} partners · {o['emails_sent']} emails · {o['social_touches']} LinkedIn/X · "
                  f"{o['replies']} replied · {o['meetings']} meetings]")
        return
    if a.campaign is None:
        sys.exit("give a campaign id")
    if a.action == "show":
        c = ws.one("SELECT * FROM campaigns WHERE id=?", (a.campaign,))
        if not c:
            sys.exit(f"no campaign {a.campaign}")
        o = campaign_outreach(ws, a.campaign)
        t, qd = o["totals"], o["queue"]
        print(f"{c['name']} ({c['property_id']}, {c['status']})")
        print(f"  partners {t['targets']} · touched {t['touched']} · emails sent {t['emails_sent']} · LinkedIn/X "
              f"{t['social_touches']} · replied {t['replies']} · meetings {t['meetings']} · in conversation+ "
              f"{t['in_conversation']} · pilot {t['pilot']} · signed {t['signed']}")
        print(f"  queue: {qd['drafts']} drafts to approve · {qd['approved']} approved · {qd['missing_email']} partners "
              f"need a contact email · next due {qd['next_due'] or '-'}")
        for p in o["partners"]:
            print(f"    {p['priority'] or '--':3} {p['name'][:34]:34} {p['stage']:16} {p['contact_email'] or 'no email':30} "
                  f"emails {p['emails_sent']}/{p['steps']} · social {p['social_touches']} · last {p['last_touch'] or '-'}")
    elif a.action == "attach":
        res = attach_partners(ws, a.campaign, resolve(a.campaign, a.partners))
        for x in res["attached"]:
            print(f"attached  {x['name']}")
        for x in res["moved"]:
            print(f"moved     {x['name']} (was in '{x['from']}')")
        for x in res["refused"]:
            print(f"refused   {x.get('name', x['id'])}: {x['reason']}")
    elif a.action == "detach":
        for pid in resolve(a.campaign, a.partners):
            print(("detached  " if detach_partner(ws, a.campaign, pid) else "not in campaign  ") + str(pid))


def cmd_investors(a, store: Store):
    """Investor targets (config/investor_targets.yaml) as partners of kind 'investor', ranked for LiqMint."""
    from .web.db import WebStore
    ws = WebStore(store.path)
    if a.action == "import":
        from .investors import import_investors
        try:
            res = import_investors(ws, a.file)
        except (FileNotFoundError, ValueError) as e:
            sys.exit(str(e))
        pri = ", ".join(f"{k} {v}" for k, v in sorted(res["by_priority"].items()))
        print(f"{res['property_id']}: {res['created']} added, {res['updated']} refreshed ({pri}). No emails drafted.")
        for err in res["errors"]:
            print(f"  error: {err}")
        return
    q, args = "SELECT name, partner_type, priority, priority_score, stage FROM partners WHERE kind='investor'", []
    if a.priority:
        q += " AND priority=?"; args.append(a.priority.upper())
    for i, r in enumerate(ws.q(q + " ORDER BY COALESCE(priority_score,0) DESC, name", args), 1):
        print(f"  {i:>3} {r['priority'] or '--':3} {r['priority_score'] or '':>3}  {r['name'][:28]:28} "
              f"{(r['partner_type'] or '')[:48]:48} {r['stage']}")


def cmd_intros(a, store: Store):
    """Paths to investors and partners through people you know (from imported LinkedIn exports)."""
    from .intros import draft, listing, send_approved, suggest
    from .web.db import WebStore
    ws = WebStore(store.path)
    if a.action == "suggest":
        res = suggest(ws, a.property.split(",") if a.property else None)
        if res.get("error"):
            sys.exit(res["error"])
        print(f"{res['targets']} targets checked · {res['suggested']} new intro paths ({res['direct']} through insiders)")
    elif a.action == "draft":
        rows = listing(ws, "suggested")
        for r in rows:
            draft(ws, r["id"])
        print(f"{len(rows)} asks drafted - an admin approves them in the app (Intros) before anything is sent")
    elif a.action == "send":
        res = send_approved(ws)
        if res.get("error"):
            sys.exit(res["error"])
        for m in res["sent"]:
            print(f"sent   #{m['id']} -> {m['to']} <{m['email']}> about {m['target']}")
        for m in res["skipped"]:
            print(f"held   #{m['id']} {m['to']}: {m['reason']}")
    else:
        for r in listing(ws, a.status):
            print(f"  #{r['id']:<4} {r['priority'] or '--':3} {r['partner_name'][:26]:26} <- {r['first_name']} {r['last_name']}"
                  f"{' (insider)' if r['path'] == 'direct' else ''} · strength {r['strength'] or 0:g} · {r['status']}")


def cmd_linkedin(a, store: Store):
    """Load LinkedIn's Connections.csv (Settings > Data privacy > Get a copy of your data) and match it to partners."""
    from .linkedin import import_connections, partners_with_connections
    from .web.db import WebStore
    ws = WebStore(store.path)
    if a.action == "import":
        if not a.file:
            sys.exit("give the path to Connections.csv")
        uid = None
        if a.by:
            u = ws.user_by_email(a.by)
            if not u:
                sys.exit(f"no user {a.by}")
            uid = u["id"]
        try:
            if a.file.lower().endswith(".zip"):
                from .intros import import_export_zip
                res = import_export_zip(ws, Path(a.file).read_bytes(), uid)
            else:
                res = import_connections(ws, Path(a.file).read_text(encoding="utf-8-sig"), uid)
        except (ValueError, FileNotFoundError) as e:
            sys.exit(str(e))
        print(f"{res['connections']} connections ({res['added']} new, {res['refreshed']} refreshed) · "
              f"{res['partners_with_connections']} partners where you know someone")
        for n in res["contacts_connected"]:
            print(f"  connected: named contact at {n}")
        for n in res["emails_filled"]:
            print(f"  email added from LinkedIn: {n}")
        if "warm" in res:
            print(f"  tie strength from the full export: {res['with_messages']} people you've messaged, {res['warm']} warm ties (2+/5)")
        return
    known = partners_with_connections(ws)
    q, args = "SELECT id, name, property_id, priority FROM partners WHERE COALESCE(is_segment,0)=0", []
    if a.property:
        q += " AND property_id=?"; args.append(a.property)
    for p in ws.q(q + " ORDER BY property_id, COALESCE(priority_score,0) DESC", args):
        for c in known.get(p["id"], []):
            print(f"  {p['priority'] or '--':3} {p['name'][:30]:30} {c['first_name']} {c['last_name']} · "
                  f"{c['position'] or ''}{' (named contact)' if c['is_contact'] else ''} · via {c['owner_name'] or 'cli'}")


def cmd_outreach(a, store: Store):
    from .outreach import EmailConfig, approve, queue_stats, send_due, sync_replies
    from .web.db import WebStore
    ws = WebStore(store.path)
    cfg = EmailConfig.from_env()
    if a.action == "status":
        st = cfg.status()
        print(f"Email mode: {st['mode']}{' (LIVE - really sends)' if st['live'] else ' (writes .eml files to output/outbox, sends nothing)' if st['mode'] == 'outbox' else ''}")
        for pr in st["problems"]:
            print(f"  problem: {pr}")
        print(f"Daily cap {st['daily_cap']} · IMAP reply sync {'on' if st['imap_configured'] else 'off (record replies by hand)'}")
        for b in st["mailboxes"]:
            print(f"  mailbox {b['name']}: {b['sender'] or '(no sender)'} · cap {b['daily_cap']}/day · IMAP "
                  f"{'on' if b['imap_configured'] else 'off'} · {', '.join(b['properties']) if b['properties'] else 'all other properties'}")
        if st["postmark"]:
            from .outreach import postmark_used_this_month
            pm = st["postmark"]
            print(f"Postmark: streams outreach={pm['stream_outreach']} notify={pm['stream_notify']} · "
                  f"{postmark_used_this_month(ws)}/{pm['monthly_cap']} this month · inbound {'on' if pm['inbound'] else 'off'} · "
                  f"cold first touch {'via Postmark' if pm['allow_cold'] else 'via SMTP' if pm['cold_via_smtp'] else 'held'}")
        print(json.dumps(queue_stats(ws), indent=2))
    elif a.action == "approve":
        print(approve(ws, [int(x) for x in a.ids], a.by or "cli"))
    elif a.action == "send":
        res = send_due(ws, cfg)
        if res.get("error"):
            sys.exit(res["error"])
        for m in res["sent"]:
            print(f"sent   #{m['id']} step {m['step']} -> {m['partner']} <{m['to']}>")
        for m in res["skipped"]:
            print(f"queued #{m['id']} step {m['step']} {m['partner']}: {m['reason']}")
        print(f"{len(res['sent'])} sent ({res['mode']} mode)")
    elif a.action == "sync-replies":
        print(sync_replies(ws, cfg))
    elif a.action == "digest":
        from .outreach import send_digest
        print(send_digest(ws, cfg))
    elif a.action == "purge-general":
        from .addresses import purge
        r = purge(ws)
        for x in r["removed"]:
            print(f"removed  {x['partner']}: {x['address']} (general inbox; {x['cancelled']} unsent emails cancelled)")
        for x in r["unverified"]:
            print(f"held     {x['partner']}: {x['address']} - not confirmed as {x['contact'] or 'the contact'}'s own address")
        print(f"{len(r['removed'])} general inboxes removed, {len(r['unverified'])} addresses held until confirmed")
    elif a.action in ("postmark-sync", "postmark-check"):
        if not cfg.postmark_token:
            sys.exit("POSTMARK_SERVER_TOKEN is not set")
        from .outreach import postmark_used_this_month
        from .postmark import check_streams, sync_suppressions
        if a.action == "postmark-sync":
            print(json.dumps(sync_suppressions(ws, cfg), indent=2))
        else:
            print(json.dumps(check_streams(cfg) | {"used_this_month": postmark_used_this_month(ws),
                                                   "monthly_cap": cfg.postmark_monthly_cap}, indent=2))


def _outreach_loop(minutes: float, db_path) -> None:
    """Background: every N minutes send due approved messages and check for replies."""
    import threading
    import time as _t
    from .outreach import EmailConfig, send_due, sync_replies
    from .web.db import WebStore

    def loop():
        ws = WebStore(db_path)
        while True:
            try:
                cfg = EmailConfig.from_env()
                r = send_due(ws, cfg)
                if any(c.imap_host and c.imap_user for c in cfg.all_mailboxes()):
                    sync_replies(ws, cfg)
                if r.get("sent"):
                    logging.getLogger("vanguard.outreach").info("scheduler sent %d", len(r["sent"]))
            except Exception:
                logging.getLogger("vanguard.outreach").exception("outreach scheduler tick failed")
            _t.sleep(minutes * 60)
    threading.Thread(target=loop, daemon=True, name="outreach-scheduler").start()


def cmd_serve(a, store: Store):
    import uvicorn
    from .web.app import UI_DIST
    try:                                   # only named people are emailed: clear general inboxes on every start
        from .addresses import purge
        from .web.db import WebStore
        r = purge(WebStore(store.path))
        if r["removed"]:
            print(f"Removed {len(r['removed'])} general-inbox addresses from partners (support@, info@ ...)")
    except Exception as ex:                # never block the app from starting
        logging.getLogger("vanguard").warning("general-inbox cleanup skipped: %s", ex)
    every = float(os.getenv("VANGUARD_OUTREACH_EVERY_MIN", "0") or 0)
    if every > 0:
        print(f"Outreach scheduler: every {every:g} min (sends only messages an admin approved)")
        _outreach_loop(every, store.path)
    if not UI_DIST.exists():
        print(f"note: UI not built ({UI_DIST} missing) - API only. Build it with `cd ui && npm install && npm run build`.")
    print(f"Vanguard-GTM web app on http://{'localhost' if a.host == '0.0.0.0' else a.host}:{a.port}")
    uvicorn.run("vanguard.web.app:app", host=a.host, port=a.port)


def cmd_create_user(a, store: Store):
    import getpass
    from .web.db import WebStore
    from .web.security import hash_password
    ws = WebStore(store.path)
    if ws.user_by_email(a.email):
        sys.exit(f"{a.email} already exists")
    pw = a.password or getpass.getpass("Password (min 10 chars): ")
    uid = ws.create_user(a.email, a.name, a.role, hash_password(pw))
    print(f"created {a.role} user {a.email} (id {uid})")


def cmd_seed_users(a, store: Store):
    """First-run convenience: one admin and one general user with random passwords, shown once."""
    from .web.db import WebStore
    from .web.security import generate_password, hash_password
    ws = WebStore(store.path)
    if ws.q("SELECT id FROM users LIMIT 1"):
        sys.exit("users already exist - use `vanguard create-user` or the Admin > Users page")
    print("Created (save these now - passwords are not stored in readable form):")
    for email, name, role in ((a.admin_email, "Admin", "admin"), (a.user_email, "Team Member", "user")):
        pw = generate_password()
        ws.create_user(email, name, role, hash_password(pw))
        print(f"  {role:5}  {email:28}  password: {pw}")


def cmd_demo_data(a, store: Store):
    from .web.demo import load_demo, purge_demo
    from .web.db import WebStore
    ws = WebStore(store.path)
    print(purge_demo(ws) if a.purge else load_demo(ws))


# ---------------------------------------------------------------- fail-proof layer (Engines 0, 5, 6)
def _as_of(value: str | None):
    from datetime import date
    from .failproof import today
    return date.fromisoformat(value) if value else today()


def cmd_tripwires(a, store: Store):
    from .failproof import FailproofStore, load_failproof, tracker, tracker_markdown
    cfg = load_failproof()
    ids = a.property.split(",") if a.property else None
    if ids:
        get_properties(ids)  # validates the ids
    t = tracker(cfg, FailproofStore(store), _as_of(a.as_of), ids)
    text = json.dumps(t, indent=1) if a.json else tracker_markdown(t)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)
    if any(p["halt"] for p in t["properties"]):
        sys.exit(2)


def cmd_record(a, store: Store):
    from .failproof import FailproofStore, load_failproof
    cfg = load_failproof()
    pf = cfg.properties.get(a.property) or sys.exit(f"unknown property {a.property!r}")
    if a.tripwire not in {t.id for t in pf.tripwires}:
        sys.exit(f"unknown tripwire {a.tripwire!r} for {a.property}: {[t.id for t in pf.tripwires]}")
    d = _as_of(a.date)
    FailproofStore(store).record(a.property, a.tripwire, a.value, d, a.note or "", a.by or "")
    print(f"recorded {a.property} {a.tripwire} = {a.value:g} on {d.isoformat()}")


def cmd_gate(a, store: Store):
    from .failproof import FailproofStore, load_failproof
    cfg = load_failproof()
    pf = cfg.properties.get(a.property) or sys.exit(f"unknown property {a.property!r}")
    gate = next((g for g in pf.gates if g.id == a.gate), None) or \
        sys.exit(f"unknown gate {a.gate!r} for {a.property}: {[g.id for g in pf.gates]}")
    status = {"pass": "passed", "fail": "failed", "open": "open"}[a.status]
    if status == "passed" and not a.by:
        sys.exit("passing a gate needs --by NAME (who verified it)")
    FailproofStore(store).set_gate(a.property, gate.id, status, a.note or "", a.by or "")
    print(f"{a.property} {gate.id} {gate.name}: {status.upper()}")
    if status == "failed":
        print(f"WALK-AWAY CONDITION: {gate.walk_away_if}")


def cmd_premortem(a, store: Store):
    from .failproof import FailproofStore, load_failproof, premortem_markdown, run_premortem
    cfg = load_failproof()
    p = get_properties([a.property])[0]
    plan = Path(a.plan).read_text(encoding="utf-8") if a.plan else ""
    llm = make_llm(a.dry_run, provider=a.provider)
    try:
        pm = asyncio.run(run_premortem(llm, p, cfg.properties[p.id], plan))
    except Exception as e:  # e.g. local model down and paid fallback off - nothing was spent
        sys.exit(f"premortem not produced ({type(e).__name__}: {e}). $0 option: add --dry-run.")
    FailproofStore(store).save_premortem(p.id, plan, pm.model_dump(mode="json"))
    md = premortem_markdown(p.id, pm)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(md)


def cmd_db(a, store: Store):
    """`db info` shows which database is in use; `db copy-from-sqlite FILE` moves data into it."""
    if a.action == "info":
        print(store.db.describe())
        with store.conn() as c:
            for t in ("runs", "tasks", "users", "partners", "outreach_messages", "tripwire_readings"):
                try:
                    n = c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                    print(f"  {t:20} {n}")
                except Exception:
                    print(f"  {t:20} (not created yet)")
        return
    if not a.file:
        sys.exit("give the SQLite file to copy from, e.g. vanguard db copy-from-sqlite data/vanguard.db")
    from .db import copy_from_sqlite
    if store.db.path and Path(a.file).resolve() == Path(store.db.path).resolve() and not store.postgres:
        sys.exit("source and destination are the same SQLite file")
    print(f"Copying {a.file} -> {store.db.describe()}")
    for table, result in copy_from_sqlite(Path(a.file), store, replace=a.replace).items():
        print(f"  {table:24} {result}")


def _utf8_console() -> None:
    """Windows consoles and pipes may default to cp1252; never crash printing names like 'Mandap & Co · P0'."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _utf8_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="vanguard", description="Vanguard-GTM orchestrator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate launch engines")
    r.add_argument("--properties", default="all", help="comma list of ids, or 'all'")
    r.add_argument("--concurrency", type=int)
    r.add_argument("--dry-run", action="store_true", help="offline mock LLM, no API calls")
    r.add_argument("--sync", action="store_true", help="push to Notion when done")
    r.add_argument("--no-research", action="store_true", help="skip Engine 1 web search (cheaper)")
    r.add_argument("-y", "--yes", action="store_true", help="don't ask to confirm the cost estimate")
    r.add_argument("--provider", choices=["local", "claude"], help="override VANGUARD_PROVIDER (default local)")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("status"); s.add_argument("--run"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("show"); s.add_argument("property"); s.add_argument("--run"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("approve", help="human sign-off; required before email export")
    s.add_argument("property"); s.add_argument("--by", required=True); s.add_argument("--run"); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("export", help="Smartlead/Instantly sequence CSVs + task backlog")
    s.add_argument("property", nargs="?", default="all"); s.add_argument("--run"); s.add_argument("--out")
    s.add_argument("--format", choices=["csv", "json"], default="csv"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("notion-setup"); s.add_argument("--parent-page", required=True); s.set_defaults(fn=cmd_notion_setup)
    s = sub.add_parser("sync", help="push a run to Notion"); s.add_argument("--run"); s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("estimate", help="pre-run cost estimate, spends nothing")
    s.add_argument("--properties", default="all"); s.add_argument("--model"); s.add_argument("--no-research", action="store_true")
    s.add_argument("--provider", choices=["local", "claude"])
    s.set_defaults(fn=cmd_estimate)
    s = sub.add_parser("prompt", help="print a self-contained prompt for producing a playbook in a Claude chat ($0 API)")
    s.add_argument("property"); s.add_argument("--out"); s.set_defaults(fn=cmd_prompt)
    s = sub.add_parser("import", help="validate + lint a playbook JSON produced in a Claude chat and store it")
    s.add_argument("property"); s.add_argument("file"); s.add_argument("--run"); s.set_defaults(fn=cmd_import)
    s = sub.add_parser("doctor", help="check keys and Notion access, spends nothing"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("create-user", help="add a web-app user")
    s.add_argument("--email", required=True); s.add_argument("--name", required=True)
    s.add_argument("--role", choices=["admin", "user"], default="user"); s.add_argument("--password")
    s.set_defaults(fn=cmd_create_user)
    s = sub.add_parser("seed-users", help="first run: create an admin and a general user with random passwords")
    s.add_argument("--admin-email", default="admin@vireoka.com"); s.add_argument("--user-email", default="team@vireoka.com")
    s.set_defaults(fn=cmd_seed_users)
    s = sub.add_parser("demo-data", help="load clearly-labelled [DEMO] campaigns/partners/results to explore the UI")
    s.add_argument("--purge", action="store_true", help="remove all [DEMO] records"); s.set_defaults(fn=cmd_demo_data)
    s = sub.add_parser("partners", help="partnerships expert: recommend, score and prioritise partners + draft outreach; "
                       "import researched named organisations")
    s.add_argument("action", choices=["recommend", "import"])
    s.add_argument("property", nargs="?", default=None,
                   help="recommend: property id(s), comma list, or all. import: targets YAML "
                        "(default config/partner_targets.yaml)")
    s.add_argument("--model", action="store_true", help="let the local model/Claude name specific organisations "
                   "(default: $0 expert playbook)")
    s.add_argument("--provider", choices=["local", "claude"]); s.set_defaults(fn=cmd_partners)
    s = sub.add_parser("outreach", help="approval-gated partner emails: status | approve | send | sync-replies | "
                       "digest | postmark-sync | postmark-check | purge-general")
    s.add_argument("action", choices=["status", "approve", "send", "sync-replies", "digest", "postmark-sync", "postmark-check",
                                      "purge-general"])
    s.add_argument("ids", nargs="*", help="message ids (approve)"); s.add_argument("--by")
    s.set_defaults(fn=cmd_outreach)
    s = sub.add_parser("campaign", help="campaigns and their partners: list | show ID | attach ID PARTNER.. | detach ID PARTNER..")
    s.add_argument("action", choices=["list", "show", "attach", "detach"])
    s.add_argument("campaign", nargs="?", type=int, help="campaign id")
    s.add_argument("partners", nargs="*", help="partner ids or exact names (attach/detach)")
    s.add_argument("--property", help="list: only this property"); s.set_defaults(fn=cmd_campaign)
    s = sub.add_parser("investors", help="investor targets for the raise: import [FILE] | list [--priority P0]")
    s.add_argument("action", choices=["import", "list"]); s.add_argument("file", nargs="?")
    s.add_argument("--priority", help="list: only this priority (P0, P1, P2)"); s.set_defaults(fn=cmd_investors)
    s = sub.add_parser("intros", help="introductions through your LinkedIn connections: suggest | list | draft | send")
    s.add_argument("action", choices=["suggest", "list", "draft", "send"])
    s.add_argument("--property", help="suggest: only these properties (comma list)")
    s.add_argument("--status", help="list: only this status"); s.set_defaults(fn=cmd_intros)
    s = sub.add_parser("linkedin", help="LinkedIn connections from LinkedIn's own data export: import FILE --by EMAIL | matches")
    s.add_argument("action", choices=["import", "matches"]); s.add_argument("file", nargs="?")
    s.add_argument("--by", help="import: the user these connections belong to (email)")
    s.add_argument("--property", help="matches: only this property"); s.set_defaults(fn=cmd_linkedin)
    s = sub.add_parser("tripwires", help="fail-proof tracker: tripwire status + gates per property (exit 2 on HALT)")
    s.add_argument("--property", help="id or comma list (default all)"); s.add_argument("--as-of", help="YYYY-MM-DD")
    s.add_argument("--json", action="store_true"); s.add_argument("--out"); s.set_defaults(fn=cmd_tripwires)
    s = sub.add_parser("record", help="record a tripwire reading: record <property> <tripwire> <value>")
    s.add_argument("property"); s.add_argument("tripwire"); s.add_argument("value", type=float)
    s.add_argument("--date", help="reading date YYYY-MM-DD (default today)"); s.add_argument("--note"); s.add_argument("--by")
    s.set_defaults(fn=cmd_record)
    s = sub.add_parser("gate", help="set a readiness gate: gate <property> <gate> pass|fail|open --by NAME")
    s.add_argument("property"); s.add_argument("gate"); s.add_argument("status", choices=["pass", "fail", "open"])
    s.add_argument("--note"); s.add_argument("--by"); s.set_defaults(fn=cmd_gate)
    s = sub.add_parser("premortem", help="Engine 0: forensic premortem of a plan (7 causes, verdict, adversary, tripwires)")
    s.add_argument("property"); s.add_argument("--plan", help="text/markdown file with the plan to test")
    s.add_argument("--dry-run", action="store_true", help="$0 offline premortem from config/failproof.yaml")
    s.add_argument("--provider", choices=["local", "claude"]); s.add_argument("--out"); s.set_defaults(fn=cmd_premortem)
    s = sub.add_parser("db", help="database: info | copy-from-sqlite FILE [--replace] (moves SQLite data into PostgreSQL)")
    s.add_argument("action", choices=["info", "copy-from-sqlite"]); s.add_argument("file", nargs="?")
    s.add_argument("--replace", action="store_true", help="overwrite tables that already hold rows")
    s.set_defaults(fn=cmd_db)
    s = sub.add_parser("serve"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8080)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    a.fn(a, Store())


if __name__ == "__main__":
    main()
