import { useEffect, useState } from "react";
import { AlertTriangle, Send, ShieldCheck } from "lucide-react";
import { api, type EmailStatus, type OutreachMessage, type Partner } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button, ErrorNote, Field, Input, Modal, Textarea, useToast } from "./ui";

type Finding = { rule_id: string; message: string; excerpt: string; severity: string };

/** Write one email to one partner (an investor, a reply, a follow-up). It is saved as a draft, checked against the
 *  claim rules, and leaves only after an admin approves it - through the same send path as every outreach email. */
export function ComposeEmail({ p, open, onClose, onChanged }: { p: Partner; open: boolean; onClose: () => void; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [saved, setSaved] = useState<OutreachMessage | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [email, setEmail] = useState<EmailStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    setTo(p.contact_email ?? ""); setSubject(""); setBody(`Hi {{first_name}},\n\n`); setSaved(null); setFindings([]); setError(null);
    api.outreachStats().then((s) => setEmail(s.email)).catch(() => setEmail(null));
  }, [open, p.contact_email]);

  const close = () => { onClose(); if (saved) onChanged(); };
  const blocked = findings.some((f) => f.severity === "block");

  /** Save (first time: create the draft; after that: edit it). Returns the message id and whether it is blocked. */
  const save = async (): Promise<{ id: number; blocked: boolean }> => {
    const addr = to.trim();
    if (saved) {
      if (addr && addr.toLowerCase() !== (p.contact_email ?? "")) await api.updatePartner(p.id, { contact_email: addr });
      const r = await api.editOutreach(saved.id, { subject, body });
      setFindings(r.lint_findings);
      return { id: saved.id, blocked: r.lint_status === "blocked" };
    }
    const m = await api.composeEmail(p.id, { subject, body, contact_email: addr || undefined });
    setSaved(m);
    const fs: Finding[] = m.lint_findings ? JSON.parse(m.lint_findings) : [];
    setFindings(fs);
    return { id: m.id, blocked: m.lint_status === "blocked" };
  };

  const saveDraft = async () => {
    setBusy("save"); setError(null);
    try {
      const r = await save();
      if (r.blocked) { toast("Saved, but the claim rules block it - fix the flagged lines", "err"); return; }
      toast(isAdmin ? "Draft saved - approve it here or in Outreach" : "Draft saved - an admin approves it in Outreach");
      onChanged(); onClose();
    } catch (e) { setError(e); } finally { setBusy(""); }
  };

  const approveAndSend = async () => {
    setBusy("send"); setError(null);
    try {
      const r = await save();
      if (r.blocked) { toast("Not sent: the claim rules block it - fix the flagged lines", "err"); return; }
      const a = await api.approveOutreach([r.id]);
      if (a.refused.length) throw new Error(a.refused[0].reason);
      const s = await api.sendDue([r.id]);
      const x = s.sent[0];
      if (x) toast(s.mode === "outbox" ? `Saved to the outbox (email isn't connected) - not sent to ${x.to}`
        : `Sent to ${x.to}${x.from ? ` from ${x.from}` : ""}${x.copy?.startsWith("not saved") ? ` - ${x.copy}` : x.copy ? ` · copy in ${x.copy}` : ""}`,
        s.mode === "outbox" || x.copy?.startsWith("not saved") ? "err" : "ok");
      else toast(`Approved, not sent: ${s.skipped[0]?.reason ?? "check Outreach"}`, "err");
      onChanged(); onClose();
    } catch (e) { setError(e); } finally { setBusy(""); }
  };

  const ready = subject.trim().length >= 3 && body.trim().length >= 20 && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to.trim());
  return (
    <Modal open={open} onClose={close} wide title={`Write to ${p.contact_name || p.name}`}
      footer={<>
        <Button variant="ghost" onClick={close}>Cancel</Button>
        <div className="flex-1" />
        <Button onClick={saveDraft} loading={busy === "save"} disabled={!ready}>Save draft</Button>
        {isAdmin && <Button variant="primary" icon={email?.live ? <Send size={14} /> : <ShieldCheck size={14} />} loading={busy === "send"}
          disabled={!ready} onClick={approveAndSend}>{email?.live ? "Approve & send" : "Approve & save to outbox"}</Button>}
      </>}>
      <ErrorNote error={error} />
      {email && !email.live && (
        <div className="mb-4 rounded-lg border border-amber/30 bg-amber-soft p-3 text-xs">
          <b>Email isn't connected yet</b> (mode: {email.mode}{email.problems.length ? ` - ${email.problems.join("; ")}` : ""}).
          Approved emails are saved to the server's outbox and nothing leaves. Set the SMTP lines in the server's .env to send for real
          (see docs/SETUP_NOTION_AND_KEYS.md, Part 7).
        </div>)}
      {email?.live && <p className="mb-4 text-xs text-muted">Sends from <b className="text-ink">{email.senders?.[p.property_id] ?? email.sender}</b> via {email.mode}, with your postal-address footer and an unsubscribe line.
        {email.imap_configured ? " Replies are picked up by Check replies." : " Replies won't be read automatically (no IMAP) - use Record reply."}</p>}
      {findings.length > 0 && (
        <div className="mb-4 space-y-1.5 rounded-lg border border-amber/30 bg-amber-soft p-3 text-xs">
          {findings.map((f, i) => <div key={i} className="flex gap-2"><AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber" />
            <span><b>{f.rule_id}</b> ({f.severity}) - {f.message} <span className="text-muted">"{f.excerpt}"</span></span></div>)}
          {blocked && <p className="pt-1 font-medium">Blocked lines must be fixed before this can be approved.</p>}
        </div>)}
      <div className="grid gap-3">
        <Field label="To" hint="Only an address the person or their firm published, or shared with you. It is saved as the contact email.">
          <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@firm.com" /></Field>
        <Field label="Subject"><Input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={140} /></Field>
        <Field label="Message" hint="{{first_name}} becomes their first name. The footer is added when it sends.">
          <Textarea rows={14} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
