import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Pencil, Trash2, Plus, Mail, Hash } from "lucide-react";
import { api, type Result } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { CAMPAIGN_STATUSES, label, num, pct, shortDate, today, usd } from "../lib/format";
import { Badge, Button, Card, CardHeader, Confirm, ErrorNote, Field, Input, Modal, Progress, Select, Spinner, Stat, useToast } from "../components/ui";
import { CampaignForm } from "./Campaigns";
import { CampaignOutreachCard } from "../components/CampaignOutreach";

const METRICS: (keyof Result)[] = ["sent", "opens", "clicks", "replies", "meetings", "signups", "conversions", "revenue_usd", "spend_usd"];

function ResultForm({ open, onClose, cid, onSaved }: { open: boolean; onClose: () => void; cid: number; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<Record<string, string>>({ date: today() });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    setBusy(true); setError(null);
    const body: Record<string, unknown> = { date: f.date, notes: f.notes || null };
    for (const m of METRICS) if (f[m]) body[m] = Number(f[m]);
    try { await api.addResult(cid, body); toast("Results logged"); setF({ date: today() }); onSaved(); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Log results" wide
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save results</Button></>}>
      <ErrorNote error={error} />
      <p className="mb-4 text-sm text-muted">Enter what the app can't see on its own — opens and clicks from another tool, signups, revenue, spend. Emails sent, replies and meetings for partners attached to this campaign are counted automatically, so don't enter those twice.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        {METRICS.map((m) => (
          <Field key={m} label={label(m.replace("_usd", " ($)"))}>
            <Input type="number" min={0} step={m.endsWith("usd") ? "0.01" : "1"} value={f[m] ?? ""} onChange={(e) => setF({ ...f, [m]: e.target.value })} placeholder="0" />
          </Field>
        ))}
        <Field label="Notes" className="sm:col-span-3"><Input value={f.notes ?? ""} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="What changed, what you learned" /></Field>
      </div>
    </Modal>
  );
}

