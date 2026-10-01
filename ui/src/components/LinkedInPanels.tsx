import { useState } from "react";
import { Linkedin, Upload, ExternalLink } from "lucide-react";
import { api, type LinkedInConnection } from "../lib/api";
import { shortDate } from "../lib/format";
import { Badge, Button, Card, CardHeader, ErrorNote, Modal, useToast } from "./ui";

/** Load LinkedIn's own Connections.csv export. No API, no scraping: the user downloads their data from LinkedIn. */
export function ImportLinkedIn({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.importLinkedIn>> | null>(null);
  const run = async () => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const r = await api.importLinkedIn(await file.text());
      setRes(r); toast(`${r.connections} connections loaded`); onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const remove = async () => {
    try { const r = await api.deleteMyLinkedIn(); toast(`Removed ${r.deleted} imported connections`); onDone(); }
    catch (e) { setError(e); }
  };
  const close = () => { setRes(null); setFile(null); setError(null); onClose(); };
  return (
    <Modal open={open} onClose={close} title="Import your LinkedIn connections" wide
      footer={res ? <Button variant="primary" onClick={close}>Done</Button> : <><Button variant="ghost" onClick={close}>Cancel</Button>
        <Button variant="primary" icon={<Upload size={14} />} loading={busy} disabled={!file} onClick={run}>Import</Button></>}>
      <ErrorNote error={error} />
      {res ? (
        <div className="space-y-2 text-sm">
          <p><b>{res.connections}</b> connections ({res.added} new, {res.refreshed} refreshed). You know someone at <b>{res.partners_with_connections}</b> partners - see the <span className="text-vireo">Known</span> column.</p>
          {res.contacts_connected.length > 0 && <p>Named contacts you're now connected with: {res.contacts_connected.join(", ")}. Each got a "Connected on LinkedIn" entry in its timeline.</p>}
          {res.emails_filled.length > 0 && <p>Contact emails added from LinkedIn (shared by the person): {res.emails_filled.join(", ")}.</p>}
        </div>
      ) : (
        <>
          <ol className="mb-4 list-decimal space-y-1.5 pl-5 text-sm text-muted">
            <li>On LinkedIn, open <b className="text-ink">Settings → Data privacy → Get a copy of your data</b>.</li>
            <li>Tick <b className="text-ink">Connections</b> only and request the archive. LinkedIn emails a download link, usually within 10 minutes.</li>
            <li>Unzip it and choose <code className="font-mono text-xs text-ink">Connections.csv</code> below.</li>
          </ol>
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-line file:bg-surface-2 file:px-3 file:py-1.5 file:text-ink" />
          <p className="mt-3 text-xs text-faint">Your connections are matched to partners by company. Re-import every week or two: newly accepted
            requests then show up on the partner's timeline. Nothing is sent to LinkedIn, and nothing here automates your account.</p>
          <button type="button" onClick={remove} className="mt-3 text-xs text-rose hover:underline">Remove my imported connections</button>
        </>
      )}
    </Modal>
  );
}

export function ConnectionsCard({ people }: { people: LinkedInConnection[] }) {
  if (!people.length) return null;
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><Linkedin size={15} className="text-vireo" />People you know here</span>}
        sub="1st-degree LinkedIn connections at this organisation, from imported LinkedIn exports. Ask them for an introduction before writing cold." />
      <ul className="divide-y divide-line">
        {people.map((c) => (
          <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-0.5 px-5 py-3 text-sm">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{c.first_name} {c.last_name}</span>
                {c.is_contact && <Badge tone="green">named contact</Badge>}
              </div>
              <div className="text-xs text-muted">{c.position ?? "—"}{c.company ? ` · ${c.company}` : ""}</div>
              <div className="text-[11px] text-faint">connected {shortDate(c.connected_on)}{c.owner_name ? ` · via ${c.owner_name}` : ""}{c.email ? ` · ${c.email}` : ""}</div>
            </div>
            {c.profile_url?.startsWith("http") && <a href={c.profile_url} target="_blank" rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-xs text-vireo hover:underline">Profile<ExternalLink size={11} /></a>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
