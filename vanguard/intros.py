"""Introductions: reach investors and partners through people you already know.

LinkedIn's export holds your 1st-degree connections only; it never lists 2nd- or 3rd-degree connections, and
nothing here calls LinkedIn or automates an account. So paths are found two ways:

  direct  - a 1st-degree connection works at the target organisation. The surest path: they can introduce you
            to the right person inside, or tell you who that is.
  bridge  - a 1st-degree connection in the target's world (another investor for an investor target; a banker,
            fintech or payments person for a bank or fintech; a consultant for an advisory firm) with a real tie
            to you. These are *likely* 2nd-degree paths: confirm the mutual connection with the LinkedIn search
            link on each target, then ask.

Tie strength (0-5) comes from your own export: messages exchanged (more and more recent = stronger), skill
endorsements in either direction, and how long you've been connected. Message text is never stored - only a
count and the last date per person.

Every ask is a draft: an admin approves it, then it is emailed (only when the connection shared an email with
LinkedIn) or sent by hand on LinkedIn and marked sent. The ask is double opt-in: the connector forwards a short
blurb only if they're comfortable, and the target says yes before any introduction is made.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import quote

from .linkedin import companies_match, import_connections, norm_company, partner_keys
from .store import now

# who a connection is, from their title and company
TAGS = {
    "investor": r"\b(venture|ventures|vc|investor|investors|investments?|angel|fund manager|general partner|limited partner|family office|syndicate|capital(?! markets)(?! one))\b",
    "bank": r"\b(bank|bancorp|credit union|banking|treasury|lending|wealth)\b",
    "fintech": r"\b(fintech|payments?|stablecoin|crypto|blockchain|digital assets?|tokeni[sz]|web3|defi|custody|wallet|exchange|ledger)\b",
    "compliance": r"\b(compliance|risk|regtech|aml|kyc|audit|assurance|regulatory|governance)\b",
    "consulting": r"\b(deloitte|kpmg|pwc|ey\b|ernst|accenture|mckinsey|bain|bcg|protiviti|crowe|grant thornton|baker tilly|forvis|guidehouse|capgemini|consult)",
    "ibm": r"\bibm\b|kyndryl",
    "senior": r"\b(partner|principal|managing director|director|head|vp|vice president|chief|cxo|ceo|cto|cfo|coo|founder|president|leader|svp|evp)\b",
}
_TAG_RE = {k: re.compile(v, re.I) for k, v in TAGS.items()}
WANTED = {   # which kinds of connector can plausibly reach which kind of target
    "investor": ("investor", "fintech"),
    "design_partner": ("bank", "fintech", "compliance"),
    "co_sell": (),            # firms compete: only insiders or people named in their background
    "integration": ("fintech",),
    "distribution": ("fintech", "bank"),
    "referral_affiliate": ("fintech", "consulting"),
}
ACTIVE = ("suggested", "draft", "approved", "sent", "accepted")


def tags_for(position: str | None, company: str | None) -> list[str]:
    text = f"{position or ''} {company or ''}"
    return [k for k, rx in _TAG_RE.items() if rx.search(text)]


def strength(msg_count: int, last_message_at: str | None, endorsements: int, connected_on: str | None,
             today: date | None = None) -> float:
    today = today or date.today()
    s = 0.0
    if msg_count:
        s += min(2.0, 0.5 + msg_count / 20)                     # any conversation counts; long ones count more
    if last_message_at:
        try:
            days = (today - date.fromisoformat(last_message_at[:10])).days
            s += 1.5 if days <= 180 else 1.0 if days <= 730 else 0.5
        except ValueError:
            pass
    s += min(1.0, endorsements * 0.25)
    if connected_on:
        try:
            years = (today - date.fromisoformat(connected_on[:10])).days / 365
            s += 0.5 if years >= 5 else 0.25 if years >= 2 else 0
        except ValueError:
            pass
    return round(min(5.0, s), 2)


# ---------------------------------------------------------------- full LinkedIn export
def _read(z: zipfile.ZipFile, name: str) -> str | None:
    for n in z.namelist():
        if n.rsplit("/", 1)[-1].lower() == name.lower():
            return z.read(n).decode("utf-8-sig", errors="replace")
    return None


def _url(u: str | None) -> str:
    u = (u or "").strip().rstrip("/").lower()
    u = re.sub(r"^(https?://)?(www\.)?", "", u)
    return u


def import_export_zip(ws, data: bytes, user_id: int | None) -> dict:
    """Load LinkedIn's full data export (.zip): connections, then message counts, endorsements and tie strength."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("not a zip file - upload the archive LinkedIn emailed you, or just Connections.csv")
    conns = _read(z, "Connections.csv")
    if not conns:
        raise ValueError("Connections.csv is not in this archive - request the archive with Connections ticked")
    res = import_connections(ws, conns, user_id)
    me = None
    msgs: dict[str, list] = {}
    text = _read(z, "messages.csv")
    if text:
        rows = list(csv.DictReader(io.StringIO(text)))
        # the account owner is the most frequent sender
        senders: dict[str, int] = {}
        for r in rows:
            senders[_url(r.get("SENDER PROFILE URL"))] = senders.get(_url(r.get("SENDER PROFILE URL")), 0) + 1
        me = max(senders, key=senders.get) if senders else None
        for r in rows:
            day = (r.get("DATE") or "")[:10]
            people = {_url(r.get("SENDER PROFILE URL"))} | {_url(u) for u in (r.get("RECIPIENT PROFILE URLS") or "").split(",")}
            for u in people - {me, ""}:
                m = msgs.setdefault(u, [0, ""])
                m[0] += 1
                m[1] = max(m[1], day)
    endorse: dict[str, int] = {}
    for fname, col in (("Endorsement_Received_Info.csv", "Endorser Public Url"), ("Endorsement_Given_Info.csv", "Endorsee Public Url")):
        t = _read(z, fname)
        if t:
            for r in csv.DictReader(io.StringIO(t)):
                u = _url(r.get(col))
                if u:
                    endorse[u] = endorse.get(u, 0) + 1
    rows = ws.q("SELECT id, profile_url, position, company, connected_on FROM linkedin_connections WHERE COALESCE(owner_id,0)=?",
                (user_id or 0,))
    warm = 0
    for c in rows:
        u = _url(c["profile_url"])
        mc, last = msgs.get(u, [0, None])
        en = endorse.get(u, 0)
        st = strength(mc, last, en, c["connected_on"])
        warm += 1 if st >= 2 else 0
        ws.update("linkedin_connections", "id", c["id"], {"msg_count": mc, "last_message_at": last or None, "endorsements": en,
                                                          "strength": st, "tags": ",".join(tags_for(c["position"], c["company"]))})
    res |= {"with_messages": sum(1 for c in rows if msgs.get(_url(c["profile_url"]))), "warm": warm,
            "files": sorted(n.rsplit("/", 1)[-1] for n in z.namelist() if n.endswith(".csv"))[:40]}
    return res


