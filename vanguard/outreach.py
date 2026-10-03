"""Partner outreach: approval-gated sending, reply tracking, opt-outs.

Safety model
  * Nothing is sent unless an ADMIN approved that specific message (status 'approved').
  * Default mode is 'outbox': approved messages are written as .eml files to output/outbox/ and marked sent,
    but nothing leaves the machine. Set VANGUARD_EMAIL_MODE=smtp to really send (your own mailbox - free).
  * SMTP mode refuses to send without a sender name, sender email and postal address (CAN-SPAM), and
    every email carries an opt-out line + List-Unsubscribe header.
  * Suppressed addresses (opt-outs, bounces) are never emailed again. Daily cap (default 20).
  * Step 2/3 go out only after the previous step was sent, the delay has passed, and nobody replied.
  * A reply (matched by In-Reply-To/References, or sender address) stops the sequence.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import json
import logging
import os
import re
import smtplib
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path
from typing import Callable, Iterable

from .store import now

log = logging.getLogger("vanguard.outreach")

OPT_OUT = re.compile(r"\b(unsubscribe|remove me|opt[- ]?out|stop emailing|do not (contact|email)|take me off)\b", re.I)
NEGATIVE = re.compile(r"\b(not interested|no thanks|no, thank|not a fit|not the right time|pass on this|we'?ll pass)\b", re.I)
POSITIVE = re.compile(r"\b(interested|sounds good|let'?s (talk|chat|connect|meet)|happy to|book|schedule|calendar|"
                      r"available|tell me more|send (it|the|over)|love to)\b", re.I)
BOUNCE_FROM = re.compile(r"(mailer-daemon|postmaster)@", re.I)


MAILBOX_KEYS = ("properties", "sender_name", "sender_email", "sender_address", "reply_to", "daily_cap",
                "smtp_host", "smtp_port", "smtp_user", "smtp_password", "imap_host", "imap_port", "imap_user", "imap_password",
                "imap_sent_folder")


def _mailboxes_from_env() -> dict:
    """VANGUARD_MAILBOXES=vireoka plus VANGUARD_MAILBOX_VIREOKA_PROPERTIES=vireoka,liqmint,... and the other
    VANGUARD_MAILBOX_VIREOKA_* keys in MAILBOX_KEYS. Unset keys fall back to the default mailbox, except the
    password; SMTP and IMAP user default to the mailbox's sender email."""
    boxes, owner = {}, {}
    for name in [n.strip().lower() for n in os.getenv("VANGUARD_MAILBOXES", "").split(",") if n.strip()]:
        pre = f"VANGUARD_MAILBOX_{re.sub(r'[^A-Z0-9]', '_', name.upper())}_"
        o = {k: os.environ[pre + k.upper()].strip() for k in MAILBOX_KEYS if os.environ.get(pre + k.upper(), "").strip()}
        o["properties"] = [x.strip() for x in o.get("properties", "").split(",") if x.strip()]
        for pid in o["properties"]:
            owner.setdefault(pid, name)
        boxes[name] = o
    return {"mailboxes": boxes, "property_mailbox": owner}


