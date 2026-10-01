import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { UserPlus, X, Send, Users } from "lucide-react";
import { api, type CampaignOutreach, type Partner } from "../lib/api";
import { useLoad } from "../lib/auth";
import { label, shortDate } from "../lib/format";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, Input, Modal, Spinner, cx, statusTone, useToast } from "./ui";

const STAGE_TONE: Record<string, string> = {
  identified: "gray", contacted: "sky", in_conversation: "violet", pilot: "amber", signed: "green", declined: "rose",
};

/** Partners in a campaign: funnel, send queue and per-partner progress. Numbers come straight from outreach. */
export function CampaignOutreachCard({ cid, propertyId, o, onChanged }: { cid: number; propertyId: string; o: CampaignOutreach; onChanged: () => void }) {
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const t = o.totals, q = o.queue;
  const funnel: [string, number][] = [["Partners", t.targets], ["Touched", t.touched], ["Replied", t.replies],
    ["In conversation", t.in_conversation], ["Pilot", t.pilot + t.signed], ["Signed", t.signed]];
  const detach = async (pid: number, name: string) => {
    try { await api.detachPartner(cid, pid); toast(`${name} removed from the campaign`); onChanged(); }
    catch (e) { toast(String((e as Error).message), "err"); }
  };
  return (
    <Card className="mt-4 overflow-hidden">
      <CardHeader title="Partners in this campaign"
        sub="Emails sent by the outreach queue, LinkedIn/X touches, replies and meetings for these partners count here automatically."
        action={<div className="flex gap-2">
          <Link to={`/outreach?campaign=${cid}&tab=draft`}><Button size="sm" icon={<Send size={13} />}>Open in Outreach</Button></Link>
          <Button size="sm" variant="primary" icon={<UserPlus size={13} />} onClick={() => setAdding(true)}>Add partners</Button>
        </div>} />
      {o.partners.length === 0 ? (
        <Empty icon={<Users size={22} />} title="No partners attached yet"
          body="Add the partners this campaign is working. Their approved emails, LinkedIn/X touches, replies and meetings will then count towards this campaign."
          action={<Button variant="primary" icon={<UserPlus size={15} />} onClick={() => setAdding(true)}>Add partners</Button>} />
      ) : (
        <>
          <ol className="grid grid-cols-3 gap-px border-b border-line bg-line sm:grid-cols-6" aria-label="Campaign funnel">
            {funnel.map(([k, v]) => (
              <li key={k} className="bg-surface px-4 py-3">
                <div className="text-[11px] text-muted">{k}</div>
                <div className="num text-xl font-semibold">{v}</div>
                {k !== "Partners" && t.targets > 0 && <div className="text-[11px] text-faint">{Math.round((v / t.targets) * 100)}%</div>}
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-b border-line px-5 py-2.5 text-xs text-muted">
            <span><b className="text-ink">{t.emails_sent}</b> emails sent</span>
            <span><b className="text-ink">{t.social_touches}</b> LinkedIn/X touches</span>
            <span><b className="text-ink">{t.meetings}</b> meetings</span>
            <span className={q.drafts ? "text-amber" : ""}><b>{q.drafts}</b> drafts awaiting approval</span>
            <span><b className="text-ink">{q.approved}</b> approved and queued{q.next_due ? ` · next due ${q.next_due === "now" ? "now" : shortDate(q.next_due)}` : ""}</span>
            {q.missing_email > 0 && <span className="text-amber"><b>{q.missing_email}</b> need a contact email before anything can send</span>}
          </div>
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[860px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {["Partner", "Stage", "Contact", "Emails", "LinkedIn/X", "Replied", "Last touch", "Next step", ""].map((h, i) =>
                  <th key={i} className="px-3 py-2 font-medium first:pl-5">{h}</th>)}</tr></thead>
              <tbody>{o.partners.map((p) => (
                <tr key={p.id} className="border-b border-line align-top last:border-0">
                  <td className="py-2.5 pl-5 pr-3"><Link to={`/partners/${p.id}`} className="font-medium hover:text-vireo">{p.name}</Link>
                    {p.priority && <div className="mt-0.5"><Badge tone={statusTone(p.priority)}>{p.priority}</Badge></div>}</td>
                  <td className="px-3 py-2.5"><Badge tone={STAGE_TONE[p.stage]}>{label(p.stage)}</Badge></td>
                  <td className="px-3 py-2.5 text-xs">{p.contact_name ?? "—"}<div className={p.contact_email ? "text-muted" : "text-amber"}>{p.contact_email ?? "no email yet"}</div></td>
                  <td className="num px-3 py-2.5">{p.emails_sent}/{p.steps}
                    <div className="text-[11px] text-faint">{p.drafts ? `${p.drafts} to approve` : p.approved ? `${p.approved} queued` : ""}</div></td>
                  <td className="num px-3 py-2.5">{p.social_touches}</td>
                  <td className="px-3 py-2.5">{p.replied ? <Badge tone="green">yes</Badge> : <span className="text-faint">—</span>}</td>
                  <td className="px-3 py-2.5 text-xs text-muted">{shortDate(p.last_touch)}</td>
                  <td className="max-w-[240px] px-3 py-2.5 text-xs"><div className="line-clamp-2">{p.next_step ?? "—"}</div>
                    {p.next_step_date && <div className="text-faint">by {shortDate(p.next_step_date)}</div>}</td>
                  <td className="px-3 py-2.5 text-right"><button onClick={() => detach(p.id, p.name)} className="rounded p-1 text-faint hover:text-rose"
                    aria-label={`Remove ${p.name} from the campaign`} title="Remove from campaign"><X size={14} /></button></td>
                </tr>))}</tbody>
            </table>
          </div>
        </>
      )}
      <AddPartners open={adding} onClose={() => setAdding(false)} cid={cid} propertyId={propertyId} onDone={onChanged} />
    </Card>
  );
}

function AddPartners({ open, onClose, cid, propertyId, onDone }: { open: boolean; onClose: () => void; cid: number; propertyId: string; onDone: () => void }) {
  const toast = useToast();
  const { data, error, loading } = useLoad(() => open ? api.partners({ property_id: propertyId }) : Promise.resolve([] as Partner[]), [open, propertyId]);
  const [sel, setSel] = useState<number[]>([]);
  const [find, setFind] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = useMemo(() => (data ?? []).filter((p) => !p.is_segment && p.campaign_id !== cid && p.stage !== "declined"
    && (!find || p.name.toLowerCase().includes(find.toLowerCase()))), [data, cid, find]);
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.attachPartners(cid, sel);
      toast(`${r.attached.length + r.moved.length} added${r.moved.length ? ` (${r.moved.length} moved from another campaign)` : ""}${r.refused.length ? ` · ${r.refused.length} refused` : ""}`);
      setSel([]); onDone(); onClose();
    } catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Add partners to this campaign" wide
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!sel.length} onClick={save}>Add {sel.length || ""}</Button></>}>
      <ErrorNote error={error} />
      <p className="mb-3 text-sm text-muted">A partner can be in one campaign at a time. Picking one that is already in another campaign moves it here.</p>
      <div className="mb-3 flex gap-2">
        <Input placeholder="Search partners" value={find} onChange={(e) => setFind(e.target.value)} />
        <Button size="sm" variant="ghost" onClick={() => setSel(sel.length ? [] : rows.map((r) => r.id))}>{sel.length ? "Clear" : `Select all ${rows.length}`}</Button>
      </div>
      {loading ? <Spinner /> : rows.length === 0 ? <p className="py-8 text-center text-sm text-muted">No other partners for this property.</p> : (
        <ul className="max-h-[50vh] divide-y divide-line overflow-y-auto rounded-lg border border-line scroll-thin">
          {rows.map((p) => (
            <li key={p.id}>
              <label className={cx("flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-surface-2", sel.includes(p.id) && "bg-vireo-soft")}>
                <input type="checkbox" className="accent-[var(--vireo)]" checked={sel.includes(p.id)}
                  onChange={(e) => setSel(e.target.checked ? [...sel, p.id] : sel.filter((x) => x !== p.id))} />
                <Badge tone={statusTone(p.priority ?? "P2")}>{p.priority ?? "–"}</Badge>
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="text-xs text-muted">{label(p.stage)}</span>
                {p.campaign_name && <span className="text-[11px] text-amber">in “{p.campaign_name}”</span>}
              </label>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