# ---------------------------------------------------------------- path finding
def _target_org(p: dict) -> str:
    """The organisation to match: the firm for an investor, the partner's own name otherwise."""
    if p["kind"] == "investor" and p.get("partner_type") and " · " in p["partner_type"]:
        firm = p["partner_type"].rsplit(" · ", 1)[-1]
        return "" if firm in ("no firm listed",) or firm.lower().startswith("angel investor") else firm
    return p["name"]


def mutuals_search_url(p: dict) -> str:
    """LinkedIn people search for the target, filtered to your 2nd-degree network (opens in your own browser)."""
    who = p.get("contact_name") or p["name"]
    org = _target_org(p)
    kw = f"{who} {org}".strip() if p["kind"] == "investor" else f"{org}"
    return ("https://www.linkedin.com/search/results/people/?keywords=" + quote(kw) + "&network=%5B%22S%22%5D")


GENERIC_ORGS = {"self employed", "self", "freelance", "retired", "confidential", "independent consultant", "independent",
                "stealth", "stealth startup", "consultant", "consulting", "", "n a", "none", "various", "student", "home",
                "private", "global", "group", "capital", "ventures", "partners", "advisors", "solutions", "technologies",
                "digital", "labs", "network", "bank", "fund", "trust", "family", "investments", "holdings", "company"}


