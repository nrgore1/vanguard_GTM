import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Siren, OctagonAlert, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { api, type FailproofProperty, type GateRow, type TripStatus, type TripwireRow } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { Badge, Button, Card, CardHeader, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, Stat, cx, useToast } from "../components/ui";

const TRIP_TONE: Record<TripStatus, string> = { not_yet_due: "gray", green: "green", amber: "amber", tripped: "rose" };
const TRIP_LABEL: Record<TripStatus, string> = { not_yet_due: "Not yet due", green: "Green", amber: "Amber", tripped: "Tripped" };
const GATE_TONE = { open: "gray", passed: "green", failed: "rose" } as const;
const FOCUS_LABEL = { primary: "Founder · primary", founder: "Founder", delegated: "Delegated" } as const;

function RecordReading({ pid, tw, onClose, onSaved }: { pid: string; tw: TripwireRow | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [value, setValue] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!tw) return null;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.recordReading(pid, { tripwire_id: tw.id, value: Number(value), date: date || undefined, note });
      toast(`Recorded ${tw.id}`); onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title={`Record ${tw.id}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={save} disabled={value === "" || Number.isNaN(Number(value))}>Save reading</Button></>}>
      <ErrorNote error={error} />
      <p className="mb-4 text-sm text-muted">{tw.signal}. <span className="text-ink">{tw.schedule}.</span></p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`Value (${tw.unit})`}><Input type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
        <Field label="Reading date" hint="Defaults to today"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Note" className="sm:col-span-2"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function GateRowView({ pid, g, admin, onSaved }: { pid: string; g: GateRow; admin: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const set = async (status: GateRow["status"]) => {
    setBusy(true);
    try {
      const r = await api.setGate(pid, g.id, { status });
      toast(r.walk_away_if ? `Walk-away condition: ${r.walk_away_if}` : `${g.id} ${status}`);
      onSaved();
    } catch (e) { toast(String(e)); } finally { setBusy(false); }
  };
  const Icon = g.status === "passed" ? CheckCircle2 : g.status === "failed" ? XCircle : CircleDashed;
  return (
    <li className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-3 last:border-0">
      <Icon size={18} className={cx("mt-0.5 shrink-0", g.status === "passed" ? "text-vireo" : g.status === "failed" ? "text-rose" : "text-muted")} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{g.id} · {g.name}</span>
          <Badge tone={GATE_TONE[g.status]}>{g.status}</Badge>
          {g.overdue && <Badge tone="amber">overdue</Badge>}
          <span className="font-mono text-[11px] text-muted">due W{g.deadline_week} · {g.deadline}</span>
        </div>
        <p className="mt-1 text-[13px] text-ink">{g.verify}</p>
        <p className="mt-0.5 text-xs text-muted">Walk away if: {g.walk_away_if}</p>
        {g.blocks.length > 0 && <p className="mt-0.5 text-xs text-muted">While open, blocks: {g.blocks.join(", ")}</p>}
      </div>
      {admin && (
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" loading={busy} disabled={g.status === "passed"} onClick={() => set("passed")}>Pass</Button>
          <Button size="sm" variant="danger" disabled={busy || g.status === "failed"} onClick={() => set("failed")}>Fail</Button>
          <Button size="sm" variant="ghost" disabled={busy || g.status === "open"} onClick={() => set("open")}>Reopen</Button>
        </div>
      )}
    </li>
  );
}

function PropertyView({ p, admin, reload }: { p: FailproofProperty; admin: boolean; reload: () => void }) {
  const [recording, setRecording] = useState<TripwireRow | null>(null);
  return (
    <>
      {p.halt && (
        <div role="alert" className="mb-4 flex items-start gap-3 rounded-xl border border-rose/40 bg-rose-soft px-4 py-3 text-sm text-rose">
          <OctagonAlert size={18} className="mt-0.5 shrink-0" />
          <div><strong>Halt.</strong> {p.tripped} tripwires have tripped. Stop, do not adjust the plan, and rerun the walk-away gates.</div>
        </div>
      )}
      {p.focus_issues.map((f) => (
        <div key={f} className="mb-4 rounded-xl border border-amber/40 bg-amber-soft px-4 py-3 text-sm text-amber">{f}</div>
      ))}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Tripped" value={p.tripped} tone={p.tripped ? "rose" : undefined} />
        <Stat label="Amber (no reading)" value={p.amber} tone={p.amber ? "amber" : undefined} />
        <Stat label="Gates passed" value={`${p.gates_passed} / ${p.gates.length}`} />
        <Stat label="Gates overdue" value={p.gates_overdue} tone={p.gates_overdue ? "amber" : undefined} />
      </div>
      <Card className="mb-5">
        <CardHeader title="Tripwires" sub="Missing evidence is never green: a due check with no reading shows amber." />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-[11px] uppercase tracking-wide text-muted">
              <tr className="border-b border-line">
                <th className="px-5 py-2 font-medium">ID</th><th className="px-3 py-2 font-medium">Signal</th>
                <th className="px-3 py-2 font-medium">Schedule</th><th className="px-3 py-2 font-medium">Latest</th>
                <th className="px-3 py-2 font-medium">Next check</th><th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">If tripped</th><th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody>
              {p.tripwires.map((t) => (
                <tr key={t.id} className="border-b border-line align-top last:border-0">
                  <td className="px-5 py-2.5 font-mono text-xs">{t.id}<div className="text-[10px] text-muted">{t.failure_mode} · {t.basis}</div></td>
                  <td className="px-3 py-2.5">{t.signal}</td>
                  <td className="px-3 py-2.5 text-xs text-muted">{t.schedule}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">{t.latest_value === null ? <span className="text-muted">—</span> : <>{t.latest_value} <span className="text-xs text-muted">{t.unit}</span><div className="text-[11px] text-muted">{t.latest_date}</div></>}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap font-mono text-xs">{t.next_check ?? "—"}</td>
                  <td className="px-3 py-2.5"><Badge tone={TRIP_TONE[t.status]}>{TRIP_LABEL[t.status]}</Badge></td>
                  <td className="px-3 py-2.5 text-xs text-muted">{t.action}</td>
                  <td className="px-5 py-2.5 text-right"><Button size="sm" onClick={() => setRecording(t)}>Record</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="mb-5">
        <CardHeader title="Readiness gates" sub={admin ? "Only admins pass or fail a gate. Open gates stop the agent from planning the tasks they block." : "Only admins pass or fail a gate."} />
        <ul>{p.gates.map((g) => <GateRowView key={g.id} pid={p.property_id} g={g} admin={admin} onSaved={reload} />)}</ul>
      </Card>
      <Card>
        <CardHeader title="Failure modes on file" sub="From the premortem. Each tripwire points at one of these." />
        <ul>
          {p.failure_modes.map((f) => (
            <li key={f.id} className="border-b border-line px-5 py-3 last:border-0">
              <div className="text-sm font-medium">{f.id} · {f.name}</div>
              <p className="mt-0.5 text-[13px]">{f.cause}</p>
              <p className="mt-0.5 text-xs text-muted">Assumption: {f.assumption} · First warning: {f.first_warning}</p>
            </li>
          ))}
        </ul>
      </Card>
      <RecordReading pid={p.property_id} tw={recording} onClose={() => setRecording(null)} onSaved={reload} />
    </>
  );
}

export default function Tripwires() {
  const { isAdmin, propName } = useAuth();
  const [sp, setSp] = useSearchParams();
  const [asOf, setAsOf] = useState("");
  const { data, error, loading, reload } = useLoad(() => api.failproof({ as_of: asOf || undefined }), [asOf]);
  const props = data?.properties ?? [];
  const selected = sp.get("property") ?? props.find((p) => p.focus === "primary")?.property_id ?? props[0]?.property_id ?? "";
  const current = useMemo(() => props.find((p) => p.property_id === selected), [props, selected]);
  return (
    <div>
      <PageHeader eyebrow="Fail-proof" title="Tripwires & gates"
        sub={data ? `Week ${data.week} of the 26-week program (started ${data.program_start}). Checks run on Fridays.` : "Measurable signals that a failure mode is starting, and the gates that must pass before launch."}
        actions={<>
          <Field label="Property"><Select value={selected} onChange={(e) => { const n = new URLSearchParams(sp); n.set("property", e.target.value); setSp(n, { replace: true }); }}>
            {props.map((p) => <option key={p.property_id} value={p.property_id}>{propName(p.property_id)} — {FOCUS_LABEL[p.focus]}{p.tripped ? ` · ${p.tripped} tripped` : ""}</option>)}
          </Select></Field>
          <Field label="As of"><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        </>} />
      <ErrorNote error={error} />
      {loading && !data ? <Spinner /> : current ? (
        <>
          <Card className="mb-5 px-5 py-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <Siren size={14} /> Owner: <span className="text-ink">{current.owner ?? "UNASSIGNED"}</span> · {FOCUS_LABEL[current.focus]}
            </div>
            <p className="mt-2 font-serif text-[17px] leading-snug text-ink">{current.one_sentence}</p>
          </Card>
          <PropertyView p={current} admin={isAdmin} reload={reload} />
        </>
      ) : null}
    </div>
  );
}
