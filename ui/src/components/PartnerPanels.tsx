import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Gauge, FileSignature, Mail, Plus, Reply, ShieldCheck, Search } from "lucide-react";
import { api, type AgreementStatus, type EmailConsent, type OutreachMessage, type Partner } from "../lib/api";
import { useAuth } from "../lib/auth";
import { label, relTime, shortDate, today } from "../lib/format";
import { Badge, Button, Card, CardHeader, ErrorNote, Field, Input, Modal, Select, Textarea, statusTone, useToast } from "./ui";
import { OUTREACH_TONE, OutreachEditor, preview } from "./OutreachEditor";

function shortUrl(u: string) {
  const t = u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
  const [host, ...rest] = t.split("/");
  const path = rest.join("/");
  return path.length > 18 ? `${host}/…${path.slice(-14)}` : t;
}

/** Plain text with http(s) links made clickable (research notes carry source and contact URLs). */
export function Linkify({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s|)]+)/g);
  return <>{parts.map((s, i) => i % 2 ? <a key={i} href={s} target="_blank" rel="noreferrer noopener" className="break-all text-vireo underline-offset-2 hover:underline">{shortUrl(s)}</a> : s)}</>;
}

const FACTOR_LABEL: Record<string, string> = { fit: "ICP fit", reach: "Reach", access: "Access", strategic: "Strategic value", speed: "Speed to result" };
const INVESTOR_FACTOR_LABEL: Record<string, string> = { thesis: "Thesis fit", stage: "Stage fit", check: "Check size", geo: "Geography", research: "Researched fit" };

export function PriorityCard({ p }: { p: Partner }) {
  if (p.priority_score == null) return null;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Gauge size={14} className="text-vireo" />{p.kind === "investor" ? "Why this investor" : "Why this partner"}</span>}
        sub={p.segment_name ? <>Named target under “{p.segment_name}”</> : p.is_segment ? "A segment to research - add named organisations below" : undefined}
        action={<div className="flex items-center gap-2"><Badge tone={statusTone(p.priority ?? "P2")}>{p.priority}</Badge><span className="num text-xl">{p.priority_score}</span></div>} />
      <div className="grid gap-5 p-5 md:grid-cols-[1fr_1.2fr]">
        <div className="space-y-2">
          {p.factors && Object.entries(p.kind === "investor" ? INVESTOR_FACTOR_LABEL : FACTOR_LABEL).map(([k, l]) => (
            <div key={k} className="grid grid-cols-[110px_1fr_20px] items-center gap-2 text-xs">
              <span className="text-muted">{l}</span>
              <div className="flex gap-[3px]" aria-label={`${l} ${p.factors?.[k]} of 5`}>
                {[1, 2, 3, 4, 5].map((i) => <span key={i} className="h-2 flex-1 rounded-sm" style={{ background: i <= (p.factors?.[k] ?? 0) ? "var(--vireo)" : "var(--surface-3)" }} />)}
              </div>
              <span className="num text-right">{p.factors?.[k]}</span>
            </div>))}
          <p className="pt-1 text-[11px] text-faint">{p.kind === "investor"
            ? "Likelihood to invest in LiqMint = thesis 25% · stage 15% · check 15% · geography 5% · researched fit 40%. P0 ≥ 75, P1 ≥ 55."
            : "Score = weighted fit 30% · reach 25% · strategic 20% · access 15% · speed 10%. P0 ≥ 75, P1 ≥ 55."}</p>
        </div>
        <dl className="space-y-2.5 text-sm">
          {p.rationale && <div><dt className="text-xs text-muted">Why</dt><dd className="whitespace-pre-line"><Linkify text={p.rationale} /></dd></div>}
          {p.deal_structure && <div><dt className="text-xs text-muted">{p.kind === "investor" ? "Check size & stages" : "Typical deal"}</dt><dd>{p.deal_structure}</dd></div>}
          {p.how_to_find && <div><dt className="flex items-center gap-1 text-xs text-muted"><Search size={11} />{p.kind === "investor" ? "Research & how to reach" : "How to find the right contact"}</dt><dd><Linkify text={p.how_to_find} /></dd></div>}
        </dl>
      </div>
    </Card>
  );
}

const AGREEMENTS: AgreementStatus[] = ["none", "proposed", "negotiating", "signed", "declined"];