@dataclass
class EmailConfig:
    mode: str
    sender_name: str
    sender_email: str
    sender_address: str
    reply_to: str
    daily_cap: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_starttls: bool
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str
    outbox_dir: Path
    postmark_token: str = ""
    postmark_stream_outreach: str = "outbound"
    postmark_stream_notify: str = "outbound"
    postmark_inbound_address: str = ""
    postmark_allow_cold: bool = False
    postmark_track_opens: bool = False
    postmark_monthly_cap: int = 100
    webhook_user: str = ""
    webhook_password: str = ""
    notify_replies: bool = True
    save_sent: bool = True     # copy each email sent by SMTP into the mailbox's Sent folder over IMAP
    sent_folder: str = ""      # "" = find it (the folder flagged \\Sent, else one named Sent)
    mailbox: str = "default"
    # extra mailboxes: name -> overrides (lower-case keys below), and property id -> mailbox name
    mailboxes: dict = field(default_factory=dict)
    property_mailbox: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "EmailConfig":
        g = os.getenv
        return cls(
            mode=(g("VANGUARD_EMAIL_MODE", "outbox") or "outbox").lower(),
            sender_name=g("VANGUARD_SENDER_NAME", ""), sender_email=g("VANGUARD_SENDER_EMAIL", ""),
            sender_address=g("VANGUARD_SENDER_ADDRESS", ""), reply_to=g("VANGUARD_REPLY_TO", ""),
            daily_cap=int(g("VANGUARD_EMAIL_DAILY_CAP", "20")),
            smtp_host=g("SMTP_HOST", ""), smtp_port=int(g("SMTP_PORT", "587")), smtp_user=g("SMTP_USER", ""),
            smtp_password=g("SMTP_PASSWORD", ""), smtp_starttls=g("SMTP_STARTTLS", "1") == "1",
            imap_host=g("IMAP_HOST", ""), imap_port=int(g("IMAP_PORT", "993")), imap_user=g("IMAP_USER", ""),
            imap_password=g("IMAP_PASSWORD", ""), imap_folder=g("IMAP_FOLDER", "INBOX"),
            outbox_dir=Path(g("VANGUARD_OUTPUT", "output")) / "outbox",
            postmark_token=g("POSTMARK_SERVER_TOKEN", ""),
            postmark_stream_outreach=g("VANGUARD_POSTMARK_STREAM_OUTREACH", "outbound") or "outbound",
            postmark_stream_notify=g("VANGUARD_POSTMARK_STREAM_NOTIFY", "outbound") or "outbound",
            postmark_inbound_address=g("VANGUARD_POSTMARK_INBOUND_ADDRESS", ""),
            postmark_allow_cold=g("VANGUARD_POSTMARK_ALLOW_COLD", "0") == "1",
            postmark_track_opens=g("VANGUARD_POSTMARK_TRACK_OPENS", "0") == "1",
            postmark_monthly_cap=int(g("VANGUARD_POSTMARK_MONTHLY_CAP", "100") or 100),
            webhook_user=g("VANGUARD_POSTMARK_WEBHOOK_USER", ""), webhook_password=g("VANGUARD_POSTMARK_WEBHOOK_PASSWORD", ""),
            notify_replies=g("VANGUARD_NOTIFY_REPLIES", "1") == "1",
            save_sent=g("VANGUARD_SAVE_SENT", "1") == "1", sent_folder=g("IMAP_SENT_FOLDER", ""),
            **_mailboxes_from_env())

    # -------------------------------------------------------- per-property mailboxes
    def for_property(self, property_id: str | None) -> "EmailConfig":
        """The config to send with for one property: its own mailbox (VANGUARD_MAILBOX_<NAME>_*) if it has one,
        otherwise the default (SMTP_*, VANGUARD_SENDER_*). A mailbox never inherits another mailbox's password."""
        name = self.property_mailbox.get(property_id or "")
        return self._mailbox(name) if name else self

    def _mailbox(self, name: str) -> "EmailConfig":
        o = self.mailboxes[name]
        sender = o.get("sender_email", "")
        return replace(self, mailbox=name, mailboxes={}, property_mailbox={},
                       sender_email=sender, sender_name=o.get("sender_name") or self.sender_name,
                       sender_address=o.get("sender_address") or self.sender_address, reply_to=o.get("reply_to", ""),
                       daily_cap=int(o.get("daily_cap") or self.daily_cap),
                       smtp_host=o.get("smtp_host") or self.smtp_host, smtp_port=int(o.get("smtp_port") or self.smtp_port),
                       smtp_user=o.get("smtp_user") or sender, smtp_password=o.get("smtp_password", ""),
                       imap_host=o.get("imap_host") or self.imap_host, imap_port=int(o.get("imap_port") or self.imap_port),
                       imap_user=(o.get("imap_user") or sender) if (o.get("imap_host") or self.imap_host) else "",
                       imap_password=o.get("imap_password") or o.get("smtp_password", ""),
                       sent_folder=o.get("imap_sent_folder") or self.sent_folder)

    def all_mailboxes(self) -> list["EmailConfig"]:
        return [self] + [self._mailbox(n) for n in self.mailboxes]

    def problems(self) -> list[str]:
        p = []
        seen: dict[str, str] = {}
        for name, o in self.mailboxes.items():
            env = f"VANGUARD_MAILBOX_{name.upper()}_"
            if not o.get("properties"):
                p.append(f"{env}PROPERTIES is empty - list the property ids this mailbox sends for")
            for pid in o.get("properties", []):
                if pid in seen:
                    p.append(f"property {pid} is in two mailboxes ({seen[pid]}, {name})")
                seen[pid] = name
            if self.mode in ("smtp", "postmark") and not o.get("sender_email"):
                p.append(f"{env}SENDER_EMAIL is required")
            if self.mode == "smtp" and not o.get("smtp_password"):
                p.append(f"{env}SMTP_PASSWORD is required in smtp mode")
        if self.mode not in ("outbox", "smtp", "postmark"):
            p.append("VANGUARD_EMAIL_MODE must be 'outbox', 'smtp' or 'postmark'")
        if self.mode == "postmark":
            for k, env in (("postmark_token", "POSTMARK_SERVER_TOKEN"), ("sender_name", "VANGUARD_SENDER_NAME"),
                           ("sender_email", "VANGUARD_SENDER_EMAIL"), ("sender_address", "VANGUARD_SENDER_ADDRESS")):
                if not getattr(self, k):
                    p.append(f"{env} is required in postmark mode")
        if self.mode == "smtp":
            for k in ("sender_name", "sender_email", "sender_address", "smtp_host", "smtp_user", "smtp_password"):
                if not getattr(self, k):
                    p.append(f"{k.upper() if k.startswith('smtp') else 'VANGUARD_' + k.upper()} is required in smtp mode")
        return p

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.sender_email and self.sender_address)

    def status(self) -> dict:
        pm = None
        if self.postmark_token or self.mode == "postmark":
            pm = {"configured": bool(self.postmark_token), "stream_outreach": self.postmark_stream_outreach,
                  "stream_notify": self.postmark_stream_notify, "inbound": bool(self.postmark_inbound_address),
                  "allow_cold": self.postmark_allow_cold, "cold_via_smtp": self.smtp_ready,
                  "monthly_cap": self.postmark_monthly_cap, "track_opens": self.postmark_track_opens,
                  "webhook_auth": bool(self.webhook_user and self.webhook_password)}
        boxes = [{"name": c.mailbox, "sender": f"{c.sender_name} <{c.sender_email}>" if c.sender_email else "",
                  "properties": self.mailboxes.get(c.mailbox, {}).get("properties", []) if c.mailbox != "default" else None,
                  "daily_cap": c.daily_cap, "imap_configured": bool(c.imap_host and c.imap_user)}
                 for c in self.all_mailboxes()]
        return {"mode": self.mode, "live": self.mode in ("smtp", "postmark") and not self.problems(),
                "auto_every_min": float(os.getenv("VANGUARD_OUTREACH_EVERY_MIN", "0") or 0),
                "mailboxes": boxes, "senders": {pid: next(b["sender"] for b in boxes if b["name"] == n)
                                                for pid, n in self.property_mailbox.items()},
                "problems": self.problems(), "sender": f"{self.sender_name} <{self.sender_email}>" if self.sender_email else "",
                "daily_cap": self.daily_cap, "imap_configured": any(b["imap_configured"] for b in boxes), "postmark": pm}


# ---------------------------------------------------------------- rendering
def render(text: str, partner: dict, cfg: EmailConfig) -> str:
    first = (partner.get("contact_name") or "").split(" ")[0] or "there"
    values = {"first_name": first, "company": partner["name"], "sender_name": cfg.sender_name or "The Vireoka team"}
    for tag, value in values.items():
        # {{tag}} is the merge-tag format; {tag} also appears in drafts written before v0.8.1
        text = text.replace("{{" + tag + "}}", value).replace("{" + tag + "}", value)
    return text


