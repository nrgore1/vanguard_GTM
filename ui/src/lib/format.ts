export const usd = (n: number | null | undefined, compact = false) =>
  n == null ? "—" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: compact ? 1 : Math.abs(n) >= 1000 ? 0 : 2,
    notation: compact ? "compact" : "standard",
  }).format(n);

export const num = (n: number | null | undefined, compact = false) =>
  n == null ? "—" : new Intl.NumberFormat("en-US", { notation: compact ? "compact" : "standard", maximumFractionDigits: 1 }).format(n);

export const pct = (a: number, b: number) => (b > 0 ? `${((a / b) * 100).toFixed(1)}%` : "—");

export const shortDate = (s: string | null | undefined) =>
  s ? new Date(s.length === 10 ? s + "T00:00:00" : s).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";

export const relTime = (s: string | null | undefined) => {
  if (!s) return "never";
  const d = (Date.now() - new Date(s.length === 10 ? s + "T00:00:00" : s).getTime()) / 86400000;
  if (d < 1) return "today";
  if (d < 2) return "yesterday";
  if (d < 30) return `${Math.floor(d)}d ago`;
  return shortDate(s);
};

export const today = () => new Date().toISOString().slice(0, 10);

export const label = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const TRACKS: Record<string, string> = {
  A: "Institutional & fintech", B: "Relationship & community", C: "AI & cognitive",
};

export const STAGES = ["identified", "contacted", "in_conversation", "pilot", "signed", "declined"] as const;
export const CAMPAIGN_STATUSES = ["draft", "scheduled", "active", "paused", "completed"] as const;
export const PARTNER_KINDS = ["design_partner", "co_sell", "distribution", "referral_affiliate", "integration"] as const;