export function AgreementCard({ p, onSaved }: { p: Partner; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ status: p.agreement_status ?? "none", date: p.agreement_signed_date ?? "", notes: p.agreement_notes ?? "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ status: p.agreement_status ?? "none", date: p.agreement_signed_date ?? "", notes: p.agreement_notes ?? "" }), [p]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updatePartner(p.id, { agreement_status: f.status as AgreementStatus, agreement_signed_date: f.date || null, agreement_notes: f.notes || null });
      toast(f.status === "signed" ? "Agreement signed 🎉" : "Agreement updated"); onSaved();
    } catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(false); }
  };
  const signed = (p.agreement_status ?? "none") === "signed";
  return (
    <Card className={signed ? "border-vireo/50" : ""}>
      <CardHeader title={<span className="flex items-center gap-2"><FileSignature size={14} className="text-vireo" />Partnership agreement</span>}
        sub={signed ? `Signed ${shortDate(p.agreement_signed_date)}` : "Track the deal through to a signed agreement"} />
      <div className="grid gap-3 p-5 sm:grid-cols-2">
        <Field label="Status"><Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as AgreementStatus })}>
          {AGREEMENTS.map((a) => <option key={a} value={a}>{a === "none" ? "No agreement yet" : label(a)}</option>)}</Select></Field>
        <Field label="Signed on"><Input type="date" value={f.date} disabled={f.status !== "signed"} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Key terms / notes" className="sm:col-span-2"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="e.g. 12% referral fee, 12 months, co-hosted mixer each quarter" /></Field>
        <div className="sm:col-span-2"><Button variant={f.status === "signed" ? "primary" : "outline"} loading={busy} onClick={save}>Save agreement</Button></div>
      </div>
    </Card>
  );
}

export function TargetsCard({ p, onAdded }: { p: Partner; onAdded: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ name: "", contact_name: "", contact_email: "", website: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!p.is_segment) return null;
  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api.addTarget(p.id, Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as typeof f);
      toast(`Added ${f.name} - drafts copied, ready for approval`); setF({ name: "", contact_name: "", contact_email: "", website: "" }); onAdded();
    } catch (err) { setError(err); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title="Named targets" sub="Add the specific businesses you'll approach. Each inherits this segment's priority and email drafts." />
      <ul className="divide-y divide-line">
        {(p.targets ?? []).map((t) => (
          <li key={t.id} className="flex items-center gap-2 px-5 py-2.5 text-sm">
            <Link to={`/partners/${t.id}`} className="min-w-0 flex-1 truncate font-medium hover:text-vireo">{t.name}</Link>
            <span className="text-xs text-muted">{t.contact_email ?? "no email yet"}</span>
            <Badge tone={statusTone(t.stage)}>{label(t.stage)}</Badge>
            {t.agreement_status === "signed" && <Badge tone="green">signed</Badge>}
          </li>))}
        {(p.targets ?? []).length === 0 && <li className="px-5 py-4 text-sm text-muted">None yet. Research using the tip above, then add them here.</li>}
      </ul>
      <form onSubmit={add} className="grid gap-3 border-t border-line p-5 sm:grid-cols-2">
        <ErrorNote error={error} />
        <Field label="Business name" className="sm:col-span-2"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. a specific planner or venue" /></Field>
        <Field label="Contact name"><Input value={f.contact_name} onChange={(e) => setF({ ...f, contact_name: e.target.value })} /></Field>
        <Field label="Contact email"><Input type="email" value={f.contact_email} onChange={(e) => setF({ ...f, contact_email: e.target.value })} /></Field>
        <Field label="Website" className="sm:col-span-2"><Input value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Button type="submit" icon={<Plus size={14} />} loading={busy} disabled={f.name.length < 2}>Add named target</Button></div>
      </form>
    </Card>
  );
}

export const CONSENT_LABEL: Record<EmailConsent, string> = {
  none: "No permission yet (cold)", opted_in: "Opted in - agreed to hear from us", existing_relationship: "Existing relationship",
  replied: "Replied to us", opted_out: "Opted out - never email",
};

