"""Postmark integration: Email API sending through message streams, webhooks, suppressions, streams check.

Streams used (IDs are configurable; the defaults exist on every Postmark server):
  VANGUARD_POSTMARK_STREAM_OUTREACH  (default "outbound")  one-to-one emails to partners who replied/opted in
  VANGUARD_POSTMARK_STREAM_NOTIFY    (default "outbound")  internal team notifications (reply alerts, digests)
  inbound stream                                           replies, via the /hooks/postmark webhook (Pro plan)

Policy: Postmark's terms require permission-based email and prohibit unsolicited messages, so cold first-touch
outreach is NOT routed through Postmark unless you explicitly set VANGUARD_POSTMARK_ALLOW_COLD=1.
Postmark docs: https://postmarkapp.com/developer/api/email-api
"""
from __future__ import annotations

import base64
import hmac
import logging
import re
from email.message import EmailMessage

import httpx

from .store import now

log = logging.getLogger("vanguard.postmark")
API = "https://api.postmarkapp.com"
TRANSPORT: httpx.BaseTransport | None = None   # test hook: tests set an httpx.MockTransport here


class PostmarkError(RuntimeError):
    pass


class PostmarkClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=API, timeout=30, transport=transport or TRANSPORT, headers={
            "Accept": "application/json", "Content-Type": "application/json", "X-Postmark-Server-Token": token})

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        r = self.http.request(method, path, json=body)
        try:
            data = r.json()
        except ValueError:
            data = {}
        # Postmark returns ErrorCode 0 on success; non-zero codes carry a Message
        if r.status_code >= 400 or (isinstance(data, dict) and data.get("ErrorCode", 0) not in (0, None)):
            raise PostmarkError(f"Postmark {method} {path} -> HTTP {r.status_code} "
                                f"code {data.get('ErrorCode') if isinstance(data, dict) else '?'}: "
                                f"{data.get('Message') if isinstance(data, dict) else r.text[:200]}")
        return data

    def send(self, payload: dict) -> str:
        return self._req("POST", "/email", payload)["MessageID"]

    def streams(self) -> list[dict]:
        return self._req("GET", "/message-streams?IncludeArchivedStreams=false").get("MessageStreams", [])

    def suppressions(self, stream: str) -> list[dict]:
        return self._req("GET", f"/message-streams/{stream}/suppressions/dump").get("Suppressions", [])

    def suppress(self, stream: str, emails: list[str]) -> list[dict]:
        if not emails:
            return []
        body = {"Suppressions": [{"EmailAddress": e} for e in emails[:50]]}   # API accepts up to 50 per call
        return self._req("POST", f"/message-streams/{stream}/suppressions", body).get("Suppressions", [])

    def close(self):
        self.http.close()


def reply_to_for(cfg, outreach_id: int | None) -> str:
    """Postmark inbound: reply+o<ID>@inbound-domain arrives as MailboxHash 'o<ID>' - exact reply matching."""
    addr = cfg.postmark_inbound_address
    if not addr or "@" not in addr:
        return cfg.reply_to or ""
    if outreach_id is None:
        return addr
    local, domain = addr.split("@", 1)
    return f"{local}+o{outreach_id}@{domain}"


def payload_from(e: EmailMessage, stream: str, tag: str | None, metadata: dict, track_opens: bool) -> dict:
    headers = [{"Name": k, "Value": e[k]} for k in ("List-Unsubscribe", "In-Reply-To", "References") if e[k]]
    p = {"From": e["From"], "To": e["To"], "Subject": e["Subject"], "TextBody": e.get_content(),
         "MessageStream": stream, "TrackOpens": track_opens, "TrackLinks": "None",
         "Metadata": {k: str(v) for k, v in metadata.items()}, "Headers": headers}
    if e["Reply-To"]:
        p["ReplyTo"] = e["Reply-To"]
    if tag:
        p["Tag"] = tag[:1000]
    return p


