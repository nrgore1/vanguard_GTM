"""LinkedIn and X as outreach channels (v0.15.0).

A partner's sequence (or a one-off message) can run on email, LinkedIn or X. Email is sent by the app. LinkedIn
and X are never automated - no API, no browser automation, no scraping - so a LinkedIn or X step is drafted,
linted, approved and scheduled exactly like an email, and when it falls due it appears in the "send by hand"
list with its text and the person's profile link. The user sends it in LinkedIn or X and marks it sent, which
logs the touch, moves the partner to contacted and starts the next step's delay. Replies stop the sequence the
same way for every channel.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from .store import now

CHANNELS = ("email", "linkedin", "x")
MANUAL = ("linkedin", "x")
LABEL = {"email": "email", "linkedin": "LinkedIn", "x": "X"}
LINKEDIN_NOTE_MAX = 200      # connection-request note on a free account (300 with Premium)

_LI = re.compile(r"^(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(in|company)/([^/?#\s]+)/?", re.I)
_X = re.compile(r"^(?:https?://)?(?:www\.)?(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})/?(?:[?#].*)?$|^@?([A-Za-z0-9_]{1,15})$", re.I)


def norm_linkedin(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    m = _LI.match(url.strip())
    if not m:
        raise ValueError(f"{url!r} is not a LinkedIn profile link (linkedin.com/in/... or linkedin.com/company/...)")
    return f"https://www.linkedin.com/{m.group(1).lower()}/{m.group(2)}"


def norm_x(handle: str | None) -> str | None:
    if not handle or not handle.strip():
        return None
    m = _X.match(handle.strip())
    if not m:
        raise ValueError(f"{handle!r} is not an X handle (@name or x.com/name)")
    return m.group(1) or m.group(2)


def profile_url(p: dict, channel: str) -> str | None:
    if channel == "linkedin":
        return p.get("linkedin_url")
    if channel == "x" and p.get("x_handle"):
        return f"https://x.com/{p['x_handle']}"
    return None


def channel_findings(channel: str, step: int, body: str, one_off: bool) -> list[dict]:
    """Platform limits, as warnings: a LinkedIn first step is usually a connection-request note."""
    out = []
    if channel == "linkedin" and (step == 1 or one_off) and len(body) > LINKEDIN_NOTE_MAX:
        out.append({"rule_id": "linkedin-note-length", "severity": "warn", "location": "body", "excerpt": body[:80],
                    "message": ("If you aren't connected yet, this goes as a connection note: " if one_off else "")
                               + f"A LinkedIn connection note is limited to {LINKEDIN_NOTE_MAX} characters on a free "
                               f"account (300 with Premium); this is {len(body)}. Shorten it, or connect first and "
                               f"send it as a message."})
    return out


def relint(ws, mid: int) -> dict:
    from .intros import _lint
    m = ws.one("SELECT m.*, p.property_id FROM outreach_messages m JOIN partners p ON p.id=m.partner_id WHERE m.id=?", (mid,))
    res = _lint(ws, m["property_id"], m["subject"], m["body"])
    fs = json.loads(res["lint_findings"] or "[]") + channel_findings(m["channel"] or "email", m["step"], m["body"], bool(m["one_off"]))
    status = "blocked" if any(f["severity"] == "block" for f in fs) else ("warn" if fs else "pass")
    fields = {"lint_status": status, "lint_findings": json.dumps(fs)}
    ws.update("outreach_messages", "id", mid, fields)
    return fields


def _contact_problem(p: dict, channel: str) -> str | None:
    if channel == "email" and not p.get("contact_email"):
        return "no contact email on the partner yet"
    if channel == "linkedin" and not p.get("linkedin_url"):
        return "no LinkedIn profile link on the partner yet"
    if channel == "x" and not p.get("x_handle"):
        return "no X handle on the partner yet"
    return None


def set_channel(ws, partner_id: int, channel: str, user_id: int | None = None) -> dict:
    """Move every unsent step of this partner's sequence (and unsent one-offs) to a channel. Changed messages go
    back to draft: the same words sent somewhere else need a fresh approval."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    p = ws.one("SELECT * FROM partners WHERE id=?", (partner_id,))
    if not p:
        raise KeyError(partner_id)
    if p["is_segment"]:
        raise ValueError("this is a segment - set the channel on each named organisation")
    problem = _contact_problem(p, channel)
    if problem and channel != "email":
        raise ValueError(problem + " - add it (Edit) first")
    ts = now()
    changed = []
    for m in ws.q("SELECT id, channel FROM outreach_messages WHERE partner_id=? AND status IN ('draft','approved')", (partner_id,)):
        if (m["channel"] or "email") != channel:
            ws.update("outreach_messages", "id", m["id"], {"channel": channel, "status": "draft", "approved_by": None,
                                                           "approved_at": None, "updated_at": ts})
            relint(ws, m["id"])
            changed.append(m["id"])
    ws.update("partners", "id", partner_id, {"preferred_channel": channel, "updated_at": ts})
    ws.audit(user_id, "channel", "partner", partner_id, {"channel": channel, "messages": changed})
    return {"partner_id": partner_id, "channel": channel, "changed": changed}


