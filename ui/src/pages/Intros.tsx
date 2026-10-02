import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Network, Search, Send, ShieldCheck, Sparkles, ExternalLink, Copy, Mail, Linkedin } from "lucide-react";
import { api, type Intro } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, relTime } from "../lib/format";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, Textarea, cx, kindTone, statusTone, useToast } from "../components/ui";

const TABS = [
  { id: "suggested", label: "Suggested" }, { id: "draft", label: "Drafts" }, { id: "approved", label: "Ready to send" },
  { id: "sent", label: "Asked" }, { id: "done", label: "Outcomes" },
];
const DONE = new Set(["accepted", "introduced", "declined", "cancelled"]);
const STATUS_TONE: Record<string, string> = { suggested: "gray", draft: "amber", approved: "sky", sent: "violet", accepted: "green", introduced: "green", declined: "rose", cancelled: "gray" };

export function Strength({ v }: { v: number | null }) {
  const n = Math.round(v ?? 0);
  return <span className="inline-flex gap-[2px] align-middle" aria-label={`tie strength ${v ?? 0} of 5`} title={`tie strength ${v ?? 0}/5`}>
    {[1, 2, 3, 4, 5].map((i) => <span key={i} className="h-1.5 w-2.5 rounded-sm" style={{ background: i <= n ? "var(--vireo)" : "var(--surface-3)" }} />)}</span>;
}

export function IntroEditor({ intro, onClose, onChanged }: { intro: Intro | null; onClose: () => void; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (intro) { setSubject(intro.subject ?? ""); setBody(intro.body ?? ""); setNote(""); setError(null); } }, [intro]);
  if (!intro) return null;
  const who = `${intro.first_name} ${intro.last_name}`;
  const editable = ["draft", "approved"].includes(intro.status);
  const run = async (key: string, fn: () => Promise<unknown>, ok: string, close = true) => {
    setBusy(key); setError(null);
    try { await fn(); toast(ok); onChanged(); if (close) onClose(); } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const copyAndOpen = async () => {
    try { await navigator.clipboard.writeText(body); toast("Message copied - paste it into LinkedIn"); } catch { toast("Copy failed - select the text and copy it", "err"); }
    if (intro.profile_url?.startsWith("http")) window.open(intro.profile_url, "_blank", "noopener");
  };
  let findings: { message: string; excerpt: string }[] = [];
  try { findings = intro.lint_findings ? JSON.parse(intro.lint_findings) : []; } catch { /* none */ }
  return (
    <Modal open onClose={onClose} wide title={`Ask ${who} for an introduction to ${intro.partner_name}`}
      footer={<div className="flex w-full flex-wrap items-center gap-2">
        {intro.status === "suggested" && <Button variant="primary" icon={<Sparkles size={14} />} loading={busy === "draft"} onClick={() => run("draft", () => api.draftIntro(intro.id), "Ask drafted - review it, then an admin approves", false)}>Draft the ask</Button>}
        {editable && <Button loading={busy === "save"} disabled={subject === intro.subject && body === intro.body} onClick={() => run("save", () => api.editIntro(intro.id, { subject, body }), "Saved - back to draft for approval", false)}>Save edits</Button>}
        {isAdmin && intro.status === "draft" && <Button variant="primary" icon={<ShieldCheck size={14} />} loading={busy === "approve"} disabled={intro.lint_status === "blocked"}
          onClick={() => run("approve", () => api.approveIntros([intro.id]), "Approved")}>Approve</Button>}
        {intro.status === "approved" && <>
          <Button icon={<Copy size={14} />} onClick={copyAndOpen}>Copy & open LinkedIn</Button>
          <Button variant="primary" icon={<Linkedin size={14} />} loading={busy === "sent"} onClick={() => run("sent", () => api.introSentLinkedIn(intro.id), "Marked as sent on LinkedIn")}>I sent it on LinkedIn</Button>
        </>}
        {intro.status === "sent" && <>
          <Input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} className="w-56" />
          <Button onClick={() => run("o1", () => api.introOutcome(intro.id, "accepted", note), "Recorded: agreed")}>Agreed to intro</Button>
          <Button variant="primary" onClick={() => run("o2", () => api.introOutcome(intro.id, "introduced", note), "Recorded: introduced")}>Introduced</Button>
          <Button variant="ghost" onClick={() => run("o3", () => api.introOutcome(intro.id, "declined", note), "Recorded: declined")}>Declined</Button>
        </>}
        {intro.status === "accepted" && <Button variant="primary" onClick={() => run("o2", () => api.introOutcome(intro.id, "introduced", note), "Recorded: introduced")}>Introduction made</Button>}
        <Button variant="ghost" className="ml-auto" onClick={onClose}>Close</Button>
      </div>}>
      <ErrorNote error={error} />
      <div className="mb-4 grid gap-3 rounded-lg border border-line bg-surface-2 p-3 text-sm sm:grid-cols-2">
        <div><div className="text-xs text-muted">Introducer</div><div className="font-medium">{who}</div>
          <div className="text-xs text-muted">{intro.position ?? "—"}{intro.company ? ` · ${intro.company}` : ""}</div>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted"><Strength v={intro.strength} />{intro.msg_count ? `${intro.msg_count} messages` : "no messages yet"}{intro.last_message_at ? ` · last ${relTime(intro.last_message_at)}` : ""}</div></div>
        <div><div className="text-xs text-muted">Target</div><Link to={`/partners/${intro.partner_id}`} className="font-medium hover:text-vireo">{intro.partner_name}</Link>
          <div className="text-xs text-muted">{label(intro.partner_kind)}{intro.target_contact && intro.target_contact !== intro.partner_name ? ` · ${intro.target_contact}` : ""}</div>
          <a href={intro.mutuals_url} target="_blank" rel="noreferrer noopener" className="mt-1 inline-flex items-center gap-1 text-xs text-vireo hover:underline"><Search size={11} />Check your 2nd-degree connections there</a></div>
        <p className="text-xs text-muted sm:col-span-2"><Badge tone={intro.path === "direct" ? "green" : "sky"}>{intro.path === "direct" ? "insider" : "likely bridge"}</Badge> {intro.reason}</p>
      </div>
      {intro.status === "suggested" ? <p className="text-sm text-muted">Draft the ask to see a double opt-in note to {intro.first_name}, with a short paragraph they can forward. You can edit it before an admin approves it.</p> : <>
        <Field label="Subject"><Input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} /></Field>
        <Field label={`Message to ${intro.first_name} (${intro.email ? `emails to ${intro.email}` : "send on LinkedIn - no email shared"})`} className="mt-3">
          <Textarea value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} className="min-h-[300px] text-[13px]" /></Field>
        {intro.lint_status === "blocked" && <div className="mt-2 rounded-lg border border-rose/40 bg-rose-soft p-2 text-xs text-rose">Blocked by the claim rules: {findings.map((f) => f.message).join("; ")}</div>}
        {intro.status === "sent" && <p className="mt-2 text-xs text-muted">Asked {relTime(intro.sent_at)} by {intro.channel}. Record what happened when {intro.first_name} answers.</p>}
      </>}
    </Modal>
  );
}