class PostmarkMailer:
    """Sends through a Postmark message stream; returns Postmark's MessageID."""
    transport_name = "postmark"

    def __init__(self, cfg, client: PostmarkClient | None = None, stream: str | None = None):
        self.cfg = cfg
        self.client = client or PostmarkClient(cfg.postmark_token)
        self.stream = stream or cfg.postmark_stream_outreach

    def send(self, e: EmailMessage, meta: dict | None = None) -> str:
        meta = meta or {}
        return self.client.send(payload_from(e, self.stream, meta.get("property_id"), meta, self.cfg.postmark_track_opens))

    def close(self):
        pass


# ---------------------------------------------------------------- webhooks
def check_basic_auth(header: str, user: str, password: str) -> bool:
    if not (user and password) or not header.startswith("Basic "):
        return False
    try:
        got = base64.b64decode(header[6:]).decode()
    except ValueError:
        return False
    return hmac.compare_digest(got, f"{user}:{password}")


def _find_outreach(ws, event: dict) -> dict | None:
    meta = event.get("Metadata") or {}
    if str(meta.get("outreach_id", "")).isdigit():
        row = ws.one("SELECT * FROM outreach_messages WHERE id=?", (int(meta["outreach_id"]),))
        if row:
            return row
    if event.get("MessageID"):
        return ws.one("SELECT * FROM outreach_messages WHERE pm_message_id=?", (event["MessageID"],))
    return None


def _suppress(ws, addr: str, reason: str):
    if addr:
        ws.q("INSERT INTO email_suppression (email, reason, at) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason, at=excluded.at", (addr.lower(), reason, now()))


def handle_event(ws, event: dict) -> dict:
    """Apply one Postmark webhook event. Unknown events are acknowledged and ignored (Postmark retries non-2xx)."""
    from .outreach import notify_reply, record_reply
    rt = event.get("RecordType")
    if rt is None and ("FromFull" in event or "MailboxHash" in event):
        rt = "Inbound"
    if rt == "Inbound":
        return handle_inbound(ws, event, record_reply, notify_reply)
    row = _find_outreach(ws, event)
    email_addr = (event.get("Email") or event.get("Recipient") or (row or {}).get("to_email") or "").lower()
    if rt == "Delivery":
        if row:
            ws.update("outreach_messages", "id", row["id"], {"delivered_at": event.get("DeliveredAt") or now()})
        return {"handled": "delivery", "matched": bool(row)}
    if rt == "Open":
        if row and not row.get("opened_at"):
            ws.update("outreach_messages", "id", row["id"], {"opened_at": event.get("ReceivedAt") or now()})
        return {"handled": "open", "matched": bool(row)}
    if rt == "Bounce":
        hard = event.get("Type") in ("HardBounce", "BadEmailAddress", "ManuallyDeactivated", "SpamNotification") \
            or event.get("Inactive") is True
        if row:
            ws.update("outreach_messages", "id", row["id"], {"status": "bounced" if hard else row["status"],
                                                             "error": f"{event.get('Type')}: {event.get('Description', '')}"[:500]})
        if hard:
            _suppress(ws, email_addr, "bounce")
        return {"handled": "bounce", "hard": hard, "matched": bool(row)}
    if rt == "SpamComplaint":
        if row:
            ws.update("outreach_messages", "id", row["id"], {"error": "spam complaint"})
            with ws.conn() as c:
                c.execute("UPDATE outreach_messages SET status='cancelled', error='spam complaint' WHERE partner_id=? "
                          "AND status IN ('draft','approved')", (row["partner_id"],))
            ws.update("partners", "id", row["partner_id"], {"email_consent": "opted_out",
                                                            "next_step": "Marked our email as spam - do not contact"})
        _suppress(ws, email_addr, "spam-complaint")
        return {"handled": "spam_complaint", "matched": bool(row)}
    if rt == "SubscriptionChange":
        if event.get("SuppressSending"):
            _suppress(ws, email_addr, "postmark-suppression")
        else:
            ws.q("DELETE FROM email_suppression WHERE email=? AND reason='postmark-suppression'", (email_addr,))
        return {"handled": "subscription_change"}
    return {"handled": "ignored", "record_type": rt}