def footer(cfg: EmailConfig) -> str:
    who = cfg.sender_name or "Vireoka"
    addr = cfg.sender_address or "[postal address - set VANGUARD_SENDER_ADDRESS]"
    return (f"\n\n--\n{who} · Vireoka LLC · {addr}\n"
            "You're receiving this one-to-one note because of your work in this area. "
            "Reply \"unsubscribe\" and we won't email you again.")


def build_email(msg: dict, partner: dict, cfg: EmailConfig) -> EmailMessage:
    e = EmailMessage()
    e["From"] = f"{cfg.sender_name} <{cfg.sender_email}>" if cfg.sender_email else "Vireoka <outbox@localhost>"
    e["To"] = partner["contact_email"]
    from .postmark import reply_to_for
    rt = reply_to_for(cfg, msg.get("id")) if cfg.postmark_inbound_address and cfg.mode == "postmark" else cfg.reply_to
    if rt:
        e["Reply-To"] = rt
    e["Subject"] = render(msg["subject"], partner, cfg)
    domain = (cfg.sender_email.split("@")[-1] if "@" in cfg.sender_email else "vanguard.local")
    e["Message-ID"] = make_msgid(domain=domain)
    unsub = e["Reply-To"] or cfg.sender_email
    if unsub:
        e["List-Unsubscribe"] = f"<mailto:{unsub}?subject=unsubscribe>"
    if msg.get("prev_message_id"):                              # thread follow-ups under the first email
        e["In-Reply-To"] = msg["prev_message_id"]
        e["References"] = msg["prev_message_id"]
    e.set_content(render(msg["body"], partner, cfg) + footer(cfg))
    return e


# ---------------------------------------------------------------- mailers
class OutboxMailer:
    """Writes .eml files instead of sending. The default: nothing leaves the machine."""
    transport_name = "outbox"

    def __init__(self, cfg: EmailConfig):
        self.dir = cfg.outbox_dir

    def send(self, e: EmailMessage, meta: dict | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "_", e["Message-ID"].strip("<>"))[:80]
        (self.dir / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{name}.eml").write_bytes(bytes(e))


class SmtpMailer:
    transport_name = "smtp"

    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        self.conn: smtplib.SMTP | None = None

    def _open(self):
        c = self.cfg
        if c.smtp_port == 465:
            self.conn = smtplib.SMTP_SSL(c.smtp_host, c.smtp_port, timeout=30)
        else:
            self.conn = smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=30)
            if c.smtp_starttls:
                self.conn.starttls()
        self.conn.login(c.smtp_user, c.smtp_password)

    def send(self, e: EmailMessage, meta: dict | None = None) -> None:
        if self.conn is None:
            self._open()
        self.conn.send_message(e)
        # SMTP doesn't keep a copy (Hostinger and most hosts don't); put one in Sent so it shows in webmail.
        self.last_copy = None
        try:
            self.last_copy = save_to_sent(self.cfg, e)
        except Exception as ex:      # the email itself went out; a missing copy must not fail the send
            self.last_copy = f"not saved to Sent: {type(ex).__name__}: {ex}"[:300]
            log.warning("sent %s but could not save a copy to Sent: %s", e["Message-ID"], ex)

    def close(self):
        if self.conn:
            try:
                self.conn.quit()
            except smtplib.SMTPException:
                pass


_LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>"(?:[^"\\]|\\.)*"|\S+)')


def find_sent_folder(lines: list) -> str:
    """Pick the Sent folder from an IMAP LIST reply: the one flagged \\Sent (RFC 6154), else one whose last
    part is Sent / Sent Items / Sent Messages, else 'Sent'."""
    named = None
    for raw in lines or []:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
        m = _LIST_RE.search(line)
        if not m:
            continue
        name = m.group("name").strip('"')
        if "\\sent" in m.group("flags").lower():
            return name
        if named is None and re.split(r"[./]", name)[-1].lower() in ("sent", "sent items", "sent messages", "sent mail"):
            named = name
    return named or "Sent"


def save_to_sent(cfg: EmailConfig, e: EmailMessage) -> str | None:
    """Append a copy of a sent email to the mailbox's Sent folder (marked read). Returns the folder, or None
    when there is no IMAP login for this mailbox or VANGUARD_SAVE_SENT=0."""
    if not (cfg.save_sent and cfg.imap_host and cfg.imap_user and cfg.imap_password):
        return None
    box = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
    try:
        box.login(cfg.imap_user, cfg.imap_password)
        folder = cfg.sent_folder or find_sent_folder(box.list()[1])
        typ, data = box.append(f'"{folder}"', "(\\Seen)", imaplib.Time2Internaldate(time.time()), bytes(e))
        if typ != "OK":
            raise imaplib.IMAP4.error(f"APPEND to {folder}: {data}")
        return folder
    finally:
        try:
            box.logout()
        except Exception:
            pass


def mailer_for(cfg: EmailConfig):
    if cfg.mode == "postmark":
        from .postmark import PostmarkMailer
        return PostmarkMailer(cfg)
    return SmtpMailer(cfg) if cfg.mode == "smtp" else OutboxMailer(cfg)


WARM_CONSENT = ("replied", "opted_in", "existing_relationship")


def postmark_used_this_month(ws) -> int:
    a = ws.one("SELECT COUNT(*) AS n FROM outreach_messages WHERE transport='postmark' "
               "AND substr(sent_at,1,7)=?", (_utc_month(),))["n"]
    b = ws.one("SELECT COUNT(*) AS n FROM notification_log WHERE transport='postmark' "
               "AND substr(at,1,7)=?", (_utc_month(),))["n"]
    return a + b


# ---------------------------------------------------------------- approval
ONE_OFF_BASE = 100   # one-off emails are numbered 101, 102, ... so they never collide with sequence steps 1-5


