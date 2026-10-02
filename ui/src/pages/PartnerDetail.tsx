import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Pencil, Trash2, Mail, Phone, Users, Presentation, FileText, StickyNote, Check, Linkedin, AtSign, Megaphone } from "lucide-react";
import { api, type PartnerStage } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, relTime, shortDate, STAGES, today } from "../lib/format";
import { Badge, Button, Card, CardHeader, Confirm, ErrorNote, Field, Input, Select, Spinner, Textarea, cx, kindTone, statusTone, useToast } from "../components/ui";
import { KIND_HELP, PartnerForm } from "./Partners";
import { AgreementCard, PriorityCard, SequenceCard, TargetsCard } from "../components/PartnerPanels";
import { ConnectionsCard } from "../components/LinkedInPanels";
import { IntroEditor, Strength } from "./Intros";
import type { Intro } from "../lib/api";

const TYPE_ICON: Record<string, typeof Mail> = { email: Mail, linkedin: Linkedin, x: AtSign, call: Phone, meeting: Users, demo: Presentation, proposal: FileText, note: StickyNote };
const TYPE_LABEL: Record<string, string> = { linkedin: "LinkedIn", x: "X (Twitter)" };

export default function PartnerDetail() {
  const { id } = useParams();
  const pid = Number(id);
  const nav = useNavigate();
  const toast = useToast();
  const { user, isAdmin, propName } = useAuth();
  const { data: p, error, loading, reload } = useLoad(() => api.partner(pid), [pid]);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [f, setF] = useState({ date: today(), type: "email", summary: "", outcome: "none", next_step: "", stage: "" });
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<unknown>(null);
  const [intro, setIntro] = useState<Intro | null>(null);

  if (loading && !p) return <Spinner />;
  if (!p) return <ErrorNote error={error} />;
  const stageIdx = STAGES.indexOf(p.stage);

  const log = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setFormErr(null);
    try {
      await api.addInteraction(pid, { ...f, next_step: f.next_step || null, stage: (f.stage || undefined) as PartnerStage | undefined });
      toast("Interaction logged"); setF({ date: today(), type: "email", summary: "", outcome: "none", next_step: "", stage: "" }); reload();
    } catch (err) { setFormErr(err); } finally { setBusy(false); }
  };
  const setStage = async (s: PartnerStage) => {
    try { await api.updatePartner(pid, { stage: s }); toast(`Stage: ${label(s)}`); reload(); } catch (err) { toast(String((err as Error).message), "err"); }
  };
  const del = async () => { try { await api.deletePartner(pid); toast("Partner deleted"); nav("/partners"); } catch (err) { toast(String((err as Error).message), "err"); } };
  const delInteraction = async (iid: number) => { try { await api.deleteInteraction(iid); reload(); } catch (err) { toast(String((err as Error).message), "err"); } };

  return (
    <>
      <Link to="/partners" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft size={15} />Partners</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono uppercase tracking-[0.16em] text-vireo">{propName(p.property_id)}</span>
            <Badge tone={kindTone(p.kind)}>{label(p.kind)}</Badge>
            {(p.source_run_id || p.source?.startsWith("agent")) && <Badge tone="violet">suggested by agent</Badge>}
            {p.source === "research" && <Badge tone="sky">researched organisation</Badge>}
            {p.is_segment ? <Badge tone="amber">segment</Badge> : null}
            {p.campaign_id && <Link to={`/campaigns/${p.campaign_id}`} className="inline-flex items-center gap-1 text-vireo hover:underline"><Megaphone size={12} />{p.campaign_name}</Link>}
          </div>
          <h1 className="font-serif text-[26px] font-semibold leading-tight">{p.name}</h1>
          <p className="mt-1 text-sm text-muted">{KIND_HELP[p.kind]}{p.partner_type ? ` · ${p.partner_type}` : ""}
            {p.website && <> · <a href={p.website} target="_blank" rel="noreferrer noopener" className="text-vireo hover:underline">{p.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a></>}</p>
        </div>
        <div className="flex gap-2">
          <Button icon={<Pencil size={14} />} onClick={() => setEditing(true)}>Edit</Button>
          {isAdmin && <Button variant="danger" icon={<Trash2 size={14} />} onClick={() => setConfirm(true)}>Delete</Button>}
        </div>
      </div>

      {/* stage stepper */}
      <Card className="mb-4 p-4">
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-6" aria-label="Pipeline stage">
          {STAGES.map((s, i) => {
            const done = p.stage !== "declined" && i < stageIdx, cur = s === p.stage;
            return (
              <li key={s}>
                <button onClick={() => setStage(s)} aria-current={cur ? "step" : undefined}
                  className={cx("flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                    cur ? (s === "declined" ? "border-rose/50 bg-rose-soft text-rose" : "border-vireo bg-vireo-soft text-vireo")
                      : done ? "border-line bg-surface-2 text-ink" : "border-line text-muted hover:bg-surface-2")}>
                  <span className={cx("grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px]", cur || done ? "border-current" : "border-line-strong")}>
                    {done ? <Check size={11} /> : i + 1}</span>{label(s)}
                </button>
              </li>
            );
          })}
        </ol>
      </Card>

      <div className={cx("mb-4 grid gap-4", !p.is_segment && "xl:grid-cols-[1.4fr_1fr]")}>
        <PriorityCard p={p} />
        {!p.is_segment && <AgreementCard p={p} onSaved={reload} />}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
        <div className="space-y-4">
          {Array.isArray(p.connections) && <ConnectionsCard people={p.connections} />}
          {!p.is_segment && <Card>
            <CardHeader title="Paths in (introductions)" sub="People you know who can introduce you. Open one to draft the ask."
              action={p.mutuals_url && <a href={p.mutuals_url} target="_blank" rel="noreferrer noopener" className="text-xs text-vireo hover:underline">Check 2nd-degree on LinkedIn</a>} />
            {(p.intros ?? []).length === 0 ? <p className="px-5 py-6 text-sm text-muted">No paths yet. Import your LinkedIn export (Partners page), then <Link to="/intros" className="text-vireo hover:underline">Find paths</Link>.</p> : (
              <ul className="divide-y divide-line">{(p.intros ?? []).map((i) => (
                <li key={i.id}><button onClick={() => setIntro(i)} className="flex w-full items-start gap-3 px-5 py-3 text-left text-sm hover:bg-surface-2">
                  <div className="min-w-0 flex-1"><div className="font-medium">{i.first_name} {i.last_name} <Badge tone={i.path === "direct" ? "green" : "sky"}>{i.path === "direct" ? "insider" : "likely bridge"}</Badge></div>
                    <div className="truncate text-xs text-muted">{i.position}{i.company ? ` · ${i.company}` : ""}</div></div>
                  <Strength v={i.strength} /><Badge tone={statusTone(i.status)}>{i.status}</Badge></button></li>))}</ul>)}
          </Card>}
          <TargetsCard p={p} onAdded={reload} />
          <SequenceCard p={p} onChanged={reload} />
          <Card>
            <CardHeader title="Details" />
            <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-2.5 p-5 text-sm">
              {([["Contact", p.contact_name ? `${p.contact_name}${p.contact_email ? ` · ${p.contact_email}` : ""}` : "—"],
                ["Owner", p.owner_name ?? "—"], ["Value sharing", p.value_sharing_model ?? "—"],
                ["First ask", p.first_ask ?? "—"], ["Next step", p.next_step ?? "—"], ["Due", shortDate(p.next_step_date)],
              ] as const).map(([k, v]) => <Fragment key={k}><dt className="text-muted">{k}</dt><dd className="min-w-0 break-words">{v}</dd></Fragment>)}
            </dl>
            {p.mutual_value && <div className="border-t border-line px-5 py-4 text-sm"><div className="mb-1 text-xs text-muted">Why both sides win</div><p className="whitespace-pre-line leading-relaxed">{p.mutual_value}</p></div>}
          </Card>
          <Card>
            <CardHeader title="Log an interaction" sub="LinkedIn and X messages, calls, meetings, demos, proposals. Emails sent from Outreach are logged for you." />
            <form onSubmit={log} className="grid gap-3 p-5 sm:grid-cols-2">
              <ErrorNote error={formErr} />
              <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
              <Field label="Type"><Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{Object.keys(TYPE_ICON).map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? label(t)}</option>)}</Select></Field>
              <Field label="What happened" className="sm:col-span-2"><Textarea required value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} placeholder="Discussed pilot scope, they want…" /></Field>
              <Field label="Outcome"><Select value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })}>{["positive", "neutral", "negative", "none"].map((o) => <option key={o} value={o}>{label(o)}</option>)}</Select></Field>
              <Field label="Move stage to"><Select value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}><option value="">Keep: {label(p.stage)}</option>{STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
              <Field label="Next step" className="sm:col-span-2"><Input value={f.next_step} onChange={(e) => setF({ ...f, next_step: e.target.value })} /></Field>
              <div className="sm:col-span-2"><Button variant="primary" type="submit" loading={busy} disabled={f.summary.length < 2}>Log interaction</Button></div>
            </form>
          </Card>
        </div>
        <Card>
          <CardHeader title="Timeline" sub={`${p.interactions.length} interactions`} />
          {p.interactions.length === 0 ? <p className="px-5 py-12 text-center text-sm text-muted">No interactions yet. Log the first touch on the left.</p> : (
            <ol className="relative px-5 py-4">
              <span className="absolute bottom-6 left-[34px] top-6 w-px bg-line" aria-hidden />
              {p.interactions.map((i) => {
                const Icon = TYPE_ICON[i.type] ?? StickyNote;
                return (
                  <li key={i.id} className="relative flex gap-3 pb-5 last:pb-0">
                    <span className="z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full border border-line-strong bg-surface-2 text-vireo"><Icon size={13} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-medium text-ink">{TYPE_LABEL[i.type] ?? label(i.type)}</span>
                        <Badge tone={statusTone(i.outcome)}>{i.outcome}</Badge>
                        <span className="text-faint">{shortDate(i.date)} · {relTime(i.date)}{i.by_name ? ` · ${i.by_name}` : ""}</span>
                        {(isAdmin || i.created_by === user?.id) && <button onClick={() => delInteraction(i.id)} className="ml-auto text-faint hover:text-rose" aria-label="Delete interaction"><Trash2 size={12} /></button>}
                      </div>
                      <p className="mt-1 whitespace-pre-line text-sm leading-relaxed">{i.summary}</p>
                      {i.next_step && <p className="mt-1 text-xs text-muted">Next: {i.next_step}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </Card>
      </div>
      <IntroEditor intro={intro} onClose={() => setIntro(null)} onChanged={() => { setIntro(null); reload(); }} />
      <PartnerForm open={editing} onClose={() => setEditing(false)} initial={p} onSaved={() => { setEditing(false); reload(); }} />
      <Confirm open={confirm} onClose={() => setConfirm(false)} onConfirm={del} title="Delete partner?"
        body={<>Removes <b className="text-ink">{p.name}</b> and its {p.interactions.length} logged interactions.</>} />
    </>
  );
}
