import { useState } from "react";
import { AtSign, Check, Copy, ExternalLink, Linkedin, Mail } from "lucide-react";
import { api, type Channel, type OutreachMessage } from "../lib/api";
import { Badge, Button, Modal, useToast } from "./ui";
import { preview } from "./OutreachEditor";

export const CHANNEL_LABEL: Record<Channel, string> = { email: "Email", linkedin: "LinkedIn", x: "X" };
export const CHANNEL_ICON: Record<Channel, typeof Mail> = { email: Mail, linkedin: Linkedin, x: AtSign };

export function ChannelBadge({ c }: { c?: Channel | null }) {
  const ch = c ?? "email";
  if (ch === "email") return null;
  const Icon = CHANNEL_ICON[ch];
  return <Badge tone={ch === "linkedin" ? "sky" : "gray"}><span className="inline-flex items-center gap-1"><Icon size={11} />{CHANNEL_LABEL[ch]}</span></Badge>;
}

export const profileUrl = (m: { channel?: Channel | null; linkedin_url?: string | null; x_handle?: string | null }) =>
  m.channel === "linkedin" ? m.linkedin_url ?? null : m.channel === "x" && m.x_handle ? `https://x.com/${m.x_handle}` : null;

/** Email / LinkedIn / X: moves this partner's unsent messages to that channel (they go back to draft). */
export function ChannelSwitch({ pid, value, has, onChanged }: {
  pid: number; value: Channel; has: Record<Channel, boolean>; onChanged: () => void;
}) {
  const toast = useToast();
  const pick = async (c: Channel) => {
    if (c === value) return;
    try { const r = await api.setChannel(pid, c); toast(`${r.changed.length} message${r.changed.length === 1 ? "" : "s"} moved to ${CHANNEL_LABEL[c]} - approve again`); onChanged(); }
    catch (e) { toast(String((e as Error).message), "err"); }
  };
  return (
    <div className="flex gap-1 rounded-lg border border-line bg-surface-2 p-0.5" role="radiogroup" aria-label="Channel">
      {(["email", "linkedin", "x"] as Channel[]).map((c) => {
        const Icon = CHANNEL_ICON[c];
        return <button key={c} role="radio" aria-checked={value === c} title={has[c] ? "" : `Add a ${c === "email" ? "contact email" : c === "linkedin" ? "LinkedIn profile" : "X handle"} first (Edit)`}
          disabled={!has[c] && c !== "email"} onClick={() => pick(c)}
          className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] disabled:opacity-40 ${value === c ? "bg-surface-3 text-ink" : "text-muted hover:text-ink"}`}>
          <Icon size={11} />{CHANNEL_LABEL[c]}</button>;
      })}
    </div>
  );
}

/** Send a LinkedIn/X message yourself: copy the text, open their profile, then mark it sent. */
export function SendByHand({ msg, onClose, onChanged }: {
  msg: (OutreachMessage & { profile_url?: string | null; due?: boolean; held?: string | null }) | null; onClose: () => void; onChanged: () => void;
}) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!msg) return null;
  const ch = (msg.channel ?? "linkedin") as Channel;
  const text = preview(msg.body, msg);
  const url = msg.profile_url ?? profileUrl(msg);
  const note = ch === "linkedin" && (msg.step === 1 || msg.one_off);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { toast("Couldn't copy - select the text and copy it", "err"); }
  };
  const done = async () => {
    setBusy(true);
    try { await api.markSent(msg.id); toast(`Logged: sent on ${CHANNEL_LABEL[ch]}`); onChanged(); onClose(); }
    catch (e) { toast(String((e as Error).message), "err"); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} wide title={`Send on ${CHANNEL_LABEL[ch]} · ${msg.partner_name ?? ""}`}
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button><div className="flex-1" />
        <Button variant="primary" icon={<Check size={14} />} loading={busy} disabled={msg.status !== "approved"} onClick={done}>I sent it</Button></>}>
      <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>Copy the message.</li>
        <li>Open {msg.contact_name || msg.partner_name}'s {CHANNEL_LABEL[ch]} profile{note ? <> and click <b className="text-ink">Connect → Add a note</b> if you aren't connected yet, otherwise <b className="text-ink">Message</b></> : <> and send it as a message</>}.</li>
        <li>Come back and click <b className="text-ink">I sent it</b>. That logs the touch and starts the wait before the next step.</li>
      </ol>
      {msg.held && <p className="mb-3 text-xs text-amber">Not due yet: {msg.held}. You can still send it now.</p>}
      <div className="relative rounded-lg border border-line bg-surface-2 p-3">
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{text}</pre>
        <div className="mt-2 flex items-center gap-3 text-xs text-faint">
          <span className={note && text.length > 200 ? "text-amber" : ""}>{text.length} characters{note ? " (connection notes: 200 free, 300 Premium)" : ""}</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button icon={copied ? <Check size={14} /> : <Copy size={14} />} onClick={copy}>{copied ? "Copied" : "Copy message"}</Button>
        {url && <a href={url} target="_blank" rel="noreferrer noopener"><Button icon={<ExternalLink size={14} />}>Open profile</Button></a>}
      </div>
    </Modal>
  );
}
