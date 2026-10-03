"""Campaign <-> outreach link.

A partner belongs to at most one campaign (partners.campaign_id). Everything that happens to an attached
partner - emails sent by the outreach queue, LinkedIn/X touches, replies, meetings, stage moves - counts towards
that campaign automatically. Nothing is stored twice: the numbers are computed from outreach_messages,
partner_interactions and partners each time they are read, so they can never drift from what really happened.

Manually logged campaign results (campaign_results) are kept for what the app cannot see on its own - opens and
clicks from another tool, signups, revenue, spend. The campaign's totals add the two together.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .store import now

SOCIAL_TYPES = ("linkedin", "x")          # touches made by hand on LinkedIn or X
MEETING_TYPES = ("meeting", "demo")       # counted as meetings held
LIVE_STAGES = ("in_conversation", "pilot", "signed")
# an accepted connection found in a LinkedIn export is an event, not a touch we made
CONNECTED_PREFIX = "Connected on LinkedIn:"


def _marks(n: int) -> str:
    return ",".join("?" * n)


def attach_partners(ws, cid: int, partner_ids: list[int], actor: int | None = None) -> dict:
    """Put partners (and, for a segment, the named organisations under it) into a campaign.

    A partner already in another campaign is moved; the result says from where. Partners of a different
    property are refused, because a campaign belongs to one property.
    """
    c = ws.one("SELECT id, property_id, name FROM campaigns WHERE id=?", (cid,))
    if not c:
        raise KeyError(cid)
    attached, moved, refused = [], [], []
    ids: list[int] = []
    for pid in partner_ids:
        p = ws.one("SELECT id, name, property_id, is_segment FROM partners WHERE id=?", (pid,))
        if not p:
            refused.append({"id": pid, "reason": "not found"})
        elif p["property_id"] != c["property_id"]:
            refused.append({"id": pid, "name": p["name"], "reason": f"belongs to {p['property_id']}, the campaign to {c['property_id']}"})
        elif p["is_segment"]:
            kids = [r["id"] for r in ws.q("SELECT id FROM partners WHERE parent_id=?", (pid,))]
            if not kids:
                refused.append({"id": pid, "name": p["name"], "reason": "segment with no named organisations yet - add them first"})
            ids += kids
        else:
            ids.append(pid)
    ts = now()
    for pid in dict.fromkeys(ids):                     # keep order, drop duplicates
        p = ws.one("SELECT p.id, p.name, p.campaign_id, c.name AS old FROM partners p LEFT JOIN campaigns c "
                   "ON c.id=p.campaign_id WHERE p.id=?", (pid,))
        if p["campaign_id"] == cid:
            continue
        ws.update("partners", "id", pid, {"campaign_id": cid, "updated_at": ts})
        (moved if p["campaign_id"] else attached).append(
            {"id": pid, "name": p["name"]} | ({"from": p["old"]} if p["campaign_id"] else {}))
    ws.update("campaigns", "id", cid, {"updated_at": ts})
    ws.audit(actor, "attach", "campaign", cid, {"attached": [a["id"] for a in attached], "moved": [m["id"] for m in moved]})
    return {"attached": attached, "moved": moved, "refused": refused}


def detach_partner(ws, cid: int, pid: int, actor: int | None = None) -> bool:
    n = ws.update("partners", "id", pid, {"campaign_id": None, "updated_at": now()}) \
        if ws.one("SELECT 1 FROM partners WHERE id=? AND campaign_id=?", (pid, cid)) else 0
    if n:
        ws.audit(actor, "detach", "campaign", cid, {"partner_id": pid})
    return bool(n)


def campaign_outreach(ws, cid: int) -> dict:
    """Everything the outreach side knows about a campaign: per-partner progress, totals and the send queue."""
    partners = ws.q("SELECT id, name, stage, priority, priority_score, contact_name, contact_email, email_consent, "
                    "next_step, next_step_date FROM partners WHERE campaign_id=? "
                    "ORDER BY COALESCE(priority_score,0) DESC, name", (cid,))
    empty = {"targets": 0, "emails_sent": 0, "social_touches": 0, "touched": 0, "replies": 0, "meetings": 0,
             "in_conversation": 0, "pilot": 0, "signed": 0, "declined": 0}
    if not partners:
        return {"partners": [], "totals": empty, "queue": {"drafts": 0, "approved": 0, "missing_email": 0, "next_due": None}}
    ids = [p["id"] for p in partners]
    mk = _marks(len(ids))
    msgs = ws.q(f"SELECT partner_id, step, delay_days, status, sent_at, replied_at, send_at, one_off, channel FROM outreach_messages "
                f"WHERE partner_id IN ({mk}) ORDER BY partner_id, step", ids)
    acts = ws.q(f"SELECT partner_id, type, MAX(date) AS last, COUNT(*) AS n FROM partner_interactions "
                f"WHERE partner_id IN ({mk}) AND summary NOT LIKE '{CONNECTED_PREFIX}%' GROUP BY partner_id, type", ids)
    by_msgs: dict[int, list] = {}
    for m in msgs:
        by_msgs.setdefault(m["partner_id"], []).append(m)
    by_acts: dict[int, dict] = {}
    for a in acts:
        by_acts.setdefault(a["partner_id"], {})[a["type"]] = a

    t = dict(empty)
    t["targets"] = len(partners)
    queue = {"drafts": 0, "approved": 0, "missing_email": 0, "next_due": None}
    rows = []
    for p in partners:
        ms = by_msgs.get(p["id"], [])
        ac = by_acts.get(p["id"], {})
        sent = [m for m in ms if m["sent_at"] and (m["channel"] or "email") == "email"]   # LinkedIn/X sends log a touch
        social = sum(ac[k]["n"] for k in SOCIAL_TYPES if k in ac)
        meetings = sum(ac[k]["n"] for k in MEETING_TYPES if k in ac)
        replied = any(m["replied_at"] for m in ms) or (p["email_consent"] or "") in ("replied", "opted_out")
        drafts = sum(1 for m in ms if m["status"] == "draft")
        approved = [m for m in ms if m["status"] == "approved"]
        t["emails_sent"] += len(sent)
        t["social_touches"] += social
        t["touched"] += 1 if (sent or social) else 0
        t["replies"] += 1 if replied else 0
        t["meetings"] += meetings
        if p["stage"] in t:
            t[p["stage"]] += 1
        queue["drafts"] += drafts
        queue["approved"] += len(approved)
        if (drafts or approved) and not p["contact_email"]:
            queue["missing_email"] += 1
        due = _next_due(ms)
        if due and (queue["next_due"] is None or due < queue["next_due"]):
            queue["next_due"] = due
        last = max([a["last"] for a in ac.values()] + [m["sent_at"][:10] for m in ms if m["sent_at"]], default=None)
        rows.append(p | {"emails_sent": len(sent), "social_touches": social, "meetings": meetings, "replied": replied,
                         "drafts": drafts, "approved": len(approved), "steps": len(ms), "last_touch": last,
                         "next_due": due})
    # in_conversation counts everyone past first contact, so the funnel reads top-down
    t["in_conversation"] = sum(1 for p in partners if p["stage"] in LIVE_STAGES)
    return {"partners": rows, "totals": t, "queue": queue}


def _next_due(ms: list[dict]) -> str | None:
    """Date the next approved step of one partner's sequence becomes due (None if nothing approved)."""
    for m in ms:
        if m["status"] != "approved":
            continue
        later = m.get("send_at") if m.get("send_at") and m["send_at"] > datetime.now(timezone.utc).isoformat() else None
        if m["step"] == 1 or m.get("one_off"):
            return later[:10] if later else "now"
        prev = next((x for x in ms if x["step"] == m["step"] - 1), None)
        if prev and prev["sent_at"]:
            due = (datetime.fromisoformat(prev["sent_at"]) + timedelta(days=m["delay_days"])).date().isoformat()
            return max(due, later[:10]) if later else due
        return None
    return None