function ConsentRow({ p, onChanged }: { p: Partner; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const v = (p.email_consent ?? "none") as EmailConsent;
  const change = async (next: EmailConsent) => {
    setBusy(true);
    try { await api.updatePartner(p.id, { email_consent: next }); toast(next === "opted_out" ? "Opted out - queued emails cancelled" : "Email permission updated"); onChanged(); }
    catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 text-sm">
      <Field label="Email permission" className="min-w-[240px] flex-1">
        <Select value={v} disabled={busy} onChange={(e) => change(e.target.value as EmailConsent)}>
          {(Object.keys(CONSENT_LABEL) as EmailConsent[]).map((k) => <option key={k} value={k}>{CONSENT_LABEL[k]}</option>)}</Select></Field>
      <p className="max-w-md text-xs text-muted">
        {v === "none" ? "Cold first touch: sent from your own mailbox, never through Postmark." :
          v === "opted_out" ? "This address is suppressed." : "Warm contact: eligible for the Postmark partner stream."}</p>
    </div>
  );
}

export function SequenceCard({ p, onChanged }: { p: Partner; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState<OutreachMessage | null>(null);
  const [reply, setReply] = useState(false);
  const [busy, setBusy] = useState(false);
  const msgs = (p.outreach ?? []).map((m) => ({ ...m, partner_name: p.name, contact_name: p.contact_name, contact_email: p.contact_email }));
  if (!msgs.length) return null;
  const drafts = msgs.filter((m) => m.status === "draft" && m.lint_status !== "blocked").map((m) => m.id);
  const approveAll = async () => {
    setBusy(true);
    try { const r = await api.approveOutreach(drafts); toast(r.refused.length ? r.refused[0].reason : `Approved ${r.approved.length} emails`, r.refused.length ? "err" : "ok"); onChanged(); }
    catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Mail size={14} className="text-vireo" />Outreach sequence</span>}
        sub={p.is_segment ? "Template for this segment - named targets get their own copy" : !p.contact_email ? "Add a contact email (Edit) before this can send" : `To ${p.contact_email}`}
        action={<div className="flex gap-2">
          {!p.is_segment && <Button size="sm" icon={<Reply size={13} />} onClick={() => setReply(true)}>Record reply</Button>}
          {isAdmin && !p.is_segment && drafts.length > 0 && <Button size="sm" variant="primary" icon={<ShieldCheck size={13} />} loading={busy} onClick={approveAll}>Approve {drafts.length}</Button>}
        </div>} />
      {!p.is_segment && <ConsentRow p={p} onChanged={onChanged} />}
      <ol className="divide-y divide-line">
        {msgs.map((m) => (
          <li key={m.id}>
            <button onClick={() => setOpen(m)} className="flex w-full items-start gap-3 px-5 py-3 text-left text-sm hover:bg-surface-2">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-line-strong text-[11px] text-muted">{m.step}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{p.is_segment ? m.subject : preview(m.subject, m)}</div>
                <div className="mt-0.5 text-xs text-faint">{m.step === 1 ? "first email" : `${m.delay_days} days after step ${m.step - 1}`}
                  {m.sent_at && ` · sent ${relTime(m.sent_at)}${m.transport ? ` via ${m.transport}` : ""}`}{m.delivered_at && " · delivered"}{m.opened_at && " · opened"}{m.approved_by && !m.sent_at && ` · approved by ${m.approved_by}`}{m.error && ` · ${m.error}`}</div>
              </div>
              {m.lint_status !== "pass" && <Badge tone={statusTone(m.lint_status)}>claims {m.lint_status}</Badge>}
              <Badge tone={OUTREACH_TONE[m.status]}>{m.status}</Badge>
            </button>
          </li>))}
      </ol>
      <OutreachEditor msg={open} onClose={() => setOpen(null)} onChanged={onChanged} />
      <ReplyModal open={reply} onClose={() => setReply(false)} pid={p.id} onSaved={onChanged} />
    </Card>
  );
}

export function ReplyModal({ open, onClose, pid, onSaved }: { open: boolean; onClose: () => void; pid: number; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ date: today(), kind: "email", summary: "", outcome: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.recordReply(pid, { date: f.date, kind: f.kind, summary: f.summary, outcome: f.outcome || undefined });
      toast(r.classification === "optout" ? "Opt-out recorded - this address won't be emailed again"
        : `Reply recorded (${r.outcome})${r.cancelled_steps ? ` · ${r.cancelled_steps} queued emails stopped` : ""}`);
      setF({ date: today(), kind: "email", summary: "", outcome: "" }); onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Record a reply"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={f.summary.length < 2} onClick={save}>Record reply</Button></>}>
      <ErrorNote error={error} />
      <p className="mb-4 text-sm text-muted">For replies that came by phone, LinkedIn or an inbox Vanguard can't read. Recording a reply stops the remaining emails in the sequence.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Channel"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["email", "linkedin", "x", "call", "meeting", "note"].map((k) => <option key={k} value={k}>{k === "linkedin" ? "LinkedIn" : k === "x" ? "X (Twitter)" : label(k)}</option>)}</Select></Field>
        <Field label="What they said" className="sm:col-span-2"><Textarea value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} placeholder="Interested - asked for the referral terms" /></Field>
        <Field label="Outcome" hint="Leave on auto to classify from the text (opt-out words are always honoured)."><Select value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })}>
          <option value="">Auto</option>{["positive", "neutral", "negative"].map((o) => <option key={o} value={o}>{label(o)}</option>)}</Select></Field>
      </div>
    </Modal>
  );
}
