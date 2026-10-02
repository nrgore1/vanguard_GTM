import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LayoutDashboard, Megaphone, Handshake, ListChecks, ShieldCheck, LogOut, Sun, Moon, Menu, X, Send, Siren, Network } from "lucide-react";
import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { Badge, cx } from "./ui";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--surface-3)" stroke="var(--line-strong)" />
      <path d="M8 9l8 15 8-15" stroke="var(--vireo)" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function useTheme() {
  const [theme, setTheme] = useState<string>(() => { try { return localStorage.getItem("vanguard.theme") ?? "dark"; } catch { return "dark"; } });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("vanguard.theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))] as const;
}

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const [theme, toggle] = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  const nav = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/campaigns", label: "Campaigns", icon: Megaphone },
    { to: "/partners", label: "Partners", icon: Handshake },
    { to: "/outreach", label: "Outreach", icon: Send },
    { to: "/intros", label: "Introductions", icon: Network },
    { to: "/tasks", label: "Tasks", icon: ListChecks },
    { to: "/tripwires", label: "Tripwires", icon: Siren },
    ...(isAdmin ? [{ to: "/admin", label: "Admin", icon: ShieldCheck }] : []),
  ];

  const sidebar = (
    <nav className="flex h-full flex-col" aria-label="Main">
      <div className="flex items-center gap-2.5 px-5 pb-6 pt-5">
        <Logo />
        <div>
          <div className="font-serif text-[17px] font-semibold leading-none">Vanguard</div>
          <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted">GTM · Vireoka</div>
        </div>
      </div>
      <div className="flex-1 space-y-0.5 px-3">
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
            className={({ isActive }) => cx(
              "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              isActive ? "bg-vireo-soft text-vireo font-medium" : "text-muted hover:bg-surface-3 hover:text-ink")}>
            <n.icon size={17} />{n.label}
          </NavLink>
        ))}
      </div>
      <div className="m-3 rounded-xl border border-line bg-surface-2 p-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-full bg-surface-3 text-xs font-semibold text-vireo">
            {user?.name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.name}</div>
            <div className="truncate text-[11px] text-muted">{user?.email}</div>
          </div>
          <Badge tone={isAdmin ? "violet" : "gray"}>{user?.role}</Badge>
        </div>
        <div className="mt-3 flex gap-1.5">
          <button onClick={toggle} className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-line py-1.5 text-xs text-muted hover:text-ink"
            aria-label="Toggle theme">{theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}{theme === "dark" ? "Light" : "Dark"}</button>
          <button onClick={logout} className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-line py-1.5 text-xs text-muted hover:text-rose">
            <LogOut size={13} />Sign out</button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-line bg-surface/80 backdrop-blur lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-64 border-r border-line bg-surface" onClick={(e) => e.stopPropagation()}>{sidebar}</aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-bg/80 px-4 py-3 backdrop-blur lg:hidden">
          <button onClick={() => setOpen(!open)} aria-label="Menu" className="rounded-md p-1.5 text-muted hover:bg-surface-3">{open ? <X size={20} /> : <Menu size={20} />}</button>
          <Logo size={24} /><span className="font-serif font-semibold">Vanguard</span>
        </header>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-7 sm:px-8"><Outlet /></main>
      </div>
    </div>
  );
}