def handle_inbound(ws, ev: dict, record_reply, notify_reply) -> dict:
    mid = ev.get("MessageID") or f"pm-{hash(str(ev))}"
    if ws.one("SELECT 1 FROM inbound_emails WHERE message_id=?", (mid,)):
        return {"handled": "inbound", "duplicate": True}
    from_addr = ((ev.get("FromFull") or {}).get("Email") or ev.get("From") or "").lower()
    from_addr = re.sub(r".*<([^>]+)>.*", r"\1", from_addr)
    row = None
    m = re.fullmatch(r"o(\d+)", ev.get("MailboxHash") or "")
    if m:
        row = ws.one("SELECT id, partner_id FROM outreach_messages WHERE id=?", (int(m.group(1)),))
    if row is None:
        hdrs = {h.get("Name", "").lower(): h.get("Value", "") for h in ev.get("Headers") or []}
        for ref in re.findall(r"<[^>]+>", f"{hdrs.get('in-reply-to', '')} {hdrs.get('references', '')}"):
            row = ws.one("SELECT id, partner_id FROM outreach_messages WHERE message_id=?", (ref,))
            if row:
                break
    if row is None and from_addr:
        p = ws.one("SELECT id FROM partners WHERE lower(contact_email)=? ORDER BY updated_at DESC LIMIT 1", (from_addr,))
        row = {"id": None, "partner_id": p["id"]} if p else None
    if row is None:
        ws.insert("inbound_emails", {"message_id": mid, "from_addr": from_addr, "subject": ev.get("Subject", ""),
                                     "received_at": now(), "classification": "unmatched"})
        return {"handled": "inbound", "matched": False}
    text = (ev.get("StrippedTextReply") or ev.get("TextBody") or ev.get("Subject") or "(no text)").strip()
    res = record_reply(ws, row["partner_id"], re.sub(r"\s+", " ", text)[:1500], outreach_id=row["id"], from_addr=from_addr)
    ws.insert("inbound_emails", {"message_id": mid, "partner_id": row["partner_id"], "outreach_id": row["id"],
                                 "from_addr": from_addr, "subject": ev.get("Subject", ""), "received_at": now(),
                                 "classification": res["classification"]})
    notify_reply(ws, row["partner_id"], text, res["classification"])
    return {"handled": "inbound", "matched": True, **res}


# ---------------------------------------------------------------- suppressions & health
def sync_suppressions(ws, cfg, client: PostmarkClient | None = None) -> dict:
    """Two-way: pull Postmark's suppressions for the outreach stream; push local opt-outs/bounces to it."""
    client = client or PostmarkClient(cfg.postmark_token)
    stream = cfg.postmark_stream_outreach
    remote = client.suppressions(stream)
    remote_set = {s["EmailAddress"].lower() for s in remote}
    pulled = 0
    for s in remote:
        addr = s["EmailAddress"].lower()
        if not ws.one("SELECT 1 FROM email_suppression WHERE email=?", (addr,)):
            _suppress(ws, addr, f"postmark:{s.get('SuppressionReason', 'suppressed')}")
            pulled += 1
    local = [r["email"] for r in ws.q("SELECT email FROM email_suppression")]
    to_push = [e for e in local if e not in remote_set]
    pushed = 0
    for i in range(0, len(to_push), 50):
        res = client.suppress(stream, to_push[i:i + 50])
        pushed += sum(1 for r in res if r.get("Status") in ("Suppressed", None))
    return {"stream": stream, "pulled": pulled, "pushed": pushed, "remote_total": len(remote_set)}


def check_streams(cfg, client: PostmarkClient | None = None) -> dict:
    client = client or PostmarkClient(cfg.postmark_token)
    found = {s["ID"]: s.get("MessageStreamType") for s in client.streams()}
    want = {"outreach": cfg.postmark_stream_outreach, "notify": cfg.postmark_stream_notify}
    missing = [f"{k}={v}" for k, v in want.items() if v not in found]
    wrong = [f"{k}={v} is a {found[v]} stream" for k, v in want.items() if v in found and found[v] != "Transactional"]
    return {"streams": found, "missing": missing, "not_transactional": wrong, "ok": not missing and not wrong}
