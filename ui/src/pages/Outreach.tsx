import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Send, ShieldCheck, CalendarClock, Inbox, MailCheck, MailWarning, RefreshCw, Sparkles, AlertTriangle, BellRing, Waypoints } from "lucide-react";
import { api, type OutreachMessage } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, relTime } from "../lib/format";
import { Badge, Button, Card, Empty, ErrorNote, Modal, PageHeader, Select, Spinner, Stat, cx, kindTone, statusTone, useToast } from "../components/ui";
import { OUTREACH_TONE, OutreachEditor, preview } from "../components/OutreachEditor";
import { AutoSendNote, ScheduleModal, fmtWhen, isFuture } from "../components/Schedule";
import { CHANNEL_LABEL, ChannelBadge, SendByHand } from "../components/Channels";
import type { ByHand } from "../lib/api";

const TABS = [
  { id: "draft", label: "Needs approval" }, { id: "approved", label: "Queued" }, { id: "hand", label: "By hand" }, { id: "sent", label: "Sent" },
  { id: "replied", label: "Replied" }, { id: "stopped", label: "Stopped" }, { id: "", label: "All" },
];
const STOPPED = new Set(["cancelled", "failed", "bounced"]);

export default function Outreach() {
  const { isAdmin, properties, propName } = useAuth();
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const tabRaw = sp.get("tab") ?? "draft", property = sp.get("property") ?? "", campaign = sp.get("campaign") ?? "";
  const campaigns = useLoad(() => api.campaigns({ property_id: property || undefined }), [property]);
  const tab = tabRaw === "all" ? "" : tabRaw;
  const stats = useLoad(api.outreachStats);
  const { data, error, loading, reload } = useLoad(() => api.outreach({ property_id: property || undefined, campaign_id: campaign ? Number(campaign) : undefined }), [property, campaign]);
  const [sel, setSel] = useState<number[]>([]);
  const [open, setOpen] = useState<OutreachMessage | null>(null);
  const [busy, setBusy] = useState("");
  const [sched, setSched] = useState(false);
  const hand = useLoad(api.byHand);
  const [sendHand, setSendHand] = useState<ByHand | null>(null);
  const [report, setReport] = useState<{ title: string; lines: string[] } | null>(null);
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); setSel([]); };
  const refresh = () => { reload(); stats.reload(); hand.reload(); };

  const rows = useMemo(() => (data ?? []).filter((m) => tab === "" ? true : tab === "stopped" ? STOPPED.has(m.status) : m.status === tab), [data, tab]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { "": (data ?? []).length, stopped: 0, hand: (hand.data ?? []).filter((m) => m.due).length };
    for (const m of data ?? []) { c[m.status] = (c[m.status] ?? 0) + 1; if (STOPPED.has(m.status)) c.stopped++; }
    return c;
  }, [data, hand.data]);
  const selectable = (m: OutreachMessage) => m.status === "draft" || (isAdmin && m.status === "approved");
  const canSelect = tab === "draft" || (isAdmin && tab === "approved");
  const scheduledLater = (data ?? []).filter((m) => (m.status === "draft" || m.status === "approved") && isFuture(m.send_at)).length;

  const act = async (key: string, fn: () => Promise<void>) => { setBusy(key); try { await fn(); } catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(""); refresh(); } };
  const approveSel = () => act("approve", async () => {
    const r = await api.approveOutreach(sel);
    setSel([]);
    toast(`Approved ${r.approved.length}${r.refused.length ? ` · ${r.refused.length} refused` : ""}`);
    if (r.refused.length) setReport({ title: "Not approved", lines: r.refused.map((x) => `#${x.id}: ${x.reason}`) });
  });
  const sendDue = () => act("send", async () => {
    const r = await api.sendDue();
    const how = r.mode === "postmark" ? "Postmark + your mailbox" : r.mode === "smtp" ? "live email" : "outbox - nothing left this machine";
    setReport({ title: `${r.sent.length} sent (${how})`,
      lines: [...r.sent.map((x) => `✓ ${x.partner} · ${x.step > 100 ? "one-off" : `step ${x.step}`} → ${x.to}${x.from ? ` from ${x.from}` : ""}${x.copy?.startsWith("not saved") ? ` (${x.copy})` : ""}${x.transport && x.transport !== r.mode ? ` (via ${x.transport})` : ""}`),
        ...r.skipped.map((x) => `· ${x.partner} · ${x.step > 100 ? "one-off" : `step ${x.step}`}: ${x.reason}`)] });
  });
  const digest = () => act("digest", async () => {
    const r = await api.sendDigest();
    toast(r.sent ? `Digest emailed to ${r.sent} admin${r.sent > 1 ? "s" : ""} (${r.transport})` : `No digest sent: ${r.reason}`, r.sent ? "ok" : "err");
  });
  const pmSync = () => act("pmsync", async () => {
    const r = await api.postmarkSync();
    toast(`Postmark suppressions: pulled ${r.pulled}, pushed ${r.pushed} (${r.stream})`);
  });
  const sync = () => act("sync", async () => {
    const r = await api.syncReplies();
    toast(`Replies matched ${r.matched} · bounces ${r.bounces} · unmatched ${r.unmatched}`);
  });

  const st = stats.data;
  const mode = st?.email;
  const pmk = mode?.postmark;
  return (
    <>
      <PageHeader eyebrow="Partnerships" title="Outreach" sub="Prioritised emails to recommended partners. The agent drafts, an admin approves, and replies stop the sequence automatically."
        actions={isAdmin && <>
          <Button icon={<BellRing size={14} />} loading={busy === "digest"} onClick={digest}>Email approval digest</Button>
          {mode?.imap_configured && <Button icon={<RefreshCw size={14} />} loading={busy === "sync"} onClick={sync}>Check replies</Button>}
          <Button variant="primary" icon={<Send size={14} />} loading={busy === "send"} onClick={sendDue}>Send due now</Button>
        </>} />

      {mode && (
        <div className={cx("mb-4 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm",
          mode.live ? "border-amber/40 bg-amber-soft" : "border-line bg-surface")}>
          {mode.live ? <MailWarning size={17} className="text-amber" /> : <Inbox size={17} className="text-vireo" />}
          <span>{mode.live ? <><b>Live email{mode.mode === "postmark" ? " via Postmark" : ""}</b> from {(mode.mailboxes ?? []).length > 1
            ? mode.mailboxes!.map((b) => `${b.sender}${b.properties ? ` (${b.properties.join(", ")})` : " (other properties)"}`).join("; ") : mode.sender}. Approved messages really send.</> :
            <><b>Outbox mode</b> - approved messages are written to <code className="font-mono text-xs">output/outbox</code>; nothing is emailed yet.</>}</span>
          <span className="text-muted">Daily cap {st?.sent_today}/{(mode.mailboxes ?? []).length > 1 ? mode.mailboxes!.map((b) => b.daily_cap).join("+") : mode.daily_cap}</span>
          <span className="text-muted">Reply sync: {mode.imap_configured ? "IMAP on" : "manual (log replies on the partner page)"}</span>
          {mode.problems.map((p) => <span key={p} className="text-rose">{p}</span>)}
        </div>
      )}
      {pmk && (
        <div className="mb-4 rounded-xl border border-line bg-surface px-4 py-3 text-sm" aria-label="Postmark streams">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <span className="flex items-center gap-2 font-medium"><Waypoints size={16} className="text-vireo" />Postmark streams</span>
            <span className="text-muted">partner emails → <code className="font-mono text-xs text-ink">{pmk.stream_outreach}</code></span>
            <span className="text-muted">team alerts → <code className="font-mono text-xs text-ink">{pmk.stream_notify}</code></span>
            <span className="text-muted">replies: {pmk.inbound ? "inbound stream (auto)" : mode?.imap_configured ? "IMAP" : "record by hand"}</span>
            <span className={cx("num", (pmk.used_this_month ?? 0) >= pmk.monthly_cap ? "text-rose" : "text-muted")}>
              {pmk.used_this_month ?? 0}/{pmk.monthly_cap} this month</span>
            {!pmk.webhook_auth && <span className="text-amber">webhook auth not set - bounces and replies won't sync</span>}
            {isAdmin && <Button size="sm" variant="ghost" className="ml-auto" loading={busy === "pmsync"} onClick={pmSync}>Sync suppressions</Button>}
          </div>
          <p className="mt-1.5 text-xs text-faint">
            Cold first touches {pmk.allow_cold ? <b className="text-amber">are allowed through Postmark (VANGUARD_POSTMARK_ALLOW_COLD)</b> :
              pmk.cold_via_smtp ? "go from your own mailbox (SMTP)" : "are held until SMTP is set or the partner opts in"}
            {" "}- Postmark only accepts permission-based email. Partners who replied, opted in or already know you go through Postmark.</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Awaiting approval" value={st?.draft ?? "–"} sub={st?.blocked ? `${st.blocked} blocked by claim rules` : "drafts from the agent"} icon={<ShieldCheck size={14} />} tone="amber" />
        <Stat label="Queued" value={st?.approved ?? "–"} sub={st?.by_hand_due ? `${st.by_hand_due} LinkedIn/X due by hand` : "approved, sending when due"} icon={<Send size={14} />} tone="sky" />
        <Stat label="Partners contacted" value={st?.partners_contacted ?? "–"} sub={`${st?.ever_sent ?? 0} emails sent`} icon={<MailCheck size={14} />} tone="violet" />
        <Stat label="Replied" value={st?.partners_replied ?? "–"} sub={st?.reply_rate != null ? `${(st.reply_rate * 100).toFixed(0)}% reply rate` : "no sends yet"} icon={<Inbox size={14} />} />
        <Stat label="Stopped" value={(st?.cancelled ?? 0) + (st?.bounced ?? 0) + (st?.failed ?? 0)} sub={`${st?.suppressed ?? 0} addresses opted out/bounced`} icon={<AlertTriangle size={14} />} tone="rose" />
      </div>

      <div className="mb-3 mt-6 flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-lg border border-line bg-surface-2 p-1" role="tablist" aria-label="Status">
          {TABS.map((t) => (
            <button key={t.id || "all"} role="tab" aria-selected={tab === t.id} onClick={() => setFilter("tab", t.id || "all")}
              className={`rounded-md px-2.5 py-1 text-xs ${tab === t.id ? "bg-surface-3 text-ink" : "text-muted hover:text-ink"}`}>
              {t.label} <span className="num text-faint">{counts[t.id] ?? 0}</span></button>
          ))}
        </div>
        <Select value={property} onChange={(e) => setFilter("property", e.target.value)} className="w-auto" aria-label="Filter by property">
          <option value="">All properties</option>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        <Select value={campaign} onChange={(e) => setFilter("campaign", e.target.value)} className="w-auto" aria-label="Filter by campaign">
          <option value="">All campaigns</option>{(campaigns.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        {canSelect && (
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setSel(sel.length ? [] : rows.filter(selectable).map((m) => m.id))}>
              {sel.length ? "Clear" : `Select all ${rows.filter(selectable).length}`}</Button>
            <Button size="sm" icon={<CalendarClock size={13} />} disabled={!sel.length} onClick={() => setSched(true)}>Schedule {sel.length || ""}</Button>
            {isAdmin && tab === "draft" && <Button size="sm" variant="primary" icon={<ShieldCheck size={13} />} disabled={!sel.length} loading={busy === "approve"} onClick={approveSel}>Approve {sel.length || ""}</Button>}
          </div>
        )}
      </div>
      <ErrorNote error={error} />
      {tab === "hand" ? (
        <Card className="overflow-hidden">
          <p className="border-b border-line px-5 py-3 text-xs text-muted">Approved LinkedIn and X messages. The app never posts for you: copy the text, send it from their profile, then click <b className="text-ink">I sent it</b> so the next step's wait starts.</p>
          {(hand.data ?? []).length === 0 ? <Empty icon={<Sparkles size={22} />} title="Nothing to send by hand" body="Move a partner's sequence to LinkedIn or X on its page (Outreach sequence → channel), or write a LinkedIn/X message with Write email." /> : (
            <ul className="divide-y divide-line">{(hand.data ?? []).filter((m) => !property || m.property_id === property).map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <ChannelBadge c={m.channel} />
                <div className="min-w-0 flex-1">
                  <Link to={`/partners/${m.partner_id}`} className="font-medium hover:text-vireo">{m.partner_name}</Link>
                  <span className="ml-2 text-xs text-muted">{m.one_off ? "message" : `step ${m.step}`}</span>
                  <div className="truncate text-xs text-faint">{preview(m.body, m)}</div>
                </div>
                {m.due ? <Badge tone="green">due now</Badge> : <span className="text-xs text-muted">{m.held?.startsWith("scheduled for") ? `scheduled ${fmtWhen(m.held.slice(14))}` : m.held}</span>}
                <Button size="sm" variant={m.due ? "primary" : "outline"} onClick={() => setSendHand(m)}>Send on {CHANNEL_LABEL[m.channel ?? "linkedin"]}</Button>
              </li>))}</ul>)}
        </Card>
      ) : (
      <Card className="overflow-hidden">
        {loading && !data ? <Spinner /> : rows.length === 0 ? (
          <Empty icon={<Sparkles size={22} />} title={tab === "draft" ? "Nothing waiting for approval" : "No messages here"}
            body={isAdmin ? "Recommend partners, then add named organisations (with a contact email) under each recommended segment - their drafted emails appear here for approval." : "Drafts appear here once partners with contact emails are added."}
            action={isAdmin && <Link to="/partners"><Button variant="primary" icon={<Sparkles size={15} />}>Recommend partners</Button></Link>} />
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[980px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {canSelect && <th className="w-8 px-3" />}
                {["Priority", "Partner", "Step", "Subject", "To", "Status", ""].map((h, i) => <th key={i} className="px-3 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((m) => {
                  const noContact = !m.contact_email && !m.to_email;
                  return (
                    <tr key={m.id} onClick={() => setOpen(m)} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-surface-2">
                      {canSelect && <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" aria-label={`Select message ${m.id}`} disabled={!selectable(m)} checked={sel.includes(m.id)}
                          onChange={(e) => setSel(e.target.checked ? [...sel, m.id] : sel.filter((x) => x !== m.id))} className="accent-[var(--vireo)]" /></td>}
                      <td className="whitespace-nowrap px-3 py-3"><Badge tone={statusTone(m.priority ?? "P2")}>{m.priority ?? "–"}</Badge> <span className="num text-xs text-muted">{m.priority_score ?? ""}</span></td>
                      <td className="max-w-[260px] px-3 py-3"><Link to={`/partners/${m.partner_id}`} onClick={(e) => e.stopPropagation()} className="line-clamp-2 font-medium hover:text-vireo">{m.partner_name}</Link>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-faint"><Badge tone={kindTone(m.partner_kind ?? "")}>{label(m.partner_kind ?? "")}</Badge>{propName(m.property_id ?? "")}</div>
                        {m.campaign_name && <div className="mt-0.5 truncate text-[11px] text-vireo">{m.campaign_name}</div>}</td>
                      <td className="num px-3 py-3 text-muted">{m.one_off ? "one-off" : m.step} <ChannelBadge c={m.channel} /></td>
                      <td className="max-w-[320px] px-3 py-3"><div className="truncate">{preview(m.subject, m)}</div>{m.lint_status !== "pass" && <Badge tone={statusTone(m.lint_status)}>claims: {m.lint_status}</Badge>}</td>
                      <td className="px-3 py-3 text-xs">{noContact ? <span className="text-amber">needs contact email</span> : <span className="text-muted">{m.to_email ?? m.contact_email}</span>}</td>
                      <td className="whitespace-nowrap px-3 py-3"><Badge tone={OUTREACH_TONE[m.status]}>{m.status}</Badge>
                        {m.transport && m.transport !== "outbox" && <Badge tone={m.transport === "postmark" ? "violet" : "gray"}>{m.transport}</Badge>}
                        {m.opened_at ? <span className="ml-1 text-[11px] text-vireo">opened</span> : m.delivered_at ? <span className="ml-1 text-[11px] text-muted">delivered</span> : null}
                        <div className="mt-0.5 text-[11px] text-faint">{m.sent_at ? `sent ${relTime(m.sent_at)}` : m.approved_by ? `by ${m.approved_by}` : ""}</div>
                        {!m.sent_at && isFuture(m.send_at) && <div className="mt-0.5 text-[11px] text-vireo">scheduled {fmtWhen(m.send_at)}</div>}</td>
                      <td className="px-3 py-3 text-right text-xs text-vireo">Open</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      )}
      <SendByHand msg={sendHand} onClose={() => setSendHand(null)} onChanged={refresh} />
      {scheduledLater > 0 && <div className="mt-3"><AutoSendNote every={mode?.auto_every_min} /></div>}
      <OutreachEditor msg={open} onClose={() => setOpen(null)} onChanged={refresh} />
      <ScheduleModal ids={sel} open={sched} onClose={() => setSched(false)} onDone={() => { setSel([]); refresh(); }} autoEvery={mode?.auto_every_min} />
      <Modal open={!!report} onClose={() => setReport(null)} title={report?.title ?? ""}>
        <ul className="space-y-1 text-sm">{report?.lines.map((l, i) => <li key={i} className={l.startsWith("✓") ? "text-ink" : "text-muted"}>{l}</li>)}</ul>
        {report?.lines.length === 0 && <p className="text-sm text-muted">Nothing was due.</p>}
      </Modal>
    </>
  );
}
