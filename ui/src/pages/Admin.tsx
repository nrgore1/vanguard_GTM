import { useEffect, useState } from "react";
import { Bot, Users as UsersIcon, ScrollText, Play, Download, RefreshCw, CheckCircle2, XCircle, Eye, UserPlus, Trash2, KeyRound, Cpu, Cloud, Mail } from "lucide-react";
import { api, type Role, type Run } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, relTime, usd } from "../lib/format";
import { Badge, Button, Card, CardHeader, Confirm, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, cx, statusTone, useToast } from "../components/ui";

type PB = { property: string; revenue_roadmap: Record<string, string | number>; lint_status: string; notes: string[];
  lint_findings: { severity: string; rule_id: string; location: string; excerpt: string }[];
  partnership_playbook: { kind: string; partner_type: string; target_entities: string[]; first_ask: string }[];
  icp_matrix: { tier_1_icp: { persona: string } } };

function PlaybookModal({ run, pid, onClose }: { run: string; pid: string | null; onClose: () => void }) {
  const [pb, setPb] = useState<PB | null>(null);
  useEffect(() => { setPb(null); if (pid) api.playbook<PB>(run, pid).then(setPb); }, [run, pid]);
  return (
    <Modal open={!!pid} onClose={onClose} wide title={`Playbook · ${pid ?? ""}`}>
      {!pb ? <Spinner /> : (
        <div className="space-y-5 text-sm">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(pb.revenue_roadmap).map(([k, v]) => <div key={k} className="rounded-lg border border-line bg-surface-2 p-2.5"><div className="text-[11px] text-muted">{label(k)}</div><div className="num mt-0.5">{String(v)}</div></div>)}
          </div>
          <div><div className="mb-1 text-xs text-muted">Tier-1 ICP</div><p>{pb.icp_matrix.tier_1_icp.persona}</p></div>
          <div><div className="mb-1.5 text-xs text-muted">Partnerships</div>
            <ul className="space-y-1.5">{pb.partnership_playbook.map((p, i) => <li key={i} className="flex gap-2"><Badge tone={p.kind === "design_partner" ? "violet" : p.kind === "co_sell" ? "sky" : "green"}>{label(p.kind)}</Badge><span>{p.partner_type}: {p.target_entities.join(", ")}</span></li>)}</ul></div>
          {pb.notes.length > 0 && <div><div className="mb-1 text-xs text-muted">Notes</div><ul className="list-inside list-disc text-muted">{pb.notes.map((n) => <li key={n}>{n}</li>)}</ul></div>}
          <div><div className="mb-1.5 text-xs text-muted">Lint findings · <Badge tone={statusTone(pb.lint_status)}>{pb.lint_status}</Badge></div>
            {pb.lint_findings.length === 0 ? <p className="text-muted">None - copy is clean.</p> :
              <ul className="space-y-1.5">{pb.lint_findings.map((f, i) => <li key={i} className="rounded-md border border-line bg-surface-2 p-2 text-xs"><Badge tone={f.severity === "block" ? "rose" : "amber"}>{f.rule_id}</Badge> <span className="text-muted">{f.location}</span><div className="mt-1">{f.excerpt}</div></li>)}</ul>}
          </div>
        </div>
      )}
    </Modal>
  );
}