COMMON_WORDS = {"bridge", "prime", "summit", "atlas", "vision", "north", "south", "first", "union", "alpha", "omega",
                "point", "focus", "scale", "launch", "growth", "value", "impact", "smart", "next", "level", "stage",
                "anchor", "signal", "early", "venture", "series", "angel", "seed", "round", "funds", "money", "trade"}


def _mentions(text: str, company_norm: str) -> bool:
    """Is this connection's employer named in the target's research (e.g. 'ex-Visa', 'IBM consulting')?"""
    if not company_norm or company_norm in GENERIC_ORGS or len(company_norm) < 4:
        return False
    if " " not in company_norm and (len(company_norm) < 5 or company_norm in COMMON_WORDS):
        return False          # one short or everyday word ('Lead', 'Peak', 'Prime') would match ordinary text
    return re.search(r"(?<![a-z])" + re.escape(company_norm) + r"(?![a-z])", text) is not None


def candidates(p: dict, conns: list[dict], limit: int = 3) -> list[dict]:
    org = _target_org(p)
    keys = partner_keys(org) if org else set()
    wanted = WANTED.get(p["kind"], ("fintech",))
    # only what research says about the target (thesis, title, portfolio, deals) - not our own advice or hooks,
    # which mention the founder's employers and would make every target look connected to them
    thesis = " ".join(l for l in str(p.get("rationale") or "").splitlines() if l.startswith("Their thesis:"))
    raw = re.sub(r"https?://\S+|www\.\S+", " ", f"{p.get('how_to_find') or ''} {thesis}")
    research = norm_company(raw.replace("Sources:", " "))
    who = p.get("contact_name") or p["name"]
    out = []
    from .linkedin import norm_person, same_person
    contact = norm_person(p.get("contact_name"))
    for c in conns:
        if contact[0] and same_person(contact, norm_person(f"{c['first_name']} {c['last_name']}")):
            continue        # you already know the target person: no introduction needed, write to them directly
        tags = set((c.get("tags") or "").split(",")) - {""}
        st = float(c.get("strength") or 0)
        senior = "senior" in tags
        cn = c.get("company_norm") or norm_company(c.get("company"))
        if keys and companies_match(cn, keys):
            score = 60 + st * 7 + (8 if senior else 0)
            why = f"works at {c['company']} ({c['position'] or 'title not shared'}) - an insider who can introduce you or name the right person"
            out.append((score, "direct", why, c))
        elif research and _mentions(research, cn) and (st >= 0.5 or senior):
            score = 35 + st * 8 + (6 if senior else 0)
            why = (f"works at {c['company']}, which appears in {who}'s background - likely knows them or people who do "
                   f"(tie strength {st:g}/5); confirm the mutual connection first")
            out.append((score, "bridge", why, c))
        elif wanted and tags & set(wanted) and st >= 1.5 and (senior or "investor" in tags):
            hit = sorted(tags & set(wanted))
            score = 20 + st * 9 + (6 if senior else 0) + (4 if "investor" in hit and p["kind"] == "investor" else 0)
            why = (f"{', '.join(hit)} network ({c['position'] or ''} at {c['company'] or 'n/a'}) and a real tie with you "
                   f"(strength {st:g}/5) - likely knows {p.get('contact_name') or p['name']}; confirm the mutual connection first")
            out.append((score, "bridge", why, c))
    out.sort(key=lambda x: -x[0])
    return [{"score": int(s), "path": path, "reason": why, "connection": c} for s, path, why, c in out[:limit]]


MAX_ASKS_PER_CONNECTOR = 4      # nobody should get a pile of intro requests from you