export default function Intros() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") ?? "suggested", kind = sp.get("kind") ?? "";
  const { data, error, loading, reload } = useLoad(() => api.intros({ kind: kind || undefined }), [kind]);
  const [open, setOpen] = useState<Intro | null>(null);
  const [sel, setSel] = useState<number[]>([]);
  const [busy, setBusy] = useState("");
  const [report, setReport] = useState<string[] | null>(null);
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); setSel([]); };
  // keep an open editor in step with fresh data (e.g. after drafting)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) setOpen((data ?? []).find((d) => d.id === open.id) ?? null); }, [data]);
  const rows = useMemo(() => (data ?? []).filter((r) => tab === "done" ? DONE.has(r.status) : r.status === tab), [data, tab]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { done: 0 };
    for (const r of data ?? []) { c[r.status] = (c[r.status] ?? 0) + 1; if (DONE.has(r.status)) c.done++; }
    return c;
  }, [data]);
  const act = async (key: string, fn: () => Promise<void>) => { setBusy(key); try { await fn(); } catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(""); reload(); } };
  const find = () => act("find", async () => {
    const r = await api.suggestIntros();
    toast(r.error ?? `${r.suggested} new paths across ${r.targets} targets (${r.direct} through insiders)`, r.error ? "err" : "ok");
  });
  const draftSel = () => act("draft", async () => { for (const id of sel) await api.draftIntro(id); toast(`${sel.length} asks drafted`); setSel([]); setFilter("tab", "draft"); });
  const approveSel = () => act("approve", async () => { const r = await api.approveIntros(sel); toast(`Approved ${r.approved.length}${r.refused.length ? ` · ${r.refused.length} refused` : ""}`); setSel([]); });
  const send = () => act("send", async () => {
    const r = await api.sendIntros();
    if (r.error) { toast(r.error, "err"); return; }
    setReport([...r.sent.map((s) => `✓ emailed ${s.to} <${s.email}> about ${s.target}`), ...r.skipped.map((s) => `· ${s.to}: ${s.reason}`)]);
  });
  const selectable = tab === "suggested" || (isAdmin && tab === "draft");
  return (
    <>
      <PageHeader eyebrow="Relationships" title="Introductions"
        sub="Reach investors and partners through people you already know. Paths come from your LinkedIn export: insiders who work at the target, and likely bridges in the target's world."
        actions={<>
          <Button icon={<Network size={15} />} loading={busy === "find"} onClick={find}>Find paths</Button>
          {isAdmin && <Button variant="primary" icon={<Send size={15} />} loading={busy === "send"} onClick={send}>Send approved emails</Button>}
        </>} />
      <div className="mb-4 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-muted">
        LinkedIn's export lists your 1st-degree connections only. An <Badge tone="green">insider</Badge> works at the target; a <Badge tone="sky">likely bridge</Badge> is in the target's world and has a real tie with you (messages, endorsements, years connected) but isn't proven to know them. Before asking a bridge, use <span className="text-ink">Check 2nd-degree</span> to see who you share. Every ask is double opt-in, and nothing goes out until an admin approves it.
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-lg border border-line bg-surface-2 p-1" role="tablist" aria-label="Status">
          {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setFilter("tab", t.id)}
            className={`rounded-md px-2.5 py-1 text-xs ${tab === t.id ? "bg-surface-3 text-ink" : "text-muted hover:text-ink"}`}>{t.label} <span className="num text-faint">{counts[t.id] ?? 0}</span></button>)}
        </div>
        <Select value={kind} onChange={(e) => setFilter("kind", e.target.value)} className="w-auto" aria-label="Target type">
          <option value="">All targets</option>{["investor", "design_partner", "co_sell", "integration", "distribution"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</Select>
        {selectable && rows.length > 0 && <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setSel(sel.length ? [] : rows.map((r) => r.id))}>{sel.length ? "Clear" : `Select all ${rows.length}`}</Button>
          {tab === "suggested" && <Button size="sm" variant="primary" icon={<Sparkles size={13} />} disabled={!sel.length} loading={busy === "draft"} onClick={draftSel}>Draft {sel.length || ""}</Button>}
          {tab === "draft" && <Button size="sm" variant="primary" icon={<ShieldCheck size={13} />} disabled={!sel.length} loading={busy === "approve"} onClick={approveSel}>Approve {sel.length || ""}</Button>}
        </div>}
      </div>
      <ErrorNote error={error} />
      <Card className="overflow-hidden">
        {loading && !data ? <Spinner /> : rows.length === 0 ? (
          <Empty icon={<Network size={22} />} title={tab === "suggested" ? "No suggested paths" : "Nothing here yet"}
            body={tab === "suggested" ? "Import your LinkedIn export on the Partners page, then click Find paths." : undefined}
            action={tab === "suggested" && <Button variant="primary" icon={<Network size={15} />} onClick={find}>Find paths</Button>} />
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[980px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {selectable && <th className="w-8 px-3" />}
                {["Target", "Introducer", "Why this path", "Via", "Status", ""].map((h, i) => <th key={i} className="px-3 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id} onClick={() => setOpen(r)} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-surface-2">
                  {selectable && <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" className="accent-[var(--vireo)]" aria-label={`Select intro ${r.id}`} checked={sel.includes(r.id)}
                      onChange={(e) => setSel(e.target.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} /></td>}
                  <td className="max-w-[230px] px-3 py-3"><Link to={`/partners/${r.partner_id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:text-vireo">{r.partner_name}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1"><Badge tone={statusTone(r.priority ?? "P2")}>{r.priority ?? "–"}</Badge><Badge tone={kindTone(r.partner_kind)}>{label(r.partner_kind)}</Badge></div>
                    <a href={r.mutuals_url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} className="mt-1 inline-flex items-center gap-1 text-[11px] text-vireo hover:underline"><Search size={10} />Check 2nd-degree</a></td>
                  <td className="max-w-[230px] px-3 py-3"><div className="font-medium">{r.first_name} {r.last_name}</div>
                    <div className="line-clamp-2 text-xs text-muted">{r.position}{r.company ? ` · ${r.company}` : ""}</div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-faint"><Strength v={r.strength} />{r.msg_count ? `${r.msg_count} msgs` : ""}</div></td>
                  <td className="max-w-[360px] px-3 py-3 text-xs"><Badge tone={r.path === "direct" ? "green" : "sky"}>{r.path === "direct" ? "insider" : "likely bridge"}</Badge>
                    <div className="mt-1 line-clamp-3 text-muted">{r.reason}</div></td>
                  <td className="px-3 py-3 text-xs">{r.email ? <span className="inline-flex items-center gap-1"><Mail size={12} />email</span> : <span className="inline-flex items-center gap-1"><Linkedin size={12} />LinkedIn</span>}</td>
                  <td className="whitespace-nowrap px-3 py-3"><Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>
                    {r.lint_status === "blocked" && <Badge tone="rose">claims: blocked</Badge>}
                    <div className="mt-0.5 text-[11px] text-faint">{r.sent_at ? `asked ${relTime(r.sent_at)}` : r.approved_by ? `by ${r.approved_by}` : ""}</div></td>
                  <td className="px-3 py-3 text-right text-xs text-vireo">Open {r.profile_url?.startsWith("http") && <a href={r.profile_url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} aria-label="LinkedIn profile"><ExternalLink size={12} className="inline" /></a>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Card>
      <IntroEditor intro={open} onClose={() => setOpen(null)} onChanged={reload} />
      <Modal open={!!report} onClose={() => setReport(null)} title="Send approved emails">
        <ul className="space-y-1 text-sm">{report?.map((l, i) => <li key={i} className={cx(l.startsWith("✓") ? "text-ink" : "text-muted")}>{l}</li>)}</ul>
        {report?.length === 0 && <p className="text-sm text-muted">Nothing approved to send.</p>}
      </Modal>
    </>
  );
}
