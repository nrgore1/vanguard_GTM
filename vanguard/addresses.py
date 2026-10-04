"""Only email named people (v0.15.1).

A general inbox (support@, info@, sales@, partnerships@ ...) is read by whoever is on duty, not by the person we
mean to reach, and cold email to it reads as spam. An address is used for outreach only when it is a named
person's own:

  role        the local part is a general inbox            -> never emailed; refused when entered
  named       the local part matches the contact's name    -> emailed (brackin@gradient.com for Andrew Brackin)
  unverified  anything else                                -> held until someone confirms it is that person's own
                                                              address (partners.email_named = 1)

Addresses a person shared with you themselves (LinkedIn export) count as confirmed.
"""
from __future__ import annotations

import re
import unicodedata

ROLE = {
    "info", "information", "support", "help", "helpdesk", "contact", "contactus", "contacts", "hello", "hi", "hey",
    "sales", "admin", "administrator", "team", "office", "press", "media", "pr", "marketing", "partner", "partners",
    "partnership", "partnerships", "projects", "project", "deals", "dealflow", "deal", "invest", "investing",
    "investors", "investor", "investments", "ir", "pitch", "pitches", "submissions", "apply", "applications",
    "careers", "career", "jobs", "hr", "recruiting", "talent", "service", "services", "customerservice",
    "customercare", "care", "enquiries", "enquiry", "inquiries", "inquiry", "general", "mail", "email", "bd",
    "business", "biz", "founders", "events", "event", "booking", "bookings", "reservations", "reservation",
    "noreply", "no-reply", "donotreply", "postmaster", "webmaster", "hostmaster", "abuse", "privacy", "legal",
    "compliance", "security", "billing", "accounts", "accounting", "finance", "payments", "feedback", "newsletter",
    "news", "community", "membership", "members", "studio", "weddings", "wedding", "discover", "connect", "hq",
    "ops", "operations", "orders", "shop", "store", "academy", "programs", "program", "community", "volunteer",
    "outreach", "aiethics", "ethics", "research", "editor", "editorial", "office", "secretary", "president",
    "director", "manager", "staff", "us", "all", "everyone", "team", "group", "tye",
}
QUALIFIERS = {"us", "usa", "uk", "in", "india", "na", "eu", "team", "desk", "dept", "global", "hq", "ny", "nyc", "sf",
              "la", "official", "main", "online", "web", "inbox", "line", "center", "centre"}
_SPLIT = re.compile(r"[._\-]+")
HONORIFICS = {"dr", "mr", "mrs", "ms", "prof", "sir", "phd", "jr", "sr"}


def local_part(addr: str) -> str:
    return (addr or "").strip().lower().split("@", 1)[0].split("+", 1)[0]


def is_role(addr: str | None) -> bool:
    loc = local_part(addr or "")
    if not loc:
        return False
    if loc in ROLE:
        return True
    toks = [t for t in _SPLIT.split(loc) if t]
    return bool(toks) and toks[0] in ROLE and all(t in ROLE or t in QUALIFIERS or t.isdigit() for t in toks[1:])


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def matches_name(addr: str | None, name: str | None) -> bool:
    """The address's local part is built from this person's name: first, last, first.last, flast, firstl, initials."""
    if not addr or not name:
        return False
    loc = re.sub(r"[^a-z]", "", _ascii(local_part(addr)))
    parts = [p for p in re.split(r"[^a-z]+", _ascii(name)) if p and p not in HONORIFICS]
    if not loc or not parts:
        return False
    first, last = parts[0], parts[-1]
    if (len(first) >= 3 and first in loc) or (len(last) >= 3 and last in loc):
        return True
    if len(loc) >= 4 and (first.startswith(loc) or last.startswith(loc)):      # naren@ for Narendra
        return True
    initials = "".join(p[0] for p in parts)
    return loc in {initials, first[0] + last, first + last[0], (first[0] + last)[:8]} and len(loc) >= 2


def classify(addr: str | None, contact_name: str | None, confirmed: bool = False) -> str:
    if not addr:
        return "none"
    if is_role(addr):
        return "role"
    if confirmed or matches_name(addr, contact_name):
        return "named"
    return "unverified"


ROLE_REASON = "general inbox ({addr}), not a named person - find a named contact"
UNVERIFIED_REASON = ("{addr} isn't confirmed as {who}'s own address - confirm it on the partner (Edit) "
                     "or find a named contact")


IMPORTED = ("research", "investor_research", "agent", "agent-segment")


def purge(ws, user_id: int | None = None) -> dict:
    """Remove general-inbox addresses from partners, and imported addresses that aren't a named person's own (both
    kept as a note in How to find), and cancel unsent emails to them. Addresses someone typed in that aren't
    confirmed are left in place and listed: they are held at send time until confirmed."""
    from .store import now
    removed, held = [], []
    for p in ws.q("SELECT id, name, contact_name, contact_email, email_named, how_to_find, source FROM partners "
                  "WHERE contact_email IS NOT NULL AND contact_email <> ''"):
        cls = classify(p["contact_email"], p["contact_name"], bool(p["email_named"]))
        if cls == "role" or (cls == "unverified" and (p["source"] or "") in IMPORTED):
            note = f"General inbox (not used for outreach): {p['contact_email']}"
            htf = p["how_to_find"] or ""
            ws.update("partners", "id", p["id"], {"contact_email": None, "email_named": 0, "updated_at": now(),
                                                  "how_to_find": (htf + " | " + note) if htf and note not in htf else (htf or note)})
            with ws.conn() as c:
                n = c.execute("UPDATE outreach_messages SET status='cancelled', error='general inbox, not a named person' "
                              "WHERE partner_id=? AND status IN ('draft','approved') AND COALESCE(channel,'email')='email'",
                              (p["id"],)).rowcount
            removed.append({"partner": p["name"], "address": p["contact_email"], "cancelled": n})
        elif cls == "unverified":
            held.append({"partner": p["name"], "address": p["contact_email"], "contact": p["contact_name"]})
    ws.audit(user_id, "purge-general-inboxes", "partner", None, {"removed": len(removed), "held": len(held)})
    return {"removed": removed, "unverified": held}
