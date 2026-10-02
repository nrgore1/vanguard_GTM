"""Web app API tests: auth, the admin/user permission model, CRUD, dashboard maths, agent-run workflow.

Each docstring starts with its ID from docs/TEST_CASES.md.
"""
from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vanguard.web import app as webapp
from vanguard.web.db import WebStore
from vanguard.web.security import hash_password, make_token

ROOT = Path(__file__).resolve().parent.parent
ADMIN_PW, USER_PW = "admin-pass-123", "user-pass-1234"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VANGUARD_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("VANGUARD_JWT_SECRET", "test-secret")
    monkeypatch.setattr("vanguard.orchestrator.OUTPUT_DIR", tmp_path / "out")
    s = WebStore(tmp_path / "v.db")
    webapp.set_store(s)
    ids = {"admin": s.create_user("admin@v.com", "Ada Admin", "admin", hash_password(ADMIN_PW)),
           "user": s.create_user("user@v.com", "Uma User", "user", hash_password(USER_PW)),
           "user2": s.create_user("other@v.com", "Otto Other", "user", hash_password(USER_PW))}
    c = TestClient(webapp.create_app())

    def login(email, pw):
        r = c.post("/api/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    return {"c": c, "s": s, "ids": ids, "A": login("admin@v.com", ADMIN_PW), "U": login("user@v.com", USER_PW),
            "U2": login("other@v.com", USER_PW), "tmp": tmp_path}


