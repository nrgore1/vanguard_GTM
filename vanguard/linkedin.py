"""LinkedIn connections, from LinkedIn's own data export - no API, no scraping, no automation.

LinkedIn does not let outside apps read your connections or send messages for you, and scraping breaks its terms.
What it does allow is "Get a copy of your data" (Settings -> Data privacy), which emails you Connections.csv:
First Name, Last Name, URL, Email Address, Company, Position, Connected On. This module loads that file and
matches each connection's company to the partner list, so a partner page can say who you already know there.

  * Each user imports their own file; connections are kept per user ("who knows someone at X").
  * Re-importing is safe: rows are keyed by (profile URL, user) and refreshed in place.
  * A partner's named contact who turns up as a connection gets a single "Connected on LinkedIn" entry in the
    partner timeline - that is how an accepted request shows up after the next export.
  * Email addresses are only those LinkedIn included (the connection chose to share it). One is copied to the
    partner only when the partner has no address yet and the connection IS the partner's named contact.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from .store import now

# too generic to match on a prefix alone ('Bank' must not match 'Bank of New York Mellon')
GENERIC = {"bank", "capital", "digital", "financial", "finance", "partners", "consulting", "ventures", "labs",
           "global", "advisory", "technologies", "technology", "solutions", "services", "crypto", "network"}
HEADER = ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"]
_SUFFIX = re.compile(r"\b(inc|llc|llp|ltd|limited|corp|corporation|co|company|pc|p c|plc|na|n a|sa|ag|gmbh|the|us|usa|"
                     r"group|holdings)\b")


def norm_company(name: str | None) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"(^and |\band$)", "", s).strip()


def partner_keys(name: str) -> set[str]:
    """'U.S. Bancorp (U.S. Bank)' -> {'u s bancorp', 'u s bank'}; 'Crowe LLP' -> {'crowe'}."""
    keys = {norm_company(name)}
    for inner in re.findall(r"\(([^)]+)\)", name):
        keys.add(norm_company(inner))
    keys.add(norm_company(re.sub(r"\([^)]*\)", " ", name)))
    keys.add(norm_company(re.split(r"\s+[-–]\s+", name)[0]))     # 'KPMG US - Digital Assets Advisory' -> 'kpmg'
    return {k for k in keys if len(k) >= 2}


def companies_match(company_norm: str, keys: set[str]) -> bool:
    if not company_norm:
        return False
    for k in keys:
        if company_norm == k:
            return True
        short, long_ = sorted((company_norm, k), key=len)
        if len(short) >= 4 and short not in GENERIC and long_.startswith(short + " "):    # 'lead' ~ 'lead bank', 'crowe' ~ 'crowe advisory'
            return True
    return False


def norm_person(name: str | None) -> tuple[str, str]:
    """('brandon', 'chasse') from 'Brandon J. Chasse, Manager' - first and last word, titles after a comma dropped."""
    s = (name or "").split(",")[0].lower()
    words = re.sub(r"[^a-z\s'-]", " ", s).split()
    return (words[0], words[-1]) if words else ("", "")


def same_person(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """First names equal, and last names equal or one is just the other's initial (LinkedIn shows 'Eleni S.')."""
    if not a[0] or a[0] != b[0]:
        return False
    la, lb = a[1].rstrip("."), b[1].rstrip(".")
    return la == lb or (len(la) == 1 and lb.startswith(la)) or (len(lb) == 1 and la.startswith(lb))


def parse_export(text: str) -> list[dict]:
    """Rows of LinkedIn's Connections.csv. The file starts with a few 'Notes:' lines before the header."""
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("First Name,")), None)
    if start is None:
        raise ValueError("this is not LinkedIn's Connections.csv - no 'First Name,Last Name,URL,...' header found")
    rows = []
    for r in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        first, last = (r.get("First Name") or "").strip(), (r.get("Last Name") or "").strip()
        if not (first or last):
            continue
        rows.append({"first_name": first, "last_name": last, "profile_url": (r.get("URL") or "").strip() or None,
                     "email": (r.get("Email Address") or "").strip().lower() or None,
                     "company": (r.get("Company") or "").strip() or None,
                     "position": (r.get("Position") or "").strip() or None,
                     "connected_on": _date(r.get("Connected On"))})
    return rows


def _date(s: str | None) -> str | None:
    s = (s or "").strip()
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s or None


