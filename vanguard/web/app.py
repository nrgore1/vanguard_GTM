"""Web app: JSON API for the React UI (/api), the machine API (/machine) and the built UI (/).

Roles
  admin : everything - users, targets (dashboard admin), task CRUD + assignment, agent runs, approvals,
          Notion sync, delete anything
  user  : view dashboard; create/edit campaigns and log results; work partners and log interactions;
          update status/notes of tasks assigned to them; delete only what they created
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date as _date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

from .. import __version__
from ..registry import get_properties, load_properties
from ..store import now
from .db import (CAMPAIGN_FIELDS, INTERACTION_FIELDS, PARTNER_FIELDS, RESULT_FIELDS, WebStore)
from .security import hash_password, make_token, read_token, verify_password

UI_DIST = Path(os.getenv("VANGUARD_UI_DIST", Path(__file__).resolve().parents[2] / "ui" / "dist"))

CampaignStatus = Literal["draft", "scheduled", "active", "paused", "completed"]
CampaignKind = Literal["email", "social", "partner", "event", "content", "paid"]
PartnerKind = Literal["design_partner", "co_sell", "distribution", "referral_affiliate", "integration", "investor"]
PartnerStage = Literal["identified", "contacted", "in_conversation", "pilot", "signed", "declined"]
InteractionType = Literal["email", "linkedin", "x", "call", "meeting", "demo", "proposal", "note"]
Outcome = Literal["positive", "neutral", "negative", "none"]
TaskStatus = Literal["Not started", "In progress", "Done", "Blocked"]
Priority = Literal["P0", "P1", "P2"]

_store: WebStore | None = None


def store() -> WebStore:
    global _store
    if _store is None:
        _store = WebStore()
    return _store


def set_store(s: WebStore) -> None:  # tests
    global _store
    _store = s


def valid_property(pid: str) -> str:
    if pid not in {p.id for p in load_properties()}:
        raise HTTPException(422, f"unknown property_id {pid!r}")
    return pid


# ------------------------------------------------------------------ auth
def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    data = read_token(token) if token else None
    if not data:
        raise HTTPException(401, "not signed in")
    u = store().user(int(data["sub"]))
    if not u or not u["active"]:
        raise HTTPException(401, "account disabled")
    return {k: u[k] for k in ("id", "email", "name", "role")}


def admin_user(u: dict = Depends(current_user)) -> dict:
    if u["role"] != "admin":
        raise HTTPException(403, "admin only")
    return u


def can_modify(u: dict, created_by: int | None) -> None:
    if u["role"] != "admin" and created_by != u["id"]:
        raise HTTPException(403, "only an admin or the creator can do this")


# ------------------------------------------------------------------ schemas
class Login(BaseModel):
    email: str
    password: str


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=80)
    role: Literal["admin", "user"] = "user"
    password: str = Field(min_length=10)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["admin", "user"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10)


class CampaignIn(BaseModel):
    property_id: str
    name: str = Field(min_length=2, max_length=160)
    kind: CampaignKind = "email"
    channel: str | None = None
    status: CampaignStatus = "draft"
    start_date: _date | None = None
    end_date: _date | None = None
    budget_usd: float = Field(default=0, ge=0)
    goal_metric: Literal["sent", "replies", "meetings", "signups", "conversions", "revenue_usd"] | None = None
    goal_value: float | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=5000)
    content: str | None = Field(default=None, max_length=50000)
    owner_id: int | None = None

    @field_validator("end_date")
    @classmethod
    def ends_after_start(cls, v, info):
        s = info.data.get("start_date")
        if v and s and v < s:
            raise ValueError("end_date is before start_date")
        return v


class CampaignPatch(CampaignIn):
    property_id: str | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    kind: CampaignKind | None = None
    status: CampaignStatus | None = None
    budget_usd: float | None = Field(default=None, ge=0)


class ResultIn(BaseModel):
    date: _date
    sent: int = Field(default=0, ge=0)
    opens: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    replies: int = Field(default=0, ge=0)
    meetings: int = Field(default=0, ge=0)
    signups: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    revenue_usd: float = Field(default=0, ge=0)
    spend_usd: float = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class PartnerIn(BaseModel):
    property_id: str
    name: str = Field(min_length=2, max_length=160)
    kind: PartnerKind = "distribution"
    stage: PartnerStage = "identified"
    partner_type: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    value_sharing_model: str | None = None
    mutual_value: str | None = Field(default=None, max_length=4000)
    first_ask: str | None = Field(default=None, max_length=2000)
    next_step: str | None = Field(default=None, max_length=2000)
    next_step_date: _date | None = None
    owner_id: int | None = None
    linkedin_url: str | None = Field(default=None, max_length=300)
    x_handle: str | None = Field(default=None, max_length=100)
    email_named: bool | None = None        # confirmed: contact_email is this person's own address


class PartnerPatch(PartnerIn):
    property_id: str | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    kind: PartnerKind | None = None
    stage: PartnerStage | None = None
    website: str | None = Field(default=None, max_length=300)
    agreement_status: Literal["none", "proposed", "negotiating", "signed", "declined"] | None = None
    agreement_signed_date: _date | None = None
    agreement_notes: str | None = Field(default=None, max_length=4000)
    email_consent: Literal["none", "opted_in", "existing_relationship", "replied", "opted_out"] | None = None


class ReplyIn(BaseModel):
    date: _date
    summary: str = Field(min_length=2, max_length=4000)
    outcome: Outcome | None = None          # left empty: classified from the text
    kind: InteractionType = "email"


class OutreachEdit(BaseModel):
    subject: str | None = Field(default=None, min_length=3, max_length=140)
    body: str | None = Field(default=None, min_length=20, max_length=2500)


class AttachIn(BaseModel):
    partner_ids: list[int] = Field(min_length=1, max_length=500)


class LinkedInImportIn(BaseModel):
    csv: str = Field(min_length=20, max_length=20_000_000)


class LinkedInZipIn(BaseModel):
    zip_b64: str = Field(min_length=20, max_length=60_000_000)


class IntroSuggestIn(BaseModel):
    property_ids: list[str] | None = None


class IntroEditIn(BaseModel):
    subject: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=5000)


class IntroOutcomeIn(BaseModel):
    outcome: Literal["accepted", "introduced", "declined", "cancelled"]
    note: str | None = Field(default=None, max_length=2000)


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class ComposeIn(BaseModel):
    subject: str = Field(min_length=3, max_length=140)
    body: str = Field(min_length=20, max_length=5000)
    contact_email: str | None = Field(default=None, max_length=200)
    send_at: str | None = Field(default=None, max_length=40)
    channel: Literal["email", "linkedin", "x"] = "email"
    linkedin_url: str | None = Field(default=None, max_length=300)
    x_handle: str | None = Field(default=None, max_length=100)
    named_confirmed: bool = False


class ChannelIn(BaseModel):
    channel: Literal["email", "linkedin", "x"]


class ScheduleIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    send_at: str | None = Field(default=None, max_length=40)       # None clears the schedule
    per_day: int | None = Field(default=None, ge=1, le=200)
    gap_min: int = Field(default=0, ge=0, le=720)
    weekdays_only: bool = False
    tz_offset_min: int = Field(default=0, ge=-840, le=840)


class SendIn(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=500)


class RecommendIn(BaseModel):
    property_id: str
    mode: Literal["offline", "model"] = "offline"
    provider: Literal["local", "claude"] | None = None


class InteractionIn(BaseModel):
    date: _date
    type: InteractionType
    summary: str = Field(min_length=2, max_length=4000)
    outcome: Outcome = "none"
    next_step: str | None = Field(default=None, max_length=2000)
    stage: PartnerStage | None = None  # optionally move the partner along in the same action


class TaskIn(BaseModel):
    property_id: str
    description: str = Field(min_length=3, max_length=2000)
    day: int = Field(default=1, ge=1, le=365)
    category: str = "Outreach"
    priority: Priority = "P1"
    owner: Literal["Human", "Tool API"] = "Human"
    kpi: str = Field(default="Done", max_length=500)
    assignee_id: int | None = None
    due_date: _date | None = None


class TaskPatch(BaseModel):
    status: TaskStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    assignee_id: int | None = None
    due_date: _date | None = None
    description: str | None = Field(default=None, min_length=3, max_length=2000)
    kpi: str | None = Field(default=None, max_length=500)


class TargetIn(BaseModel):
    arr_target_usd: float = Field(gt=0)
    monthly_conversions_target: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class RunIn(BaseModel):
    properties: list[str] = ["all"]
    dry_run: bool = True
    provider: Literal["local", "claude"] | None = None


def _clean(model: BaseModel, fields: list[str]) -> dict:
    d = model.model_dump(exclude_unset=True)
    return {k: (v.isoformat() if isinstance(v, _date) else v) for k, v in d.items() if k in fields}


def _social(data: dict) -> dict:
    """Normalise a LinkedIn profile link and an X handle; 422 if they aren't one. A general-inbox email address
    is refused, and a changed address needs confirming again as the person's own."""
    from ..addresses import is_role
    from ..channels import norm_linkedin, norm_x
    if data.get("contact_email"):
        data["contact_email"] = str(data["contact_email"]).strip().lower()
        if is_role(data["contact_email"]):
            raise HTTPException(422, f"{data['contact_email']} is a general inbox (support@, info@ and the like), not a "
                                     f"named person. Leave the email empty and reach them on LinkedIn or X, or find a named contact.")
    if "email_named" in data:
        data["email_named"] = 1 if data["email_named"] else 0
    try:
        if "linkedin_url" in data:
            data["linkedin_url"] = norm_linkedin(data["linkedin_url"])
        if "x_handle" in data:
            data["x_handle"] = norm_x(data["x_handle"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    return data


# ------------------------------------------------------------------ routes
api = APIRouter(prefix="/api")


_FAILS: dict[str, list[float]] = {}
LOGIN_MAX_FAILS, LOGIN_WINDOW_S = 8, 15 * 60


@api.post("/auth/login")
def login(body: Login, request: Request):
    import time
    key = f"{request.client.host if request.client else '?'}|{body.email.lower().strip()}"
    recent = [t for t in _FAILS.get(key, []) if time.time() - t < LOGIN_WINDOW_S]
    if len(recent) >= LOGIN_MAX_FAILS:
        raise HTTPException(429, "too many failed sign-ins - try again in 15 minutes")
    s = store()
    u = s.user_by_email(body.email)
    if not u or not u["active"] or not verify_password(body.password, u["password_hash"]):
        _FAILS[key] = recent + [time.time()]
        raise HTTPException(401, "wrong email or password")
    _FAILS.pop(key, None)
    s.update("users", "id", u["id"], {"last_login": now()})
    s.audit(u["id"], "login", "user", u["id"])
    return {"token": make_token(u["id"], u["role"]),
            "user": {k: u[k] for k in ("id", "email", "name", "role")}}


@api.get("/me")
def me(u: dict = Depends(current_user)):
    return u


@api.get("/users")
def list_users(u: dict = Depends(current_user)):
    cols = "id, email, name, role, active, created_at, last_login" if u["role"] == "admin" else "id, name, role"
    return store().q(f"SELECT {cols} FROM users ORDER BY role, name")


@api.post("/users", status_code=201)
def create_user(body: UserIn, a: dict = Depends(admin_user)):
    s = store()
    if s.user_by_email(body.email):
        raise HTTPException(409, "email already registered")
    uid = s.create_user(body.email, body.name, body.role, hash_password(body.password))
    s.audit(a["id"], "create", "user", uid, {"email": body.email, "role": body.role})
    return {"id": uid}


@api.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, a: dict = Depends(admin_user)):
    s = store()
    if not s.user(uid):
        raise HTTPException(404)
    if uid == a["id"] and (body.role == "user" or body.active is False):
        raise HTTPException(409, "you can't demote or disable yourself")
    data = body.model_dump(exclude_unset=True, exclude={"password"})
    if "active" in data:
        data["active"] = int(data["active"])
    if body.password:
        data["password_hash"] = hash_password(body.password)
    s.update("users", "id", uid, data)
    s.audit(a["id"], "update", "user", uid, {k: v for k, v in data.items() if k != "password_hash"})
    return {"ok": True}


@api.delete("/users/{uid}")
def delete_user(uid: int, a: dict = Depends(admin_user)):
    if uid == a["id"]:
        raise HTTPException(409, "you can't delete yourself")
    if not store().delete("users", "id", uid):
        raise HTTPException(404)
    store().audit(a["id"], "delete", "user", uid)
    return {"ok": True}


@api.get("/properties")
def properties(u: dict = Depends(current_user)):
    return [p.model_dump(include={"id", "url", "name", "track", "motion", "positioning_status", "task_prefix",
                                  "positioning", "pricing_facts"}) for p in load_properties()]


@api.get("/dashboard")
def dashboard(u: dict = Depends(current_user)):
    s = store()
    d = s.dashboard([p.id for p in load_properties()], s.latest_run_id())
    names = {p.id: (p.name, p.track) for p in load_properties()}
    for row in d["properties"]:
        row["name"], row["track"] = names[row["property_id"]]
    d["recent_interactions"] = s.q(
        "SELECT i.*, p.name AS partner_name, p.property_id, u.name AS by_name FROM partner_interactions i "
        "JOIN partners p ON p.id=i.partner_id LEFT JOIN users u ON u.id=i.created_by "
        "ORDER BY i.date DESC, i.id DESC LIMIT 8")
    d["my_open_tasks"] = s.q("SELECT rowid AS id, property_id, task_id, status, priority, body FROM tasks "
                             "WHERE assignee_id=? AND status != 'Done' ORDER BY priority, day LIMIT 8", (u["id"],))
    for t in d["my_open_tasks"]:
        t["description"] = json.loads(t.pop("body"))["description"]
    return d


@api.put("/targets/{pid}")
def set_target(pid: str, body: TargetIn, a: dict = Depends(admin_user)):
    s = store()
    valid_property(pid)
    data = body.model_dump() | {"property_id": pid, "updated_by": a["id"], "updated_at": now()}
    if s.one("SELECT 1 FROM targets WHERE property_id=?", (pid,)):
        s.update("targets", "property_id", pid, data)
    else:
        s.insert("targets", data)
    s.audit(a["id"], "update", "target", pid, body.model_dump())
    return {"ok": True}


# campaigns --------------------------------------------------------------------
@api.get("/campaigns")
def list_campaigns(property_id: str | None = None, status: str | None = None, u: dict = Depends(current_user)):
    sql = ("SELECT c.*, uo.name AS owner_name, COALESCE(SUM(r.sent),0) AS sent, COALESCE(SUM(r.replies),0) AS replies, "
           "COALESCE(SUM(r.meetings),0) AS meetings, COALESCE(SUM(r.signups),0) AS signups, "
           "COALESCE(SUM(r.conversions),0) AS conversions, COALESCE(SUM(r.revenue_usd),0) AS revenue_usd, "
           "COALESCE(SUM(r.spend_usd),0) AS spend_usd FROM campaigns c LEFT JOIN campaign_results r ON r.campaign_id=c.id "
           "LEFT JOIN users uo ON uo.id=c.owner_id WHERE 1=1")
    args: list = []
    if property_id:
        sql += " AND c.property_id=?"; args.append(property_id)
    if status:
        sql += " AND c.status=?"; args.append(status)
    s = store()
    rows = s.q(sql + " GROUP BY c.id, uo.name ORDER BY c.updated_at DESC", args)
    from ..campaign_link import outreach_totals_by_campaign
    auto = outreach_totals_by_campaign(s, [r["id"] for r in rows])
    for r in rows:   # outreach activity counts towards the campaign on top of hand-logged results
        a = auto.get(r["id"], {})
        r["outreach_summary"] = a
        r["sent"] += a.get("emails_sent", 0)
        r["replies"] += a.get("replies", 0)
        r["meetings"] += a.get("meetings", 0)
    return rows


@api.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, u: dict = Depends(current_user)):
    valid_property(body.property_id)
    data = _clean(body, CAMPAIGN_FIELDS) | {"created_by": u["id"], "created_at": now(), "updated_at": now()}
    data.setdefault("owner_id", u["id"])
    cid = store().insert("campaigns", data)
    store().audit(u["id"], "create", "campaign", cid, {"name": body.name})
    return {"id": cid}


