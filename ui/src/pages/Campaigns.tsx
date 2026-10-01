import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Megaphone, Plus, Search } from "lucide-react";
import { api, type Campaign } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { CAMPAIGN_STATUSES, label, num, pct, relTime, usd } from "../lib/format";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, Textarea, statusTone, useToast } from "../components/ui";

const KINDS = ["email", "social", "partner", "event", "content", "paid"];
const GOALS = ["meetings", "signups", "conversions", "replies", "revenue_usd", "sent"];

export function CampaignForm({ open, onClose, initial, onSaved }: {
  open: boolean; onClose: () => void; initial?: Partial<Campaign>; onSaved: (id: number) => void;
}) {
  const { properties, users } = useAuth();
  const toast = useToast();
  const blank: Partial<Campaign> = { property_id: properties[0]?.id, kind: "email", status: "draft", budget_usd: 0, goal_metric: "meetings" };
  const [f, setF] = useState<Partial<Campaign>>(initial ?? blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) { setF(initial ?? blank); setError(null); } }, [open]);
  const set = (k: keyof Campaign) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : (e.target.value || null) });

  const save = async () => {
    setBusy(true); setError(null);
    const body = { ...f };
    for (const k of ["id", "owner_name", "results", "sent", "replies", "meetings", "signups", "conversions", "revenue_usd", "spend_usd", "updated_at", "created_by", "source_run_id"] as const) delete (body as Record<string, unknown>)[k];
    if (body.owner_id !== undefined && body.owner_id !== null) body.owner_id = Number(body.owner_id);
    try {
      const id = initial?.id ? (await api.updateCampaign(initial.id, body), initial.id) : (await api.createCampaign(body)).id;
      toast(initial?.id ? "Campaign updated" : "Campaign created");
      onSaved(id);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} wide title={initial?.id ? "Edit campaign" : "New campaign"}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save} disabled={!f.name || !f.property_id}>{initial?.id ? "Save changes" : "Create campaign"}</Button></>}>
      <ErrorNote error={error} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" className="sm:col-span-2"><Input value={f.name ?? ""} onChange={set("name")} placeholder="e.g. Treasury heads — Canton walkthrough" /></Field>
        <Field label="Property"><Select value={f.property_id ?? ""} onChange={set("property_id")}>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Field label="Status"><Select value={f.status ?? "draft"} onChange={set("status")}>{CAMPAIGN_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Type"><Select value={f.kind ?? "email"} onChange={set("kind")}>{KINDS.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Channel" hint="LinkedIn, Instagram, Smartlead, event name…"><Input value={f.channel ?? ""} onChange={set("channel")} /></Field>
        <Field label="Start date"><Input type="date" value={f.start_date ?? ""} onChange={set("start_date")} /></Field>
        <Field label="End date"><Input type="date" value={f.end_date ?? ""} onChange={set("end_date")} /></Field>
        <Field label="Goal metric"><Select value={f.goal_metric ?? ""} onChange={set("goal_metric")}>{GOALS.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Goal value"><Input type="number" min={0} value={f.goal_value ?? ""} onChange={set("goal_value")} /></Field>
        <Field label="Budget (USD)"><Input type="number" min={0} value={f.budget_usd ?? 0} onChange={set("budget_usd")} /></Field>
        <Field label="Owner"><Select value={f.owner_id ?? ""} onChange={set("owner_id")}><option value="">Me</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select></Field>
        <Field label="Description / audience" className="sm:col-span-2"><Textarea value={f.description ?? ""} onChange={set("description")} placeholder="Who it targets, trigger, offer…" /></Field>
      </div>
    </Modal>
  );
}