def founder_properties() -> list[str]:
    try:
        from .failproof import load_failproof
        return list(load_failproof().focus.founder)
    except Exception:
        return ["liqmint-institutional", "liqmint", "vireoka"]


def suggest(ws, property_ids: list[str] | None = None, priorities=("P0", "P1"), per_target: int = 3,
            user_id: int | None = None) -> dict:
    """Find up to `per_target` introducers for every P0/P1 investor and partner of the founder's properties (by
    default); no connector is proposed for more than MAX_ASKS_PER_CONNECTOR targets; existing work is kept."""
    conns = ws.q("SELECT * FROM linkedin_connections")
    if not conns:
        return {"targets": 0, "suggested": 0, "direct": 0, "error": "no LinkedIn connections imported yet"}
    property_ids = property_ids or founder_properties()
    # every priority is checked for insiders; likely bridges are only proposed for P0/P1 targets
    sql = "SELECT * FROM partners WHERE COALESCE(is_segment,0)=0 AND stage NOT IN ('signed','declined')"
    args: list = []
    if property_ids:
        sql += f" AND property_id IN ({','.join('?' * len(property_ids))})"
        args += list(property_ids)
    targets = ws.q(sql, args)
    made = direct = 0
    ts = now()
    load: dict[int, int] = {}
    for r in ws.q("SELECT connection_id, COUNT(*) AS n FROM intro_requests WHERE status!='cancelled' GROUP BY connection_id"):
        load[r["connection_id"]] = r["n"]
    # best paths first across all targets, so a connector's few asks go to the targets they fit best
    pool = []
    for p in targets:
        for cand in candidates(p, conns, per_target + 3):
            if cand["path"] != "direct" and p.get("priority") not in priorities:
                continue
            pool.append((cand["score"] + (p.get("priority_score") or 0) / 10, p, cand))
    pool.sort(key=lambda x: -x[0])
    per: dict[int, int] = {}
    for _, p, cand in pool:
        c = cand["connection"]
        if per.get(p["id"], 0) >= per_target:
            continue
        if cand["path"] != "direct" and load.get(c["id"], 0) >= MAX_ASKS_PER_CONNECTOR:
            continue
        if True:
            row = ws.one("SELECT id, status FROM intro_requests WHERE partner_id=? AND connection_id=?", (p["id"], c["id"]))
            fields = {"path": cand["path"], "reason": cand["reason"], "score": cand["score"], "updated_at": ts}
            per[p["id"]] = per.get(p["id"], 0) + 1
            if row:
                if row["status"] == "suggested":
                    ws.update("intro_requests", "id", row["id"], fields)
                continue
            ws.insert("intro_requests", fields | {"partner_id": p["id"], "connection_id": c["id"], "status": "suggested",
                                                  "channel": "email" if c.get("email") else "linkedin",
                                                  "created_by": user_id, "created_at": ts})
            load[c["id"]] = load.get(c["id"], 0) + 1
            made += 1
            direct += cand["path"] == "direct"
    ws.audit(user_id, "suggest", "intros", None, {"targets": len(targets), "suggested": made})
    return {"targets": len(targets), "suggested": made, "direct": direct}


# ---------------------------------------------------------------- drafting
def _one_liner(p: dict) -> str:
    if p["property_id"] in ("liqmint-institutional", "liqmint", "vireoka"):
        return ("LiqMint is a governance, risk and evidence layer for institutional stablecoin and tokenized-asset "
                "operations: policy checks before a transaction moves, the client's custodian stays the signer, and an "
                "examiner-ready record afterwards.")
    return "Vireoka builds governance infrastructure for autonomous AI agents."


ASK = {
    "investor": "We're raising our first institutional round for Vireoka, and {target} looks like a strong fit for what we're building",
    "design_partner": "We're looking for two or three design partners for LiqMint, and {target} is high on our list",
    "co_sell": "I'd like to explore whether {org}'s practice and LiqMint could serve the same clients together",
    "integration": "I'd like to explore an integration between LiqMint and {org}",
    "distribution": "I'd like to explore a distribution partnership between LiqMint and {org}",
}