def hold_reason(ws, m: dict, at: datetime | None = None) -> str | None:
    """Why an approved LinkedIn/X message isn't due yet (None = due now). Same rules as email sending."""
    at = at or datetime.now(timezone.utc)
    if m["stage"] in ("declined", "signed"):
        return f"partner is {m['stage']}"
    if m["is_segment"]:
        return "this is a segment"
    problem = _contact_problem(m, m["channel"])
    if problem:
        return problem
    if m["send_at"] and datetime.fromisoformat(m["send_at"]) > at:
        return f"scheduled for {m['send_at']}"
    if m["one_off"]:
        return None
    if ws.one("SELECT 1 FROM outreach_messages WHERE partner_id=? AND status='replied'", (m["partner_id"],)):
        return "partner already replied - sequence stopped"
    if m["step"] > 1:
        prev = ws.one("SELECT sent_at FROM outreach_messages WHERE partner_id=? AND step=?", (m["partner_id"], m["step"] - 1))
        if not prev or not prev["sent_at"]:
            return f"waiting for step {m['step'] - 1} to be sent"
        due = datetime.fromisoformat(prev["sent_at"]) + timedelta(days=m["delay_days"])
        if due > at:
            return f"due {due.date()}"
    return None


MANUAL_SQL = ("SELECT m.*, p.name AS partner_name, p.property_id, p.stage, p.is_segment, p.contact_name, "
              "p.contact_email, p.linkedin_url, p.x_handle, p.priority, p.priority_score FROM outreach_messages m "
              "JOIN partners p ON p.id=m.partner_id WHERE m.status='approved' AND m.channel IN ('linkedin','x')")


def by_hand(ws, at: datetime | None = None) -> list[dict]:
    """Approved LinkedIn/X messages with whether each is due now, and the profile link to send it from."""
    out = []
    for m in ws.q(MANUAL_SQL + " ORDER BY COALESCE(p.priority_score,0) DESC, m.partner_id, m.step"):
        why = hold_reason(ws, m, at)
        out.append(m | {"due": why is None, "held": why, "profile_url": profile_url(m, m["channel"])})
    return out


def mark_sent(ws, mid: int, user_id: int | None = None, at: datetime | None = None) -> dict:
    """The user sent this LinkedIn/X message by hand: record it like an email send."""
    m = ws.one("SELECT m.*, p.stage, p.linkedin_url, p.x_handle, p.name AS p_name, p.contact_name FROM outreach_messages m JOIN partners p "
               "ON p.id=m.partner_id WHERE m.id=?", (mid,))
    if not m:
        raise KeyError(mid)
    if (m["channel"] or "email") not in MANUAL:
        raise ValueError("emails are sent by the app - use Send due now")
    if m["status"] != "approved":
        raise ValueError(f"status is {m['status']} - it needs an admin's approval first" if m["status"] == "draft"
                         else f"status is {m['status']}")
    at = at or datetime.now(timezone.utc)
    ts = at.isoformat(timespec="seconds")
    ch = m["channel"]
    ws.update("outreach_messages", "id", mid, {"status": "sent", "sent_at": ts, "transport": ch, "updated_at": ts,
                                               "to_email": profile_url(m, ch)})
    from .outreach import EmailConfig, render
    text = render(m["body"], {"name": m["p_name"], "contact_name": m["contact_name"]}, EmailConfig.from_env())
    first = re.sub(r"\s+", " ", text).strip()
    what = "message" if m["one_off"] else f"step {m['step']}"
    ws.insert("partner_interactions", {"partner_id": m["partner_id"], "date": ts[:10], "type": ch,
                                       "summary": f"Sent {what} on {LABEL[ch]}: {first[:300]}", "outcome": "none",
                                       "created_by": user_id, "created_at": ts})
    if m["stage"] == "identified":
        ws.update("partners", "id", m["partner_id"], {"stage": "contacted", "updated_at": ts})
    ws.audit(user_id, "mark-sent", "outreach", mid, {"channel": ch})
    return {"id": mid, "status": "sent", "sent_at": ts, "channel": ch}