def parse_send_at(value: str | None) -> str | None:
    """An ISO date-time with a UTC offset (what the browser sends) -> UTC ISO string; '' or None -> None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{value!r} is not a date and time (expected ISO 8601, e.g. 2026-10-09T09:00:00-04:00)")
    if dt.tzinfo is None:
        raise ValueError("send_at needs a time zone (e.g. -04:00 or Z)")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def schedule(ws, ids: Iterable[int], send_at: str | None, per_day: int | None = None, gap_min: int = 0,
             weekdays_only: bool = False, tz_offset_min: int = 0, is_admin: bool = False) -> dict:
    """Set (or clear, with send_at None) when messages may go out. With per_day, the messages are spread over
    days at the same time of day, per_day each, gap_min minutes apart within a day, skipping Saturdays and
    Sundays (in the user's time zone, tz_offset_min east of UTC) when weekdays_only. A scheduled time is a
    "not before": approval is still required, and a sequence step still waits for its delay after the previous
    step. Approved messages can only be rescheduled by an admin."""
    start = parse_send_at(send_at)
    ok, refused = [], []
    rows = []
    for mid in ids:
        m = ws.one("SELECT m.id, m.status, p.is_segment FROM outreach_messages m JOIN partners p ON p.id=m.partner_id "
                   "WHERE m.id=?", (mid,))
        if not m:
            refused.append({"id": mid, "reason": "not found"})
        elif m["is_segment"]:
            refused.append({"id": mid, "reason": "segment template - schedule the named organisations' copies"})
        elif m["status"] not in ("draft", "approved"):
            refused.append({"id": mid, "reason": f"status is {m['status']}"})
        elif m["status"] == "approved" and not is_admin:
            refused.append({"id": mid, "reason": "already approved - only an admin can reschedule it"})
        else:
            rows.append(m["id"])
    if start is None:
        for mid in rows:
            ws.update("outreach_messages", "id", mid, {"send_at": None, "updated_at": now()})
            ok.append({"id": mid, "send_at": None})
        return {"scheduled": ok, "refused": refused}
    local = timedelta(minutes=tz_offset_min)
    t0 = datetime.fromisoformat(start)
    day, slot = t0, 0
    if weekdays_only:
        while (day + local).weekday() >= 5:
            day += timedelta(days=1)
    for mid in rows:
        if per_day and slot >= per_day:
            slot, day = 0, day + timedelta(days=1)
            while weekdays_only and (day + local).weekday() >= 5:
                day += timedelta(days=1)
        at = day + timedelta(minutes=gap_min * slot)
        ws.update("outreach_messages", "id", mid, {"send_at": at.isoformat(timespec="seconds"), "updated_at": now()})
        ok.append({"id": mid, "send_at": at.isoformat(timespec="seconds")})
        slot += 1
    return {"scheduled": ok, "refused": refused}


def compose(ws, partner_id: int, subject: str, body: str, user_id: int | None = None,
            contact_email: str | None = None, send_at: str | None = None) -> dict:
    """Write a single email to one partner (an investor, a reply, a follow-up). It is a draft like any other:
    it goes through the claim rules, needs an admin's approval, and only leaves through send_due."""
    p = ws.one("SELECT id, property_id, is_segment, contact_email FROM partners WHERE id=?", (partner_id,))
    if not p:
        raise KeyError(partner_id)
    if p["is_segment"]:
        raise ValueError("this is a segment - add a named organisation under it and write to them")
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject or not body:
        raise ValueError("subject and body are both required")
    ts = now()
    if contact_email:
        addr = contact_email.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr):
            raise ValueError(f"{contact_email!r} is not an email address")
        if addr != (p["contact_email"] or ""):
            ws.update("partners", "id", partner_id, {"contact_email": addr, "updated_at": ts})
    from .intros import _lint
    last = ws.one("SELECT MAX(step) AS n FROM outreach_messages WHERE partner_id=?", (partner_id,))["n"] or 0
    when = parse_send_at(send_at)
    mid = ws.insert("outreach_messages", {"partner_id": partner_id, "step": max(last, ONE_OFF_BASE) + 1, "delay_days": 0,
                                          "subject": subject, "body": body, "status": "draft", "one_off": 1, "send_at": when,
                                          "created_by": user_id, "created_at": ts, "updated_at": ts}
                    | _lint(ws, p["property_id"], subject, body))
    ws.audit(user_id, "compose", "outreach", mid, {"partner_id": partner_id})
    return ws.one("SELECT * FROM outreach_messages WHERE id=?", (mid,))


def approve(ws, ids: Iterable[int], approver: str) -> dict:
    ok, refused = [], []
    for mid in ids:
        m = ws.one("SELECT m.id, m.status, m.lint_status, p.is_segment FROM outreach_messages m "
                   "JOIN partners p ON p.id=m.partner_id WHERE m.id=?", (mid,))
        if not m:
            refused.append({"id": mid, "reason": "not found"})
        elif m["is_segment"]:
            refused.append({"id": mid, "reason": "segment template - add a named organisation under it and approve theirs"})
        elif m["lint_status"] == "blocked":
            refused.append({"id": mid, "reason": "blocked by the lint gate - edit the copy first"})
        elif m["status"] not in ("draft",):
            refused.append({"id": mid, "reason": f"status is {m['status']}"})
        else:
            ws.update("outreach_messages", "id", mid, {"status": "approved", "approved_by": approver,
                                                         "approved_at": now(), "updated_at": now()})
            ok.append(mid)
    return {"approved": ok, "refused": refused}


# ---------------------------------------------------------------- sending
def _sent_today(ws, cfg: "EmailConfig | None" = None) -> int:
    """Emails (outreach and intro asks) sent today; with cfg, only from that mailbox (rows from before v0.13.0,
    with no from_email, count for the default mailbox)."""
    day = _utc_day()
    if cfg is None:
        return ws.one("SELECT COUNT(*) AS n FROM outreach_messages WHERE substr(sent_at,1,10)=?", (day,))["n"]
    cond, args = ("from_email=?", [cfg.sender_email.lower()]) if cfg.mailbox != "default" else \
        ("(from_email IS NULL OR from_email=?)", [cfg.sender_email.lower()])
    return sum(ws.one(f"SELECT COUNT(*) AS n FROM {t} WHERE substr(sent_at,1,10)=? AND {cond}", [day] + args)["n"]
               for t in ("outreach_messages", "intro_requests"))