def draft(ws, intro_id: int, sender_name: str = "Narendra") -> dict:
    r = ws.one("SELECT i.*, p.name AS p_name, p.kind, p.property_id, p.contact_name, p.partner_type, c.first_name, "
               "c.last_name, c.email FROM intro_requests i JOIN partners p ON p.id=i.partner_id "
               "JOIN linkedin_connections c ON c.id=i.connection_id WHERE i.id=?", (intro_id,))
    if not r:
        raise KeyError(intro_id)
    org = _target_org(dict(r, name=r["p_name"])) or r["p_name"]
    org = re.split(r"\s+[-–]\s+|\s*\(", org)[0].strip() or org
    person = r["contact_name"] if r["contact_name"] and r["contact_name"] != r["p_name"] else None
    if r["kind"] == "investor":
        target = f"{r['contact_name'] or r['p_name']}" + (f" at {org}" if org and org != r["p_name"] else "")
    else:
        target = f"{person} at {r['p_name']}" if person else r["p_name"]
    first = (r["first_name"] or "").split(" ")[0] or "there"
    one = _one_liner(dict(r))
    ask = ASK.get(r["kind"], ASK["design_partner"]).format(target=target, org=org)
    whom = (r["contact_name"] if r["kind"] == "investor" else person) or "the right person"
    if r["path"] == "direct":
        body = (f"Hi {first},\n\nI hope you're well. A quick ask, and please say no if it isn't a fit.\n\n"
                f"{ask}. Since you're at {org}, would you be open to introducing me to {whom}"
                + (" (or whoever is closer to this)" if whom != "the right person" else "") +
                f", or forwarding the short note below if you think it's worth their time?\n\n"
                f"Either way, I'd value your honest read on whether this is a fit for {org}.\n\nThank you,\n{sender_name}")
    else:
        body = (f"Hi {first},\n\nI hope you're well. A quick ask, and please say no if it isn't a fit.\n\n"
                f"{ask}. If you know {whom}, would you be comfortable forwarding the short note below "
                f"and asking whether they'd take a 20-minute call? I'd only want the introduction if they say yes.\n\n"
                f"If you don't know them well, no problem at all - just let me know.\n\nThank you,\n{sender_name}")
    blurb = (f"Narendra Gore (ex-IBM Consulting sector leader for Hybrid Cloud and GenAI; Ph.D. in computer "
             f"engineering) is the founder of Vireoka. {one} "
             + ("He is raising Vireoka's first round and would value 20 minutes with you."
                if r["kind"] == "investor" else "He would value 20 minutes to see whether a short, scoped pilot makes sense."))
    subject = f"Quick ask: an introduction to {whom if whom != 'the right person' else 'someone at ' + org}"
    fields = {"subject": subject, "body": body + "\n\n---\nNote to forward:\n" + blurb, "blurb": blurb,
              "status": "draft", "updated_at": now()} | _lint(ws, r["property_id"], subject, body + "\n" + blurb)
    if r["status"] in ("suggested", "draft"):
        ws.update("intro_requests", "id", intro_id, fields)
    return fields


def _lint(ws, property_id: str, subject: str, body: str) -> dict:
    from .lint_gate import LintGate
    from .registry import get_properties
    prop = next((p for p in get_properties(["all"]) if p.id == property_id), None)
    if not prop:
        return {"lint_status": "pass", "lint_findings": None}
    fs = LintGate().check_items([("subject", subject), ("body", body)], prop.lint_profile, prop.banned_terms)
    return {"lint_status": LintGate.status(fs), "lint_findings": json.dumps([f.model_dump() for f in fs])}


def edit(ws, intro_id: int, subject: str | None, body: str | None) -> dict:
    r = ws.one("SELECT i.*, p.property_id FROM intro_requests i JOIN partners p ON p.id=i.partner_id WHERE i.id=?", (intro_id,))
    if not r:
        raise KeyError(intro_id)
    if r["status"] not in ("suggested", "draft", "approved"):
        raise ValueError(f"already {r['status']}")
    s, b = subject or r["subject"] or "", body or r["body"] or ""
    fields = {"subject": s, "body": b, "status": "draft", "approved_by": None, "approved_at": None,
              "updated_at": now()} | _lint(ws, r["property_id"], s, b)
    ws.update("intro_requests", "id", intro_id, fields)
    return fields