function AgentTab() {
  const toast = useToast();
  const { properties } = useAuth();
  const status = useLoad(api.agentStatus);
  const runs = useLoad(api.runs);
  const [sel, setSel] = useState<string[]>([]);
  const [dry, setDry] = useState(true);
  const [provider, setProvider] = useState("local");
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [view, setView] = useState<string | null>(null);

  const anyRunning = (runs.data ?? []).some((r) => r.status === "running");
  useEffect(() => { if (!anyRunning) return; const t = setInterval(runs.reload, 3000); return () => clearInterval(t); }, [anyRunning, runs.reload]);
  useEffect(() => { if (open) api.run(open).then(setDetail); else setDetail(null); }, [open, runs.data]);

  const act = async (key: string, fn: () => Promise<unknown>, ok: (r: never) => string) => {
    setBusy(key);
    try { const r = await fn(); toast(ok(r as never)); runs.reload(); if (open) api.run(open).then(setDetail); }
    catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(""); }
  };
  const s = status.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader title="Agent configuration" sub="Read from the server's .env - change it there" />
          {!s ? <Spinner /> : (
            <ul className="divide-y divide-line text-sm">
              <li className="flex items-center gap-3 px-5 py-3"><Cpu size={16} className="text-vireo" /><span className="flex-1">Provider <b className="font-medium">{String(s.provider)}</b>{s.provider === "local" && <span className="text-muted"> · {String(s.local_model)}</span>}</span>
                {s.provider === "local" && (s.local_ok ? <Badge tone="green">ready</Badge> : <Badge tone="rose">not ready</Badge>)}</li>
              {s.provider === "local" && !s.local_ok && <li className="px-5 py-2 text-xs text-muted">{String(s.local_message)}</li>}
              <li className="flex items-center gap-3 px-5 py-3"><Cloud size={16} className="text-sky" /><span className="flex-1">Claude {s.provider === "local" ? "fallback" : ""} · {String(s.claude_model)}</span>
                {s.paid_runs ? <Badge tone="amber">on · cap {usd(Number(s.cap_usd))}</Badge> : <Badge tone="green">off · $0</Badge>}</li>
              <li className="flex items-center gap-3 px-5 py-3"><KeyRound size={16} className="text-muted" /><span className="flex-1">Keys</span>
                <Badge tone={s.claude_key_set ? "green" : "gray"}>Anthropic {s.claude_key_set ? "set" : "unset"}</Badge><Badge tone={s.notion_token_set ? "green" : "gray"}>Notion {s.notion_token_set ? "set" : "unset"}</Badge></li>
              {s.email && <li className="flex flex-wrap items-center gap-2 px-5 py-3"><Mail size={16} className="text-violet" /><span className="flex-1">Email · <b className="font-medium">{s.email.mode}</b>
                {s.email.postmark && <span className="text-muted"> · Postmark {s.email.postmark.stream_outreach}/{s.email.postmark.stream_notify}</span>}</span>
                {s.email.live ? <Badge tone="amber">live</Badge> : s.email.mode === "outbox" ? <Badge tone="green">outbox · sends nothing</Badge> : <Badge tone="rose">needs setup</Badge>}
                {s.email.postmark && <Badge tone={s.email.postmark.configured ? "green" : "rose"}>Postmark {s.email.postmark.configured ? "token set" : "no token"}</Badge>}</li>}
              {s.email?.problems.map((pr) => <li key={pr} className="px-5 py-2 text-xs text-rose">{pr}</li>)}
              <li className="px-5 py-3 text-xs text-faint">Version {String(s.version)}</li>
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title="Start a run" sub="Generates playbooks + 30-day plans for the selected properties, in parallel" />
          <div className="space-y-4 p-5">
            <div className="flex flex-wrap gap-1.5">
              <button onClick={() => setSel([])} className={cx("rounded-full border px-2.5 py-1 text-xs", sel.length === 0 ? "border-vireo bg-vireo-soft text-vireo" : "border-line text-muted")}>All 8</button>
              {properties.map((p) => {
                const on = sel.includes(p.id);
                return <button key={p.id} onClick={() => setSel(on ? sel.filter((x) => x !== p.id) : [...sel, p.id])}
                  className={cx("rounded-full border px-2.5 py-1 text-xs", on ? "border-vireo bg-vireo-soft text-vireo" : "border-line text-muted hover:text-ink")}>{p.name}</button>;
              })}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Mode"><Select value={dry ? "dry" : "real"} onChange={(e) => setDry(e.target.value === "dry")}>
                <option value="dry">Dry run ($0, placeholder)</option><option value="real">Real run</option></Select></Field>
              <Field label="Provider"><Select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={dry}>
                <option value="local">Local model ($0)</option><option value="claude">Claude only (paid)</option></Select></Field>
            </div>
            <Button variant="primary" icon={<Play size={15} />} loading={busy === "start"}
              onClick={() => act("start", () => api.startRun({ properties: sel.length ? sel : ["all"], dry_run: dry, provider: dry ? undefined : provider }), (r: { run_id: string }) => `Started ${r.run_id}`)}>
              Start run</Button>
          </div>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader title="Runs" sub="Approve playbooks, import them as draft campaigns and partners, sync tasks to Notion" action={<Button size="sm" variant="ghost" icon={<RefreshCw size={13} />} onClick={runs.reload}>Refresh</Button>} />
        {runs.loading && !runs.data ? <Spinner /> : (runs.data ?? []).length === 0 ? <p className="px-5 py-10 text-center text-sm text-muted">No runs yet.</p> : (
          <ul className="divide-y divide-line">
            {(runs.data ?? []).map((r) => (
              <li key={r.id}>
                <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full flex-wrap items-center gap-3 px-5 py-3 text-left text-sm hover:bg-surface-2">
                  <span className="font-mono text-xs">{r.id}</span>
                  <Badge tone={r.status === "completed" ? "green" : statusTone(r.status)}>{r.status}</Badge>
                  <span className="text-muted">{r.property_ids.length} properties</span>
                  <span className="text-muted">{String(r.usage.model ?? "")}</span>
                  <span className="num ml-auto text-muted">{usd(Number(r.usage.cost_usd ?? 0))}</span>
                  <span className="text-xs text-faint">{relTime(r.created_at)}</span>
                </button>
                {open === r.id && detail && (
                  <div className="border-t border-line bg-surface-2/50 px-5 py-4">
                    <div className="mb-3 flex flex-wrap gap-2">
                      <Button size="sm" icon={<Download size={13} />} loading={busy === "import"} onClick={() => act("import", () => api.importRun(r.id), (x: { campaigns: number; partners: number; messages: number; skipped: number }) => `Imported ${x.campaigns} campaigns, ${x.partners} partners, ${x.messages} draft emails${x.skipped ? `, skipped ${x.skipped} blocked` : ""}`)}>Import to campaigns & partners</Button>
                      <Button size="sm" icon={<RefreshCw size={13} />} loading={busy === "sync"} onClick={() => act("sync", () => api.syncRun(r.id), (x: { tasks: number }) => `Synced ${x.tasks} tasks to Notion`)}>Sync to Notion</Button>
                    </div>
                    {Object.entries(detail.errors).map(([k, v]) => <div key={k} className="mb-2 rounded-md border border-rose/30 bg-rose-soft px-3 py-1.5 text-xs text-rose"><b>{k}</b>: {v}</div>)}
                    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      {(detail.playbooks ?? []).map((p) => (
                        <div key={p.property_id} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
                          <span className="min-w-0 flex-1 truncate">{p.property_id}</span>
                          <Badge tone={statusTone(p.lint_status)}>{p.lint_status}</Badge>
                          <button onClick={() => setView(p.property_id)} className="text-muted hover:text-ink" aria-label={`View ${p.property_id} playbook`}><Eye size={14} /></button>
                          {p.approved_by ? <CheckCircle2 size={15} className="text-vireo" aria-label="approved" /> : p.lint_status === "blocked" ? <XCircle size={15} className="text-rose" aria-label="blocked" /> :
                            <Button size="sm" variant="ghost" loading={busy === `ap-${p.property_id}`} onClick={() => act(`ap-${p.property_id}`, () => api.approve(r.id, p.property_id), () => `Approved ${p.property_id}`)}>Approve</Button>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {open && <PlaybookModal run={open} pid={view} onClose={() => setView(null)} />}
    </div>
  );
}

function UsersTab() {
  const toast = useToast();
  const { user: me, refreshUsers } = useAuth();
  const { data, error, loading, reload } = useLoad(api.users);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ email: "", name: "", role: "user" as Role, password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [del, setDel] = useState<number | null>(null);
  const [reset, setReset] = useState<{ id: number; name: string } | null>(null);
  const [pw, setPw] = useState("");
  const done = (msg: string) => { toast(msg); reload(); refreshUsers(); };

  const create = async () => {
    setBusy(true); setErr(null);
    try { await api.createUser(f); setAdding(false); setF({ email: "", name: "", role: "user", password: "" }); done("User created"); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const upd = async (id: number, b: Parameters<typeof api.updateUser>[1], msg: string) => { try { await api.updateUser(id, b); done(msg); } catch (e) { toast(String((e as Error).message), "err"); } };

  return (
    <Card className="overflow-hidden">
      <CardHeader title="Users" sub="Admins manage everything; users run campaigns, partners and their own tasks" action={<Button size="sm" variant="primary" icon={<UserPlus size={14} />} onClick={() => setAdding(true)}>Add user</Button>} />
      <ErrorNote error={error} />
      {loading && !data ? <Spinner /> : (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs text-muted">{["Name", "Email", "Role", "Status", "Last sign-in", ""].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr></thead>
          <tbody>{(data ?? []).map((u) => (
            <tr key={u.id} className="border-b border-line last:border-0">
              <td className="px-5 py-3 font-medium">{u.name}{u.id === me?.id && <span className="ml-1.5 text-xs text-faint">(you)</span>}</td>
              <td className="px-5 py-3 text-muted">{u.email}</td>
              <td className="px-5 py-3"><select value={u.role} disabled={u.id === me?.id} onChange={(e) => upd(u.id, { role: e.target.value as Role }, "Role updated")} aria-label={`Role of ${u.name}`}
                className="rounded-md border border-line bg-surface-2 px-1.5 py-1 text-xs"><option value="user">user</option><option value="admin">admin</option></select></td>
              <td className="px-5 py-3"><button disabled={u.id === me?.id} onClick={() => upd(u.id, { active: !u.active }, u.active ? "User disabled" : "User enabled")}>
                <Badge tone={u.active ? "green" : "gray"}>{u.active ? "active" : "disabled"}</Badge></button></td>
              <td className="px-5 py-3 text-xs text-faint">{relTime(u.last_login)}</td>
              <td className="px-5 py-3 text-right">
                <button onClick={() => { setReset({ id: u.id, name: u.name }); setPw(""); }} className="mr-2 text-faint hover:text-ink" aria-label={`Reset password for ${u.name}`}><KeyRound size={14} /></button>
                {u.id !== me?.id && <button onClick={() => setDel(u.id)} className="text-faint hover:text-rose" aria-label={`Delete ${u.name}`}><Trash2 size={14} /></button>}
              </td>
            </tr>))}</tbody>
        </table>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title="Add user"
        footer={<><Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={create}>Create user</Button></>}>
        <ErrorNote error={err} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Role"><Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}><option value="user">General user</option><option value="admin">Admin</option></Select></Field>
          <Field label="Email" className="sm:col-span-2"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="At least 10 characters. Share it privately." className="sm:col-span-2"><Input type="text" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        </div>
      </Modal>
      <Modal open={!!reset} onClose={() => setReset(null)} title={`Reset password · ${reset?.name ?? ""}`}
        footer={<><Button variant="ghost" onClick={() => setReset(null)}>Cancel</Button><Button variant="primary" disabled={pw.length < 10} onClick={async () => { if (reset) { await upd(reset.id, { password: pw }, "Password reset"); setReset(null); } }}>Set password</Button></>}>
        <Field label="New password" hint="At least 10 characters"><Input value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
      </Modal>
      <Confirm open={del !== null} onClose={() => setDel(null)} onConfirm={async () => { try { await api.deleteUser(del!); done("User deleted"); } catch (e) { toast(String((e as Error).message), "err"); } setDel(null); }}
        title="Delete user?" body="Their campaigns, partners and logged results stay; they just can't sign in." />
    </Card>
  );
}

function AuditTab() {
  const { data, loading } = useLoad(api.audit);
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Audit log" sub="Last 100 changes" />
      {loading && !data ? <Spinner /> : (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full min-w-[700px] text-sm">
            <thead><tr className="border-b border-line text-left text-xs text-muted">{["When", "Who", "Action", "Entity", "Detail"].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>{(data ?? []).map((a) => (
              <tr key={a.id} className="border-b border-line last:border-0">
                <td className="whitespace-nowrap px-5 py-2 text-xs text-faint">{new Date(a.at).toLocaleString()}</td>
                <td className="px-5 py-2">{a.user_name ?? "system"}</td>
                <td className="px-5 py-2"><Badge tone={a.action === "delete" ? "rose" : a.action === "create" ? "green" : "gray"}>{a.action}</Badge></td>
                <td className="px-5 py-2 text-muted">{a.entity} <span className="font-mono text-xs">{a.entity_id}</span></td>
                <td className="max-w-[360px] truncate px-5 py-2 font-mono text-[11px] text-faint">{a.detail}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function Admin() {
  const [tab, setTab] = useState<"agent" | "users" | "audit">("agent");
  const tabs = [{ id: "agent", label: "Agent & runs", icon: Bot }, { id: "users", label: "Users", icon: UsersIcon }, { id: "audit", label: "Audit log", icon: ScrollText }] as const;
  return (
    <>
      <PageHeader eyebrow="Admin" title="Administration" sub="Run the agent, approve playbooks, manage users and review every change. Edit ARR targets from the dashboard cards." />
      <div className="mb-5 flex gap-1 border-b border-line" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cx("-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm", tab === t.id ? "border-vireo text-ink" : "border-transparent text-muted hover:text-ink")}>
            <t.icon size={15} />{t.label}</button>
        ))}
      </div>
      {tab === "agent" && <AgentTab />}
      {tab === "users" && <UsersTab />}
      {tab === "audit" && <AuditTab />}
    </>
  );
}
