import { X, Loader2, AlertTriangle } from "lucide-react";
import { cloneElement, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

/* ---------- buttons ---------- */
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline" | "danger"; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode;
};
export function Button({ variant = "outline", size = "md", loading, icon, className, children, disabled, ...p }: BtnProps) {
  return (
    <button
      {...p}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-vireo text-vireo-ink hover:brightness-110 shadow-[0_0_0_1px_var(--vireo),0_8px_20px_-10px_var(--vireo)]",
        variant === "outline" && "border border-line-strong bg-surface-2 text-ink hover:bg-surface-3",
        variant === "ghost" && "text-muted hover:text-ink hover:bg-surface-3",
        variant === "danger" && "border border-rose/40 bg-rose-soft text-rose hover:bg-rose/20",
        className,
      )}
    >
      {loading ? <Loader2 size={15} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ---------- surfaces ---------- */
export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cx("rounded-xl border border-line bg-surface shadow-card", className)}>{children}</div>;
}
export function CardHeader({ title, sub, action }: { title: ReactNode; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
      <div>
        <h3 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h3>
        {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ eyebrow, title, sub, actions }: { eyebrow?: string; title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-1 font-mono text-[11px] uppercase tracking-[0.18em] text-vireo">{eyebrow}</div>}
        <h1 className="font-serif text-[28px] leading-tight font-semibold text-ink">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------- badges ---------- */
const TONES: Record<string, string> = {
  green: "bg-vireo-soft text-vireo", amber: "bg-amber-soft text-amber", rose: "bg-rose-soft text-rose",
  sky: "bg-sky-soft text-sky", violet: "bg-violet-soft text-violet", gray: "bg-surface-3 text-muted",
};
export function Badge({ tone = "gray", children, className }: { tone?: keyof typeof TONES | string; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium", TONES[tone] ?? TONES.gray, className)}>{children}</span>;
}
export const statusTone = (s: string) => ({
  active: "green", scheduled: "sky", draft: "gray", paused: "amber", completed: "violet",
  "Done": "green", "In progress": "sky", "Not started": "gray", "Blocked": "rose",
  pass: "green", warn: "amber", blocked: "rose", signed: "green", pilot: "violet", in_conversation: "sky",
  contacted: "amber", identified: "gray", declined: "rose", positive: "green", neutral: "gray", negative: "rose",
  P0: "rose", P1: "amber", P2: "gray", completed_run: "green", partial: "amber", failed: "rose", running: "sky",
} as Record<string, string>)[s] ?? "gray";

export const kindTone = (k: string) => ({
  design_partner: "violet", co_sell: "sky", distribution: "green", referral_affiliate: "amber", integration: "gray",
} as Record<string, string>)[k] ?? "gray";

/* ---------- form fields ---------- */
const inputCls = "h-9 rounded-lg border border-line-strong bg-surface-2 px-3 text-sm placeholder:text-faint focus:border-vireo focus:outline-none";
/** Label + control, linked by id (so the control's accessible name is exactly the label). */
export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, { id, "aria-describedby": hint ? `${id}-hint` : undefined })
    : children;
  return (
    <div className={cx("block", className)}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">{label}</label>
      {control}
      {hint && <span id={`${id}-hint`} className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </div>
  );
}
// full width unless the caller sets its own width (w-auto, w-48, max-w-…)
const width = (c?: string) => (c && /(^|\s)(w-|max-w-)/.test(c) ? "" : "w-full");
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(inputCls, width(p.className), p.className)} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(inputCls, "pr-8", width(p.className), p.className)} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
  <textarea {...p} className={cx(inputCls, "h-auto min-h-[84px] py-2 leading-relaxed", width(p.className), p.className)} />;

/* ---------- modal ---------- */
export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    ref.current?.querySelector<HTMLElement>("input,select,textarea")?.focus();
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className={cx("rise w-full rounded-2xl border border-line-strong bg-surface shadow-2xl", wide ? "max-w-3xl" : "max-w-lg")}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="font-serif text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-3 hover:text-ink" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4 scroll-thin">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ open, onClose, onConfirm, title, body, busy }: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: string; body: ReactNode; busy?: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}>Delete</Button></>}>
      <div className="flex gap-3 text-sm text-muted"><AlertTriangle className="shrink-0 text-rose" size={18} />{body}</div>
    </Modal>
  );
}

/* ---------- bits ---------- */
export function Stat({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted">
        <span className="uppercase tracking-wider">{label}</span>
        {icon && <span className={cx("rounded-md p-1.5", TONES[tone ?? "green"])}>{icon}</span>}
      </div>
      <div className="num mt-2 text-[26px] font-medium leading-none text-ink">{value}</div>
      {sub && <div className="mt-1.5 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

export function Progress({ value, max, tone = "vireo" }: { value: number; max: number; tone?: string }) {
  const p = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuenow={Math.round(p)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.max(p, value > 0 ? 1.5 : 0)}%`, background: `var(--${tone})` }} />
    </div>
  );
}

export function Empty({ icon, title, body, action }: { icon: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-xl bg-vireo-soft p-3 text-vireo">{icon}</div>
      <div className="font-serif text-lg font-semibold">{title}</div>
      {body && <p className="mt-1 max-w-sm text-sm text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="flex items-center justify-center gap-2 py-16 text-muted"><Loader2 className="animate-spin" size={18} />{label}…</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div role="alert" className="mb-3 rounded-lg border border-rose/30 bg-rose-soft px-3 py-2 text-sm text-rose">{String((error as Error).message ?? error)}</div>;
}

/* ---------- toast ---------- */
const ToastCtx = createContext<(msg: string, tone?: "ok" | "err") => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; tone: string }[]>([]);
  const push = useCallback((msg: string, tone: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg, tone }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[60] flex flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx("rise pointer-events-auto rounded-lg border px-3.5 py-2.5 text-sm shadow-card",
            t.tone === "err" ? "border-rose/40 bg-surface text-rose" : "border-vireo/40 bg-surface text-ink")}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