def approve(ws, ids: list[int], approver: str) -> dict:
    ok, refused = [], []
    for i in ids:
        r = ws.one("SELECT status, lint_status, body FROM intro_requests WHERE id=?", (i,))
        if not r:
            refused.append({"id": i, "reason": "not found"})
        elif r["status"] != "draft" or not r["body"]:
            refused.append({"id": i, "reason": f"status is {r['status']} - draft the ask first"})
        elif r["lint_status"] == "blocked":
            refused.append({"id": i, "reason": "blocked by the claim rules - edit the copy first"})
        else:
            ws.update("intro_requests", "id", i, {"status": "approved", "approved_by": approver, "approved_at": now(),
                                                  "updated_at": now()})
            ok.append(i)
    return {"approved": ok, "refused": refused}


def send_approved(ws, cfg=None, mailer=None, actor: int | None = None) -> dict:
    """Email approved asks whose connector shared an address; LinkedIn ones wait to be sent by hand. Each ask
    goes from the mailbox of the target's property (EmailConfig.for_property), within that mailbox's daily cap."""
    from .outreach import EmailConfig, MailRouter, footer
    cfg = cfg or EmailConfig.from_env()
    if cfg.problems():
        return {"sent": [], "skipped": [], "error": "; ".join(cfg.problems())}
    router = MailRouter(ws, cfg, mailer)
    sent, skipped = [], []
    for r in ws.q("SELECT i.*, c.email, c.first_name, c.last_name, p.name AS p_name, p.property_id FROM intro_requests i "
                  "JOIN linkedin_connections c ON c.id=i.connection_id JOIN partners p ON p.id=i.partner_id "
                  "WHERE i.status='approved' ORDER BY i.score DESC"):
        who = f"{r['first_name']} {r['last_name']}"
        if not r["email"]:
            skipped.append({"id": r["id"], "to": who, "reason": "no email shared on LinkedIn - send it on LinkedIn and mark it sent"})
            continue
        if ws.one("SELECT 1 FROM email_suppression WHERE email=?", (r["email"].lower(),)):
            ws.update("intro_requests", "id", r["id"], {"status": "cancelled", "error": "address opted out"})
            skipped.append({"id": r["id"], "to": who, "reason": "opted out - cancelled"})
            continue
        mc = router.config(r["property_id"])
        if not router.room(mc):
            skipped.append({"id": r["id"], "to": who, "reason": f"daily cap of {mc.daily_cap} reached"})
            continue
        e = EmailMessage()
        e["From"] = f"{mc.sender_name} <{mc.sender_email}>" if mc.sender_email else "Vireoka <outbox@localhost>"
        e["To"] = r["email"]
        if mc.reply_to:
            e["Reply-To"] = mc.reply_to
        e["Subject"] = r["subject"]
        e["Message-ID"] = make_msgid(domain=mc.sender_email.split("@")[-1] if "@" in mc.sender_email else "vanguard.local")
        e.set_content(r["body"] + footer(mc))
        try:
            router.mailer(mc).send(e, {"intro_id": r["id"]})
        except Exception as ex:
            ws.update("intro_requests", "id", r["id"], {"error": f"{type(ex).__name__}: {ex}"[:400]})
            skipped.append({"id": r["id"], "to": who, "reason": f"send failed: {ex}"})
            continue
        router.used(mc)
        _mark_sent(ws, r, "email", r["email"], actor)
        ws.update("intro_requests", "id", r["id"], {"from_email": mc.sender_email.lower() or None})
        sent.append({"id": r["id"], "to": who, "email": r["email"], "target": r["p_name"], "from": mc.sender_email})
    router.close()
    if mailer is not None and hasattr(mailer, "close"):
        mailer.close()
    return {"sent": sent, "skipped": skipped, "mode": cfg.mode}


