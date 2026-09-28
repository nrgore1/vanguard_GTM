import { useState } from "react";
import { Navigate } from "react-router-dom";
import { ArrowRight, Lock } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { Logo } from "../components/Layout";

export default function Login() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (user) return <Navigate to="/" replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(email, password); } catch (err) { setError(err); } finally { setBusy(false); }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="flex items-center gap-3"><Logo size={34} /><span className="font-serif text-xl font-semibold">Vanguard-GTM</span></div>
        <div className="max-w-md">
          <div className="mb-4 font-mono text-[11px] uppercase tracking-[0.22em] text-vireo">Portfolio go-to-market</div>
          <h1 className="font-serif text-[40px] font-semibold leading-[1.1]">Eight launch engines.<br />One ledger of what's working.</h1>
          <p className="mt-5 text-[15px] leading-relaxed text-muted">
            Plan with the agent, run campaigns, work design and co-selling partners, and track every result against the $2M target for each property.
          </p>
        </div>
        <svg viewBox="0 0 400 120" className="w-full max-w-md opacity-80" aria-hidden>
          {[18, 26, 22, 34, 30, 44, 52, 48, 63, 71, 80, 96].map((h, i) => (
            <rect key={i} x={i * 33} y={120 - h} width="20" height={h} rx="3" fill={i > 8 ? "var(--vireo)" : "var(--line-strong)"} />
          ))}
        </svg>
      </section>
      <section className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="rise w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden"><Logo size={32} /><span className="font-serif text-xl font-semibold">Vanguard-GTM</span></div>
          <h2 className="font-serif text-2xl font-semibold">Sign in</h2>
          <p className="mb-6 mt-1 text-sm text-muted">Use the account your admin created for you.</p>
          <ErrorNote error={error} />
          <div className="space-y-4">
            <Field label="Email"><Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@vireoka.com" /></Field>
            <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
            <Button variant="primary" type="submit" loading={busy} className="w-full" icon={<Lock size={15} />}>Sign in <ArrowRight size={15} /></Button>
          </div>
          <p className="mt-6 text-xs text-faint">First time? Run <code className="font-mono text-muted">vanguard seed-users</code> to create the admin and team accounts.</p>
        </form>
      </section>
    </div>
  );
}