class MailRouter:
    """Picks the mailbox for each property and keeps one connection and one daily allowance per mailbox."""

    def __init__(self, ws, cfg: "EmailConfig", mailer=None, cold_mailer=None, limit: int | None = None):
        self.ws, self.cfg, self.fixed, self.fixed_cold, self.limit = ws, cfg, mailer, cold_mailer, limit
        self.mailers: dict = {}
        self.colds: dict = {}
        self.rooms: dict = {}
        self.total = 0

    def config(self, property_id: str | None) -> "EmailConfig":
        return self.cfg.for_property(property_id)

    def mailer(self, c: "EmailConfig"):
        if self.fixed is not None:
            return self.fixed
        if c.mailbox not in self.mailers:
            self.mailers[c.mailbox] = mailer_for(c)
        return self.mailers[c.mailbox]

    def cold(self, c: "EmailConfig"):
        if self.fixed_cold is not None:
            return self.fixed_cold
        if c.mailbox not in self.colds:
            self.colds[c.mailbox] = SmtpMailer(c) if c.smtp_ready else None
        return self.colds[c.mailbox]

    def room(self, c: "EmailConfig") -> bool:
        if self.limit is not None and self.total >= self.limit:
            return False
        if c.mailbox not in self.rooms:
            self.rooms[c.mailbox] = max(0, c.daily_cap - _sent_today(self.ws, c))
        return self.rooms[c.mailbox] > 0

    def used(self, c: "EmailConfig"):
        self.rooms[c.mailbox] = self.rooms.get(c.mailbox, 1) - 1
        self.total += 1

    def close(self):
        for m in list(self.mailers.values()) + [x for x in self.colds.values() if x]:
            if hasattr(m, "close"):
                m.close()


def _suppressed(ws, addr: str) -> bool:
    return bool(ws.one("SELECT 1 FROM email_suppression WHERE email=?", (addr.lower(),)))


def send_due(ws, cfg: EmailConfig | None = None, mailer=None, at: datetime | None = None,
             limit: int | None = None, actor: int | None = None, cold_mailer=None,
             only: Iterable[int] | None = None) -> dict:
    """Send every approved message that is due, in priority order, within the daily cap.

    postmark mode: warm partners (replied / opted in / existing relationship) go through the Postmark outreach
    stream; cold first-touch goes through your own SMTP mailbox if configured, otherwise it is held - Postmark
    only permits permission-based email (unless VANGUARD_POSTMARK_ALLOW_COLD=1).

    only: send just these approved message ids (the "Approve & send" button on a one-off email)."""
    cfg = cfg or EmailConfig.from_env()
    if cfg.problems():
        return {"sent": [], "skipped": [], "error": "; ".join(cfg.problems())}
    at = at or datetime.now(timezone.utc)
    router = MailRouter(ws, cfg, mailer, cold_mailer, limit)
    pm_room = cfg.postmark_monthly_cap - postmark_used_this_month(ws) if cfg.mode == "postmark" else None
    rows = ws.q("SELECT m.*, p.name AS p_name, p.contact_email, p.contact_name, p.stage, p.property_id, "
                "p.priority_score, p.is_segment, p.email_consent FROM outreach_messages m JOIN partners p ON p.id=m.partner_id "
                "WHERE m.status='approved' ORDER BY COALESCE(p.priority_score,0) DESC, m.partner_id, m.step")
    if only is not None:
        keep = {int(i) for i in only}
        rows = [r for r in rows if r["id"] in keep]
    sent, skipped = [], []
    for m in rows:
        partner = {"name": m["p_name"], "contact_email": m["contact_email"], "contact_name": m["contact_name"]}
        why = None
        if m["stage"] in ("declined", "signed"):
            ws.update("outreach_messages", "id", m["id"], {"status": "cancelled", "error": f"partner {m['stage']}"})
            why = f"partner is {m['stage']} - cancelled"
        elif m["is_segment"]:
            why = "this is a segment - add named organisations under it, then approve their messages"
        elif not m["contact_email"]:
            why = "no contact email on the partner yet"
        elif _suppressed(ws, m["contact_email"]):
            ws.update("outreach_messages", "id", m["id"], {"status": "cancelled", "error": "address suppressed"})
            why = "address opted out / bounced - cancelled"
        elif m["send_at"] and datetime.fromisoformat(m["send_at"]) > at:
            why = f"scheduled for {m['send_at']}"
        elif m["one_off"]:
            pass        # written by hand for this partner: no sequence order, and a reply doesn't stop it
        elif ws.one("SELECT 1 FROM outreach_messages WHERE partner_id=? AND status='replied'", (m["partner_id"],)):
            ws.update("outreach_messages", "id", m["id"], {"status": "cancelled", "error": "partner replied"})
            why = "partner already replied - sequence stopped"
        elif m["step"] > 1:
            prev = ws.one("SELECT sent_at, message_id FROM outreach_messages WHERE partner_id=? AND step=?",
                          (m["partner_id"], m["step"] - 1))
            if not prev or not prev["sent_at"]:
                why = f"waiting for step {m['step'] - 1} to be sent"
            elif datetime.fromisoformat(prev["sent_at"]) + timedelta(days=m["delay_days"]) > at:
                why = f"due {(datetime.fromisoformat(prev['sent_at']) + timedelta(days=m['delay_days'])).date()}"
            else:
                m = dict(m) | {"prev_message_id": prev["message_id"]}
        mc = router.config(m["property_id"])
        if why is None and not router.room(mc):
            why = (f"daily cap of {mc.daily_cap} reached" + (f" for {mc.sender_email}" if mc.mailbox != "default" else "")
                   if limit is None or router.total < limit else f"limit of {limit} reached")
        use = base = router.mailer(mc)
        if why is None and cfg.mode == "postmark":
            warm = (m["email_consent"] or "none") in WARM_CONSENT
            if not warm and not cfg.postmark_allow_cold:
                if router.cold(mc) is not None:
                    use = router.cold(mc)            # hybrid: first touch from your own mailbox
                else:
                    why = ("held: Postmark only allows permission-based email - send this first touch from your own "
                           "mailbox (set SMTP_*), or mark the partner 'opted in' once they've agreed to hear from you")
            if why is None and use is base and pm_room is not None and pm_room <= 0:
                why = f"Postmark monthly cap of {cfg.postmark_monthly_cap} reached (VANGUARD_POSTMARK_MONTHLY_CAP)"
        if why:
            skipped.append({"id": m["id"], "partner": m["p_name"], "step": m["step"], "reason": why})
            continue
        e = build_email(dict(m), partner, mc)
        meta = {"outreach_id": m["id"], "partner_id": m["partner_id"], "property_id": m["property_id"], "step": m["step"]}
        try:
            provider_id = use.send(e, meta)
        except Exception as ex:  # keep going with the rest of the queue
            ws.update("outreach_messages", "id", m["id"], {"status": "failed", "error": f"{type(ex).__name__}: {ex}"[:500]})
            skipped.append({"id": m["id"], "partner": m["p_name"], "step": m["step"], "reason": f"send failed: {ex}"})
            continue
        router.used(mc)
        ts = at.isoformat(timespec="seconds")
        transport = getattr(use, "transport_name", cfg.mode)
        if transport == "postmark" and pm_room is not None:
            pm_room -= 1
        ws.update("outreach_messages", "id", m["id"], {"status": "sent", "sent_at": ts, "message_id": e["Message-ID"],
                                                         "to_email": partner["contact_email"], "updated_at": ts,
                                                         "transport": transport, "pm_message_id": provider_id,
                                                         "from_email": mc.sender_email.lower() or None})
        ws.insert("partner_interactions", {"partner_id": m["partner_id"], "date": at.date().isoformat(), "type": "email",
                                           "summary": (f"Sent email from {mc.sender_email}: " if m["one_off"] else f"Sent step {m['step']}: ")
                                                      + str(e["Subject"]), "outcome": "none",
                                           "created_by": actor, "created_at": ts})
        if m["stage"] == "identified":
            ws.update("partners", "id", m["partner_id"], {"stage": "contacted", "updated_at": ts})
        ws.audit(actor, "send", "outreach", m["id"], {"to": partner["contact_email"], "transport": transport})
        sent.append({"id": m["id"], "partner": m["p_name"], "step": m["step"], "to": partner["contact_email"],
                     "transport": transport, "from": mc.sender_email, "copy": getattr(use, "last_copy", None)})
    router.close()
    for mm in (mailer, cold_mailer):
        if mm is not None and hasattr(mm, "close"):
            mm.close()
    return {"sent": sent, "skipped": skipped, "mode": cfg.mode}


