import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Target, TrendingUp, Megaphone, Handshake, CheckCircle2, Pencil, ArrowUpRight, Table2, BarChart3, Send, FileSignature } from "lucide-react";
import { api, type PropertyDash } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { num, pct, relTime, shortDate, TRACKS, usd, label } from "../lib/format";
import { Badge, Button, Card, CardHeader, ErrorNote, Field, Input, Modal, PageHeader, Progress, Spinner, Stat, statusTone, useToast } from "../components/ui";

// Partner stages are ordinal: one hue, light -> dark (sequential), never categorical.
const STAGE_ORDER = ["identified", "contacted", "in_conversation", "pilot", "signed"];
const STAGE_SHADE = ["0.18", "0.34", "0.52", "0.74", "1"];

function ChartTip({ active, payload, label: l, fmt }: { active?: boolean; payload?: { value: number }[]; label?: string; fmt: (n: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-xs shadow-card">
      <div className="text-muted">Week of {shortDate(l)}</div>
      <div className="num mt-0.5 text-sm text-ink">{fmt(payload[0].value)}</div>
    </div>
  );
}

function WeeklyChart({ data, dataKey, title, fmt }: { data: Record<string, number | string>[]; dataKey: string; title: string; fmt: (n: number) => string }) {
  const [table, setTable] = useState(false);
  return (
    <Card>
      <CardHeader title={title} sub="Logged campaign results, by week"
        action={<button onClick={() => setTable(!table)} className="rounded-md p-1.5 text-muted hover:bg-surface-3 hover:text-ink" aria-label={table ? "Show chart" : "Show table"}>
          {table ? <BarChart3 size={15} /> : <Table2 size={15} />}</button>} />
      <div className="px-3 pb-3 pt-4">
        {data.length === 0 ? <p className="py-16 text-center text-sm text-muted">No results logged yet.</p> : table ? (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted"><th className="px-2 py-1 font-medium">Week of</th><th className="px-2 py-1 text-right font-medium">{title}</th></tr></thead>
            <tbody>{data.map((d) => <tr key={String(d.start)} className="border-t border-line"><td className="px-2 py-1.5">{shortDate(String(d.start))}</td><td className="num px-2 py-1.5 text-right">{fmt(Number(d[dataKey]))}</td></tr>)}</tbody>
          </table>
        ) : (
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={data} margin={{ left: 4, right: 8, top: 4 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis dataKey="start" tickFormatter={shortDate} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v) => fmt(v)} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} width={58} />
              <Tooltip cursor={{ fill: "var(--surface-3)" }} content={<ChartTip fmt={fmt} />} />
              <Bar dataKey={dataKey} fill="var(--vireo)" radius={[4, 4, 0, 0]} maxBarSize={34} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
}

function PropertyCard({ p, onEdit, isAdmin }: { p: PropertyDash; onEdit: () => void; isAdmin: boolean }) {
  const f = p.funnel;
  const partnersTotal = STAGE_ORDER.reduce((s, k) => s + (p.partners[k] ?? 0), 0);
  const steps: [string, number][] = [["Sent", f.sent], ["Replies", f.replies], ["Meetings", f.meetings], ["Conversions", f.conversions]];
  const maxStep = Math.max(1, ...steps.map((s) => s[1]));
  return (
    <Card className="rise flex flex-col p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-faint" title={TRACKS[p.track]}>Track {p.track}</div>
          <h3 className="mt-1 line-clamp-2 font-serif text-lg font-semibold leading-snug">{p.name}</h3>
        </div>
        <div className="flex items-center gap-1">
          {p.playbook ? <Badge tone={p.playbook.approved_by ? "green" : statusTone(p.playbook.lint_status)}>{p.playbook.approved_by ? "approved" : p.playbook.lint_status === "blocked" ? "blocked" : "draft plan"}</Badge> : <Badge>no plan</Badge>}
          {isAdmin && <button onClick={onEdit} className="rounded-md p-1 text-faint hover:bg-surface-3 hover:text-ink" aria-label={`Edit target for ${p.name}`}><Pencil size={13} /></button>}
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <span className="num text-[22px] text-ink">{usd(p.arr_run_rate_usd, true)}</span>
          <span className="text-xs text-muted">of {usd(p.arr_target_usd, true)} ARR target</span>
        </div>
        <div className="mt-2"><Progress value={p.arr_run_rate_usd} max={p.arr_target_usd} /></div>
        <div className="mt-1.5 text-[11px] text-faint">{pct(p.arr_run_rate_usd, p.arr_target_usd)} of target</div>
      </div>

      <div className="mt-5 space-y-1.5">
        {steps.map(([l, v]) => (
          <div key={l} className="grid grid-cols-[76px_1fr_52px] items-center gap-2 text-xs">
            <span className="text-muted">{l}</span>
            <div className="h-2 rounded-sm bg-surface-3"><div className="h-2 rounded-sm bg-vireo/70" style={{ width: `${(v / maxStep) * 100}%` }} /></div>
            <span className="num text-right text-ink">{num(v, true)}</span>
          </div>
        ))}
      </div>

      <div className="mt-5">
        <div className="mb-1.5 flex justify-between text-xs"><span className="text-muted">Partner pipeline</span><span className="num text-ink">{partnersTotal}</span></div>
        <div className="flex h-2.5 gap-[2px] overflow-hidden rounded-sm" title={STAGE_ORDER.map((s) => `${label(s)}: ${p.partners[s] ?? 0}`).join(" · ")}>
          {partnersTotal === 0 ? <div className="h-full w-full bg-surface-3" /> : STAGE_ORDER.map((s, i) => (p.partners[s] ?? 0) > 0 && (
            <div key={s} className="h-full" style={{ flex: p.partners[s], background: "var(--vireo)", opacity: Number(STAGE_SHADE[i]) }} />
          ))}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-faint">
          {STAGE_ORDER.map((s, i) => <span key={s} className="inline-flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-[2px]" style={{ background: "var(--vireo)", opacity: Number(STAGE_SHADE[i]) }} />{label(s)} {p.partners[s] ?? 0}</span>)}
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2 text-xs">
        <span className="inline-flex items-center gap-1.5 text-muted"><FileSignature size={13} className="text-vireo" />Agreements</span>
        <span><span className="num text-ink">{p.agreements?.signed ?? 0}</span> <span className="text-muted">signed · {(p.agreements?.negotiating ?? 0) + (p.agreements?.proposed ?? 0)} in talks</span></span>
      </div>
      <Link to={`/outreach?property=${p.property_id}&tab=all`} className="mb-4 mt-1.5 flex justify-between px-3 text-[11px] text-faint hover:text-ink">
        <span>Partner emails: {p.outreach?.sent ?? 0} sent · {p.outreach?.replied ?? 0} replied</span><span>{p.outreach?.drafts ?? 0} to approve</span></Link>
      <div className="mt-auto grid grid-cols-2 gap-3 border-t border-line pt-3.5 text-xs">
        <Link to={`/campaigns?property=${p.property_id}`} className="group flex items-center justify-between text-muted hover:text-ink">
          <span><span className="num text-ink">{p.campaigns.active}</span> active / {p.campaigns.total} campaigns</span><ArrowUpRight size={13} className="opacity-0 group-hover:opacity-100" /></Link>
        <Link to={`/tasks?property=${p.property_id}`} className="group flex items-center justify-between text-muted hover:text-ink">
          <span><span className="num text-ink">{p.tasks.done}</span>/{p.tasks.total} tasks done</span><ArrowUpRight size={13} className="opacity-0 group-hover:opacity-100" /></Link>
      </div>
    </Card>
  );
}

export default function Dashboard() {
  const { user, isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useLoad(api.dashboard);
  const [edit, setEdit] = useState<PropertyDash | null>(null);
  const [target, setTarget] = useState({ arr: 0, conv: 0 });
  const [saving, setSaving] = useState(false);

  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorNote error={error} />;

  const P = data.properties;
  const sum = (f: (p: PropertyDash) => number) => P.reduce((s, p) => s + f(p), 0);
  const arr = sum((p) => p.arr_run_rate_usd), goal = sum((p) => p.arr_target_usd);
  const agreementsSigned = sum((p) => p.agreements?.signed ?? 0);
  const negotiating = sum((p) => (p.agreements?.negotiating ?? 0) + (p.agreements?.proposed ?? 0));
  const contacted = sum((p) => p.outreach?.sent ?? 0), replied = sum((p) => p.outreach?.replied ?? 0);
  const partners = sum((p) => Object.entries(p.partners).filter(([k]) => k !== "declined").reduce((s, [, v]) => s + v, 0));
  const tDone = sum((p) => p.tasks.done), tAll = sum((p) => p.tasks.total);

  const openEdit = (p: PropertyDash) => { setEdit(p); setTarget({ arr: p.arr_target_usd, conv: p.monthly_conversions_target }); };
  const saveTarget = async () => {
    if (!edit) return;
    setSaving(true);
    try { await api.setTarget(edit.property_id, { arr_target_usd: target.arr, monthly_conversions_target: target.conv }); toast("Target updated"); setEdit(null); reload(); }
    catch (e) { toast(String((e as Error).message), "err"); } finally { setSaving(false); }
  };

  return (
    <>
      <PageHeader eyebrow="Portfolio" title={`Good ${new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}, ${user?.name.split(" ")[0]}`}
        sub="Every property against its ARR target, with the campaigns, partners and tasks moving it."
        actions={<><Link to="/campaigns?new=1"><Button variant="primary" icon={<Megaphone size={15} />}>New campaign</Button></Link></>} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="ARR run-rate" value={usd(arr, true)} sub={<>{pct(arr, goal)} of {usd(goal, true)} portfolio target</>} icon={<TrendingUp size={14} />} />
        <Stat label="Revenue logged" value={usd(sum((p) => p.revenue_to_date_usd), true)} sub="All time, all campaigns" icon={<Target size={14} />} tone="sky" />
        <Stat label="Active campaigns" value={sum((p) => p.campaigns.active)} sub={`${sum((p) => p.campaigns.total)} total`} icon={<Megaphone size={14} />} tone="amber" />
        <Stat label="Agreements signed" value={agreementsSigned} sub={`${negotiating} in negotiation · ${partners} partners in pipeline`} icon={<Handshake size={14} />} tone="violet" />
        <Stat label="Partner emails" value={contacted} sub={`${replied} replied${contacted ? ` · ${((replied / contacted) * 100).toFixed(0)}%` : ""}`} icon={<Send size={14} />} tone="sky" />
        <Stat label="Tasks done" value={pct(tDone, tAll)} sub={`${tDone} of ${tAll} in the current plan`} icon={<CheckCircle2 size={14} />} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <WeeklyChart data={data.weekly} dataKey="revenue_usd" title="Revenue" fmt={(n) => usd(n, true)} />
        <WeeklyChart data={data.weekly} dataKey="meetings" title="Meetings booked" fmt={(n) => num(n)} />
      </div>

      <div className="mb-3 mt-8 flex items-end justify-between">
        <h2 className="font-serif text-xl font-semibold">Properties</h2>
        <span className="text-right text-xs text-muted">ARR run-rate = last 30 days of logged revenue × 12<br />{data.latest_run ? <>Plan from run <span className="font-mono">{data.latest_run}</span></> : "No agent run yet"}</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {P.map((p) => <PropertyCard key={p.property_id} p={p} isAdmin={isAdmin} onEdit={() => openEdit(p)} />)}
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="My open tasks" sub="Assigned to you" action={<Link to="/tasks?mine=1" className="text-xs text-vireo hover:underline">All tasks</Link>} />
          <ul className="divide-y divide-line">
            {data.my_open_tasks.length === 0 && <li className="px-5 py-8 text-center text-sm text-muted">Nothing assigned to you right now.</li>}
            {data.my_open_tasks.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                <Badge tone={statusTone(t.priority)}>{t.priority}</Badge>
                <span className="font-mono text-[11px] text-faint">{t.task_id}</span>
                <span className="min-w-0 flex-1 truncate">{t.description}</span>
                <Badge tone={statusTone(t.status)}>{t.status}</Badge>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Recent partner activity" action={<Link to="/partners" className="text-xs text-vireo hover:underline">Partners</Link>} />
          <ul className="divide-y divide-line">
            {data.recent_interactions.length === 0 && <li className="px-5 py-8 text-center text-sm text-muted">No partner interactions logged yet.</li>}
            {data.recent_interactions.map((i) => (
              <li key={i.id} className="px-5 py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <Link to={`/partners/${i.partner_id}`} className="truncate font-medium hover:text-vireo">{i.partner_name}</Link>
                  <Badge tone={statusTone(i.outcome)}>{i.type}</Badge>
                  <span className="ml-auto shrink-0 text-xs text-faint">{relTime(i.date)}</span>
                </div>
                <div className="mt-0.5 truncate text-xs text-muted">{i.summary}{i.by_name ? ` · ${i.by_name}` : ""}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Target · ${edit?.name ?? ""}`}
        footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" loading={saving} onClick={saveTarget}>Save target</Button></>}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="ARR target (USD)"><Input type="number" min={1} value={target.arr} onChange={(e) => setTarget({ ...target, arr: Number(e.target.value) })} /></Field>
          <Field label="Monthly conversions target"><Input type="number" min={0} value={target.conv} onChange={(e) => setTarget({ ...target, conv: Number(e.target.value) })} /></Field>
        </div>
      </Modal>
    </>
  );
}
