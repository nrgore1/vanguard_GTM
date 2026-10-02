import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Handshake, Plus, CalendarClock, MessageSquare, Sparkles, LayoutGrid, ListOrdered, FileSignature, Microscope, Linkedin } from "lucide-react";
import { ImportLinkedIn } from "../components/LinkedInPanels";
import { api, type Partner, type PartnerStage } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, PARTNER_KINDS, relTime, shortDate, STAGES } from "../lib/format";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, Textarea, cx, kindTone, statusTone, useToast } from "../components/ui";

export const KIND_HELP: Record<string, string> = {
  design_partner: "Early customer co-building a scoped pilot",
  co_sell: "B2B partner selling alongside you",
  distribution: "Channel that reaches your ICP",
  referral_affiliate: "Refers customers for a fee",
  integration: "Product integration partner",
  investor: "Investor or fundraising contact",
};

export function PartnerForm({ open, onClose, initial, onSaved }: { open: boolean; onClose: () => void; initial?: Partial<Partner>; onSaved: (id: number) => void }) {
  const { properties, users } = useAuth();
  const toast = useToast();
  const blank: Partial<Partner> = { property_id: properties[0]?.id, kind: "design_partner", stage: "identified" };
  const [f, setF] = useState<Partial<Partner>>(initial ?? blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) { setF(initial ?? blank); setError(null); } }, [open]);
  const set = (k: keyof Partner) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value || null });
  const save = async () => {
    setBusy(true); setError(null);
    const body: Record<string, unknown> = { ...f };
    for (const k of ["id", "owner_name", "interactions", "last_contact", "created_by", "updated_at", "source_run_id", "created_at", "connections", "campaign_id", "campaign_name", "outreach", "targets"]) delete body[k];
    if (body.owner_id) body.owner_id = Number(body.owner_id);
    try {
      const id = initial?.id ? (await api.updatePartner(initial.id, body), initial.id) : (await api.createPartner(body)).id;
      toast(initial?.id ? "Partner updated" : "Partner added"); onSaved(id);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} wide title={initial?.id ? "Edit partner" : "Add partner"}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save} disabled={!f.name}>{initial?.id ? "Save" : "Add partner"}</Button></>}>
      <ErrorNote error={error} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Organisation" className="sm:col-span-2"><Input value={f.name ?? ""} onChange={set("name")} /></Field>
        <Field label="Property"><Select value={f.property_id ?? ""} onChange={set("property_id")}>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Field label="Partnership type" hint={KIND_HELP[f.kind ?? ""]}><Select value={f.kind ?? ""} onChange={set("kind")}>{PARTNER_KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
        <Field label="Stage"><Select value={f.stage ?? "identified"} onChange={set("stage")}>{STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Owner"><Select value={f.owner_id ?? ""} onChange={set("owner_id")}><option value="">Me</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select></Field>
        <Field label="Contact name"><Input value={f.contact_name ?? ""} onChange={set("contact_name")} /></Field>
        <Field label="Contact email"><Input type="email" value={f.contact_email ?? ""} onChange={set("contact_email")} /></Field>
        <Field label="Value-sharing model"><Input value={f.value_sharing_model ?? ""} onChange={set("value_sharing_model")} placeholder="revenue share, referral fee…" /></Field>
        <Field label="Next step date"><Input type="date" value={f.next_step_date ?? ""} onChange={set("next_step_date")} /></Field>
        <Field label="Next step" className="sm:col-span-2"><Input value={f.next_step ?? ""} onChange={set("next_step")} /></Field>
        <Field label="Why both sides win" className="sm:col-span-2"><Textarea value={f.mutual_value ?? ""} onChange={set("mutual_value")} /></Field>
      </div>
    </Modal>
  );
}

function RecommendModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (pid: string) => void }) {
  const { properties } = useAuth();
  const toast = useToast();
  const [pid, setPid] = useState("jodibana");
  const [mode, setMode] = useState<"offline" | "model">("offline");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.recommendPartners>> | null>(null);
  useEffect(() => { if (open) { setResult(null); setError(null); } }, [open]);
  const go = async () => {
    setBusy(true); setError(null);
    try { const r = await api.recommendPartners({ property_id: pid, mode }); setResult(r); toast(`${r.recommendations.length} partners recommended`); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} wide title="Recommend partners"
      footer={result ? <><Button variant="ghost" onClick={onClose}>Close</Button><Link to="/outreach"><Button>Review drafts</Button></Link>
        <Button variant="primary" onClick={() => { onDone(pid); onClose(); }}>Show partners</Button></>
        : <><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Sparkles size={15} />} loading={busy} onClick={go}>Recommend</Button></>}>
      <ErrorNote error={error} />
      {!result ? (
        <div className="space-y-4">
          <p className="text-sm text-muted">The partnerships expert picks design partners, co-selling partners and channels for a property, scores each one (fit, reach, access, strategic value, speed) and drafts a 3-step email sequence. Nothing is sent until an admin approves.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Property"><Select value={pid} onChange={(e) => setPid(e.target.value)}>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            <Field label="Source" hint={mode === "offline" ? "Uses the curated partner playbook - instant, $0." : "Your local model names specific organisations ($0); Claude only as a capped fallback."}>
              <Select value={mode} onChange={(e) => setMode(e.target.value as "offline" | "model")}>
                <option value="offline">Expert playbook ($0, instant)</option><option value="model">Agent names organisations (local model)</option></Select></Field>
          </div>
        </div>
      ) : (
        <div>
          <p className="mb-3 text-sm text-muted">{result.partners} new partners · {result.updated} refreshed · {result.messages} draft emails</p>
          <ol className="divide-y divide-line rounded-lg border border-line">
            {result.recommendations.map((r) => (
              <li key={r.rank} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="num w-5 text-right text-faint">{r.rank}</span>
                <Badge tone={statusTone(r.priority)}>{r.priority}</Badge><span className="num w-8 text-muted">{r.score}</span>
                <span className="min-w-0 flex-1 truncate">{r.name}</span><Badge tone={kindTone(r.kind)}>{label(r.kind)}</Badge>
              </li>))}
          </ol>
        </div>
      )}
    </Modal>
  );
}

const AGREEMENT_TONE: Record<string, string> = { none: "gray", proposed: "amber", negotiating: "sky", signed: "green", declined: "rose" };