export default function CampaignDetail() {
  const { id } = useParams();
  const cid = Number(id);
  const nav = useNavigate();
  const toast = useToast();
  const { user, isAdmin, propName } = useAuth();
  const { data: c, error, loading, reload } = useLoad(() => api.campaign(cid), [cid]);
  const [editing, setEditing] = useState(false);
  const [logging, setLogging] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  if (loading && !c) return <Spinner />;
  if (!c) return <ErrorNote error={error} />;
  const R = c.results ?? [];
  const tot = Object.fromEntries(METRICS.map((m) => [m, R.reduce((s, r) => s + Number(r[m] ?? 0), 0)])) as Record<string, number>;
  // outreach activity for attached partners counts on top of hand-logged results
  const ot = c.outreach?.totals;
  const auto = { sent: ot?.emails_sent ?? 0, replies: ot?.replies ?? 0, meetings: ot?.meetings ?? 0 };
  tot.sent += auto.sent; tot.replies += auto.replies; tot.meetings += auto.meetings;
  const fromOutreach = (n: number) => (n ? ` · ${n} from outreach` : "");
  const canDelete = isAdmin || c.created_by === user?.id;
  const goalActual = c.goal_metric ? tot[c.goal_metric] ?? 0 : 0;

  let steps: { step: number; name: string; subject: string; body: string; delay_days: number }[] | null = null;
  let hooks: string[] | null = null;
  try { const j = c.content ? JSON.parse(c.content) : null; if (Array.isArray(j) && typeof j[0] === "object") steps = j; else if (Array.isArray(j)) hooks = j; } catch { /* free text */ }

  const setStatus = async (s: string) => {
    try { await api.updateCampaign(cid, { status: s as never }); toast(`Status: ${label(s)}`); reload(); } catch (e) { toast(String((e as Error).message), "err"); }
  };
  const del = async () => {
    setBusy(true);
    try { await api.deleteCampaign(cid); toast("Campaign deleted"); nav("/campaigns"); } catch (e) { toast(String((e as Error).message), "err"); setBusy(false); }
  };
  const delResult = async (rid: number) => {
    try { await api.deleteResult(rid); toast("Entry removed"); reload(); } catch (e) { toast(String((e as Error).message), "err"); }
  };

  return (
    <>
      <Link to="/campaigns" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft size={15} />Campaigns</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="font-mono uppercase tracking-[0.16em] text-vireo">{propName(c.property_id)}</span>·<span>{label(c.kind)}{c.channel ? ` · ${c.channel}` : ""}</span>
            {c.source_run_id && <Badge tone="violet">from agent run</Badge>}
          </div>
          <h1 className="font-serif text-[26px] font-semibold leading-tight">{c.name}</h1>
          <div className="mt-1.5 text-sm text-muted">{shortDate(c.start_date)} – {shortDate(c.end_date)} · owner {c.owner_name ?? "—"} · budget {usd(c.budget_usd)}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={c.status} onChange={(e) => setStatus(e.target.value)} className="w-auto" aria-label="Status">
            {CAMPAIGN_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select>
          <Button icon={<Pencil size={14} />} onClick={() => setEditing(true)}>Edit</Button>
          {canDelete && <Button variant="danger" icon={<Trash2 size={14} />} onClick={() => setConfirm(true)}>Delete</Button>}
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setLogging(true)}>Log results</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Sent" value={num(tot.sent, true)} sub={`${pct(tot.opens, tot.sent)} opened${fromOutreach(auto.sent)}`} />
        <Stat label="Replies" value={num(tot.replies)} sub={`${pct(tot.replies, ot?.touched ? Math.max(ot.touched, tot.sent) : tot.sent)} reply rate${fromOutreach(auto.replies)}`} tone="sky" />
        <Stat label="Meetings" value={num(tot.meetings)} sub={`${num(tot.signups)} signups${fromOutreach(auto.meetings)}`} tone="violet" />
        <Stat label="Conversions" value={num(tot.conversions)} sub={`${usd(tot.revenue_usd, true)} revenue`} tone="green" />
        <Stat label="Spend" value={usd(tot.spend_usd, true)} sub={tot.conversions ? `${usd(tot.spend_usd / tot.conversions)} per conversion` : "no conversions yet"} tone="amber" />
      </div>

      {c.goal_metric && c.goal_value ? (
        <Card className="mt-4 p-5">
          <div className="mb-2 flex items-baseline justify-between text-sm"><span className="text-muted">Goal: {num(c.goal_value)} {label(c.goal_metric)}</span>
            <span className="num">{num(goalActual)} <span className="text-muted">({pct(goalActual, c.goal_value)})</span></span></div>
          <Progress value={goalActual} max={c.goal_value} />
        </Card>
      ) : null}

      {c.outreach && <CampaignOutreachCard cid={cid} propertyId={c.property_id} o={c.outreach} onChanged={reload} />}

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader title="Results log" sub={`${R.length} hand-logged entries`} />
          {R.length === 0 ? <p className="px-5 py-10 text-center text-sm text-muted">No results yet. Log the first numbers when the campaign starts sending.</p> : (
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="border-b border-line text-left text-xs text-muted">
                  {["Date", "Sent", "Replies", "Meetings", "Signups", "Conv.", "Revenue", "By", ""].map((h, i) => <th key={i} className={`px-4 py-2 font-medium ${i && i < 7 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
                <tbody>{R.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5">{shortDate(r.date)}{r.notes && <div className="max-w-[160px] truncate text-[11px] text-faint">{r.notes}</div>}</td>
                    {(["sent", "replies", "meetings", "signups", "conversions"] as const).map((m) => <td key={m} className="num px-4 py-2.5 text-right">{num(r[m])}</td>)}
                    <td className="num px-4 py-2.5 text-right">{usd(r.revenue_usd, true)}</td>
                    <td className="px-4 py-2.5 text-xs text-muted">{r.by_name ?? "—"}</td>
                    <td className="px-2 py-2.5 text-right">{(isAdmin || r.created_by === user?.id) &&
                      <button onClick={() => delResult(r.id)} className="rounded p-1 text-faint hover:text-rose" aria-label="Delete entry"><Trash2 size={13} /></button>}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </Card>
        <Card>
          <CardHeader title={steps ? "Email sequence" : hooks ? "Hooks" : "Brief"} sub={steps ? "5 steps from the agent's playbook - export is gated by approval" : undefined} />
          <div className="space-y-3 p-5 text-sm">
            {c.description && <p className="whitespace-pre-line text-muted">{c.description}</p>}
            {steps?.map((s) => (
              <div key={s.step} className="rounded-lg border border-line bg-surface-2 p-3">
                <div className="flex items-center gap-2 text-xs text-muted"><Mail size={13} className="text-vireo" />Step {s.step} · {label(s.name)} · +{s.delay_days}d</div>
                <div className="mt-1 font-medium">{s.subject}</div>
                <p className="mt-1 line-clamp-4 whitespace-pre-line text-xs text-muted">{s.body}</p>
              </div>
            ))}
            {hooks?.map((h, i) => <div key={i} className="flex gap-2 rounded-lg border border-line bg-surface-2 p-3"><Hash size={14} className="mt-0.5 shrink-0 text-vireo" /><span>{h}</span></div>)}
            {!c.description && !steps && !hooks && <p className="text-muted">No brief yet — add a description with Edit.</p>}
          </div>
        </Card>
      </div>

      <CampaignForm open={editing} onClose={() => setEditing(false)} initial={c} onSaved={() => { setEditing(false); reload(); }} />
      <ResultForm open={logging} onClose={() => setLogging(false)} cid={cid} onSaved={reload} />
      <Confirm open={confirm} onClose={() => setConfirm(false)} onConfirm={del} busy={busy} title="Delete campaign?"
        body={<>This removes <b className="text-ink">{c.name}</b> and all {R.length} results logged against it. This can't be undone.</>} />
    </>
  );
}