# ---------------------------------------------------------------- replies
def classify(text: str) -> str:
    if OPT_OUT.search(text or ""):
        return "optout"
    if NEGATIVE.search(text or ""):
        return "negative"
    if POSITIVE.search(text or ""):
        return "positive"
    return "neutral"


def record_reply(ws, partner_id: int, summary: str, when: date | None = None, outcome: str | None = None,
                 outreach_id: int | None = None, from_addr: str | None = None, actor: int | None = None,
                 kind: str = "email") -> dict:
    """Apply a partner's reply: stop the sequence, log it, move the stage, honour opt-outs."""
    cls = classify(summary)
    outcome = outcome or {"optout": "negative", "negative": "negative", "positive": "positive"}.get(cls, "neutral")
    ts = now()
    p = ws.one("SELECT * FROM partners WHERE id=?", (partner_id,))
    if not p:
        raise KeyError(partner_id)
    if outreach_id is None:
        last = ws.one("SELECT id FROM outreach_messages WHERE partner_id=? AND sent_at IS NOT NULL ORDER BY step DESC LIMIT 1",
                      (partner_id,))
        outreach_id = last["id"] if last else None
    if outreach_id:
        ws.update("outreach_messages", "id", outreach_id, {"status": "replied", "replied_at": ts, "updated_at": ts})
    with ws.conn() as c:
        cancelled = c.execute("UPDATE outreach_messages SET status='cancelled', error='partner replied', updated_at=? "
                              "WHERE partner_id=? AND status IN ('draft','approved') AND COALESCE(one_off,0)=0",
                              (ts, partner_id)).rowcount
    ws.insert("partner_interactions", {"partner_id": partner_id, "date": (when or datetime.now(timezone.utc).date()).isoformat(), "type": kind,
                                       "summary": ("Reply: " + summary.strip())[:4000], "outcome": outcome,
                                       "next_step": "Opted out - do not contact" if cls == "optout" else "Respond to reply",
                                       "created_by": actor, "created_at": ts})
    upd = {"updated_at": ts, "email_consent": "opted_out" if cls == "optout" else "replied"}
    if cls == "optout":
        addr = (from_addr or p["contact_email"] or "").lower()
        if addr:
            ws.q("INSERT INTO email_suppression (email, reason, at) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason, at=excluded.at", (addr, "opt-out", ts))
        upd["next_step"] = "Opted out - do not contact"
    elif p["stage"] in ("identified", "contacted"):
        upd["stage"] = "in_conversation"
        upd["next_step"] = "Respond to reply"
    ws.update("partners", "id", partner_id, upd)
    ws.audit(actor, "reply", "partner", partner_id, {"classification": cls, "cancelled_steps": cancelled})
    return {"classification": cls, "outcome": outcome, "cancelled_steps": cancelled, "stage": upd.get("stage", p["stage"])}