export default function Partners() {
  const { properties, propName } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const property = sp.get("property") ?? "", kind = sp.get("kind") ?? "";
  const { data, error, loading, reload, setData } = useLoad(() => api.partners({ property_id: property || undefined, kind: kind || undefined }), [property, kind]);
  const [adding, setAdding] = useState(false);
  const [recommending, setRecommending] = useState(false);
  const { isAdmin } = useAuth();
  const view = sp.get("view") ?? "priority";
  const [dragOver, setDragOver] = useState<string | null>(null);
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };

  const move = async (p: Partner, stage: PartnerStage) => {
    if (p.stage === stage) return;
    setData((d) => d?.map((x) => (x.id === p.id ? { ...x, stage } : x)) ?? null);  // optimistic
    try { await api.updatePartner(p.id, { stage }); toast(`${p.name} → ${label(stage)}`); }
    catch (e) { toast(String((e as Error).message), "err"); reload(); }
  };

  const [importing, setImporting] = useState(false);
  const [linkedIn, setLinkedIn] = useState(false);
  const importResearch = async () => {
    setImporting(true);
    try {
      const r = await api.importResearch();
      const added = Object.values(r.properties).reduce((n, s) => n + s.created, 0);
      const refreshed = Object.values(r.properties).reduce((n, s) => n + s.updated, 0);
      const inv = r.investors ? ` · investors: ${r.investors.created} added, ${r.investors.updated} refreshed` : "";
      toast(`${added} researched partners added${refreshed ? `, ${refreshed} refreshed` : ""} - drafts await approval${inv}`, r.errors.length ? "err" : "ok");
      reload();
    } catch (e) { toast(String((e as Error).message), "err"); } finally { setImporting(false); }
  };

  const byStage = (s: string) => (data ?? []).filter((p) => p.stage === s);

  return (
    <>
      <PageHeader eyebrow="Relationships" title="Partners" sub="Design partners, co-selling partners and distribution channels. Drag a card to move it through the pipeline; open it to log calls and emails."
        actions={<>
          <Button icon={<Linkedin size={15} />} onClick={() => setLinkedIn(true)}>Import LinkedIn connections</Button>
          {isAdmin && <Button icon={<Microscope size={15} />} loading={importing} onClick={importResearch}>Load researched partners</Button>}
          {isAdmin && <Button icon={<Sparkles size={15} />} onClick={() => setRecommending(true)}>Recommend partners</Button>}
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setAdding(true)}>Add partner</Button></>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={property} onChange={(e) => setFilter("property", e.target.value)} className="w-auto" aria-label="Filter by property">
          <option value="">All properties</option>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        <Select value={kind} onChange={(e) => setFilter("kind", e.target.value)} className="w-auto" aria-label="Filter by type">
          <option value="">All partnership types</option>{PARTNER_KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</Select>
        <div className="ml-auto flex gap-1 rounded-lg border border-line bg-surface-2 p-1" role="tablist" aria-label="View">
          {([["priority", "Priority list", ListOrdered], ["board", "Pipeline board", LayoutGrid]] as const).map(([v, l, I]) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setFilter("view", v === "priority" ? "" : v)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs ${view === v ? "bg-surface-3 text-ink" : "text-muted hover:text-ink"}`}><I size={13} />{l}</button>))}
        </div>
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Spinner /> : (data ?? []).length === 0 ? (
        <Card><Empty icon={<Handshake size={22} />} title="No partners yet" body="Add one, or ask an admin to import the agent's partnership playbook."
          action={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setAdding(true)}>Add partner</Button>} /></Card>
      ) : view === "priority" ? (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[1040px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {["#", "Priority", "Partner", "Type", "Property", "Stage", "Agreement", "Contact", "Known", "Last touch"].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {(data ?? []).map((p, i) => (
                  <tr key={p.id} onClick={() => nav(`/partners/${p.id}`)} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-surface-2">
                    <td className="num px-3 py-3 text-faint">{i + 1}</td>
                    <td className="whitespace-nowrap px-3 py-3">{p.priority ? <><Badge tone={statusTone(p.priority)}>{p.priority}</Badge> <span className="num text-xs text-muted">{p.priority_score}</span></> : <span className="text-faint">–</span>}</td>
                    <td className="max-w-[320px] px-3 py-3"><Link to={`/partners/${p.id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:text-vireo">{p.name}</Link>
                      <div className="mt-0.5 flex flex-wrap gap-1">{p.is_segment ? <Badge tone="amber">segment - add named targets</Badge> : null}
                        {p.source?.startsWith("agent") && <Badge tone="violet">agent pick</Badge>}
                        {p.source === "research" && <Badge tone="sky">researched</Badge>}</div></td>
                    <td className="px-3 py-3"><Badge tone={kindTone(p.kind)}>{label(p.kind)}</Badge></td>
                    <td className="whitespace-nowrap px-3 py-3 text-muted">{propName(p.property_id)}</td>
                    <td className="px-3 py-3"><Badge tone={statusTone(p.stage)}>{label(p.stage)}</Badge></td>
                    <td className="px-3 py-3">{p.agreement_status && p.agreement_status !== "none" ? <Badge tone={AGREEMENT_TONE[p.agreement_status]}><FileSignature size={11} />{p.agreement_status}</Badge> : <span className="text-faint">–</span>}</td>
                    <td className="px-3 py-3 text-xs text-muted">{p.contact_email ?? (p.is_segment ? "" : <span className="text-amber">needed</span>)}</td>
                    <td className="px-3 py-3">{typeof p.connections === "number" && p.connections > 0
                      ? <Badge tone="sky"><Linkedin size={11} />{p.connections}</Badge> : <span className="text-faint">–</span>}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-faint">{relTime(p.last_contact)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4 pb-2 scroll-thin sm:-mx-8 sm:px-8">
          <div className="grid min-w-[1180px] grid-cols-6 gap-3">
            {STAGES.map((s) => (
              <section key={s} aria-label={label(s)}
                onDragOver={(e) => { e.preventDefault(); setDragOver(s); }} onDragLeave={() => setDragOver(null)}
                onDrop={(e) => { setDragOver(null); const p = data?.find((x) => x.id === Number(e.dataTransfer.getData("text/plain"))); if (p) move(p, s as PartnerStage); }}
                className={cx("flex min-h-[420px] flex-col rounded-xl border bg-surface/60 p-2 transition-colors", dragOver === s ? "border-vireo bg-vireo-soft" : "border-line")}>
                <div className="flex items-center justify-between px-2 pb-2 pt-1">
                  <span className={cx("text-xs font-semibold uppercase tracking-wider", s === "declined" ? "text-faint" : s === "signed" ? "text-vireo" : "text-muted")}>{label(s)}</span>
                  <span className="num text-xs text-faint">{byStage(s).length}</span>
                </div>
                <div className="flex flex-col gap-2">
                  {byStage(s).map((p) => (
                    <article key={p.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(p.id))}
                      onClick={() => nav(`/partners/${p.id}`)}
                      className="cursor-pointer rounded-lg border border-line bg-surface p-3 shadow-card transition hover:-translate-y-px hover:border-line-strong">
                      <div className="flex items-start justify-between gap-2">
                        <Link to={`/partners/${p.id}`} onClick={(e) => e.stopPropagation()} className="line-clamp-2 text-[13px] font-medium leading-snug hover:text-vireo">{p.name}</Link>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1"><Badge tone={kindTone(p.kind)}>{label(p.kind)}</Badge>
                        {p.priority && <Badge tone={statusTone(p.priority)}>{p.priority} · {p.priority_score}</Badge>}
                        {p.agreement_status === "signed" && <Badge tone="green"><FileSignature size={11} />signed</Badge>}</div>
                      <div className="mt-2 text-[11px] text-faint">{propName(p.property_id)}</div>
                      <div className="mt-2 flex items-center gap-3 border-t border-line pt-2 text-[11px] text-muted">
                        <span className="inline-flex items-center gap-1"><MessageSquare size={11} />{Number(p.interactions ?? 0)} · {relTime(p.last_contact)}</span>
                        {p.next_step_date && <span className="inline-flex items-center gap-1"><CalendarClock size={11} />{shortDate(p.next_step_date)}</span>}
                      </div>
                      <select aria-label={`Move ${p.name}`} value={p.stage} onClick={(e) => e.stopPropagation()} onChange={(e) => move(p, e.target.value as PartnerStage)}
                        className="mt-2 w-full rounded-md border border-line bg-surface-2 px-1.5 py-1 text-[11px] text-muted">
                        {STAGES.map((x) => <option key={x} value={x}>Move to: {label(x)}</option>)}
                      </select>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}
      <RecommendModal open={recommending} onClose={() => setRecommending(false)} onDone={(pid) => { setFilter("property", pid); reload(); }} />
      <PartnerForm open={adding} onClose={() => setAdding(false)} initial={property ? { property_id: property, kind: "design_partner", stage: "identified" } : undefined}
        onSaved={(id) => nav(`/partners/${id}`)} />
      <ImportLinkedIn open={linkedIn} onClose={() => setLinkedIn(false)} onDone={reload} />
    </>
  );
}
