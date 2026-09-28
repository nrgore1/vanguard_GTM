import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ListChecks, Plus, Trash2, Search, Lock } from "lucide-react";
import { api, type Task, type TaskStatus } from "../lib/api";
import { useAuth, useLoad } from "../lib/auth";
import { label, shortDate } from "../lib/format";
import { Badge, Button, Card, Confirm, Empty, ErrorNote, Field, Input, Modal, PageHeader, Select, Spinner, Textarea, statusTone, useToast } from "../components/ui";

const STATUSES: TaskStatus[] = ["Not started", "In progress", "Done", "Blocked"];

function NewTask({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { properties, users } = useAuth();
  const toast = useToast();
  const [f, setF] = useState<Record<string, string>>({ property_id: properties[0]?.id ?? "", priority: "P1", day: "1", category: "Outreach", owner: "Human" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.createTask({ ...f, day: Number(f.day), assignee_id: f.assignee_id ? Number(f.assignee_id) : null, due_date: f.due_date || null });
      toast(`Created ${r.task_id}`); onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open={open} onClose={onClose} title="New task" wide
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save} disabled={(f.description ?? "").length < 3}>Create task</Button></>}>
      <ErrorNote error={error} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Description" className="sm:col-span-3"><Textarea value={f.description ?? ""} onChange={set("description")} /></Field>
        <Field label="Property"><Select value={f.property_id} onChange={set("property_id")}>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Field label="Priority"><Select value={f.priority} onChange={set("priority")}>{["P0", "P1", "P2"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Plan day"><Input type="number" min={1} max={365} value={f.day} onChange={set("day")} /></Field>
        <Field label="Category"><Select value={f.category} onChange={set("category")}>{["Email", "Content", "Outreach", "Partnership", "Tech Integration", "Research", "Analytics"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Assignee"><Select value={f.assignee_id ?? ""} onChange={set("assignee_id")}><option value="">Unassigned</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select></Field>
        <Field label="Due date"><Input type="date" value={f.due_date ?? ""} onChange={set("due_date")} /></Field>
        <Field label="KPI (how we know it's done)" className="sm:col-span-3"><Input value={f.kpi ?? ""} onChange={set("kpi")} /></Field>
      </div>
    </Modal>
  );
}

export default function Tasks() {
  const { properties, users, propName, isAdmin, user } = useAuth();
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const property = sp.get("property") ?? "", status = sp.get("status") ?? "", mine = sp.get("mine") === "1";
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState<Task | null>(null);
  const { data, error, loading, reload, setData } = useLoad(() => api.tasks({ property_id: property || undefined, status: status || undefined, mine }), [property, status, mine]);
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const all = useMemo(() => (data ?? []).filter((t) => !q || `${t.task_id} ${t.description}`.toLowerCase().includes(q.toLowerCase())), [data, q]);
  const PAGE = 40;
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [property, status, mine, q]);
  const pages = Math.max(1, Math.ceil(all.length / PAGE));
  const rows = all.slice(page * PAGE, page * PAGE + PAGE);
  const counts = useMemo(() => Object.fromEntries(STATUSES.map((s) => [s, (data ?? []).filter((t) => t.status === s).length])), [data]);

  const patch = async (t: Task, body: Partial<Task>) => {
    setData((d) => d?.map((x) => (x.id === t.id ? { ...x, ...body, assignee_name: body.assignee_id !== undefined ? users.find((u) => u.id === body.assignee_id)?.name ?? null : x.assignee_name } : x)) ?? null);
    try { await api.updateTask(t.id, body); } catch (e) { toast(String((e as Error).message), "err"); reload(); }
  };
  const remove = async () => {
    if (!del) return;
    try { await api.deleteTask(del.id); toast(`Deleted ${del.task_id}`); setDel(null); reload(); } catch (e) { toast(String((e as Error).message), "err"); }
  };

  return (
    <>
      <PageHeader eyebrow="Operations" title="Tasks" sub={isAdmin ? "The agent's 30-day plans plus manual tasks. Assign owners, reprioritise, add or remove tasks." : "The current 30-day plans. Update the status of tasks assigned to you."}
        actions={isAdmin && <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>New task</Button>} />
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {STATUSES.map((s) => (
          <button key={s} onClick={() => setFilter("status", status === s ? "" : s)} aria-pressed={status === s}
            className={`rounded-xl border p-3 text-left transition-colors ${status === s ? "border-vireo bg-vireo-soft" : "border-line bg-surface hover:bg-surface-2"}`}>
            <div className="text-xs text-muted">{s}</div><div className="num mt-1 text-xl">{counts[s] ?? 0}</div>
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input placeholder="Search tasks" value={q} onChange={(e) => setQ(e.target.value)} className="w-full pl-9" aria-label="Search tasks" /></div>
        <Select value={property} onChange={(e) => setFilter("property", e.target.value)} className="w-auto" aria-label="Filter by property">
          <option value="">All properties</option>{properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-muted">
          <input type="checkbox" checked={mine} onChange={(e) => setFilter("mine", e.target.checked ? "1" : "")} className="accent-[var(--vireo)]" />Only mine</label>
      </div>
      <ErrorNote error={error} />
      <Card className="overflow-hidden">
        {loading && !data ? <Spinner /> : rows.length === 0 ? (
          <Empty icon={<ListChecks size={22} />} title="No tasks here" body={mine ? "Nothing is assigned to you with these filters." : "Run the agent or add a task to populate the plan."} />
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[980px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                {["Task", "Day", "Pri.", "Description", "Property", "Status", "Assignee", "Due", ""].map((h, i) => <th key={i} className="px-3 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((t) => {
                  const mayEdit = isAdmin || t.assignee_id === user?.id;
                  return (
                    <tr key={t.id} className="border-b border-line align-top last:border-0 hover:bg-surface-2/60">
                      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px] text-muted">{t.task_id}</td>
                      <td className="num px-3 py-2.5 text-muted">{t.day}</td>
                      <td className="px-3 py-2.5">{isAdmin ? (
                        <select value={t.priority} onChange={(e) => patch(t, { priority: e.target.value as Task["priority"] })} aria-label={`Priority of ${t.task_id}`}
                          className="rounded-md border border-line bg-surface-2 px-1 py-0.5 text-xs">{["P0", "P1", "P2"].map((x) => <option key={x}>{x}</option>)}</select>
                      ) : <Badge tone={statusTone(t.priority)}>{t.priority}</Badge>}</td>
                      <td className="max-w-[420px] px-3 py-2.5"><div className="leading-snug">{t.description}</div>
                        <div className="mt-0.5 text-[11px] text-faint">{label(t.category)} · {t.owner}{t.tool ? ` (${t.tool})` : ""} · KPI: {t.kpi}</div></td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-muted">{propName(t.property_id)}</td>
                      <td className="px-3 py-2.5">{mayEdit ? (
                        <select value={t.status} onChange={(e) => patch(t, { status: e.target.value as TaskStatus })} aria-label={`Status of ${t.task_id}`}
                          className="rounded-md border border-line bg-surface-2 px-1.5 py-1 text-xs">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
                      ) : <span className="inline-flex items-center gap-1"><Badge tone={statusTone(t.status)}>{t.status}</Badge><Lock size={11} className="text-faint" aria-label="Assigned to someone else" /></span>}</td>
                      <td className="whitespace-nowrap px-3 py-2.5">{isAdmin ? (
                        <select value={t.assignee_id ?? ""} onChange={(e) => patch(t, { assignee_id: e.target.value ? Number(e.target.value) : null })} aria-label={`Assignee of ${t.task_id}`}
                          className="max-w-[140px] rounded-md border border-line bg-surface-2 px-1.5 py-1 text-xs"><option value="">Unassigned</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
                      ) : <span className="text-muted">{t.assignee_name ?? "—"}</span>}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{isAdmin ? (
                        <input type="date" value={t.due_date ?? ""} onChange={(e) => patch(t, { due_date: e.target.value || null })} aria-label={`Due date of ${t.task_id}`}
                          className="rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-xs" />) : shortDate(t.due_date)}</td>
                      <td className="px-2 py-2.5">{isAdmin && <button onClick={() => setDel(t)} className="rounded p-1 text-faint hover:text-rose" aria-label={`Delete ${t.task_id}`}><Trash2 size={14} /></button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-muted">
              <span>{page * PAGE + 1}–{Math.min(all.length, (page + 1) * PAGE)} of {all.length}</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
                <span className="num">{page + 1} / {pages}</span>
                <Button size="sm" variant="ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          </div>
        )}
      </Card>
      {isAdmin && <NewTask open={creating} onClose={() => setCreating(false)} onSaved={reload} />}
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={remove} title="Delete task?" body={<>Delete <b className="text-ink">{del?.task_id}</b>? This can't be undone.</>} />
    </>
  );
}