export default function Campaigns() {
  const { properties, propName } = useAuth();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const property = sp.get("property") ?? "", status = sp.get("status") ?? "";
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(sp.get("new") === "1");
  const { data, error, loading } = useLoad(() => api.campaigns({ property_id: property || undefined, status: status || undefined }), [property, status]);
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); n.delete("new"); setSp(n, { replace: true }); };
  const rows = useMemo(() => (data ?? []).filter((c) => !q || c.name.toLowerCase().includes(q.toLowerCase())), [data, q]);

  return (
    <>
      <PageHeader eyebrow="Execution" title="Campaigns" sub="Create, run and measure outbound, social, partner and event campaigns for every property."
        actions={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>New campaign</Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input placeholder="Search campaigns" value={q} onChange={(e) => setQ(e.target.value)} className="w-full pl-9" aria-label="Search campaigns" /></div>
        <Select value={property} onChange={(e) => setFilter("property", e.target.value)} className="w-auto" aria-label="Filter by property">
          <option value="">All properties</option>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        <div className="flex gap-1 rounded-lg border border-line bg-surface-2 p-1" role="tablist" aria-label="Status">
          {["", ...CAMPAIGN_STATUSES].map((s) => (
            <button key={s || "all"} role="tab" aria-selected={status === s} onClick={() => setFilter("status", s)}
              className={`rounded-md px-2.5 py-1 text-xs ${status === s ? "bg-surface-3 text-ink" : "text-muted hover:text-ink"}`}>{s ? label(s) : "All"}</button>
          ))}
        </div>
      </div>
      <ErrorNote error={error} />
      <Card className="overflow-hidden">
        {loading && !data ? <Spinner /> : rows.length === 0 ? (
          <Empty icon={<Megaphone size={22} />} title="No campaigns yet" body="Create one, or ask an admin to import the agent's playbooks as draft campaigns."
            action={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>New campaign</Button>} />
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[960px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {["Campaign", "Property", "Status", "Partners", "Sent", "Replies", "Meetings", "Conv.", "Revenue", "Owner", "Updated"].map((h, i) =>
                  <th key={h} className={`px-4 py-2.5 font-medium ${i >= 3 && i <= 8 ? "text-right" : ""}`}>{h}</th>)}
              </tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} onClick={() => nav(`/campaigns/${c.id}`)} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2">
                    <td className="max-w-[300px] px-4 py-3"><Link to={`/campaigns/${c.id}`} onClick={(e) => e.stopPropagation()} className="block truncate font-medium hover:text-vireo">{c.name}</Link>
                      <span className="text-xs text-faint">{label(c.kind)}{c.channel ? ` · ${c.channel}` : ""}</span></td>
                    <td className="px-4 py-3 text-muted">{propName(c.property_id)}</td>
                    <td className="px-4 py-3"><Badge tone={statusTone(c.status)}>{label(c.status)}</Badge></td>
                    <td className="num px-4 py-3 text-right">{num(c.outreach_summary?.targets ?? 0)}
                      {c.outreach_summary?.social_touches ? <div className="text-[11px] text-faint">{c.outreach_summary.social_touches} LinkedIn/X</div> : null}</td>
                    <td className="num px-4 py-3 text-right">{num(c.sent, true)}</td>
                    <td className="num px-4 py-3 text-right">{num(c.replies)}<span className="ml-1 text-[11px] text-faint">{c.sent ? pct(c.replies ?? 0, c.sent) : ""}</span></td>
                    <td className="num px-4 py-3 text-right">{num(c.meetings)}</td>
                    <td className="num px-4 py-3 text-right">{num(c.conversions)}</td>
                    <td className="num px-4 py-3 text-right">{usd(c.revenue_usd, true)}</td>
                    <td className="px-4 py-3 text-muted">{c.owner_name ?? "—"}</td>
                    <td className="px-4 py-3 text-xs text-faint">{relTime(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <CampaignForm open={creating} onClose={() => setCreating(false)} initial={property ? { property_id: property, kind: "email", status: "draft", budget_usd: 0, goal_metric: "meetings" } : undefined}
        onSaved={(id) => nav(`/campaigns/${id}`)} />
    </>
  );
}