def outreach_totals_by_campaign(ws, cids: list[int]) -> dict[int, dict]:
    """sent / replies / meetings from outreach, per campaign, for the campaign list."""
    if not cids:
        return {}
    out = {cid: {"emails_sent": 0, "replies": 0, "meetings": 0, "targets": 0, "social_touches": 0} for cid in cids}
    mk = _marks(len(cids))
    for r in ws.q(f"SELECT p.campaign_id AS cid, COUNT(*) AS n FROM partners p WHERE p.campaign_id IN ({mk}) "
                  f"GROUP BY p.campaign_id", cids):
        out[r["cid"]]["targets"] = r["n"]
    for r in ws.q(f"SELECT p.campaign_id AS cid, COUNT(*) AS n FROM outreach_messages m JOIN partners p "
                  f"ON p.id=m.partner_id WHERE p.campaign_id IN ({mk}) AND m.sent_at IS NOT NULL "
                  f"AND COALESCE(m.channel,'email')='email' GROUP BY p.campaign_id", cids):
        out[r["cid"]]["emails_sent"] = r["n"]
    for r in ws.q(f"SELECT p.campaign_id AS cid, COUNT(*) AS n FROM partners p WHERE p.campaign_id IN ({mk}) AND "
                  f"(p.email_consent IN ('replied','opted_out') OR EXISTS (SELECT 1 FROM outreach_messages m "
                  f"WHERE m.partner_id=p.id AND m.replied_at IS NOT NULL)) GROUP BY p.campaign_id", cids):
        out[r["cid"]]["replies"] = r["n"]
    for r in ws.q(f"SELECT p.campaign_id AS cid, i.type, COUNT(*) AS n FROM partner_interactions i JOIN partners p "
                  f"ON p.id=i.partner_id WHERE p.campaign_id IN ({mk}) AND i.type IN ({_marks(4)}) "
                  f"AND i.summary NOT LIKE '{CONNECTED_PREFIX}%' "
                  f"GROUP BY p.campaign_id, i.type", cids + list(MEETING_TYPES + SOCIAL_TYPES)):
        key = "meetings" if r["type"] in MEETING_TYPES else "social_touches"
        out[r["cid"]][key] += r["n"]
    return out
