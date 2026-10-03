import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { api } from "../lib/api";
import { Button, ErrorNote, Field, Input, Modal, useToast } from "./ui";

/** "2026-10-09T09:00" from an <input type="datetime-local"> (the viewer's time zone) -> UTC ISO for the API. */
export const localToIso = (local: string) => (local ? new Date(local).toISOString() : null);
/** Minutes east of UTC at that local time (DST-aware), so the server can tell weekends in the viewer's zone. */
export const tzOffsetAt = (local: string) => -new Date(local || Date.now()).getTimezoneOffset();
/** A UTC ISO time shown in the viewer's time zone, e.g. "Fri, Oct 9, 9:00 AM". */
export const fmtWhen = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
/** A datetime-local value for a UTC ISO time. */
export const isoToLocal = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
/** Next weekday at 9:00 local, as a datetime-local value - a sensible default for outreach. */
export const nextMorning = () => {
  const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  return isoToLocal(d.toISOString());
};
export const isFuture = (iso: string | null | undefined) => !!iso && new Date(iso).getTime() > Date.now();

export function AutoSendNote({ every }: { every: number | undefined }) {
  if (every === undefined) return null;
  return every > 0
    ? <p className="text-xs text-muted">Automatic sending checks every {every} min, so a scheduled email goes within {every} min of its time.</p>
    : <p className="text-xs text-amber">Automatic sending is off: a scheduled email goes the first time an admin clicks <b>Send due now</b> after its time.
        Set <code className="font-mono">VANGUARD_OUTREACH_EVERY_MIN=10</code> on the server to send on time.</p>;
}

/** Schedule several emails: a start time, optionally spread N per day, minutes apart, weekdays only. */
export function ScheduleModal({ ids, open, onClose, onDone, autoEvery }: {
  ids: number[]; open: boolean; onClose: () => void; onDone: () => void; autoEvery?: number;
}) {
  const toast = useToast();
  const [when, setWhen] = useState("");
  const [perDay, setPerDay] = useState("");
  const [gap, setGap] = useState("5");
  const [weekdays, setWeekdays] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (open) { setWhen(nextMorning()); setError(null); } }, [open]);
  const run = async (clear = false) => {
    setBusy(true); setError(null);
    try {
      const r = await api.scheduleOutreach({ ids, send_at: clear ? null : localToIso(when), per_day: perDay ? Number(perDay) : null,
        gap_min: Number(gap) || 0, weekdays_only: weekdays, tz_offset_min: tzOffsetAt(when) });
      const last = r.scheduled[r.scheduled.length - 1];
      toast(clear ? `Schedule cleared for ${r.scheduled.length}` : `Scheduled ${r.scheduled.length}${last ? `, last ${fmtWhen(last.send_at)}` : ""}`
        + (r.refused.length ? ` · ${r.refused.length} refused: ${r.refused[0].reason}` : ""), r.refused.length ? "err" : "ok");
      onDone(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const n = ids.length, pd = Number(perDay) || n;
  return (
    <Modal open={open} onClose={onClose} title={`Schedule ${n} email${n === 1 ? "" : "s"}`}
      footer={<><Button variant="ghost" onClick={() => run(true)} loading={busy}>Clear schedule</Button><div className="flex-1" />
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={<CalendarClock size={14} />} loading={busy} disabled={!when} onClick={() => run()}>Schedule</Button></>}>
      <ErrorNote error={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Start" className="sm:col-span-2" hint="Your local time."><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <Field label="Per day" hint="Leave empty to send all at the start time."><Input type="number" min={1} value={perDay} onChange={(e) => setPerDay(e.target.value)} placeholder="all" /></Field>
        <Field label="Minutes apart" hint="Spacing within a day; looks less like a blast."><Input type="number" min={0} value={gap} onChange={(e) => setGap(e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={weekdays} onChange={(e) => setWeekdays(e.target.checked)} className="accent-[var(--vireo)]" />
          Weekdays only (a weekend start moves to Monday)</label>
      </div>
      <p className="mt-3 text-xs text-muted">{n} email{n === 1 ? "" : "s"} over {Math.ceil(n / pd)} day{Math.ceil(n / pd) === 1 ? "" : "s"}. Scheduling doesn't approve anything:
        drafts still need an admin's approval, and a follow-up step still waits for its delay after the previous step. The daily cap still applies.</p>
      <div className="mt-2"><AutoSendNote every={autoEvery} /></div>
    </Modal>
  );
}