@api.get("/campaigns/{cid}")
def get_campaign(cid: int, u: dict = Depends(current_user)):
    s = store()
    c = s.one("SELECT c.*, uo.name AS owner_name FROM campaigns c LEFT JOIN users uo ON uo.id=c.owner_id WHERE c.id=?",
              (cid,))
    if not c:
        raise HTTPException(404)
    c["results"] = s.q("SELECT r.*, u.name AS by_name FROM campaign_results r LEFT JOIN users u ON u.id=r.created_by "
                       "WHERE campaign_id=? ORDER BY date DESC, id DESC", (cid,))
    from ..campaign_link import campaign_outreach
    c["outreach"] = campaign_outreach(s, cid)
    return c


@api.post("/campaigns/{cid}/partners")
def attach_campaign_partners(cid: int, body: AttachIn, u: dict = Depends(current_user)):
    from ..campaign_link import attach_partners
    try:
        return attach_partners(store(), cid, body.partner_ids, actor=u["id"])
    except KeyError:
        raise HTTPException(404)


@api.delete("/campaigns/{cid}/partners/{pid}")
def detach_campaign_partner(cid: int, pid: int, u: dict = Depends(current_user)):
    from ..campaign_link import detach_partner
    if not detach_partner(store(), cid, pid, actor=u["id"]):
        raise HTTPException(404, "that partner is not in this campaign")
    return {"ok": True}