# Where the quoted original starts in a reply. Everything from here on is our own email, including the footer's
# 'Reply "unsubscribe"' line, so it must never be read as the person's words.
_QUOTE_START = re.compile(
    r"^\s*(>|On .+wrote:\s*$|On .+(\d{4}|[AP]M).*$|-{2,}\s*Original Message\s*-{2,}|_{8,}|From:\s.+|Sent from my )", re.I)
_HTML_QUOTE = re.compile(r'<blockquote|<div[^>]+(class="gmail_quote|id="divRplyFwdMsg|id="appendonsend|class="yahoo_quoted)', re.I)
_OUR_FOOTER = re.compile(r"(You're receiving this one-to-one note[^\n]*|Reply \"unsubscribe\" and we won't email you again\.?)", re.I)


def _body_text(msg: email.message.Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else msg
    text = part.get_content() if part is not None else ""
    if part is not None and part.get_content_type() == "text/html":
        q = _HTML_QUOTE.search(text)
        text = text[:q.start()] if q else text
        text = re.sub(r"(?i)<br\s*/?>|</(p|div)>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
    keep = []
    for line in text.splitlines():  # drop the quoted original
        if _QUOTE_START.match(line):
            break
        keep.append(line)
    text = _OUR_FOOTER.sub(" ", "\n".join(keep))
    return re.sub(r"\s+", " ", text).strip()[:1500]


def _reply_text(msg: email.message.Message) -> str:
    """What the person wrote, plus the subject when it isn't just 'Re: <our subject>'. An unsubscribe sent by
    a mail client's Unsubscribe button (our List-Unsubscribe mailto) is a new email whose subject says
    'unsubscribe' and whose body may be empty or boilerplate."""
    body = _body_text(msg)
    subj = (msg.get("Subject") or "").strip()
    if subj and not re.match(r"^(re|aw|sv|antw)\s*:", subj, re.I) and OPT_OUT.search(subj):
        return f"{subj} {body}".strip()
    return body


def process_inbound(ws, messages: Iterable[email.message.Message], actor: int | None = None) -> dict:
    """Match inbound emails to outreach (threading headers first, then sender address) and apply them."""
    stats = {"matched": 0, "bounces": 0, "unmatched": 0, "duplicates": 0}
    for msg in messages:
        mid = (msg.get("Message-ID") or "").strip() or f"<noid-{hash(msg.as_string())}>"
        if ws.one("SELECT 1 FROM inbound_emails WHERE message_id=?", (mid,)):
            stats["duplicates"] += 1
            continue
        from_addr = parseaddr(msg.get("From", ""))[1].lower()
        refs = " ".join(filter(None, [msg.get("In-Reply-To"), msg.get("References")]))
        ref_ids = re.findall(r"<[^>]+>", refs)
        row = None
        for r in ref_ids:
            row = ws.one("SELECT id, partner_id, to_email FROM outreach_messages WHERE message_id=?", (r,))
            if row:
                break
        if BOUNCE_FROM.search(from_addr):
            if row is None:  # bounces quote the original; look for our Message-ID in the body
                raw = msg.as_string()
                for r in re.findall(r"<[^>\s]+@[^>\s]+>", raw):
                    row = ws.one("SELECT id, partner_id, to_email FROM outreach_messages WHERE message_id=?", (r,))
                    if row:
                        break
            if row:
                ws.update("outreach_messages", "id", row["id"], {"status": "bounced", "error": "bounced"})
                if row["to_email"]:
                    ws.q("INSERT INTO email_suppression (email, reason, at) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason, at=excluded.at",
                         (row["to_email"].lower(), "bounce", now()))
                ws.insert("inbound_emails", {"message_id": mid, "partner_id": row["partner_id"], "outreach_id": row["id"],
                                             "from_addr": from_addr, "subject": msg.get("Subject", ""),
                                             "received_at": now(), "classification": "bounce"})
                stats["bounces"] += 1
            else:
                stats["unmatched"] += 1
            continue
        if row is None and from_addr:
            p = ws.one("SELECT id FROM partners WHERE lower(contact_email)=? ORDER BY updated_at DESC LIMIT 1", (from_addr,))
            if p:
                row = {"id": None, "partner_id": p["id"]}
        if row is None:
            stats["unmatched"] += 1
            continue
        text = _reply_text(msg)
        res = record_reply(ws, row["partner_id"], text or msg.get("Subject", "(no text)"), outreach_id=row["id"],
                           from_addr=from_addr, actor=actor)
        ws.insert("inbound_emails", {"message_id": mid, "partner_id": row["partner_id"], "outreach_id": row["id"],
                                     "from_addr": from_addr, "subject": msg.get("Subject", ""), "received_at": now(),
                                     "classification": res["classification"]})
        stats["matched"] += 1
    return stats


def fetch_imap(cfg: EmailConfig, since_days: int = 14) -> list[email.message.Message]:
    box = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
    try:
        box.login(cfg.imap_user, cfg.imap_password)
        box.select(cfg.imap_folder, readonly=True)          # never marks mail read or deletes anything
        since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        _, data = box.search(None, f'(SINCE "{since}")')
        out = []
        for num in (data[0] or b"").split():
            _, parts = box.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                out.append(email.message_from_bytes(raw, policy=email.policy.default))
        return out
    finally:
        try:
            box.logout()
        except Exception:
            pass


def sync_replies(ws, cfg: EmailConfig | None = None, fetch: Callable[[EmailConfig], list] | None = None,
                 actor: int | None = None) -> dict:
    """Read every configured inbox (the default one and each VANGUARD_MAILBOX_*) and match replies."""
    cfg = cfg or EmailConfig.from_env()
    boxes = [c for c in cfg.all_mailboxes() if c.imap_host and c.imap_user]
    if not boxes and fetch is None:
        return {"error": "IMAP not configured (IMAP_HOST, IMAP_USER, IMAP_PASSWORD) - record replies by hand instead"}
    total: dict = {}
    for c in boxes or [cfg]:
        res = process_inbound(ws, (fetch or fetch_imap)(c), actor=actor)
        for k, v in res.items():
            total[k] = total.get(k, 0) + v if isinstance(v, (int, float)) else v
    if len(boxes) > 1:
        total["mailboxes"] = len(boxes)
    return total


def queue_stats(ws) -> dict:
    s = ws.one("SELECT SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) AS draft, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved, SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent, "
               "SUM(CASE WHEN status='replied' THEN 1 ELSE 0 END) AS replied, SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
               "SUM(CASE WHEN status='bounced' THEN 1 ELSE 0 END) AS bounced, SUM(CASE WHEN sent_at IS NOT NULL THEN 1 ELSE 0 END) AS ever_sent, "
               "SUM(CASE WHEN lint_status='blocked' AND status='draft' THEN 1 ELSE 0 END) AS blocked FROM outreach_messages m "
               "JOIN partners p ON p.id=m.partner_id WHERE COALESCE(p.is_segment,0)=0")
    s = {k: (v or 0) for k, v in s.items()}
    contacted = ws.one("SELECT COUNT(DISTINCT partner_id) AS n FROM outreach_messages WHERE sent_at IS NOT NULL")["n"]
    replied = ws.one("SELECT COUNT(DISTINCT partner_id) AS n FROM outreach_messages WHERE status='replied'")["n"]
    s |= {"partners_contacted": contacted, "partners_replied": replied,
          "reply_rate": round(replied / contacted, 3) if contacted else None, "sent_today": _sent_today(ws),
          "suppressed": ws.one("SELECT COUNT(*) AS n FROM email_suppression")["n"]}
    return s


# ---------------------------------------------------------------- team notifications
def _team_recipients(ws, partner_id: int | None = None) -> list[str]:
    emails = [r["email"] for r in ws.q("SELECT email FROM users WHERE role='admin' AND active=1")]
    if partner_id:
        owner = ws.one("SELECT u.email FROM partners p JOIN users u ON u.id=p.owner_id WHERE p.id=? AND u.active=1", (partner_id,))
        if owner and owner["email"] not in emails:
            emails.append(owner["email"])
    return emails


def notify_team(ws, subject: str, body: str, to: list[str], kind: str, cfg: EmailConfig | None = None,
                client=None) -> dict:
    """Internal notification (reply alerts, approval digests) via the Postmark notify stream, or SMTP, or outbox."""
    cfg = cfg or EmailConfig.from_env()
    to = [t for t in to if t]
    if not to:
        return {"sent": 0, "reason": "no recipients"}
    e = EmailMessage()
    e["From"] = f"Vanguard-GTM <{cfg.sender_email}>" if cfg.sender_email else "Vanguard-GTM <outbox@localhost>"
    e["To"] = ", ".join(to)
    e["Subject"] = subject
    e["Message-ID"] = make_msgid(domain=cfg.sender_email.split("@")[-1] if "@" in cfg.sender_email else "vanguard.local")
    e.set_content(body)
    if cfg.postmark_token:
        if postmark_used_this_month(ws) >= cfg.postmark_monthly_cap:
            return {"sent": 0, "reason": "Postmark monthly cap reached"}
        from .postmark import PostmarkClient, payload_from
        c = client or PostmarkClient(cfg.postmark_token)
        c.send(payload_from(e, cfg.postmark_stream_notify, "vanguard-notify", {"kind": kind}, False))
        transport = "postmark"
    elif cfg.smtp_ready:
        SmtpMailer(cfg).send(e)
        transport = "smtp"
    else:
        OutboxMailer(cfg).send(e)
        transport = "outbox"
    ws.insert("notification_log", {"at": now(), "transport": transport, "to_addr": e["To"], "subject": subject, "kind": kind})
    return {"sent": len(to), "transport": transport}


def notify_reply(ws, partner_id: int, text: str, classification: str, cfg: EmailConfig | None = None, client=None) -> dict:
    cfg = cfg or EmailConfig.from_env()
    if not cfg.notify_replies:
        return {"sent": 0, "reason": "disabled"}
    p = ws.one("SELECT name, property_id FROM partners WHERE id=?", (partner_id,))
    label = {"optout": "opted out", "negative": "declined", "positive": "replied - looks positive"}.get(classification, "replied")
    body = (f"{p['name']} ({p['property_id']}) {label}.\n\n\"{text.strip()[:800]}\"\n\n"
            f"Remaining emails in the sequence were stopped. Open the partner in Vanguard to respond.")
    try:
        return notify_team(ws, f"[Vanguard] {p['name']} {label}", body, _team_recipients(ws, partner_id), "reply", cfg, client)
    except Exception as ex:   # a notification must never break reply processing
        log.warning("reply notification failed: %s", ex)
        return {"sent": 0, "reason": str(ex)}


def send_digest(ws, cfg: EmailConfig | None = None, client=None) -> dict:
    st = queue_stats(ws)
    top = ws.q("SELECT p.name, p.priority, m.step FROM outreach_messages m JOIN partners p ON p.id=m.partner_id "
               "WHERE m.status='draft' AND COALESCE(p.is_segment,0)=0 AND m.lint_status!='blocked' "
               "ORDER BY COALESCE(p.priority_score,0) DESC LIMIT 10")
    lines = [f"- {r['priority'] or '--'} {r['name']} (step {r['step']})" for r in top]
    body = (f"{st['draft']} partner emails are waiting for approval, {st['approved']} are queued, "
            f"{st['partners_replied']} partners have replied so far.\n\nTop of the queue:\n" + ("\n".join(lines) or "- none") +
            "\n\nOpen Vanguard -> Outreach to review and approve.")
    return notify_team(ws, f"[Vanguard] {st['draft']} partner emails awaiting approval", body,
                       [r["email"] for r in ws.q("SELECT email FROM users WHERE role='admin' AND active=1")], "digest", cfg, client)


def dumps(o) -> str:
    return json.dumps(o, default=str)


def _utc_day() -> str:
    from datetime import datetime as _dt, timezone as _tz
    return _dt.now(_tz.utc).date().isoformat()


def _utc_month() -> str:
    return _utc_day()[:7]