def import_connections(ws, text: str, user_id: int | None) -> dict:
    rows = parse_export(text)
    ts = now()
    added = refreshed = 0
    for r in rows:
        key = r["profile_url"] or f"{r['first_name']} {r['last_name']}|{r['company'] or ''}"
        data = r | {"profile_url": key, "company_norm": norm_company(r["company"]), "updated_at": ts}
        old = ws.one("SELECT id FROM linkedin_connections WHERE profile_url=? AND COALESCE(owner_id,0)=?",
                     (key, user_id or 0))
        if old:
            ws.update("linkedin_connections", "id", old["id"], data); refreshed += 1
        else:
            ws.insert("linkedin_connections", data | {"owner_id": user_id, "imported_at": ts}); added += 1
    linked = _link_contacts(ws, user_id)
    ws.audit(user_id, "import", "linkedin_connections", None, {"added": added, "refreshed": refreshed} |
             {k: len(v) for k, v in linked.items()})
    return {"connections": len(rows), "added": added, "refreshed": refreshed,
            "partners_with_connections": len(partners_with_connections(ws)), **linked}


def _link_contacts(ws, user_id: int | None) -> dict:
    """Named contacts that are now connections: one timeline entry each, and their shared email if the partner has none."""
    conns = ws.q("SELECT * FROM linkedin_connections")
    by_first: dict[str, list[dict]] = {}
    for c in conns:
        by_first.setdefault(norm_person(f"{c['first_name']} {c['last_name']}")[0], []).append(c)
    connected, emails = [], []
    for p in ws.q("SELECT id, name, contact_name, contact_email, linkedin_url FROM partners WHERE contact_name IS NOT NULL "
                  "AND COALESCE(is_segment,0)=0"):
        keys = partner_keys(p["name"])
        want = norm_person(p["contact_name"])
        hit = next((c for c in by_first.get(want[0], [])
                    if same_person(want, norm_person(f"{c['first_name']} {c['last_name']}"))
                    and companies_match(c["company_norm"], keys)), None)
        if not hit:
            continue
        who = f"{hit['first_name']} {hit['last_name']}"
        if not p["linkedin_url"] and (hit["profile_url"] or "").startswith("http"):   # for LinkedIn sequences
            ws.update("partners", "id", p["id"], {"linkedin_url": hit["profile_url"]})
        if not ws.one("SELECT 1 FROM partner_interactions WHERE partner_id=? AND type='linkedin' AND summary LIKE ?",
                      (p["id"], f"Connected on LinkedIn: {who}%")):
            since = f" since {hit['connected_on']}" if hit["connected_on"] else ""
            ws.insert("partner_interactions", {
                "partner_id": p["id"], "date": (hit["connected_on"] or now()[:10]), "type": "linkedin",
                "summary": f"Connected on LinkedIn: {who} ({hit['position'] or 'title not shared'}){since}. "
                           f"From the LinkedIn connections export.",
                "outcome": "positive", "next_step": "Send the follow-up message", "created_by": user_id, "created_at": now()})
            connected.append(p["name"])
        if hit["email"] and not p["contact_email"]:
            ws.update("partners", "id", p["id"], {"contact_email": hit["email"], "email_named": 1,   # their own, shared by them
                                                  "updated_at": now()})
            emails.append(p["name"])
    return {"contacts_connected": connected, "emails_filled": emails}


def partners_with_connections(ws, partner_ids: list[int] | None = None) -> dict[int, list[dict]]:
    """partner id -> the imported connections who work there (any user's), best match first."""
    conns = ws.q("SELECT c.*, u.name AS owner_name FROM linkedin_connections c LEFT JOIN users u ON u.id=c.owner_id")
    if not conns:
        return {}
    by_first: dict[str, list[dict]] = {}
    for c in conns:
        if c["company_norm"]:
            by_first.setdefault(c["company_norm"].split()[0], []).append(c)
    sql, args = "SELECT id, name, contact_name FROM partners WHERE COALESCE(is_segment,0)=0", []
    if partner_ids is not None:
        if not partner_ids:
            return {}
        sql += f" AND id IN ({','.join('?' * len(partner_ids))})"; args = list(partner_ids)
    out: dict[int, list[dict]] = {}
    for p in ws.q(sql, args):
        keys = partner_keys(p["name"])
        firsts = {k.split()[0] for k in keys if k}
        hits = [c for f in firsts for c in by_first.get(f, []) if companies_match(c["company_norm"], keys)]
        if hits:
            contact = norm_person(p["contact_name"])
            is_contact = lambda c: same_person(contact, norm_person(f"{c['first_name']} {c['last_name']}"))
            seen, uniq = set(), []
            for c in sorted(hits, key=lambda c: (not is_contact(c), c["last_name"] or "")):
                if c["id"] not in seen:
                    seen.add(c["id"]); uniq.append(c | {"is_contact": is_contact(c)})
            out[p["id"]] = uniq
    return out
