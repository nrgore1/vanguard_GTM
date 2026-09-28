import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, XCircle, Send, AlertTriangle } from "lucide-react";
import { api, type OutreachMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { label, shortDate } from "../lib/format";
import { Badge, Button, ErrorNote, Field, Input, Modal, Textarea, statusTone, useToast } from "./ui";

export const OUTREACH_TONE: Record<string, string> = {
  draft: "gray", approved: "sky", sent: "violet", replied: "green", cancelled: "gray", failed: "rose", bounced: "rose",
};

/** Preview merge tags the way the recipient will see them. */
export function preview(text: string, m: Pick<OutreachMessage, "contact_name" | "partner_name">, sender = "You") {
  return text.replace(/\{\{first_name\}\}/g, (m.contact_name ?? "").split(" ")[0] || "there")
    .replace(/\{\{company\}\}/g, m.partner_name ?? "their organisation").replace(/\{\{sender_name\}\}/g, sender);
}

export function OutreachEditor({ msg, onClose, onChanged }: { msg: OutreachMessage | null; onClose: () => void; onChanged: () => void }) {
  const { isAdmin, user } = useAuth();
  const toast = useToast();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [findings, setFindings] = useState<{ rule_id: string; message: string; excerpt: string; severity: string }[]>([]);
  const [tab, setTab] = useState<"edit" | "preview">("edit");

  useEffect(() => {
    if (!msg) return;
    setSubject(msg.subject); setBody(msg.body); setError(null); setTab("edit");
    try { setFindings(msg.lint_findings ? JSON.parse(msg.lint_findings) : []); } catch { setFindings([]); }
  }, [msg]);
  if (!msg) return null;
  const editable = msg.status === "draft" || msg.status === "approved";
  const dirty = subject !== msg.subject || body !== msg.body;

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key); setError(null);
    try { await fn(); toast(ok); onChanged(); onClose(); } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const save = async () => {
    setBusy("save"); setError(null);
    try {
      const r = await api.editOutreach(msg.id, { subject, body });
      setFindings(r.lint_findings);
      toast(r.lint_status === "blocked" ? "Saved - blocked by the claim rules, fix before approval" : "Saved - needs admin approval");
      onChanged();
      if (r.lint_status !== "blocked") onClose();
    } catch (e) { setError(e); } finally { setBusy(""); }
  };

  return (
    <Modal open wide onClose={onClose} title={`Step ${msg.step} · ${msg.partner_name ?? "partner"}`}
      footer={<>
        {isAdmin && editable && <Button variant="ghost" icon={<XCircle size={14} />} loading={busy === "cancel"}
          onClick={() => run("cancel", () => api.cancelOutreach(msg.id), "Message cancelled")}>Cancel message</Button>}
        <div className="flex-1" />
        {editable && <Button onClick={save} loading={busy === "save"} disabled={!dirty}>Save edits</Button>}
        {isAdmin && msg.status === "draft" && <Button variant="primary" icon={<ShieldCheck size={15} />} loading={busy === "approve"}
          disabled={dirty || msg.lint_status === "blocked"} onClick={() => run("approve", async () => {
            const r = await api.approveOutreach([msg.id]);
            if (r.refused.length) throw new Error(r.refused[0].reason);
          }, "Approved - it will send when due")}>Approve to send</Button>}
      </>}>
      <ErrorNote error={error} />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={OUTREACH_TONE[msg.status]}>{msg.status}</Badge>
        <Badge tone={statusTone(msg.lint_status)}>claims check: {msg.lint_status}</Badge>
        {msg.partner_id && <Link to={`/partners/${msg.partner_id}`} className="text-vireo hover:underline" onClick={onClose}>Open partner</Link>}
        <span className="text-muted">To: {msg.to_email ?? msg.contact_email ?? <span className="text-amber">no contact email yet</span>}</span>
        {msg.step > 1 && <span className="text-muted">· sends {msg.delay_days} days after step {msg.step - 1}</span>}
        {msg.approved_by && <span className="text-muted">· approved by {msg.approved_by} {shortDate(msg.approved_at)}</span>}
        {msg.sent_at && <span className="text-muted">· sent {shortDate(msg.sent_at)}</span>}
        {msg.error && <span className="text-rose">· {msg.error}</span>}
      </div>
      {findings.length > 0 && (
        <div className="mb-4 space-y-1.5 rounded-lg border border-amber/30 bg-amber-soft p-3 text-xs">
          {findings.map((f, i) => <div key={i} className="flex gap-2"><AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber" />
            <span><b>{f.rule_id}</b> - {f.message} <span className="text-muted">"{f.excerpt}"</span></span></div>)}
        </div>
      )}
      <div className="mb-3 flex gap-1" role="tablist">
        {(["edit", "preview"] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
          className={`rounded-md px-2.5 py-1 text-xs ${tab === t ? "bg-surface-3 text-ink" : "text-muted"}`}>{label(t)}</button>)}
      </div>
      {tab === "edit" ? (
        <div className="space-y-3">
          <Field label="Subject"><Input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} /></Field>
          <Field label="Body" hint="Merge tags: {{first_name}} {{company}} {{sender_name}}. The sender, postal address and opt-out line are added automatically.">
            <Textarea value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} className="min-h-[260px] font-mono text-[13px]" /></Field>
          {!isAdmin && editable && <p className="text-xs text-muted">Edits go back to draft. An admin approves before anything is sent.</p>}
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-surface-2 p-4 text-sm">
          <div className="mb-3 border-b border-line pb-2 font-medium">{preview(subject, msg, user?.name)}</div>
          <p className="whitespace-pre-line leading-relaxed">{preview(body, msg, user?.name)}</p>
          <p className="mt-4 border-t border-dashed border-line pt-2 text-xs text-faint">-- Sender name · Vireoka LLC · postal address · "Reply unsubscribe and we won't email you again."</p>
        </div>
      )}
      {msg.status === "approved" && <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-sky"><Send size={12} />Queued - goes out with the next "Send due now" or scheduler tick.</p>}
    </Modal>
  );
}