def _campaign(e, h, **kw):
    body = {"property_id": "oratoplus", "name": "Founder pitch practice push", "kind": "email", "status": "active"} | kw
    r = e["c"].post("/api/campaigns", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- auth
def test_web_01_login_and_tokens(env):
    """WEB-01: good login returns a token; bad password, disabled account, tampered and expired tokens are refused."""
    c = env["c"]
    assert c.post("/api/auth/login", json={"email": "admin@v.com", "password": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "ADMIN@v.com", "password": ADMIN_PW}).status_code == 200
    assert c.get("/api/me", headers=env["A"]).json()["role"] == "admin"
    tok = env["A"]["Authorization"]
    assert c.get("/api/me", headers={"Authorization": tok[:-3] + "abc"}).status_code == 401
    expired = make_token(env["ids"]["admin"], "admin", ttl=-5)
    assert c.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    env["s"].update("users", "id", env["ids"]["user"], {"active": 0})
    assert c.get("/api/me", headers=env["U"]).status_code == 401
    assert c.post("/api/auth/login", json={"email": "user@v.com", "password": USER_PW}).status_code == 401
    row = env["s"].user(env["ids"]["admin"])
    assert row["password_hash"].startswith("pbkdf2_sha256$") and ADMIN_PW not in row["password_hash"]


def test_web_02_everything_requires_sign_in(env):
    """WEB-02: every /api route except login answers 401 without a token."""
    c = env["c"]
    for m, path in [("get", "/api/me"), ("get", "/api/dashboard"), ("get", "/api/campaigns"), ("post", "/api/campaigns"),
                    ("get", "/api/partners"), ("get", "/api/tasks"), ("get", "/api/users"), ("get", "/api/runs"),
                    ("get", "/api/audit"), ("put", "/api/targets/oratoplus"), ("get", "/api/properties")]:
        assert getattr(c, m)(path).status_code == 401, path


def test_web_03_general_user_cannot_use_admin_functions(env):
    """WEB-03: a general user gets 403 on user admin, targets, task create/delete, partner delete, runs and audit."""
    c, U = env["c"], env["U"]
    denied = [
        c.post("/api/users", json={"email": "x@v.com", "name": "X", "role": "user", "password": "x" * 12}, headers=U),
        c.patch(f"/api/users/{env['ids']['user2']}", json={"role": "admin"}, headers=U),
        c.delete(f"/api/users/{env['ids']['user2']}", headers=U),
        c.put("/api/targets/oratoplus", json={"arr_target_usd": 1}, headers=U),
        c.post("/api/tasks", json={"property_id": "oratoplus", "description": "sneaky task"}, headers=U),
        c.get("/api/runs", headers=U), c.post("/api/runs", json={"dry_run": True}, headers=U),
        c.get("/api/audit", headers=U), c.get("/api/agent/status", headers=U),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)
    pid = c.post("/api/partners", json={"property_id": "atmakosh", "name": "Some Lab", "kind": "design_partner"}, headers=U).json()["id"]
    assert c.delete(f"/api/partners/{pid}", headers=U).status_code == 403
    users = c.get("/api/users", headers=U).json()
    assert users and "email" not in users[0]            # users see names only, never emails


# ---------------------------------------------------------------- campaigns
def test_web_04_campaign_crud_and_ownership(env):
    """WEB-04: users create/edit campaigns; only the creator or an admin can delete; input is validated."""
    c = env["c"]
    cid = _campaign(env, env["U"], budget_usd=500)
    assert c.patch(f"/api/campaigns/{cid}", json={"status": "paused", "goal_metric": "meetings", "goal_value": 12}, headers=env["U2"]).status_code == 200
    got = c.get(f"/api/campaigns/{cid}", headers=env["U"]).json()
    assert got["status"] == "paused" and got["owner_name"] == "Uma User" and got["goal_value"] == 12
    assert c.delete(f"/api/campaigns/{cid}", headers=env["U2"]).status_code == 403
    assert c.delete(f"/api/campaigns/{cid}", headers=env["U"]).status_code == 200
    cid2 = _campaign(env, env["U"])
    assert c.delete(f"/api/campaigns/{cid2}", headers=env["A"]).status_code == 200
    bad = [dict(property_id="nope"), dict(budget_usd=-1), dict(status="live"),
           dict(start_date="2026-10-10", end_date="2026-10-01"), dict(name="x")]
    for b in bad:
        body = {"property_id": "oratoplus", "name": "Valid name"} | b
        assert c.post("/api/campaigns", json=body, headers=env["U"]).status_code == 422, b
    assert c.get("/api/campaigns/999", headers=env["U"]).status_code == 404


def test_web_05_results_feed_the_dashboard(env):
    """WEB-05: logged results roll up into campaign totals, the property funnel, run-rate (last 30 days x 12) and weekly series."""
    c = env["c"]
    cid = _campaign(env, env["U"])
    today = date.today()
    c.post(f"/api/campaigns/{cid}/results", json={"date": today.isoformat(), "sent": 100, "replies": 7, "meetings": 3,
                                                  "conversions": 2, "revenue_usd": 600}, headers=env["U"])
    c.post(f"/api/campaigns/{cid}/results", json={"date": (today - timedelta(days=60)).isoformat(), "sent": 50,
                                                  "revenue_usd": 1000}, headers=env["U2"])
    assert c.post(f"/api/campaigns/{cid}/results", json={"date": today.isoformat(), "sent": -1}, headers=env["U"]).status_code == 422
    row = next(x for x in c.get("/api/campaigns", headers=env["U"]).json() if x["id"] == cid)
    assert (row["sent"], row["replies"], row["revenue_usd"]) == (150, 7, 1600)
    d = c.get("/api/dashboard", headers=env["U"]).json()
    ora = next(p for p in d["properties"] if p["property_id"] == "oratoplus")
    assert ora["revenue_to_date_usd"] == 1600 and ora["arr_run_rate_usd"] == 600 * 12
    assert ora["funnel"]["meetings"] == 3 and ora["campaigns"] == {"total": 1, "active": 1} and ora["arr_target_usd"] == 2_000_000
    assert sum(w["revenue_usd"] for w in d["weekly"]) == 1600 and len(d["properties"]) == 8
    other = c.get(f"/api/campaigns/{cid}", headers=env["U"]).json()["results"]
    by_other = next(r for r in other if r["created_by"] == env["ids"]["user2"])
    assert c.delete(f"/api/results/{by_other['id']}", headers=env["U"]).status_code == 403
    assert c.delete(f"/api/results/{by_other['id']}", headers=env["U2"]).status_code == 200
    assert c.put("/api/targets/oratoplus", json={"arr_target_usd": 1_500_000, "monthly_conversions_target": 40}, headers=env["A"]).status_code == 200
    ora = next(p for p in c.get("/api/dashboard", headers=env["U"]).json()["properties"] if p["property_id"] == "oratoplus")
    assert ora["arr_target_usd"] == 1_500_000 and ora["monthly_conversions_target"] == 40


# ---------------------------------------------------------------- partners
def test_web_06_partner_pipeline_and_interactions(env):
    """WEB-06: add partners, reject duplicates, log interactions that move the stage, delete own interactions only."""
    c, U = env["c"], env["U"]
    r = c.post("/api/partners", json={"property_id": "liqmint-institutional", "name": "Custody Co", "kind": "co_sell",
                                      "contact_email": "not-an-email"}, headers=U)
    assert r.status_code == 422
    pid = c.post("/api/partners", json={"property_id": "liqmint-institutional", "name": "Custody Co", "kind": "co_sell"}, headers=U).json()["id"]
    assert c.post("/api/partners", json={"property_id": "liqmint-institutional", "name": "Custody Co"}, headers=U).status_code == 409
    iid = c.post(f"/api/partners/{pid}/interactions", json={"date": date.today().isoformat(), "type": "call",
                 "summary": "Discovery call - they want a Canton pilot scope", "outcome": "positive", "stage": "in_conversation",
                 "next_step": "Send pilot scope"}, headers=U).json()["id"]
    p = c.get(f"/api/partners/{pid}", headers=env["U2"]).json()
    assert p["stage"] == "in_conversation" and p["next_step"] == "Send pilot scope" and len(p["interactions"]) == 1
    assert c.patch(f"/api/partners/{pid}", json={"stage": "pilot"}, headers=env["U2"]).status_code == 200
    lst = c.get("/api/partners?kind=co_sell", headers=U).json()
    assert lst[0]["interactions"] == 1 and lst[0]["stage"] == "pilot"
    assert c.post(f"/api/partners/{pid}/interactions", json={"date": "2026-09-01", "type": "tweet", "summary": "x y"}, headers=U).status_code == 422
    assert c.delete(f"/api/interactions/{iid}", headers=env["U2"]).status_code == 403
    assert c.delete(f"/api/interactions/{iid}", headers=U).status_code == 200
    assert c.delete(f"/api/partners/{pid}", headers=env["A"]).status_code == 200


# ---------------------------------------------------------------- tasks
def _dry_run(env) -> str:
    r = env["c"].post("/api/runs", json={"properties": ["oratoplus", "vireoka"], "dry_run": True}, headers=env["A"])
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def test_web_07_task_permissions(env):
    """WEB-07: users update status/notes only on tasks assigned to them; admins assign, reprioritise, create and delete."""
    c = env["c"]
    _dry_run(env)
    tasks = c.get("/api/tasks?property_id=oratoplus", headers=env["U"]).json()
    assert len(tasks) == 30 and tasks[0]["task_id"].startswith("ORA-")
    t = tasks[0]["id"]
    assert c.patch(f"/api/tasks/{t}", json={"status": "Done"}, headers=env["U"]).status_code == 403   # not assigned
    assert c.patch(f"/api/tasks/{t}", json={"assignee_id": env["ids"]["user"], "priority": "P0",
                                            "due_date": "2026-10-15"}, headers=env["A"]).status_code == 200
    assert c.patch(f"/api/tasks/{t}", json={"status": "In progress", "notes": "Drafted"}, headers=env["U"]).status_code == 200
    assert c.patch(f"/api/tasks/{t}", json={"priority": "P2"}, headers=env["U"]).status_code == 403
    assert c.patch(f"/api/tasks/{t}", json={"status": "Done"}, headers=env["U2"]).status_code == 403
    mine = c.get("/api/tasks?mine=true", headers=env["U"]).json()
    assert [(m["status"], m["priority"], m["notes"], m["due_date"]) for m in mine] == [("In progress", "P0", "Drafted", "2026-10-15")]
    assert c.get("/api/dashboard", headers=env["U"]).json()["my_open_tasks"][0]["id"] == t
    new = c.post("/api/tasks", json={"property_id": "oratoplus", "description": "Pitch Toastmasters district 6",
                                     "priority": "P0", "assignee_id": env["ids"]["user2"]}, headers=env["A"]).json()
    assert new["task_id"] == "ORA-M001"
    assert any(x["task_id"] == "ORA-M001" for x in c.get("/api/tasks", headers=env["U"]).json())
    assert c.delete(f"/api/tasks/{t}", headers=env["U"]).status_code == 403
    assert c.delete(f"/api/tasks/{t}", headers=env["A"]).status_code == 200


# ---------------------------------------------------------------- agent from the UI
def test_web_08_run_approve_import(env):
    """WEB-08: admin starts a dry run, approves a playbook, imports drafts (idempotent); blocked playbooks are skipped."""
    c, A = env["c"], env["A"]
    rid = _dry_run(env)
    run = c.get(f"/api/runs/{rid}", headers=A).json()
    assert run["status"] == "completed" and {p["property_id"] for p in run["playbooks"]} == {"oratoplus", "vireoka"}
    assert c.post(f"/api/runs/{rid}/approve/oratoplus", headers=A).status_code == 200
    env["s"].update("playbooks", "property_id", "vireoka", {"lint_status": "blocked"})
    assert c.post(f"/api/runs/{rid}/approve/vireoka", headers=A).status_code == 409
    first = c.post(f"/api/runs/{rid}/import", headers=A).json()
    # oratoplus: 2 campaigns; 5 expert recommendations (with 3-step drafts) + 3 playbook partners
    assert first == {"campaigns": 2, "partners": 5 + 3, "messages": 5 * 3, "skipped": 1}
    assert c.post(f"/api/runs/{rid}/import", headers=A).json() == {"campaigns": 0, "partners": 0, "messages": 0, "skipped": 1}
    camps = c.get("/api/campaigns?property_id=oratoplus", headers=env["U"]).json()
    assert {x["status"] for x in camps} == {"draft"} and all(x["source_run_id"] == rid for x in camps)
    email = next(x for x in camps if x["kind"] == "email")
    assert len(json.loads(email["content"])) == 5
    kinds = {p["kind"] for p in c.get("/api/partners?property_id=oratoplus", headers=env["U"]).json()}
    assert {"design_partner", "co_sell"} <= kinds
    assert c.post("/api/runs", json={"properties": ["nope"]}, headers=A).status_code == 422
    assert c.post(f"/api/runs/{rid}/sync", headers=A).status_code == 409       # no NOTION_TOKEN -> clear refusal


def test_web_09_real_runs_respect_the_zero_cost_default(env, monkeypatch):
    """WEB-09: from the UI, a real run is refused (409, nothing started) when the local model is down and the Claude
    fallback is off, and a Claude-only run is refused at cap 0."""
    monkeypatch.setenv("VANGUARD_LOCAL_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("VANGUARD_MAX_COST_USD", raising=False)
    c, A = env["c"], env["A"]
    r = c.post("/api/runs", json={"properties": ["oratoplus"], "dry_run": False}, headers=A)
    assert r.status_code == 409 and "nothing was started" in r.json()["detail"]
    r = c.post("/api/runs", json={"properties": ["oratoplus"], "dry_run": False, "provider": "claude"}, headers=A)
    assert r.status_code == 409 and "VANGUARD_MAX_COST_USD=0" in r.json()["detail"]
    assert c.get("/api/runs", headers=A).json() == []
    st = c.get("/api/agent/status", headers=A).json()
    assert st["provider"] == "local" and st["local_ok"] is False and st["paid_runs"] is False


# ---------------------------------------------------------------- users & audit
def test_web_10_user_administration(env):
    """WEB-10: admin creates users (unique email, 10+ char password), changes roles, disables, resets passwords, deletes;
    can't demote, disable or delete themselves."""
    c, A = env["c"], env["A"]
    assert c.post("/api/users", json={"email": "new@v.com", "name": "Nia", "role": "user", "password": "short"}, headers=A).status_code == 422
    uid = c.post("/api/users", json={"email": "new@v.com", "name": "Nia", "role": "user", "password": "long-enough-1"}, headers=A).json()["id"]
    assert c.post("/api/users", json={"email": "NEW@v.com", "name": "Dup", "role": "user", "password": "long-enough-1"}, headers=A).status_code == 409
    assert c.patch(f"/api/users/{uid}", json={"role": "admin"}, headers=A).status_code == 200
    assert c.post("/api/auth/login", json={"email": "new@v.com", "password": "long-enough-1"}).json()["user"]["role"] == "admin"
    assert c.patch(f"/api/users/{uid}", json={"password": "another-pass-2"}, headers=A).status_code == 200
    assert c.post("/api/auth/login", json={"email": "new@v.com", "password": "another-pass-2"}).status_code == 200
    me = env["ids"]["admin"]
    assert c.patch(f"/api/users/{me}", json={"role": "user"}, headers=A).status_code == 409
    assert c.patch(f"/api/users/{me}", json={"active": False}, headers=A).status_code == 409
    assert c.delete(f"/api/users/{me}", headers=A).status_code == 409
    assert c.delete(f"/api/users/{uid}", headers=A).status_code == 200


def test_web_11_audit_log_records_changes(env):
    """WEB-11: logins, creates, updates and deletes are written to the audit log with the acting user."""
    c = env["c"]
    cid = _campaign(env, env["U"])
    c.patch(f"/api/campaigns/{cid}", json={"status": "completed"}, headers=env["U"])
    c.delete(f"/api/campaigns/{cid}", headers=env["A"])
    log = c.get("/api/audit", headers=env["A"]).json()
    acts = [(e["action"], e["entity"], e["user_name"]) for e in log]
    assert ("delete", "campaign", "Ada Admin") in acts and ("update", "campaign", "Uma User") in acts
    assert ("create", "campaign", "Uma User") in acts and ("login", "user", "Uma User") in acts


# ---------------------------------------------------------------- demo data, serving, CLI
def test_web_12_demo_data_is_labelled_and_purgeable(env):
    """WEB-12: demo data is all [DEMO]/demo- and --purge removes exactly it, leaving real records alone."""
    from vanguard.web.demo import load_demo, purge_demo
    real = _campaign(env, env["U"], name="Real campaign")
    msg = load_demo(env["s"])
    assert "[DEMO]" in msg
    names = [x["name"] for x in env["c"].get("/api/campaigns", headers=env["U"]).json()]
    assert len(names) == 25 and all(n.startswith("[DEMO]") for n in names if n != "Real campaign")
    purge_demo(env["s"])
    assert [x["id"] for x in env["c"].get("/api/campaigns", headers=env["U"]).json()] == [real]
    assert env["s"].q("SELECT COUNT(*) AS n FROM runs WHERE id LIKE 'demo-%'")[0]["n"] == 0
    assert env["s"].q("SELECT COUNT(*) AS n FROM campaign_results")[0]["n"] == 0


def test_web_13_serving_ui_and_machine_api(env, tmp_path, monkeypatch):
    """WEB-13: the built UI is served for client-side routes, unknown /api paths stay JSON 404, /machine is mounted."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>vanguard ui</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(webapp, "UI_DIST", dist)
    c = TestClient(webapp.create_app())
    assert "vanguard ui" in c.get("/campaigns/12").text and "vanguard ui" in c.get("/").text
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").json()["detail"] == "Not Found"
    assert c.get("/health").json()["ok"] is True and c.get("/machine/health").json() == {"ok": True}


def test_web_14_cli_user_commands(tmp_path):
    """WEB-14: `seed-users` creates one admin and one user with printed random passwords, once; `create-user` adds more."""
    e = {k: v for k, v in os.environ.items()} | {"VANGUARD_DB": str(tmp_path / "c.db"), "PYTHONPATH": str(ROOT)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "vanguard", *a], cwd=ROOT, env=e, capture_output=True, text=True)
    r = run("seed-users")
    assert r.returncode == 0 and "admin@vireoka.com" in r.stdout and "team@vireoka.com" in r.stdout
    pw = next(l.split("password: ")[1].strip() for l in r.stdout.splitlines() if "admin@vireoka.com" in l)
    s = WebStore(tmp_path / "c.db")
    from vanguard.web.security import verify_password
    assert verify_password(pw, s.user_by_email("admin@vireoka.com")["password_hash"])
    assert run("seed-users").returncode != 0
    r = run("create-user", "--email", "sam@v.com", "--name", "Sam", "--role", "admin", "--password", "sams-password-1")
    assert r.returncode == 0 and s.user_by_email("sam@v.com")["role"] == "admin"
    assert run("create-user", "--email", "sam@v.com", "--name", "Sam", "--password", "sams-password-1").returncode != 0


def test_web_15_login_rate_limit(env):
    """WEB-15: 8 failed sign-ins for one email from one client lock it for 15 minutes (429), even with the right password."""
    from vanguard.web.app import _FAILS
    _FAILS.clear()
    c = env["c"]
    codes = [c.post("/api/auth/login", json={"email": "user@v.com", "password": f"bad-{i}"}).status_code for i in range(9)]
    assert codes == [401] * 8 + [429]
    assert c.post("/api/auth/login", json={"email": "user@v.com", "password": USER_PW}).status_code == 429
    assert c.post("/api/auth/login", json={"email": "admin@v.com", "password": ADMIN_PW}).status_code == 200
    _FAILS.clear()


# ---------------------------------------------------------------- partner outreach (v0.4.0)
import email as _email
from email.message import EmailMessage as _EM


def _recommend(env, pid="jodibana"):
    r = env["c"].post("/api/partners/recommend", json={"property_id": pid}, headers=env["A"])
    assert r.status_code == 200, r.text
    return r.json()


def _named(env, seg_name_part="wedding planners", name="Rang Mahal Weddings NJ", email="owner@rangmahal.example"):
    c = env["c"]
    seg = next(p for p in c.get("/api/partners?property_id=jodibana", headers=env["U"]).json()
               if seg_name_part in p["name"].lower() and p["is_segment"])
    r = c.post(f"/api/partners/{seg['id']}/targets", json={"name": name, "contact_name": "Meera Shah",
                                                           "contact_email": email}, headers=env["U"])
    assert r.status_code == 201, r.text
    return seg, r.json()["id"]


def test_web_16_expert_recommends_and_prioritises_partners(env):
    """WEB-16: for Jodibana the expert recommends wedding planners, photographers, destination resorts, venues,
    community organisations and bridal/jewellery partners - scored, ranked P0-P2, each with a 3-step draft sequence;
    it covers design partners and co-selling partners; general users can't trigger it."""
    c = env["c"]
    assert c.post("/api/partners/recommend", json={"property_id": "jodibana"}, headers=env["U"]).status_code == 403
    res = _recommend(env)
    names = " ".join(r["name"].lower() for r in res["recommendations"])
    for want in ("wedding planners", "photographers", "destination wedding resorts", "banquet halls", "temples", "bridal"):
        assert want in names, want
    kinds = {r["kind"] for r in res["recommendations"]}
    assert {"design_partner", "co_sell", "referral_affiliate"} <= kinds
    scores = [r["score"] for r in res["recommendations"]]
    assert scores == sorted(scores, reverse=True) and res["recommendations"][0]["priority"] == "P0"
    assert all(r["lint_status"] != "blocked" for r in res["recommendations"])
    assert res["partners"] == 6 and res["messages"] == 18
    assert _recommend(env)["partners"] == 0                      # idempotent: refreshes, never duplicates
    top = c.get("/api/partners?property_id=jodibana", headers=env["U"]).json()[0]
    assert top["priority"] == "P0" and top["source"] == "agent" and top["how_to_find"]
    detail = c.get(f"/api/partners/{top['id']}", headers=env["U"]).json()
    assert [m["step"] for m in detail["outreach"]] == [1, 2, 3] and detail["factors"]["fit"] >= 1
    assert "{{first_name}}" in detail["outreach"][0]["body"]


def test_web_17_admin_approval_gates_every_send(env, tmp_path, monkeypatch):
    """WEB-17: nothing sends until an admin approves; segments can't be emailed; named targets inherit drafts;
    outbox mode writes an .eml with the compliance footer and List-Unsubscribe; step 2 waits for its delay."""
    monkeypatch.setenv("VANGUARD_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("VANGUARD_SENDER_NAME", "Narendra Gore")
    monkeypatch.setenv("VANGUARD_SENDER_EMAIL", "partners@vireoka.com")
    monkeypatch.setenv("VANGUARD_SENDER_ADDRESS", "123 Example Ave, Minneapolis, MN")
    c, A = env["c"], env["A"]
    _recommend(env)
    seg, pid = _named(env)
    seg_msgs = c.get(f"/api/outreach?partner_id={seg['id']}", headers=A).json()
    res = c.post("/api/outreach/approve", json={"ids": [seg_msgs[0]["id"]]}, headers=A).json()
    assert res["approved"] == [] and "segment" in res["refused"][0]["reason"]
    msgs = c.get(f"/api/outreach?partner_id={pid}", headers=A).json()
    assert len(msgs) == 3 and {m["status"] for m in msgs} == {"draft"}
    assert c.post("/api/outreach/approve", json={"ids": [m["id"] for m in msgs]}, headers=env["U"]).status_code == 403
    assert c.post("/api/outreach/send-due", headers=env["U"]).status_code == 403
    assert c.post("/api/outreach/send-due", headers=A).json()["sent"] == []          # nothing approved yet
    assert c.post("/api/outreach/approve", json={"ids": [m["id"] for m in msgs]}, headers=A).json()["approved"] == [m["id"] for m in msgs]
    out = c.post("/api/outreach/send-due", headers=A).json()
    assert [(m["step"], m["to"]) for m in out["sent"]] == [(1, "owner@rangmahal.example")] and out["mode"] == "outbox"
    assert any(s["step"] == 2 and s["reason"].startswith("due ") for s in out["skipped"])
    eml = next((tmp_path / "out" / "outbox").glob("*.eml"))
    m = _email.message_from_bytes(eml.read_bytes(), policy=_email.policy.default)
    body = m.get_body().get_content()
    assert m["To"] == "owner@rangmahal.example" and "Rang Mahal Weddings NJ" in m["Subject"]
    assert body.startswith("Hi Meera,") and "123 Example Ave" in body and "unsubscribe" in body.lower()
    assert "{{" not in body and m["List-Unsubscribe"] == "<mailto:partners@vireoka.com?subject=unsubscribe>"
    p = c.get(f"/api/partners/{pid}", headers=A).json()
    assert p["stage"] == "contacted" and p["interactions"][0]["summary"].startswith("Sent step 1")
    # step 2 goes out once its delay has passed, threaded under step 1
    from vanguard.outreach import send_due
    from datetime import datetime, timedelta, timezone
    later = send_due(env["s"], at=datetime.now(timezone.utc) + timedelta(days=5))
    assert [x["step"] for x in later["sent"]] == [2]
    sent2 = env["s"].one("SELECT message_id FROM outreach_messages WHERE partner_id=? AND step=1", (pid,))["message_id"]
    m2 = [_email.message_from_bytes(f.read_bytes(), policy=_email.policy.default) for f in (tmp_path / "out" / "outbox").glob("*.eml")]
    assert any(x["In-Reply-To"] == sent2 for x in m2)


def test_web_18_editing_needs_reapproval_and_lint_blocks(env):
    """WEB-18: editing a message resets it to draft; copy that breaks the claim rules is blocked and can't be approved."""
    c, A = env["c"], env["A"]
    _recommend(env)
    _, pid = _named(env)
    m1 = c.get(f"/api/outreach?partner_id={pid}", headers=A).json()[0]
    c.post("/api/outreach/approve", json={"ids": [m1["id"]]}, headers=A)
    r = c.patch(f"/api/outreach/{m1['id']}", json={"body": "Hi {{first_name}}, we guarantee a match in 30 days for every family you refer to us."}, headers=env["U"]).json()
    assert r["lint_status"] == "blocked" and any(f["rule_id"] == "no-guaranteed-match" for f in r["lint_findings"])
    m = c.get(f"/api/outreach?partner_id={pid}", headers=A).json()[0]
    assert m["status"] == "draft" and m["approved_by"] is None
    assert "lint" in c.post("/api/outreach/approve", json={"ids": [m1["id"]]}, headers=A).json()["refused"][0]["reason"]


def test_web_19_replies_stop_sequence_and_move_stage(env, tmp_path, monkeypatch):
    """WEB-19: an IMAP reply threaded to our email is matched, stops the remaining steps, logs the reply and moves the
    partner to in_conversation; duplicates are ignored; an opt-out suppresses the address for good; a bounce too."""
    monkeypatch.setenv("VANGUARD_OUTPUT", str(tmp_path / "out"))
    c, A, s = env["c"], env["A"], env["s"]
    _recommend(env)
    _, pid = _named(env)
    _, pid2 = _named(env, "photographers", "Lens & Lehenga Studio", "hello@lenslehenga.example")
    _, pid3 = _named(env, "banquet", "Royal Albert's Palace", "events@rap.example")
    ids = [m["id"] for m in c.get("/api/outreach?status=draft", headers=A).json() if m["partner_id"] in (pid, pid2, pid3)]
    c.post("/api/outreach/approve", json={"ids": ids}, headers=A)
    sent = c.post("/api/outreach/send-due", headers=A).json()["sent"]
    assert len(sent) == 3
    mid = lambda p: s.one("SELECT message_id FROM outreach_messages WHERE partner_id=? AND step=1", (p,))["message_id"]

    def mk(frm, text, reply_to=None, msgid=None):
        e = _EM(); e["From"] = frm; e["To"] = "partners@vireoka.com"; e["Subject"] = "Re: partnership idea"
        e["Message-ID"] = msgid or _email.utils.make_msgid(); e.set_content(text)
        if reply_to:
            e["In-Reply-To"] = reply_to
        return _email.message_from_bytes(bytes(e), policy=_email.policy.default)

    inbox = [mk("Meera Shah <owner@rangmahal.example>", "Sounds good - let's talk Thursday.\n\nOn Mon, X wrote:\n> old", mid(pid), "<r1@x>"),
             mk("Meera Shah <owner@rangmahal.example>", "Sounds good", mid(pid), "<r1@x>"),              # duplicate
             mk("hello@lenslehenga.example", "Please unsubscribe me.", None, "<r2@x>"),                     # matched by address
             mk("MAILER-DAEMON@mx.example", f"Delivery failed for {mid(pid3)}", None, "<b1@x>"),
             mk("stranger@else.example", "hi", None, "<r3@x>")]
    from vanguard.outreach import sync_replies
    st = sync_replies(s, fetch=lambda cfg: inbox)
    assert st == {"matched": 2, "bounces": 1, "unmatched": 1, "duplicates": 1}
    p = c.get(f"/api/partners/{pid}", headers=A).json()
    assert p["stage"] == "in_conversation" and p["interactions"][0]["summary"].startswith("Reply: Sounds good - let's talk Thursday.")
    assert "old" not in p["interactions"][0]["summary"] and p["interactions"][0]["outcome"] == "positive"
    assert [m["status"] for m in p["outreach"]] == ["replied", "cancelled", "cancelled"]
    supp = {r["email"]: r["reason"] for r in s.q("SELECT * FROM email_suppression")}
    assert supp == {"hello@lenslehenga.example": "opt-out", "events@rap.example": "bounce"}
    assert c.get(f"/api/partners/{pid2}", headers=A).json()["next_step"] == "Opted out - do not contact"
    stats = c.get("/api/outreach/stats", headers=env["U"]).json()
    assert stats["partners_contacted"] == 3 and stats["partners_replied"] == 2 and stats["suppressed"] == 2
    assert c.post("/api/outreach/sync-replies", headers=A).status_code == 409          # no IMAP configured -> clear message


def test_web_20_manual_reply_and_agreement_on_dashboard(env):
    """WEB-20: a reply received by phone/LinkedIn is recorded by any user; marking the agreement signed moves the
    partner to signed, cancels queued outreach and shows on the dashboard."""
    c, A = env["c"], env["A"]
    _recommend(env)
    _, pid = _named(env)
    r = c.post(f"/api/partners/{pid}/reply", json={"date": "2026-09-28", "summary": "Called back - interested in the referral terms.",
                                                   "kind": "call"}, headers=env["U"]).json()
    assert r["classification"] == "positive" and r["stage"] == "in_conversation" and r["cancelled_steps"] == 3
    assert c.patch(f"/api/partners/{pid}", json={"agreement_status": "negotiating"}, headers=env["U"]).status_code == 200
    c.patch(f"/api/partners/{pid}", json={"agreement_status": "signed", "agreement_notes": "12% referral, 12 months"}, headers=env["U2"])
    p = c.get(f"/api/partners/{pid}", headers=A).json()
    assert p["stage"] == "signed" and p["agreement_signed_date"] and p["agreement_notes"].startswith("12%")
    jb = next(x for x in c.get("/api/dashboard", headers=env["U"]).json()["properties"] if x["property_id"] == "jodibana")
    assert jb["agreements"]["signed"] == 1 and jb["partners"]["signed"] == 1
    assert c.patch(f"/api/partners/{pid}", json={"agreement_status": "maybe"}, headers=A).status_code == 422


def test_web_21_smtp_mode_refuses_without_compliance_details_and_respects_cap(env, tmp_path, monkeypatch):
    """WEB-21: smtp mode won't send without sender name/email/postal address; the daily cap holds; send failures are
    recorded and don't stop the rest of the queue."""
    c, A, s = env["c"], env["A"], env["s"]
    monkeypatch.setenv("VANGUARD_EMAIL_MODE", "smtp")
    _recommend(env)
    _, pid = _named(env)
    c.post("/api/outreach/approve", json={"ids": [m["id"] for m in c.get(f"/api/outreach?partner_id={pid}", headers=A).json()]}, headers=A)
    r = c.post("/api/outreach/send-due", headers=A)
    assert r.status_code == 409 and "VANGUARD_SENDER_ADDRESS" in r.json()["detail"]
    from vanguard.outreach import EmailConfig, send_due
    cfg = EmailConfig.from_env()
    cfg.mode, cfg.daily_cap = "outbox", 0
    cfg.outbox_dir = tmp_path / "ob"
    assert "daily cap" in send_due(s, cfg)["skipped"][0]["reason"]

    class Boom:
        def send(self, e):
            raise OSError("connection refused")
    cfg.daily_cap = 5
    res = send_due(s, cfg, mailer=Boom())
    assert res["sent"] == [] and "send failed" in res["skipped"][0]["reason"]
    assert s.one("SELECT status FROM outreach_messages WHERE partner_id=? AND step=1", (pid,))["status"] == "failed"


def test_web_22_cli_partner_recommendations(tmp_path):
    """WEB-22: `vanguard partners recommend jodibana` prints the ranked plan at $0 and stores partners + drafts."""
    e = {k: v for k, v in os.environ.items()} | {"VANGUARD_DB": str(tmp_path / "c.db"), "PYTHONPATH": str(ROOT)}
    r = subprocess.run([sys.executable, "-m", "vanguard", "partners", "recommend", "jodibana"], cwd=ROOT, env=e,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "1 P0" in r.stdout and "wedding planners" in r.stdout.lower()
    r = subprocess.run([sys.executable, "-m", "vanguard", "outreach", "status"], cwd=ROOT, env=e, capture_output=True, text=True)
    assert "outbox" in r.stdout and '"draft": 0' in r.stdout     # segment templates aren't in the sending queue
    s = WebStore(tmp_path / "c.db")
    assert s.one("SELECT COUNT(*) AS n FROM outreach_messages")["n"] == 18 and \
        s.one("SELECT COUNT(*) AS n FROM partners WHERE is_segment=1")["n"] == 6


# ---------------------------------------------------------------- Postmark streams (v0.5.0)
import base64 as _b64

import httpx as _httpx


class FakePostmark:
    """Records every Postmark API call; answers like api.postmarkapp.com."""

    def __init__(self, streams=None, remote_suppressed=()):
        self.calls, self.n = [], 0
        self.streams = streams or [{"ID": "outbound", "MessageStreamType": "Transactional"},
                                   {"ID": "partners", "MessageStreamType": "Transactional"},
                                   {"ID": "inbound", "MessageStreamType": "Inbound"}]
        self.remote = list(remote_suppressed)

    def __call__(self, req: _httpx.Request):
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, req.url.path, body, req.headers.get("X-Postmark-Server-Token")))
        if req.url.path == "/email":
            self.n += 1
            return _httpx.Response(200, json={"ErrorCode": 0, "Message": "OK", "MessageID": f"pm-{self.n}", "To": body["To"]})
        if req.url.path == "/message-streams":
            return _httpx.Response(200, json={"MessageStreams": self.streams, "TotalCount": len(self.streams)})
        if req.url.path.endswith("/suppressions/dump"):
            return _httpx.Response(200, json={"Suppressions": [{"EmailAddress": e, "SuppressionReason": "HardBounce"}
                                                               for e in self.remote]})
        if req.url.path.endswith("/suppressions"):
            return _httpx.Response(200, json={"Suppressions": [{"EmailAddress": s["EmailAddress"], "Status": "Suppressed"}
                                                               for s in body["Suppressions"]]})
        return _httpx.Response(404, json={"ErrorCode": 404, "Message": "not found"})

    def emails(self, stream=None):
        return [b for m, p, b, _ in self.calls if p == "/email" and (stream is None or b["MessageStream"] == stream)]


@pytest.fixture
def pm(env, monkeypatch, tmp_path):
    fake = FakePostmark()
    monkeypatch.setattr("vanguard.postmark.TRANSPORT", _httpx.MockTransport(fake))
    for k, v in {"VANGUARD_EMAIL_MODE": "postmark", "POSTMARK_SERVER_TOKEN": "pm-test-token",
                 "VANGUARD_POSTMARK_STREAM_OUTREACH": "partners", "VANGUARD_POSTMARK_STREAM_NOTIFY": "outbound",
                 "VANGUARD_POSTMARK_INBOUND_ADDRESS": "reply@inbound.vireoka.example",
                 "VANGUARD_SENDER_NAME": "Narendra Gore", "VANGUARD_SENDER_EMAIL": "partners@vireoka.com",
                 "VANGUARD_SENDER_ADDRESS": "123 Example Ave, Minneapolis, MN", "VANGUARD_OUTPUT": str(tmp_path / "out"),
                 "VANGUARD_POSTMARK_WEBHOOK_USER": "pmhook", "VANGUARD_POSTMARK_WEBHOOK_PASSWORD": "s3cret-hook"}.items():
        monkeypatch.setenv(k, v)
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "VANGUARD_POSTMARK_ALLOW_COLD", "VANGUARD_POSTMARK_MONTHLY_CAP"):
        monkeypatch.delenv(k, raising=False)
    return fake


def _approved_pair(env):
    c, A = env["c"], env["A"]
    _recommend(env)
    _, pid = _named(env)
    _, pid2 = _named(env, "photographers", "Lens & Lehenga Studio", "hello@lenslehenga.example")
    ids = [m["id"] for m in c.get("/api/outreach?status=draft", headers=A).json() if m["partner_id"] in (pid, pid2)]
    assert len(c.post("/api/outreach/approve", json={"ids": ids}, headers=A).json()["approved"]) == 6
    return pid, pid2


HOOK = {"Authorization": "Basic " + _b64.b64encode(b"pmhook:s3cret-hook").decode()}


def test_web_23_postmark_streams_consent_routing_and_payload(env, pm):
    """WEB-23: in postmark mode cold first touches are held (or go via your SMTP mailbox) because Postmark only allows
    permission-based email; partners who opted in go through the outreach stream with Metadata, Tag, a +o<id> Reply-To,
    List-Unsubscribe and no tracking; the monthly cap holds; VANGUARD_POSTMARK_ALLOW_COLD overrides."""
    c, A, s = env["c"], env["A"], env["s"]
    pid, pid2 = _approved_pair(env)
    out = c.post("/api/outreach/send-due", headers=A).json()
    assert out["sent"] == [] and pm.emails() == []
    assert all("permission-based" in x["reason"] for x in out["skipped"] if x["step"] == 1)
    assert c.patch(f"/api/partners/{pid}", json={"email_consent": "opted_in"}, headers=env["U"]).status_code == 200
    out = c.post("/api/outreach/send-due", headers=A).json()
    assert [(x["step"], x["transport"]) for x in out["sent"]] == [(1, "postmark")]
    m1 = s.one("SELECT * FROM outreach_messages WHERE partner_id=? AND step=1", (pid,))
    assert m1["transport"] == "postmark" and m1["pm_message_id"] == "pm-1" and m1["status"] == "sent"
    p = pm.emails("partners")[0]
    assert p["To"] == "owner@rangmahal.example" and p["From"] == "Narendra Gore <partners@vireoka.com>"
    assert p["Tag"] == "jodibana" and p["Metadata"]["outreach_id"] == str(m1["id"]) and p["Metadata"]["partner_id"] == str(pid)
    assert p["ReplyTo"] == f"reply+o{m1['id']}@inbound.vireoka.example"
    assert p["TrackOpens"] is False and p["TrackLinks"] == "None" and "123 Example Ave" in p["TextBody"]
    # one-click unsubscribe goes to the inbound stream too, so opt-outs are processed automatically
    assert {"Name": "List-Unsubscribe", "Value": f"<mailto:reply+o{m1['id']}@inbound.vireoka.example?subject=unsubscribe>"} in p["Headers"]
    assert pm.calls[0][3] == "pm-test-token"
    # hybrid: the cold partner goes out through your own mailbox instead
    from vanguard.outreach import EmailConfig, send_due

    class Smtp:
        transport_name, sent = "smtp", []

        def send(self, e, meta=None):
            self.sent.append(e["To"])
    cold = Smtp()
    res = send_due(s, EmailConfig.from_env(), cold_mailer=cold)
    assert [(x["to"], x["transport"]) for x in res["sent"]] == [("hello@lenslehenga.example", "smtp")] and len(pm.emails()) == 1
    # monthly cap (counts outreach + notifications on Postmark this month)
    from datetime import datetime, timedelta, timezone
    cfg = EmailConfig.from_env()
    cfg.postmark_monthly_cap = 1
    res = send_due(s, cfg, at=datetime.now(timezone.utc) + timedelta(days=5))
    assert any("monthly cap" in x["reason"] for x in res["skipped"] if x["step"] == 2 and x["partner"] == "Rang Mahal Weddings NJ")
    # allow_cold: an explicit opt-in to send first touches through Postmark
    _, pid3 = _named(env, "banquet", "Royal Albert's Palace", "events@rap.example")
    c.post("/api/outreach/approve", json={"ids": [m["id"] for m in c.get(f"/api/outreach?partner_id={pid3}", headers=A).json()]}, headers=A)
    cfg = EmailConfig.from_env()
    cfg.postmark_allow_cold = True
    res = send_due(s, cfg)
    assert ("events@rap.example", "postmark") in [(x["to"], x["transport"]) for x in res["sent"]]
    st = c.get("/api/outreach/stats", headers=env["U"]).json()["email"]
    assert st["mode"] == "postmark" and st["live"] and st["postmark"]["stream_outreach"] == "partners"
    assert st["postmark"]["used_this_month"] >= 2 and st["postmark"]["monthly_cap"] == 100


def test_web_24_postmark_webhooks(env, pm, monkeypatch):
    """WEB-24: /hooks/postmark needs Basic Auth (503 when unset); Delivery and Open are recorded; a hard bounce and a
    spam complaint suppress the address and stop the sequence; SubscriptionChange syncs; an Inbound reply matched by
    its MailboxHash stops the sequence, marks consent 'replied', and alerts the team on the notify stream."""
    c, A, s = env["c"], env["A"], env["s"]
    pid, pid2 = _approved_pair(env)
    for p in (pid, pid2):
        c.patch(f"/api/partners/{p}", json={"email_consent": "existing_relationship"}, headers=A)
    sent = c.post("/api/outreach/send-due", headers=A).json()["sent"]
    assert len(sent) == 2
    m1 = s.one("SELECT * FROM outreach_messages WHERE partner_id=? AND step=1", (pid,))
    m2 = s.one("SELECT * FROM outreach_messages WHERE partner_id=? AND step=1", (pid2,))
    assert c.post("/hooks/postmark", json={"RecordType": "Delivery"}).status_code == 401
    assert c.post("/hooks/postmark", json={"RecordType": "Delivery"},
                  headers={"Authorization": "Basic " + _b64.b64encode(b"pmhook:wrong").decode()}).status_code == 401
    r = c.post("/hooks/postmark", json={"RecordType": "Delivery", "MessageID": m1["pm_message_id"],
                                        "DeliveredAt": "2026-09-27T10:00:00Z", "Recipient": m1["to_email"]}, headers=HOOK)
    assert r.json() == {"handled": "delivery", "matched": True}
    c.post("/hooks/postmark", json={"RecordType": "Open", "MessageID": m1["pm_message_id"], "ReceivedAt": "2026-09-27T11:00:00Z"}, headers=HOOK)
    row = s.one("SELECT delivered_at, opened_at FROM outreach_messages WHERE id=?", (m1["id"],))
    assert row == {"delivered_at": "2026-09-27T10:00:00Z", "opened_at": "2026-09-27T11:00:00Z"}
    # inbound reply to partner 1, matched by the +o<id> mailbox hash
    inbound = {"FromFull": {"Email": "owner@rangmahal.example", "Name": "Meera Shah"}, "MailboxHash": f"o{m1['id']}",
               "Subject": "Re: partnership", "MessageID": "in-1", "TextBody": "Sounds good, let's talk Thursday.\n> old",
               "StrippedTextReply": "Sounds good, let's talk Thursday."}
    r = c.post("/hooks/postmark", json=inbound, headers=HOOK).json()
    assert r["handled"] == "inbound" and r["matched"] and r["classification"] == "positive"
    assert c.post("/hooks/postmark", json=inbound, headers=HOOK).json()["duplicate"] is True
    p = c.get(f"/api/partners/{pid}", headers=A).json()
    assert p["stage"] == "in_conversation" and p["email_consent"] == "replied"
    assert [m["status"] for m in p["outreach"]] == ["replied", "cancelled", "cancelled"]
    alert = pm.emails("outbound")[-1]            # admins + the partner owner (Uma added the target)
    assert alert["To"] == "admin@v.com, user@v.com" and "Rang Mahal Weddings NJ" in alert["Subject"] and "Thursday" in alert["TextBody"]
    assert s.one("SELECT kind, transport FROM notification_log") == {"kind": "reply", "transport": "postmark"}
    # spam complaint on partner 2: suppress + stop + opted_out
    r = c.post("/hooks/postmark", json={"RecordType": "SpamComplaint", "MessageID": m2["pm_message_id"],
                                        "Email": "hello@lenslehenga.example", "Metadata": {"outreach_id": str(m2["id"])}}, headers=HOOK)
    assert r.json()["matched"]
    p2 = c.get(f"/api/partners/{pid2}", headers=A).json()
    assert p2["email_consent"] == "opted_out" and {m["status"] for m in p2["outreach"][1:]} == {"cancelled"}
    # hard bounce vs soft bounce
    _, pid3 = _named(env, "banquet", "Royal Albert's Palace", "events@rap.example")
    c.patch(f"/api/partners/{pid3}", json={"email_consent": "opted_in"}, headers=A)
    c.post("/api/outreach/approve", json={"ids": [m["id"] for m in c.get(f"/api/outreach?partner_id={pid3}", headers=A).json()]}, headers=A)
    c.post("/api/outreach/send-due", headers=A)
    m3 = s.one("SELECT * FROM outreach_messages WHERE partner_id=? AND step=1", (pid3,))
    soft = c.post("/hooks/postmark", json={"RecordType": "Bounce", "Type": "SoftBounce", "MessageID": m3["pm_message_id"],
                                           "Email": "events@rap.example"}, headers=HOOK).json()
    assert soft["hard"] is False and s.one("SELECT status FROM outreach_messages WHERE id=?", (m3["id"],))["status"] == "sent"
    c.post("/hooks/postmark", json={"RecordType": "Bounce", "Type": "HardBounce", "MessageID": m3["pm_message_id"],
                                    "Email": "events@rap.example", "Description": "mailbox does not exist"}, headers=HOOK)
    assert s.one("SELECT status FROM outreach_messages WHERE id=?", (m3["id"],))["status"] == "bounced"
    supp = {r["email"]: r["reason"] for r in s.q("SELECT * FROM email_suppression")}
    assert supp == {"hello@lenslehenga.example": "spam-complaint", "events@rap.example": "bounce"}
    # subscription change (e.g. a manual suppression in Postmark, then reactivation)
    c.post("/hooks/postmark", json={"RecordType": "SubscriptionChange", "Recipient": "x@y.example", "SuppressSending": True}, headers=HOOK)
    assert s.one("SELECT reason FROM email_suppression WHERE email='x@y.example'")["reason"] == "postmark-suppression"
    c.post("/hooks/postmark", json={"RecordType": "SubscriptionChange", "Recipient": "x@y.example", "SuppressSending": False}, headers=HOOK)
    assert s.one("SELECT 1 FROM email_suppression WHERE email='x@y.example'") is None
    assert c.post("/hooks/postmark", json={"RecordType": "LinkClick"}, headers=HOOK).json()["handled"] == "ignored"
    monkeypatch.delenv("VANGUARD_POSTMARK_WEBHOOK_PASSWORD")
    assert c.post("/hooks/postmark", json={"RecordType": "Delivery"}, headers=HOOK).status_code == 503


def test_web_25_postmark_admin_suppression_sync_streams_digest(env, pm, monkeypatch):
    """WEB-25: admins check streams (missing / non-transactional), sync suppressions both ways and email an approval
    digest on the notify stream; a manual 'opted out' consent suppresses the address; general users get 403."""
    c, A, U, s = env["c"], env["A"], env["U"], env["s"]
    for path in ("/api/outreach/postmark-sync", "/api/outreach/digest"):
        assert c.post(path, headers=U).status_code == 403
    assert c.get("/api/email/postmark", headers=U).status_code == 403
    st = c.get("/api/email/postmark", headers=A).json()
    assert st["ok"] and st["streams"]["partners"] == "Transactional" and st["used_this_month"] == 0
    monkeypatch.setenv("VANGUARD_POSTMARK_STREAM_NOTIFY", "broadcast")
    pm.streams.append({"ID": "broadcast", "MessageStreamType": "Broadcasts"})
    st = c.get("/api/email/postmark", headers=A).json()
    assert not st["ok"] and "broadcast is a Broadcasts stream" in st["not_transactional"][0]
    monkeypatch.setenv("VANGUARD_POSTMARK_STREAM_NOTIFY", "outbound")
    # suppression sync: pull Postmark's, push ours
    pm.remote = ["bounced@remote.example"]
    _recommend(env)
    _, pid = _named(env)
    assert c.patch(f"/api/partners/{pid}", json={"email_consent": "opted_out"}, headers=U).status_code == 200
    assert {m["status"] for m in c.get(f"/api/partners/{pid}", headers=A).json()["outreach"]} == {"cancelled"}
    r = c.post("/api/outreach/postmark-sync", headers=A).json()
    assert r == {"stream": "partners", "pulled": 1, "pushed": 1, "remote_total": 1}
    pushed = [b for m, p, b, _ in pm.calls if m == "POST" and p == "/message-streams/partners/suppressions"][0]
    assert pushed == {"Suppressions": [{"EmailAddress": "owner@rangmahal.example"}]}
    assert s.one("SELECT reason FROM email_suppression WHERE email='bounced@remote.example'")["reason"] == "postmark:HardBounce"
    # digest to admins on the notify stream
    _named(env, "photographers", "Lens & Lehenga Studio", "hello@lenslehenga.example")
    d = c.post("/api/outreach/digest", headers=A).json()
    assert d == {"sent": 1, "transport": "postmark"}
    mail = pm.emails("outbound")[-1]
    assert mail["To"] == "admin@v.com" and "3 partner emails awaiting approval" in mail["Subject"]
    assert "Lens & Lehenga Studio" in mail["TextBody"] and mail["Metadata"] == {"kind": "digest"}
    assert c.get("/api/outreach/stats", headers=U).json()["email"]["postmark"]["used_this_month"] == 1
    monkeypatch.delenv("POSTMARK_SERVER_TOKEN")
    monkeypatch.setenv("VANGUARD_EMAIL_MODE", "outbox")
    assert c.get("/api/email/postmark", headers=A).status_code == 409
    assert c.post("/api/outreach/digest", headers=A).json()["transport"] == "outbox"


# ---------------------------------------------------------------- researched partners (v0.6.0)
def test_web_26_import_researched_partners(env):
    """WEB-26: admins load config/partner_targets.yaml: every organisation becomes a named partner (source research)
    under its category with its own 3 draft emails, playbook examples like Fireblocks are enriched instead of
    duplicated, re-running changes nothing, nothing is approved or sent, and general users get 403."""
    c, A, s = env["c"], env["A"], env["s"]
    assert c.post("/api/partners/import-research", headers=env["U"]).status_code == 403
    r = c.post("/api/partners/import-research", headers=A).json()
    assert r["errors"] == []
    from vanguard.targets import load
    data = load()
    total = sum(len(v) for v in data.values())
    assert sum(p["created"] + p["updated"] for p in r["properties"].values()) == total and set(r["properties"]) == set(data)
    assert s.one("SELECT COUNT(*) AS n FROM partners WHERE source='research'")["n"] == total
    fb = s.q("SELECT * FROM partners WHERE property_id='liqmint-institutional' AND name LIKE 'Fireblocks%'")
    assert len(fb) == 1 and fb[0]["source"] == "research" and "Source: https://" in fb[0]["rationale"]
    kp = s.q("SELECT name FROM partners WHERE property_id='liqmint-institutional' AND name LIKE '%KPMG%'")
    assert [x["name"] for x in kp] == ["KPMG"]                          # enriched the playbook example, no duplicate
    iam = s.one("SELECT * FROM partners WHERE property_id='jodibana' AND name='India Association of Minnesota (IAM)'")
    seg = s.one("SELECT * FROM partners WHERE id=?", (iam["parent_id"],))
    assert seg["is_segment"] == 1 and seg["category"] == "community_orgs" and iam["kind"] == "design_partner"
    assert iam["priority"] == "P0" and iam["website"] == "https://iamn.org/" and "iamn.org/contact" in iam["how_to_find"]
    msgs = s.q("SELECT * FROM outreach_messages WHERE partner_id=? ORDER BY step", (iam["id"],))
    assert [m["status"] for m in msgs] == ["draft"] * 3 and "{{company}}" in msgs[0]["subject"] + msgs[0]["body"]
    assert s.one("SELECT COUNT(*) AS n FROM outreach_messages WHERE status!='draft'")["n"] == 0
    # re-run: idempotent, and a hand-entered email is never overwritten
    c.patch(f"/api/partners/{iam['id']}", json={"contact_email": "partnerships@iamn.example"}, headers=A)
    r2 = c.post("/api/partners/import-research", headers=A).json()
    assert all(p["created"] == 0 for p in r2["properties"].values())
    assert s.one("SELECT COUNT(*) AS n FROM partners WHERE source='research'")["n"] == total
    assert s.one("SELECT contact_email FROM partners WHERE id=?", (iam["id"],))["contact_email"] == "partnerships@iamn.example"
    listed = c.get("/api/partners?property_id=jodibana", headers=env["U"]).json()
    assert any(p["priority"] == "P0" and p["source"] == "research" for p in listed)


def test_web_27_researched_targets_file_quality(tmp_path):
    """WEB-27: config/partner_targets.yaml is well-formed: known property + category, https website/evidence/contact
    links, valid inbox format, no duplicate names; the CLI imports it at $0."""
    import re
    import yaml
    from vanguard.targets import load
    pp = yaml.safe_load((ROOT / "config" / "partner_playbooks.yaml").read_text(encoding="utf-8"))
    cats = {pid: {c["id"] for c in v["categories"]} for pid, v in (pp.get("properties") or pp).items()
            if isinstance(v, dict) and "categories" in v}
    seen = set()
    for pid, items in load().items():
        assert pid in cats and len(items) >= 10, pid
        for t in items:
            assert t["category"] in cats[pid], (pid, t["name"])
            assert (pid, t["name"].lower()) not in seen
            seen.add((pid, t["name"].lower()))
            for k in ("evidence_url", "contact_url"):
                assert t[k].startswith("https://"), (t["name"], k)
            assert t.get("website") is None or t["website"].startswith("https://")
            assert t["why"] and t["priority_hint"] in ("P0", "P1", "P2") and t["confidence"] in ("high", "medium")
            if t.get("contact_email"):
                assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", t["contact_email"].lower())
            for person in t.get("contacts") or []:      # named people always carry the source that shows the role
                assert person["name"] and person["title"] and person["source"].startswith("https://"), t["name"]
                assert person["confidence"] in ("high", "medium") and "@" not in str(person)
            if t.get("recent_hook"):
                assert t["recent_hook_url"].startswith("https://"), t["name"]
    e = {k: v for k, v in os.environ.items()} | {"VANGUARD_DB": str(tmp_path / "c.db"), "PYTHONPATH": str(ROOT)}
    r = subprocess.run([sys.executable, "-m", "vanguard", "partners", "import"], cwd=ROOT, env=e, capture_output=True, text=True)
    assert r.returncode == 0 and "researched organisations added" in r.stdout and "problem" not in r.stdout, r.stdout + r.stderr


def test_failproof_tracker_readings_and_gates(env):
    """WEB-28: everyone sees the tripwire tracker and can record readings; only admins pass or fail gates; unknown
    tripwires and gates are refused; a failed gate returns its walk-away condition."""
    c, A, U = env["c"], env["A"], env["U"]
    t = c.get("/api/failproof", params={"as_of": "2026-10-16"}, headers=U).json()
    assert t["week"] == 3 and len(t["properties"]) == 8
    r = c.post("/api/failproof/liqmint-institutional/readings",
               json={"tripwire_id": "TW-3", "value": 8, "date": "2026-10-15"}, headers=U)
    assert r.status_code == 201
    assert c.post("/api/failproof/liqmint-institutional/readings", json={"tripwire_id": "nope", "value": 1},
                  headers=U).status_code == 422
    p = c.get("/api/failproof", params={"as_of": "2026-10-16", "property_id": "liqmint-institutional"},
              headers=U).json()["properties"][0]
    assert next(w for w in p["tripwires"] if w["id"] == "TW-3")["status"] == "green"
    assert c.put("/api/failproof/liqmint-institutional/gates/G1", json={"status": "passed"}, headers=U).status_code == 403
    r = c.put("/api/failproof/liqmint-institutional/gates/G1", json={"status": "failed"}, headers=A)
    assert r.status_code == 200 and "consulting" in r.json()["walk_away_if"]
    assert c.put("/api/failproof/liqmint-institutional/gates/G9", json={"status": "passed"}, headers=A).status_code == 404
    assert c.get("/api/failproof/liqmint-institutional/premortem", headers=U).status_code == 404


def test_web_29_contacts_new_categories_and_merge_tags(env):
    """WEB-29: researched contacts land on the partner (first named person as contact_name, route and people in
    how_to_find, timely hook in the rationale) without overwriting a hand-entered name; categories added to the
    playbook after a first import get their segment on the next import; drafts keep the {{company}} merge tag and
    sending also fills {company} left in drafts written before v0.8.1."""
    c, A, s = env["c"], env["A"], env["s"]
    assert c.post("/api/partners/import-research", headers=A).json()["errors"] == []
    lead = s.one("SELECT * FROM partners WHERE property_id='liqmint-institutional' AND name='Lead Bank'")
    assert lead["contact_name"] == "Eleni Steinman" and lead["category"] == "stablecoin_banks"
    assert "Person: Eleni Steinman - Head of Stablecoins" in lead["how_to_find"] and "Route:" in lead["how_to_find"]
    assert "Timely hook:" in lead["rationale"] and lead["priority"] == "P0"
    body = s.one("SELECT body FROM outreach_messages WHERE partner_id=? AND step=1", (lead["id"],))["body"]
    assert "{{company}}" in body and "{company}" not in body.replace("{{company}}", "")
    assert s.one("SELECT COUNT(*) AS n FROM outreach_messages WHERE body LIKE '%{company}%' "
                 "AND body NOT LIKE '%{{company}}%'")["n"] == 0
    # tier-1 banks are relationships, not first design partners
    assert s.one("SELECT priority FROM partners WHERE name='BNY (Bank of New York Mellon)'")["priority"] == "P1"
    # a hand-entered name survives a re-import
    c.patch(f"/api/partners/{lead['id']}", json={"contact_name": "Someone Else"}, headers=A)
    c.post("/api/partners/import-research", headers=A)
    assert s.one("SELECT contact_name FROM partners WHERE id=?", (lead["id"],))["contact_name"] == "Someone Else"
    # a category added after the first import: delete its segment and partners, re-import, it comes back
    seg = s.one("SELECT id FROM partners WHERE category='midsize_advisory' AND is_segment=1")
    for r in s.q("SELECT id FROM partners WHERE category='midsize_advisory'"):
        s.delete("partners", "id", r["id"])
    assert c.post("/api/partners/import-research", headers=A).json()["errors"] == []
    assert s.one("SELECT COUNT(*) AS n FROM partners WHERE category='midsize_advisory' AND is_segment=1")["n"] == 1
    assert s.one("SELECT COUNT(*) AS n FROM partners WHERE name='Protiviti'")["n"] == 1 and seg
    # old drafts with single braces still render correctly
    from vanguard.outreach import EmailConfig, render
    out = render("Hi {{first_name}} at {company} / {{company}}", {"contact_name": "Eleni Steinman", "name": "Lead Bank"},
                 EmailConfig.from_env())
    assert out == "Hi Eleni at Lead Bank / Lead Bank"


def test_web_30_campaign_outreach_link(env):
    """WEB-30: partners attach to a campaign (a segment brings its named organisations; another property is
    refused; attaching again moves, not duplicates); sent emails, LinkedIn/X touches, replies and meetings for
    attached partners count towards the campaign automatically and add to hand-logged results; the outreach list
    filters by campaign; deleting the campaign keeps the partners."""
    c, A, U, s = env["c"], env["A"], env["U"], env["s"]
    assert c.post("/api/partners/import-research", headers=A).json()["errors"] == []
    cid = _campaign(env, U, property_id="liqmint-institutional", name="Q4 design partners", goal_metric="replies", goal_value=5)
    cid2 = _campaign(env, U, property_id="liqmint-institutional", name="Advisory co-sell")
    lead = s.one("SELECT id, contact_name FROM partners WHERE name='Lead Bank' AND property_id='liqmint-institutional'")["id"]
    prot = s.one("SELECT id FROM partners WHERE name='Protiviti'")["id"]
    seg = s.one("SELECT id FROM partners WHERE category='midsize_advisory' AND is_segment=1")["id"]
    other = s.one("SELECT id FROM partners WHERE property_id!='liqmint-institutional' LIMIT 1")["id"]
    r = c.post(f"/api/campaigns/{cid}/partners", json={"partner_ids": [lead, other]}, headers=U).json()
    assert [a["id"] for a in r["attached"]] == [lead] and r["refused"][0]["id"] == other
    r = c.post(f"/api/campaigns/{cid2}/partners", json={"partner_ids": [seg]}, headers=U).json()
    kids = {k["id"] for k in s.q("SELECT id FROM partners WHERE parent_id=?", (seg,))}
    assert {a["id"] for a in r["attached"]} == kids and prot in kids
    r = c.post(f"/api/campaigns/{cid}/partners", json={"partner_ids": [prot]}, headers=U).json()
    assert r["moved"][0]["from"] == "Advisory co-sell"
    assert c.post("/api/campaigns/999/partners", json={"partner_ids": [lead]}, headers=U).status_code == 404
    # activity on attached partners
    c.post(f"/api/partners/{lead}/interactions", json={"date": "2026-10-01", "type": "linkedin",
           "summary": "LinkedIn connection request sent", "stage": "contacted"}, headers=U)
    c.post(f"/api/partners/{prot}/interactions", json={"date": "2026-10-02", "type": "x", "summary": "DM on X"}, headers=U)
    c.patch(f"/api/partners/{prot}", json={"contact_email": "claudia@protiviti.example"}, headers=A)
    mids = [m["id"] for m in c.get(f"/api/outreach?campaign_id={cid}", headers=A).json() if m["partner_id"] == prot and m["step"] == 1]
    assert c.post("/api/outreach/approve", json={"ids": mids}, headers=A).json()["approved"] == mids
    sent = c.post("/api/outreach/send-due", headers=A).json()["sent"]
    assert [x["partner"] for x in sent] == ["Protiviti"]
    c.post(f"/api/partners/{prot}/reply", json={"date": "2026-10-03", "summary": "Happy to talk next week", "kind": "email"}, headers=U)
    c.post(f"/api/partners/{prot}/interactions", json={"date": "2026-10-08", "type": "meeting", "summary": "Intro call"}, headers=U)
    c.post(f"/api/campaigns/{cid}/results", json={"date": "2026-10-09", "sent": 10, "replies": 1, "revenue_usd": 0}, headers=U)
    d = c.get(f"/api/campaigns/{cid}", headers=U).json()
    t = d["outreach"]["totals"]
    assert (t["targets"], t["emails_sent"], t["social_touches"], t["touched"], t["replies"], t["meetings"]) == (2, 1, 2, 2, 1, 1)
    assert t["in_conversation"] == 1 and d["outreach"]["queue"]["missing_email"] == 1
    row = next(p for p in d["outreach"]["partners"] if p["id"] == prot)
    assert row["replied"] and row["emails_sent"] == 1 and row["last_touch"] == "2026-10-08"
    lst = {x["id"]: x for x in c.get("/api/campaigns?property_id=liqmint-institutional", headers=U).json()}
    assert (lst[cid]["sent"], lst[cid]["replies"], lst[cid]["meetings"]) == (11, 2, 1)
    assert lst[cid]["outreach_summary"]["targets"] == 2 and lst[cid2]["outreach_summary"]["targets"] == len(kids) - 1
    assert all(m["campaign_id"] == cid for m in c.get(f"/api/outreach?campaign_id={cid}", headers=U).json())
    assert c.get(f"/api/partners/{prot}", headers=U).json()["campaign_name"] == "Q4 design partners"
    # detach, then delete a campaign: partners stay
    assert c.delete(f"/api/campaigns/{cid}/partners/{lead}", headers=U).json() == {"ok": True}
    assert c.delete(f"/api/campaigns/{cid}/partners/{lead}", headers=U).status_code == 404
    assert c.delete(f"/api/campaigns/{cid}", headers=U).json() == {"ok": True}
    assert s.one("SELECT campaign_id FROM partners WHERE id=?", (prot,))["campaign_id"] is None


def test_web_31_linkedin_connections_import(env):
    """WEB-31: any user imports LinkedIn's own Connections.csv export; connections are matched to partners by
    company, shown on the partner page and counted in the partner list; a named contact who is now a connection gets
    one 'Connected on LinkedIn' timeline entry that does not count as a touch; a file that isn't the export is
    refused; each user can delete their own imported connections."""
    c, A, U, s = env["c"], env["A"], env["U"], env["s"]
    c.post("/api/partners/import-research", headers=A)
    export = ("Notes:\n\"When exporting your connection data...\"\n\n"
              "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
              "Eleni,S.,https://www.linkedin.com/in/eleni,,Lead,Head of Stablecoins,02 Oct 2026\n"
              "Pat,Lee,https://www.linkedin.com/in/pl,,U.S. Bank,VP Digital Assets,01 Jan 2021\n"
              "Joe,Bloggs,https://www.linkedin.com/in/jb,,Bank,Teller,01 Jan 2020\n")
    assert c.post("/api/linkedin/connections", json={"csv": "name,company\nA,B\nC,D"}, headers=U).status_code == 400
    r = c.post("/api/linkedin/connections", json={"csv": export}, headers=U).json()
    assert (r["connections"], r["added"]) == (3, 3) and "Lead Bank" in r["contacts_connected"]
    assert c.post("/api/linkedin/connections", json={"csv": export}, headers=U).json()["contacts_connected"] == []
    lead = s.one("SELECT id FROM partners WHERE name='Lead Bank' AND property_id='liqmint-institutional'")["id"]
    p = c.get(f"/api/partners/{lead}", headers=A).json()
    assert [(x["first_name"], x["is_contact"], x["owner_name"]) for x in p["connections"]] == [("Eleni", True, "Uma User")]
    tl = [i for i in p["interactions"] if i["summary"].startswith("Connected on LinkedIn: Eleni S.")]
    assert len(tl) == 1 and tl[0]["type"] == "linkedin" and tl[0]["date"] == "2026-10-02"
    rows = {x["name"]: x for x in c.get("/api/partners?property_id=liqmint-institutional", headers=U).json()}
    assert rows["Lead Bank"]["connections"] == 1 and rows["U.S. Bancorp (U.S. Bank)"]["connections"] == 1
    assert all(x["connections"] == 0 for n, x in rows.items() if n.startswith("BNY"))   # 'Bank' alone matches nothing
    cid = _campaign(env, U, property_id="liqmint-institutional", name="LinkedIn warm intros", kind="social", channel="LinkedIn")
    c.post(f"/api/campaigns/{cid}/partners", json={"partner_ids": [lead]}, headers=U)
    assert c.get(f"/api/campaigns/{cid}", headers=U).json()["outreach"]["totals"]["social_touches"] == 0
    summ = c.get("/api/linkedin/connections", headers=A).json()
    assert summ["by_user"][0]["n"] == 3 and summ["partners_with_connections"] >= 2
    assert c.delete("/api/linkedin/connections", headers=A).json()["deleted"] == 0
    assert c.delete("/api/linkedin/connections", headers=U).json()["deleted"] == 3


def test_web_32_investor_contacts(env):
    """WEB-32: an investor can be tracked as a partner of kind 'investor' (no drafted emails are created), logged
    with an interaction that moves it to contacted, filtered by kind, and an unknown kind is still refused."""
    c, U, s = env["c"], env["U"], env["s"]
    r = c.post("/api/partners", json={"property_id": "vireoka", "name": "Robert Fabbio", "kind": "investor",
                                      "contact_name": "Robert Fabbio", "next_step": "Follow up to schedule a call"}, headers=U)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    c.post(f"/api/partners/{pid}/interactions", json={"date": "2026-10-02", "type": "note", "stage": "contacted",
           "summary": "Reached out about the raise; he is willing to talk"}, headers=U)
    p = c.get(f"/api/partners/{pid}", headers=U).json()
    assert p["kind"] == "investor" and p["stage"] == "contacted" and p["outreach"] == []
    assert [x["name"] for x in c.get("/api/partners?kind=investor", headers=U).json()] == ["Robert Fabbio"]
    assert c.post("/api/partners", json={"property_id": "vireoka", "name": "X Fund", "kind": "lender"}, headers=U).status_code == 422


def test_web_33_investor_targets(env):
    """WEB-33: 'Load researched partners' also loads config/investor_targets.yaml: every investor becomes a partner
    of kind investor under Vireoka with rank, score, priority, the five investor factors, reasons, conference
    considerations and sourced research; no emails are drafted; re-importing refreshes without touching the stage
    or a hand-entered email; the file is well-formed (ranks 1..N, priorities match scores, https sources, no
    unpublished email)."""
    import yaml
    c, A, s = env["c"], env["A"], env["s"]
    data = yaml.safe_load((ROOT / "config" / "investor_targets.yaml").read_text(encoding="utf-8"))
    inv = data["investors"]
    assert data["property_id"] == "vireoka" and len(inv) >= 150
    assert [e["rank"] for e in inv] == list(range(1, len(inv) + 1))
    for e in inv:
        assert e["priority"] == ("P0" if e["score"] >= 75 else "P1" if e["score"] >= 55 else "P2"), e["name"]
        assert set(e["factors"]) == {"thesis", "stage", "check", "geo", "research"}
        for src in (e.get("research") or {}).get("sources", []):
            assert src.startswith("https://"), (e["name"], src)
        em = (e.get("research") or {}).get("published_email")
        assert em is None or re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", em), (e["name"], em)   # a bare address, no notes
    r = c.post("/api/partners/import-research", headers=A).json()
    assert r["investors"]["created"] == len(inv) and r["investors"]["by_priority"]["P0"] >= 5
    top = s.one("SELECT * FROM partners WHERE kind='investor' AND name=?", (inv[0]["name"],))
    assert top["property_id"] == "vireoka" and top["priority"] == "P0" and top["stage"] == "identified"
    assert "Rank #1 of" in top["rationale"] and "Key considerations:" in top["rationale"]
    assert "Sources: https://" in top["how_to_find"]
    assert json.loads(top["factors"])["research"] >= 4
    assert s.one("SELECT COUNT(*) AS n FROM outreach_messages m JOIN partners p ON p.id=m.partner_id "
                 "WHERE p.kind='investor'")["n"] == 0
    c.patch(f"/api/partners/{top['id']}", json={"stage": "contacted", "contact_email": "me@fund.example"}, headers=A)
    r = c.post("/api/partners/import-research", headers=A).json()
    assert r["investors"]["created"] == 0 and r["investors"]["updated"] == len(inv)
    row = s.one("SELECT stage, contact_email FROM partners WHERE id=?", (top["id"],))
    assert (row["stage"], row["contact_email"]) == ("contacted", "me@fund.example")


def _linkedin_zip(extra_rows: str = "") -> str:
    import base64
    import io as _io
    import zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("Connections.csv", "Notes:\n\"export notes\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                   "Sam,Okafor,https://www.linkedin.com/in/sam-okafor,sam@lead.example,Lead,VP Treasury Operations,03 Mar 2019\n"
                   "Eleni,S.,https://www.linkedin.com/in/eleni,,Lead,Head of Stablecoins,02 Oct 2026\n"
                   "Andrea,Volk,https://www.linkedin.com/in/avolk,,TA Ventures,Partner,05 May 2018\n"
                   "Joe,Bloggs,https://www.linkedin.com/in/jb,,Acme Widgets,Engineer,01 Jan 2020\n" + extra_rows)
        z.writestr("messages.csv", "\"CONVERSATION ID\",\"CONVERSATION TITLE\",\"FROM\",\"SENDER PROFILE URL\",\"TO\",\"RECIPIENT PROFILE URLS\",\"DATE\",\"SUBJECT\",\"CONTENT\",\"FOLDER\",\"ATTACHMENTS\"\n"
                   + "".join(f"\"c{i}\",\"\",\"Me\",\"https://www.linkedin.com/in/me\",\"X\",\"https://www.linkedin.com/in/{u}\",\"2026-09-{10 + i % 9:02d} 10:00:00 UTC\",\"\",\"private text\",\"INBOX\",\"\"\n"
                             for i, u in enumerate(["sam-okafor"] * 6 + ["avolk"] * 12))
                   + "\"c99\",\"\",\"Andrea Volk\",\"https://www.linkedin.com/in/avolk\",\"Me\",\"https://www.linkedin.com/in/me\",\"2026-09-30 10:00:00 UTC\",\"\",\"hi\",\"INBOX\",\"\"\n")
        z.writestr("Endorsement_Received_Info.csv", "Endorsement Date,Skill Name,Endorser First Name,Endorser Last Name,Endorser Public Url,Endorsement Status\n"
                   "2024/01/01 10:00:00 UTC,Fintech,Andrea,Volk,www.linkedin.com/in/avolk,ACCEPTED\n")
    return "data:application/zip;base64," + base64.b64encode(buf.getvalue()).decode()


def test_web_34_introductions(env):
    """WEB-34: the full LinkedIn export (.zip) loads connections with tie strength from message counts and
    endorsements (message text is not stored); Find paths proposes an insider at a target and a likely bridge for an
    investor, never the target person themselves; an ask is drafted as a double opt-in note with a forwardable
    blurb; only an admin approves; approved asks are emailed when the connector shared an email, otherwise held for
    LinkedIn and marked sent by hand; outcomes log on the partner and an introduction moves it to contacted."""
    c, A, U, s = env["c"], env["A"], env["U"], env["s"]
    c.post("/api/partners/import-research", headers=A)
    assert c.post("/api/linkedin/export", json={"zip_b64": "data:application/zip;base64,bm90IGEgemlw"}, headers=U).status_code == 400
    r = c.post("/api/linkedin/export", json={"zip_b64": _linkedin_zip()}, headers=U).json()
    assert r["connections"] == 4 and r["with_messages"] == 2 and r["warm"] >= 1
    sam = s.one("SELECT * FROM linkedin_connections WHERE first_name='Sam'")
    andrea = s.one("SELECT * FROM linkedin_connections WHERE first_name='Andrea'")
    assert sam["msg_count"] == 6 and andrea["msg_count"] == 13 and andrea["endorsements"] == 1
    assert andrea["strength"] > sam["strength"] > 0 and "investor" in andrea["tags"]
    assert "private text" not in json.dumps(s.q("SELECT * FROM linkedin_connections"))
    res = c.post("/api/intros/suggest", json={}, headers=U).json()
    assert res["suggested"] >= 2 and res["direct"] >= 1
    rows = c.get("/api/intros", headers=U).json()
    lead = next(x for x in rows if x["partner_name"] == "Lead Bank")
    assert lead["path"] == "direct" and lead["first_name"] == "Sam" and "check" not in lead["mutuals_url"]
    assert "network=%5B%22S%22%5D" in lead["mutuals_url"]
    assert not any(x["first_name"] == "Eleni" for x in rows if x["partner_name"] == "Lead Bank")   # the target herself
    inv = [x for x in rows if x["partner_kind"] == "investor"]
    assert inv and all(x["first_name"] == "Andrea" and x["path"] == "bridge" for x in inv)
    assert len(inv) <= 4                                                                  # nobody gets a pile of asks
    assert not any(x["first_name"] == "Joe" for x in rows)
    d = c.post(f"/api/intros/{lead['id']}/draft", headers=U).json()
    assert d["status"] == "draft" and "Eleni Steinman" in d["subject"] and "Note to forward:" in d["body"]
    assert "say no if it isn't a fit" in d["body"] and d["lint_status"] in ("pass", "warn")
    assert c.post("/api/intros/approve", json={"ids": [lead["id"]]}, headers=U).status_code == 403
    c.post(f"/api/intros/{inv[0]['id']}/draft", headers=U)
    ok = c.post("/api/intros/approve", json={"ids": [lead["id"], inv[0]["id"], 99999]}, headers=A).json()
    assert ok["approved"] == [lead["id"], inv[0]["id"]] and ok["refused"][0]["id"] == 99999
    sent = c.post("/api/intros/send", headers=A).json()
    assert [x["email"] for x in sent["sent"]] == ["sam@lead.example"] and sent["mode"] == "outbox"
    assert any("send it on LinkedIn" in x["reason"] for x in sent["skipped"])
    assert c.post(f"/api/intros/{lead['id']}/sent-linkedin", headers=U).status_code == 409   # already sent by email
    assert c.post(f"/api/intros/{inv[0]['id']}/sent-linkedin", headers=U).json() == {"ok": True}
    c.post(f"/api/intros/{lead['id']}/outcome", json={"outcome": "introduced", "note": "Intro email to Eleni"}, headers=U)
    p = c.get(f"/api/partners/{lead['partner_id']}", headers=U).json()
    assert p["stage"] == "contacted" or p["stage"] != "identified"
    assert any("made the introduction" in i["summary"] for i in p["interactions"])
    assert any("Asked Sam Okafor for an introduction" in i["summary"] for i in p["interactions"])
    assert [i["status"] for i in p["intros"] if i["id"] == lead["id"]] == ["introduced"]