def _mark_sent(ws, r: dict, channel: str, to_email: str | None, actor: int | None):
    ts = now()
    ws.update("intro_requests", "id", r["id"], {"status": "sent", "sent_at": ts, "channel": channel, "to_email": to_email,
                                                "updated_at": ts})
    who = f"{r['first_name']} {r['last_name']}"
    ws.insert("partner_interactions", {"partner_id": r["partner_id"], "date": ts[:10], "type": "linkedin" if channel == "linkedin" else "email",
                                       "summary": f"Asked {who} for an introduction ({r['path']} path, by {channel}).",
                                       "outcome": "none", "next_step": f"Wait for {who.split(' ')[0]}'s answer",
                                       "created_by": actor, "created_at": ts})


def mark_sent_linkedin(ws, intro_id: int, actor: int | None) -> None:
    r = ws.one("SELECT i.*, c.first_name, c.last_name FROM intro_requests i JOIN linkedin_connections c "
               "ON c.id=i.connection_id WHERE i.id=?", (intro_id,))
    if not r:
        raise KeyError(intro_id)
    if r["status"] != "approved":
        raise ValueError("approve the ask first")
    _mark_sent(ws, r, "linkedin", None, actor)


OUTCOMES = {"accepted": "agreed to make the introduction", "introduced": "made the introduction",
            "declined": "declined or didn't know them", "cancelled": "cancelled"}


def record_outcome(ws, intro_id: int, outcome: str, note: str | None, actor: int | None) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    r = ws.one("SELECT i.*, c.first_name, c.last_name, p.stage FROM intro_requests i JOIN linkedin_connections c "
               "ON c.id=i.connection_id JOIN partners p ON p.id=i.partner_id WHERE i.id=?", (intro_id,))
    if not r:
        raise KeyError(intro_id)
    ts = now()
    ws.update("intro_requests", "id", intro_id, {"status": outcome, "outcome": note, "updated_at": ts})
    who = f"{r['first_name']} {r['last_name']}"
    if outcome in ("accepted", "introduced", "declined"):
        ws.insert("partner_interactions", {
            "partner_id": r["partner_id"], "date": ts[:10], "type": "note",
            "summary": f"{who} {OUTCOMES[outcome]}." + (f" {note}" if note else ""),
            "outcome": "positive" if outcome != "declined" else "neutral",
            "next_step": "Follow up within a day of the introduction" if outcome == "introduced" else None,
            "created_by": actor, "created_at": ts})
    if outcome == "introduced" and r["stage"] == "identified":
        ws.update("partners", "id", r["partner_id"], {"stage": "contacted", "updated_at": ts})
    return {"ok": True, "status": outcome}


def listing(ws, status: str | None = None, partner_id: int | None = None, kind: str | None = None) -> list[dict]:
    sql = ("SELECT i.*, p.name AS partner_name, p.kind AS partner_kind, p.priority, p.priority_score, p.property_id, "
           "p.contact_name AS target_contact, p.partner_type, c.first_name, c.last_name, c.position, c.company, c.email, "
           "c.profile_url, c.strength, c.msg_count, c.last_message_at, c.endorsements FROM intro_requests i "
           "JOIN partners p ON p.id=i.partner_id JOIN linkedin_connections c ON c.id=i.connection_id WHERE 1=1")
    args: list = []
    if status:
        sql += " AND i.status=?"; args.append(status)
    if partner_id:
        sql += " AND i.partner_id=?"; args.append(partner_id)
    if kind:
        sql += " AND p.kind=?"; args.append(kind)
    rows = ws.q(sql + " ORDER BY COALESCE(p.priority_score,0) DESC, p.name, i.score DESC LIMIT 2000", args)
    for r in rows:
        r["mutuals_url"] = mutuals_search_url({"kind": r["partner_kind"], "name": r["partner_name"],
                                               "contact_name": r["target_contact"], "partner_type": r["partner_type"]})
    return rows