@api.patch("/campaigns/{cid}")
def patch_campaign(cid: int, body: CampaignPatch, u: dict = Depends(current_user)):
    s = store()
    if not s.one("SELECT id FROM campaigns WHERE id=?", (cid,)):
        raise HTTPException(404)
    data = _clean(body, CAMPAIGN_FIELDS)
    if "property_id" in data:
        valid_property(data["property_id"])
    s.update("campaigns", "id", cid, data | {"updated_at": now()})
    s.audit(u["id"], "update", "campaign", cid, data)
    return {"ok": True}


@api.delete("/campaigns/{cid}")
def delete_campaign(cid: int, u: dict = Depends(current_user)):
    s = store()
    c = s.one("SELECT created_by FROM campaigns WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404)
    can_modify(u, c["created_by"])
    with s.conn() as conn:   # partners stay; they just leave the campaign
        conn.execute("UPDATE partners SET campaign_id=NULL WHERE campaign_id=?", (cid,))
    s.delete("campaigns", "id", cid)
    s.audit(u["id"], "delete", "campaign", cid)
    return {"ok": True}


@api.post("/campaigns/{cid}/results", status_code=201)
def add_result(cid: int, body: ResultIn, u: dict = Depends(current_user)):
    s = store()
    if not s.one("SELECT id FROM campaigns WHERE id=?", (cid,)):
        raise HTTPException(404)
    rid = s.insert("campaign_results", _clean(body, RESULT_FIELDS) | {"campaign_id": cid, "created_by": u["id"],
                                                                     "created_at": now()})
    s.update("campaigns", "id", cid, {"updated_at": now()})
    s.audit(u["id"], "create", "result", rid, {"campaign_id": cid})
    return {"id": rid}


@api.delete("/results/{rid}")
def delete_result(rid: int, u: dict = Depends(current_user)):
    s = store()
    r = s.one("SELECT created_by FROM campaign_results WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404)
    can_modify(u, r["created_by"])
    s.delete("campaign_results", "id", rid)
    s.audit(u["id"], "delete", "result", rid)
    return {"ok": True}


# partners -----------------------------------------------------------------------
@api.get("/partners")
def list_partners(property_id: str | None = None, kind: str | None = None, u: dict = Depends(current_user)):
    sql = ("SELECT p.*, uo.name AS owner_name, (SELECT COUNT(*) FROM partner_interactions i WHERE i.partner_id=p.id) "
           "AS interactions, (SELECT MAX(date) FROM partner_interactions i WHERE i.partner_id=p.id) AS last_contact, "
           "cc.name AS campaign_name FROM partners p LEFT JOIN users uo ON uo.id=p.owner_id "
           "LEFT JOIN campaigns cc ON cc.id=p.campaign_id WHERE 1=1")
    args: list = []
    if property_id:
        sql += " AND p.property_id=?"; args.append(property_id)
    if kind:
        sql += " AND p.kind=?"; args.append(kind)
    s = store()
    rows = s.q(sql + " ORDER BY COALESCE(p.priority_score, -1) DESC, p.updated_at DESC", args)
    from ..linkedin import partners_with_connections
    known = partners_with_connections(s)
    for r in rows:   # how many people we already know there (from LinkedIn exports)
        r["connections"] = len(known.get(r["id"], []))
    return rows


@api.post("/partners", status_code=201)
def create_partner(body: PartnerIn, u: dict = Depends(current_user)):
    s = store()
    valid_property(body.property_id)
    if s.one("SELECT id FROM partners WHERE property_id=? AND name=?", (body.property_id, body.name)):
        raise HTTPException(409, "this partner already exists for that property")
    data = _social(_clean(body, PARTNER_FIELDS)) | {"created_by": u["id"], "created_at": now(), "updated_at": now()}
    data.setdefault("owner_id", u["id"])
    pid = s.insert("partners", data)
    s.audit(u["id"], "create", "partner", pid, {"name": body.name})
    return {"id": pid}


@api.get("/partners/{pid}")
def get_partner(pid: int, u: dict = Depends(current_user)):
    s = store()
    p = s.one("SELECT p.*, uo.name AS owner_name, cc.name AS campaign_name FROM partners p LEFT JOIN users uo "
              "ON uo.id=p.owner_id LEFT JOIN campaigns cc ON cc.id=p.campaign_id WHERE p.id=?", (pid,))
    if not p:
        raise HTTPException(404)
    p["interactions"] = s.q("SELECT i.*, u.name AS by_name FROM partner_interactions i LEFT JOIN users u "
                            "ON u.id=i.created_by WHERE partner_id=? ORDER BY date DESC, id DESC", (pid,))
    p["outreach"] = s.q("SELECT * FROM outreach_messages WHERE partner_id=? ORDER BY step", (pid,))
    from ..addresses import classify
    p["email_status"] = classify(p["contact_email"], p["contact_name"], bool(p.get("email_named")))
    p["targets"] = s.q("SELECT id, name, stage, contact_email, agreement_status FROM partners WHERE parent_id=? "
                       "ORDER BY name", (pid,))
    p["segment_name"] = (s.one("SELECT name FROM partners WHERE id=?", (p["parent_id"],)) or {}).get("name") \
        if p.get("parent_id") else None
    p["factors"] = json.loads(p["factors"]) if p.get("factors") else None
    from ..linkedin import partners_with_connections
    p["connections"] = [{k: c[k] for k in ("id", "first_name", "last_name", "profile_url", "email", "company", "position",
                                           "connected_on", "owner_name", "is_contact")}
                        for c in partners_with_connections(s, [pid]).get(pid, [])]
    from ..intros import listing, mutuals_search_url
    p["intros"] = listing(s, partner_id=pid)
    p["mutuals_url"] = mutuals_search_url(p)
    return p


# LinkedIn connections (from LinkedIn's own "Get a copy of your data" export - no API, no scraping) ----------
@api.post("/linkedin/connections")
def import_linkedin(body: LinkedInImportIn, u: dict = Depends(current_user)):
    from ..linkedin import import_connections
    try:
        return import_connections(store(), body.csv, u["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@api.post("/linkedin/export")
def import_linkedin_export(body: LinkedInZipIn, u: dict = Depends(current_user)):
    """LinkedIn's full data export (.zip): connections plus message counts and endorsements for tie strength."""
    import base64
    import binascii
    from ..intros import import_export_zip
    try:
        data = base64.b64decode(body.zip_b64.split(",", 1)[-1], validate=False)
        return import_export_zip(store(), data, u["id"])
    except (ValueError, binascii.Error) as e:
        raise HTTPException(400, str(e))


# introductions -------------------------------------------------------------------------
@api.post("/intros/suggest")
def suggest_intros(body: IntroSuggestIn, u: dict = Depends(current_user)):
    from ..intros import suggest
    return suggest(store(), body.property_ids, user_id=u["id"])


@api.get("/intros")
def list_intros(status: str | None = None, partner_id: int | None = None, kind: str | None = None,
                u: dict = Depends(current_user)):
    from ..intros import listing
    return listing(store(), status, partner_id, kind)


@api.post("/intros/{iid}/draft")
def draft_intro(iid: int, u: dict = Depends(current_user)):
    from ..intros import draft
    try:
        return draft(store(), iid, (u.get("name") or "Narendra").split(" ")[0])
    except KeyError:
        raise HTTPException(404)


@api.patch("/intros/{iid}")
def edit_intro(iid: int, body: IntroEditIn, u: dict = Depends(current_user)):
    from ..intros import edit
    try:
        return edit(store(), iid, body.subject, body.body)
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(409, str(e))


@api.post("/intros/approve")
def approve_intros(body: IdsIn, a: dict = Depends(admin_user)):
    from ..intros import approve
    res = approve(store(), body.ids, a["name"])
    store().audit(a["id"], "approve", "intros", ",".join(map(str, res["approved"])))
    return res


@api.post("/intros/send")
def send_intros(a: dict = Depends(admin_user)):
    from ..intros import send_approved
    return send_approved(store(), actor=a["id"])


@api.post("/intros/{iid}/sent-linkedin")
def intro_sent_linkedin(iid: int, u: dict = Depends(current_user)):
    from ..intros import mark_sent_linkedin
    try:
        mark_sent_linkedin(store(), iid, u["id"])
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@api.post("/intros/{iid}/outcome")
def intro_outcome(iid: int, body: IntroOutcomeIn, u: dict = Depends(current_user)):
    from ..intros import record_outcome
    try:
        return record_outcome(store(), iid, body.outcome, body.note, u["id"])
    except KeyError:
        raise HTTPException(404)


@api.get("/linkedin/connections")
def linkedin_summary(u: dict = Depends(current_user)):
    s = store()
    rows = s.q("SELECT c.owner_id, u.name AS owner_name, COUNT(*) AS n, MAX(c.updated_at) AS last_import FROM "
               "linkedin_connections c LEFT JOIN users u ON u.id=c.owner_id GROUP BY c.owner_id, u.name")
    from ..linkedin import partners_with_connections
    return {"by_user": rows, "partners_with_connections": len(partners_with_connections(s))}


@api.delete("/linkedin/connections")
def delete_my_linkedin(u: dict = Depends(current_user)):
    s = store()
    with s.conn() as c:
        n = c.execute("DELETE FROM linkedin_connections WHERE owner_id=?", (u["id"],)).rowcount
    s.audit(u["id"], "delete", "linkedin_connections", u["id"], {"rows": n})
    return {"deleted": n}


@api.patch("/partners/{pid}")
def patch_partner(pid: int, body: PartnerPatch, u: dict = Depends(current_user)):
    s = store()
    if not s.one("SELECT id FROM partners WHERE id=?", (pid,)):
        raise HTTPException(404)
    data = _social(_clean(body, PARTNER_FIELDS))
    if data.get("agreement_status") == "signed":
        data.setdefault("agreement_signed_date", _date.today().isoformat())
        data["stage"] = "signed"
    elif data.get("agreement_status") == "declined":
        data["stage"] = "declined"
    old = s.one("SELECT contact_email FROM partners WHERE id=?", (pid,))
    if "contact_email" in data and (data["contact_email"] or None) != (old["contact_email"] or None) and "email_named" not in data:
        data["email_named"] = 0                     # a new address must be confirmed again
    s.update("partners", "id", pid, data | {"updated_at": now()})
    if data.get("email_consent") == "opted_out":      # never email them again
        row = s.one("SELECT contact_email FROM partners WHERE id=?", (pid,))
        if row and row["contact_email"]:
            s.q("INSERT INTO email_suppression (email, reason, at) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason, at=excluded.at",
                (row["contact_email"].lower(), "opted-out (manual)", now()))
        with s.conn() as c:
            c.execute("UPDATE outreach_messages SET status='cancelled', error='partner opted out' WHERE partner_id=? "
                      "AND status IN ('draft','approved')", (pid,))
    if data.get("stage") in ("signed", "declined"):   # stop any queued outreach
        with s.conn() as c:
            c.execute("UPDATE outreach_messages SET status='cancelled', error=? WHERE partner_id=? AND status IN "
                      "('draft','approved')", (f"partner {data['stage']}", pid))
    s.audit(u["id"], "update", "partner", pid, data)
    return {"ok": True}


@api.delete("/partners/{pid}")
def delete_partner(pid: int, a: dict = Depends(admin_user)):
    if not store().delete("partners", "id", pid):
        raise HTTPException(404)
    store().audit(a["id"], "delete", "partner", pid)
    return {"ok": True}


@api.post("/partners/{pid}/interactions", status_code=201)
def add_interaction(pid: int, body: InteractionIn, u: dict = Depends(current_user)):
    s = store()
    if not s.one("SELECT id FROM partners WHERE id=?", (pid,)):
        raise HTTPException(404)
    iid = s.insert("partner_interactions", _clean(body, INTERACTION_FIELDS) | {"partner_id": pid, "created_by": u["id"],
                                                                              "created_at": now()})
    upd = {"updated_at": now()}
    if body.stage:
        upd["stage"] = body.stage
    if body.next_step:
        upd["next_step"] = body.next_step
    s.update("partners", "id", pid, upd)
    s.audit(u["id"], "create", "interaction", iid, {"partner_id": pid, "stage": body.stage})
    return {"id": iid}


@api.delete("/interactions/{iid}")
def delete_interaction(iid: int, u: dict = Depends(current_user)):
    s = store()
    r = s.one("SELECT created_by FROM partner_interactions WHERE id=?", (iid,))
    if not r:
        raise HTTPException(404)
    can_modify(u, r["created_by"])
    s.delete("partner_interactions", "id", iid)
    return {"ok": True}


# partner outreach ---------------------------------------------------------------------
@api.post("/partners/recommend")
async def recommend_partners(body: RecommendIn, a: dict = Depends(admin_user)):
    """The partnerships expert: recommend, score and prioritise partners for one property + draft sequences."""
    from ..lint_gate import LintGate
    from ..llm import make_llm
    from ..partners import plan_partners
    from ..providers import FallbackLLM
    prop = get_properties([valid_property(body.property_id)])[0]
    llm = None
    if body.mode == "model":
        llm = make_llm(False, provider=body.provider)
        if isinstance(llm, FallbackLLM):
            ok, msg = await llm.primary.check()
            if not ok and not llm.backup_enabled:
                raise HTTPException(409, f"{msg}. Use mode 'offline' (the $0 expert playbook) or start the local model.")
        elif not (llm.meter.budget_usd or 0) > 0:
            raise HTTPException(409, "Claude-only runs are off (VANGUARD_MAX_COST_USD=0)")
    recs = await plan_partners(llm, prop, None, LintGate())
    s = store()
    made = {"partners": 0, "messages": 0, "updated": 0}
    for r in recs:
        res = s.upsert_recommendation(prop.id, r, None, a["id"])
        made["partners"] += res["partner_created"]
        made["updated"] += 1 - res["partner_created"]
        made["messages"] += res["messages"]
    s.audit(a["id"], "recommend", "partners", prop.id, made | {"mode": body.mode})
    return made | {"recommendations": [{k: r[k] for k in ("rank", "name", "kind", "category", "score", "priority",
                                                          "lint_status")} for r in recs]}


@api.post("/partners/import-research")
def import_research(a: dict = Depends(admin_user)):
    """Load config/partner_targets.yaml (real, researched organisations) as named partners with draft emails."""
    from ..targets import import_targets
    res = import_targets(store(), user_id=a["id"])
    store().audit(a["id"], "import-research", "partner", None,
                  {k: v for k, v in res.items() if k != "errors"} | {"errors": len(res["errors"])})
    # investor targets for the raise (config/investor_targets.yaml) load with the same button
    from ..investors import import_investors
    try:
        inv = import_investors(store(), user_id=a["id"])
        res["investors"] = {k: inv[k] for k in ("created", "updated", "by_priority")}
        res["errors"] += inv["errors"]
    except (FileNotFoundError, ValueError) as e:
        res["errors"].append(f"investors: {e}")
    return res


@api.get("/outreach")
def list_outreach(status: str | None = None, property_id: str | None = None, partner_id: int | None = None,
                  campaign_id: int | None = None, u: dict = Depends(current_user)):
    sql = ("SELECT m.*, p.name AS partner_name, p.property_id, p.kind AS partner_kind, p.stage AS partner_stage, "
           "p.contact_email, p.contact_name, p.linkedin_url, p.x_handle, p.priority_score, p.priority, p.is_segment, p.campaign_id, "
           "cc.name AS campaign_name FROM outreach_messages m "
           "JOIN partners p ON p.id=m.partner_id LEFT JOIN campaigns cc ON cc.id=p.campaign_id WHERE 1=1")
    args: list = []
    if not partner_id:   # segment templates live on the segment's page, not in the sending queue
        sql += " AND COALESCE(p.is_segment,0)=0"
    if status:
        sql += " AND m.status=?"; args.append(status)
    if property_id:
        sql += " AND p.property_id=?"; args.append(property_id)
    if partner_id:
        sql += " AND m.partner_id=?"; args.append(partner_id)
    if campaign_id:
        sql += " AND p.campaign_id=?"; args.append(campaign_id)
    return store().q(sql + " ORDER BY COALESCE(p.priority_score,0) DESC, p.name, m.step LIMIT 1000", args)


@api.get("/outreach/stats")
def outreach_stats(u: dict = Depends(current_user)):
    from ..outreach import EmailConfig, postmark_used_this_month, queue_stats
    cfg = EmailConfig.from_env()
    from ..channels import by_hand
    st = queue_stats(store()) | {"email": cfg.status()}
    st["by_hand_due"] = sum(1 for m in by_hand(store()) if m["due"])
    if st["email"]["postmark"]:
        st["email"]["postmark"]["used_this_month"] = postmark_used_this_month(store())
    return st


@api.patch("/outreach/{mid}")
def edit_outreach(mid: int, body: OutreachEdit, u: dict = Depends(current_user)):
    from ..lint_gate import LintGate
    s = store()
    m = s.one("SELECT m.*, p.property_id FROM outreach_messages m JOIN partners p ON p.id=m.partner_id WHERE m.id=?", (mid,))
    if not m:
        raise HTTPException(404)
    if m["status"] not in ("draft", "approved"):
        raise HTTPException(409, f"can't edit a message that is {m['status']}")
    subject, text = body.subject or m["subject"], body.body or m["body"]
    prop = get_properties([m["property_id"]])[0]
    fs = LintGate().check_items([("subject", subject), ("body", text)], prop.lint_profile, prop.banned_terms)
    lint = LintGate.status(fs)
    s.update("outreach_messages", "id", mid, {"subject": subject, "body": text, "lint_status": lint,
                                              "lint_findings": json.dumps([f.model_dump() for f in fs]),
                                              "status": "draft", "approved_by": None, "approved_at": None,
                                              "updated_at": now()})   # any edit needs fresh approval
    from ..channels import relint
    res = relint(s, mid)                                              # adds LinkedIn length limits
    s.audit(u["id"], "update", "outreach", mid)
    return {"ok": True, "lint_status": res["lint_status"], "lint_findings": json.loads(res["lint_findings"])}


@api.post("/outreach/approve")
def approve_outreach(body: IdsIn, a: dict = Depends(admin_user)):
    from ..outreach import approve
    res = approve(store(), body.ids, a["name"])
    store().audit(a["id"], "approve", "outreach", ",".join(map(str, res["approved"])))
    return res


@api.post("/outreach/{mid}/cancel")
def cancel_outreach(mid: int, a: dict = Depends(admin_user)):
    s = store()
    m = s.one("SELECT status FROM outreach_messages WHERE id=?", (mid,))
    if not m:
        raise HTTPException(404)
    if m["status"] not in ("draft", "approved", "failed"):
        raise HTTPException(409, f"can't cancel a message that is {m['status']}")
    s.update("outreach_messages", "id", mid, {"status": "cancelled", "error": f"cancelled by {a['name']}", "updated_at": now()})
    s.audit(a["id"], "cancel", "outreach", mid)
    return {"ok": True}


@api.post("/partners/{pid}/email")
def compose_email(pid: int, body: ComposeIn, u: dict = Depends(current_user)):
    """Write a one-off email to this partner. It is saved as a draft; an admin approves it and it leaves through
    the normal send path (daily cap, opt-outs, footer, timeline entry)."""
    from ..outreach import compose
    try:
        return compose(store(), pid, body.subject, body.body, u["id"], body.contact_email, body.send_at,
                       body.channel, body.linkedin_url, body.x_handle, body.named_confirmed)
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.post("/partners/purge-general-inboxes")
def purge_general_inboxes(a: dict = Depends(admin_user)):
    """Remove general-inbox addresses (support@, info@ ...) from partners and cancel unsent emails to them."""
    from ..addresses import purge
    return purge(store(), a["id"])


@api.post("/partners/{pid}/channel")
def set_partner_channel(pid: int, body: ChannelIn, u: dict = Depends(current_user)):
    """Run this partner's unsent messages on email, LinkedIn or X. Changed messages go back to draft."""
    from ..channels import set_channel
    try:
        return set_channel(store(), pid, body.channel, u["id"])
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.get("/outreach/by-hand")
def outreach_by_hand(u: dict = Depends(current_user)):
    """Approved LinkedIn/X messages: due now or why not yet, with the profile link to send from."""
    from ..channels import by_hand
    return by_hand(store())


@api.post("/outreach/{mid}/mark-sent")
def outreach_mark_sent(mid: int, u: dict = Depends(current_user)):
    """You sent this LinkedIn/X message yourself: log it, move the partner to contacted, start the next delay."""
    from ..channels import mark_sent
    try:
        return mark_sent(store(), mid, u["id"])
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(409, str(e))


@api.post("/outreach/schedule")
def schedule_outreach(body: ScheduleIn, u: dict = Depends(current_user)):
    """Set when messages may go out (or clear it). Scheduling never approves or sends anything."""
    from ..outreach import schedule
    try:
        res = schedule(store(), body.ids, body.send_at, body.per_day, body.gap_min, body.weekdays_only,
                       body.tz_offset_min, is_admin=u["role"] == "admin")
    except ValueError as e:
        raise HTTPException(422, str(e))
    store().audit(u["id"], "schedule", "outreach", ",".join(str(x["id"]) for x in res["scheduled"]),
                  {"send_at": body.send_at, "per_day": body.per_day})
    return res


@api.post("/outreach/send-due")
def send_outreach(body: SendIn | None = None, a: dict = Depends(admin_user)):
    from ..outreach import send_due
    res = send_due(store(), actor=a["id"], only=body.ids if body else None)
    if res.get("error"):
        raise HTTPException(409, res["error"])
    return res


@api.post("/outreach/sync-replies")
def sync_outreach_replies(a: dict = Depends(admin_user)):
    from ..outreach import sync_replies
    res = sync_replies(store(), actor=a["id"])
    if res.get("error"):
        raise HTTPException(409, res["error"])
    return res


@api.post("/outreach/digest")
def outreach_digest(a: dict = Depends(admin_user)):
    """Email the admins a digest of partner emails awaiting approval (Postmark notify stream, SMTP or outbox)."""
    from ..outreach import send_digest
    try:
        res = send_digest(store())
    except Exception as ex:
        raise HTTPException(502, f"digest failed: {ex}")
    store().audit(a["id"], "digest", "outreach", None, res)
    return res


def _postmark_cfg():
    from ..outreach import EmailConfig
    cfg = EmailConfig.from_env()
    if not cfg.postmark_token:
        raise HTTPException(409, "Postmark is not configured (POSTMARK_SERVER_TOKEN)")
    return cfg


@api.post("/outreach/postmark-sync")
def postmark_sync(a: dict = Depends(admin_user)):
    """Two-way suppression sync with the Postmark outreach stream."""
    from ..postmark import PostmarkError, sync_suppressions
    try:
        res = sync_suppressions(store(), _postmark_cfg())
    except PostmarkError as ex:
        raise HTTPException(502, str(ex))
    store().audit(a["id"], "postmark-sync", "outreach", None, res)
    return res


@api.get("/email/postmark")
def postmark_status(a: dict = Depends(admin_user)):
    """Stream check (configured streams exist and are transactional) plus this month's usage against the cap."""
    from ..outreach import postmark_used_this_month
    from ..postmark import PostmarkError, check_streams
    cfg = _postmark_cfg()
    try:
        res = check_streams(cfg)
    except PostmarkError as ex:
        res = {"ok": False, "error": str(ex), "streams": {}, "missing": [], "not_transactional": []}
    return res | {"used_this_month": postmark_used_this_month(store()), "monthly_cap": cfg.postmark_monthly_cap,
                  "status": cfg.status()["postmark"]}


class NamedTargetIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_email: EmailStr | None = None
    website: str | None = Field(default=None, max_length=300)


@api.post("/partners/{pid}/targets", status_code=201)
def add_target(pid: int, body: NamedTargetIn, u: dict = Depends(current_user)):
    """Add a named organisation (e.g. a specific wedding planner) under a recommended segment."""
    s = store()
    seg = s.one("SELECT property_id, is_segment FROM partners WHERE id=?", (pid,))
    if not seg:
        raise HTTPException(404)
    if not seg["is_segment"]:
        raise HTTPException(409, "targets can only be added under a segment recommendation")
    if s.one("SELECT id FROM partners WHERE property_id=? AND name=?", (seg["property_id"], body.name)):
        raise HTTPException(409, "this partner already exists for that property")
    new = s.add_target(pid, body.model_dump(), u["id"])
    s.audit(u["id"], "create", "partner", new, {"segment": pid, "name": body.name})
    return {"id": new}


@api.post("/partners/{pid}/reply")
def partner_reply(pid: int, body: ReplyIn, u: dict = Depends(current_user)):
    from ..outreach import record_reply
    try:
        return record_reply(store(), pid, body.summary, when=body.date, outcome=body.outcome, actor=u["id"], kind=body.kind)
    except KeyError:
        raise HTTPException(404)


# tasks ---------------------------------------------------------------------------
def _task_row(r: dict) -> dict:
    body = json.loads(r.pop("body"))
    return {**body, **r}


@api.get("/tasks")
def list_tasks(property_id: str | None = None, status: str | None = None, mine: bool = False,
               run_id: str | None = None, u: dict = Depends(current_user)):
    s = store()
    rid = run_id or s.latest_run_id() or ""
    sql = ("SELECT t.rowid AS id, t.run_id, t.property_id, t.task_id, t.day, t.priority, t.owner, t.status, t.body, "
           "t.assignee_id, t.due_date, t.notes, t.updated_at, u.name AS assignee_name FROM tasks t "
           "LEFT JOIN users u ON u.id=t.assignee_id WHERE (t.run_id=? OR t.run_id='manual')")
    args: list = [rid]
    if property_id:
        sql += " AND t.property_id=?"; args.append(property_id)
    if status:
        sql += " AND t.status=?"; args.append(status)
    if mine:
        sql += " AND t.assignee_id=?"; args.append(u["id"])
    return [_task_row(r) for r in s.q(sql + " ORDER BY t.day, t.priority, t.task_id", args)]


@api.post("/tasks", status_code=201)
def create_task(body: TaskIn, a: dict = Depends(admin_user)):
    s = store()
    prop = next(p for p in load_properties() if p.id == valid_property(body.property_id))
    n = s.one("SELECT COUNT(*) AS n FROM tasks WHERE run_id='manual' AND property_id=?", (prop.id,))["n"] + 1
    task_id = f"{prop.task_prefix}-M{n:03d}"
    payload = {"day": body.day, "task_id": task_id, "description": body.description, "category": body.category,
               "priority": body.priority, "owner": body.owner, "tool": None, "dependencies": [], "kpi": body.kpi}
    s.insert("tasks", {"run_id": "manual", "property_id": prop.id, "task_id": task_id, "day": body.day,
                       "priority": body.priority, "owner": body.owner, "status": "Not started",
                       "body": json.dumps(payload), "assignee_id": body.assignee_id,
                       "due_date": body.due_date.isoformat() if body.due_date else None, "updated_at": now()})
    s.audit(a["id"], "create", "task", task_id)
    return {"task_id": task_id}


@api.patch("/tasks/{tid}")
def patch_task(tid: int, body: TaskPatch, u: dict = Depends(current_user)):
    s = store()
    t = s.one("SELECT rowid AS id, assignee_id, body FROM tasks WHERE rowid=?", (tid,))
    if not t:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if u["role"] != "admin":
        if t["assignee_id"] != u["id"]:
            raise HTTPException(403, "you can only update tasks assigned to you")
        if set(data) - {"status", "notes"}:
            raise HTTPException(403, "only an admin can change priority, assignee, due date or wording")
    row: dict = {}
    content = json.loads(t["body"])
    for k, v in data.items():
        if k in ("description", "kpi"):
            content[k] = v
        elif k == "priority":
            content[k] = v; row[k] = v
        elif k == "due_date":
            row[k] = v.isoformat() if v else None
        else:
            row[k] = v
    row["body"] = json.dumps(content)
    row["updated_at"] = now()
    s.update("tasks", "rowid", tid, row)
    s.audit(u["id"], "update", "task", tid, {k: str(v) for k, v in data.items()})
    return {"ok": True}


@api.delete("/tasks/{tid}")
def delete_task(tid: int, a: dict = Depends(admin_user)):
    if not store().delete("tasks", "rowid", tid):
        raise HTTPException(404)
    store().audit(a["id"], "delete", "task", tid)
    return {"ok": True}


# fail-proof layer: tripwires, gates, premortems -----------------------------------
class ReadingIn(BaseModel):
    tripwire_id: str
    value: float
    date: _date | None = None
    note: str = Field(default="", max_length=500)


class GateIn(BaseModel):
    status: Literal["open", "passed", "failed"]
    note: str = Field(default="", max_length=500)


def _failproof():
    from ..failproof import FailproofStore, load_failproof
    return load_failproof(), FailproofStore(store())


@api.get("/failproof")
def failproof_tracker(as_of: _date | None = None, property_id: str | None = None, u: dict = Depends(current_user)):
    from ..failproof import today, tracker
    cfg, fs = _failproof()
    return tracker(cfg, fs, as_of or today(), [valid_property(property_id)] if property_id else None)


@api.post("/failproof/{pid}/readings", status_code=201)
def failproof_reading(pid: str, body: ReadingIn, u: dict = Depends(current_user)):
    from ..failproof import today
    cfg, fs = _failproof()
    valid_property(pid)
    if body.tripwire_id not in {t.id for t in cfg.properties[pid].tripwires}:
        raise HTTPException(422, f"unknown tripwire {body.tripwire_id!r} for {pid}")
    d = body.date or today()
    fs.record(pid, body.tripwire_id, body.value, d, body.note, u["email"])
    store().audit(u["id"], "record", "tripwire", f"{pid}:{body.tripwire_id}", body.model_dump(mode="json"))
    return {"ok": True}


@api.put("/failproof/{pid}/gates/{gid}")
def failproof_gate(pid: str, gid: str, body: GateIn, a: dict = Depends(admin_user)):
    cfg, fs = _failproof()
    valid_property(pid)
    gate = next((g for g in cfg.properties[pid].gates if g.id == gid), None)
    if not gate:
        raise HTTPException(404, f"unknown gate {gid!r} for {pid}")
    fs.set_gate(pid, gid, body.status, body.note, a["email"])
    store().audit(a["id"], "update", "gate", f"{pid}:{gid}", body.model_dump())
    return {"ok": True, "walk_away_if": gate.walk_away_if if body.status == "failed" else None}


@api.get("/failproof/{pid}/premortem")
def failproof_premortem(pid: str, u: dict = Depends(current_user)):
    _, fs = _failproof()
    valid_property(pid)
    pm = fs.latest_premortem(pid)
    if not pm:
        raise HTTPException(404, "no premortem yet - run `vanguard premortem <property>`")
    return pm


# agent (admin) -------------------------------------------------------------------
@api.get("/agent/status")
def agent_status(a: dict = Depends(admin_user)):
    from ..providers import LocalLLM
    provider = os.getenv("VANGUARD_PROVIDER", "local")
    local_ok, local_msg = (False, "not used")
    if provider == "local":
        local_ok, local_msg = asyncio.run(LocalLLM().check()) if not _in_loop() else (None, "check from CLI")
    cap = float(os.getenv("VANGUARD_MAX_COST_USD", "0") or 0)
    return {"version": __version__, "provider": provider, "local_model": os.getenv("VANGUARD_LOCAL_MODEL", "qwen3.6:27b"),
            "local_ok": local_ok, "local_message": local_msg, "paid_runs": cap > 0, "cap_usd": cap,
            "claude_model": os.getenv("VANGUARD_MODEL", "claude-sonnet-5"),
            "claude_key_set": bool(os.getenv("ANTHROPIC_API_KEY")), "notion_token_set": bool(os.getenv("NOTION_TOKEN")),
            "email": _email_status()}


def _email_status() -> dict:
    from ..outreach import EmailConfig
    return EmailConfig.from_env().status()


def _in_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


@api.get("/runs")
def list_runs(a: dict = Depends(admin_user)):
    rows = store().q("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 50")
    for r in rows:
        r["property_ids"] = json.loads(r["property_ids"])
        r["errors"] = json.loads(r["errors"] or "{}")
        r["usage"] = json.loads(r.get("usage") or "{}")
    return rows


@api.get("/runs/{run_id}")
def get_run(run_id: str, u: dict = Depends(current_user)):
    s = store()
    r = s.run(run_id)
    if not r:
        raise HTTPException(404)
    r["playbooks"] = [{k: p[k] for k in ("property_id", "lint_status", "approved_by", "approved_at")}
                      for p in s.playbooks(run_id)]
    return r


@api.get("/runs/{run_id}/playbooks/{pid}")
def get_playbook(run_id: str, pid: str, u: dict = Depends(current_user)):
    pb = store().playbook(run_id, pid)
    if not pb:
        raise HTTPException(404)
    return pb.model_dump(mode="json")


@api.post("/runs", status_code=202)
async def start_run(body: RunIn, bg: BackgroundTasks, a: dict = Depends(admin_user)):
    from ..llm import make_llm
    from ..orchestrator import new_run_id, run_portfolio
    from ..providers import FallbackLLM
    try:
        props = get_properties(body.properties)
    except KeyError as e:
        raise HTTPException(422, str(e))
    llm = make_llm(body.dry_run, provider=body.provider)
    if isinstance(llm, FallbackLLM):
        ok, msg = await llm.primary.check()
        if not ok and not llm.backup_enabled:
            raise HTTPException(409, f"{msg}. Claude fallback is off, so nothing was started.")
    elif not body.dry_run and not (llm.meter.budget_usd or 0) > 0:
        raise HTTPException(409, "Claude-only runs are off (VANGUARD_MAX_COST_USD=0)")
    rid = new_run_id()
    bg.add_task(run_portfolio, llm, props, store(), run_id=rid)
    store().audit(a["id"], "start", "run", rid, body.model_dump())
    return {"run_id": rid, "properties": [p.id for p in props]}


@api.post("/runs/{run_id}/approve/{pid}")
def approve(run_id: str, pid: str, a: dict = Depends(admin_user)):
    if not store().approve(run_id, pid, a["name"]):
        raise HTTPException(409, "missing, or blocked by the lint gate")
    store().audit(a["id"], "approve", "playbook", f"{run_id}/{pid}")
    return {"ok": True}


@api.post("/runs/{run_id}/import")
def import_run(run_id: str, property_ids: list[str] | None = None, a: dict = Depends(admin_user)):
    if not store().run(run_id):
        raise HTTPException(404)
    return store().import_from_run(run_id, property_ids, a["id"])


@api.post("/runs/{run_id}/sync")
async def sync(run_id: str, a: dict = Depends(admin_user)):
    from ..notion_sync import Notion
    if not os.getenv("NOTION_TOKEN"):
        raise HTTPException(409, "NOTION_TOKEN not configured")
    n = Notion()
    try:
        res = await n.sync_run(store(), run_id)
    finally:
        await n.aclose()
    store().audit(a["id"], "sync", "run", run_id, res)
    return res


@api.get("/audit")
def audit(limit: int = Query(100, le=500), a: dict = Depends(admin_user)):
    return store().q("SELECT l.*, u.name AS user_name FROM audit_log l LEFT JOIN users u ON u.id=l.user_id "
                     "ORDER BY l.id DESC LIMIT ?", (limit,))


# ------------------------------------------------------------------ app
def create_app() -> FastAPI:
    app = FastAPI(title="Vanguard-GTM", version=__version__)
    app.include_router(api)

    from ..api import app as machine_app  # the bearer-token machine API
    app.mount("/machine", machine_app)

    @app.post("/hooks/postmark", include_in_schema=False)
    async def postmark_webhook(request: Request):
        """Postmark webhooks (Delivery, Bounce, SpamComplaint, Open, SubscriptionChange, Inbound), Basic Auth."""
        from ..outreach import EmailConfig
        from ..postmark import check_basic_auth, handle_event
        cfg = EmailConfig.from_env()
        if not (cfg.webhook_user and cfg.webhook_password):
            raise HTTPException(503, "webhook disabled: set VANGUARD_POSTMARK_WEBHOOK_USER and _PASSWORD")
        if not check_basic_auth(request.headers.get("authorization", ""), cfg.webhook_user, cfg.webhook_password):
            raise HTTPException(401, "bad credentials", headers={"WWW-Authenticate": "Basic"})
        try:
            event = await request.json()
        except ValueError:
            raise HTTPException(400, "expected JSON")
        if not isinstance(event, dict):
            raise HTTPException(400, "expected a JSON object")
        return handle_event(store(), event)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__}

    if UI_DIST.exists():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str, request: Request):
            if path.startswith(("api/", "machine/", "hooks/")):
                return JSONResponse({"detail": "Not Found"}, 404)
            f = UI_DIST / path
            return FileResponse(f if path and f.is_file() else UI_DIST / "index.html")
    return app


app = create_app()
