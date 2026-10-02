// Typed client for the Vanguard-GTM web API (/api). Token lives in localStorage.
export type Role = "admin" | "user";
export interface User { id: number; email: string; name: string; role: Role }
export interface Property {
  id: string; url: string; name: string; track: string; motion: string; positioning_status: string;
  task_prefix: string; positioning: string; pricing_facts: string[];
}
export type CampaignStatus = "draft" | "scheduled" | "active" | "paused" | "completed";
export interface Campaign {
  id: number; property_id: string; name: string; kind: string; channel: string | null; status: CampaignStatus;
  start_date: string | null; end_date: string | null; budget_usd: number; goal_metric: string | null;
  goal_value: number | null; description: string | null; content: string | null; owner_id: number | null;
  owner_name?: string | null; created_by: number | null; source_run_id: string | null; updated_at: string;
  sent?: number; replies?: number; meetings?: number; signups?: number; conversions?: number;
  revenue_usd?: number; spend_usd?: number; results?: Result[];
  outreach?: CampaignOutreach; outreach_summary?: { targets: number; emails_sent: number; social_touches: number; replies: number; meetings: number };
}
export interface CampaignOutreachTotals {
  targets: number; emails_sent: number; social_touches: number; touched: number; replies: number; meetings: number;
  in_conversation: number; pilot: number; signed: number; declined: number;
}
export interface CampaignPartnerRow {
  id: number; name: string; stage: PartnerStage; priority: string | null; priority_score: number | null;
  contact_name: string | null; contact_email: string | null; next_step: string | null; next_step_date: string | null;
  emails_sent: number; social_touches: number; meetings: number; replied: boolean; drafts: number; approved: number;
  steps: number; last_touch: string | null; next_due: string | null;
}
export interface CampaignOutreach {
  partners: CampaignPartnerRow[]; totals: CampaignOutreachTotals;
  queue: { drafts: number; approved: number; missing_email: number; next_due: string | null };
}
export interface Result {
  id: number; campaign_id: number; date: string; sent: number; opens: number; clicks: number; replies: number;
  meetings: number; signups: number; conversions: number; revenue_usd: number; spend_usd: number;
  notes: string | null; created_by: number | null; by_name?: string;
}
export type PartnerStage = "identified" | "contacted" | "in_conversation" | "pilot" | "signed" | "declined";
export type PartnerKind = "design_partner" | "co_sell" | "distribution" | "referral_affiliate" | "integration" | "investor";
export interface Partner {
  id: number; property_id: string; name: string; kind: PartnerKind; stage: PartnerStage; partner_type: string | null;
  contact_name: string | null; contact_email: string | null; value_sharing_model: string | null;
  mutual_value: string | null; first_ask: string | null; next_step: string | null; next_step_date: string | null;
  owner_id: number | null; owner_name?: string | null; interactions?: number | Interaction[]; source_run_id?: string | null;
  last_contact?: string | null; created_by: number | null; updated_at: string;
  category?: string | null; is_segment?: number; priority_score?: number | null; priority?: "P0" | "P1" | "P2" | null;
  factors?: Record<string, number> | null; rationale?: string | null; deal_structure?: string | null;
  how_to_find?: string | null; website?: string | null; source?: string | null; parent_id?: number | null;
  agreement_status?: AgreementStatus | null; agreement_signed_date?: string | null; agreement_notes?: string | null;
  outreach?: OutreachMessage[]; targets?: { id: number; name: string; stage: string; contact_email: string | null; agreement_status: string | null }[];
  segment_name?: string | null; email_consent?: EmailConsent | null;
  campaign_id?: number | null; campaign_name?: string | null;
  connections?: number | LinkedInConnection[]; intros?: Intro[]; mutuals_url?: string;
}
export interface LinkedInConnection {
  id: number; first_name: string; last_name: string; profile_url: string | null; email: string | null; company: string | null;
  position: string | null; connected_on: string | null; owner_name: string | null; is_contact: boolean;
}
export type IntroStatus = "suggested" | "draft" | "approved" | "sent" | "accepted" | "introduced" | "declined" | "cancelled";
export interface Intro {
  id: number; partner_id: number; connection_id: number; path: "direct" | "bridge"; reason: string | null; score: number;
  status: IntroStatus; channel: "email" | "linkedin"; subject: string | null; body: string | null; blurb: string | null;
  lint_status: string | null; lint_findings: string | null; approved_by: string | null; sent_at: string | null; outcome: string | null;
  partner_name: string; partner_kind: PartnerKind; priority: string | null; priority_score: number | null; property_id: string;
  target_contact: string | null; first_name: string; last_name: string; position: string | null; company: string | null;
  email: string | null; profile_url: string | null; strength: number | null; msg_count: number | null;
  last_message_at: string | null; endorsements: number | null; mutuals_url: string;
}
export interface AgentStatus {
  version: string; provider: string; local_model: string; local_ok: boolean | null; local_message: string;
  paid_runs: boolean; cap_usd: number; claude_model: string; claude_key_set: boolean; notion_token_set: boolean;
  email?: EmailStatus;
}
export type EmailConsent = "none" | "opted_in" | "existing_relationship" | "replied" | "opted_out";
export interface PostmarkStatus {
  configured: boolean; stream_outreach: string; stream_notify: string; inbound: boolean; allow_cold: boolean;
  cold_via_smtp: boolean; monthly_cap: number; track_opens: boolean; webhook_auth: boolean; used_this_month?: number;
}
export interface EmailStatus {
  mode: string; live: boolean; problems: string[]; sender: string; daily_cap: number; imap_configured: boolean;
  postmark: PostmarkStatus | null;
}
export type AgreementStatus = "none" | "proposed" | "negotiating" | "signed" | "declined";
export type OutreachStatus = "draft" | "approved" | "sent" | "replied" | "cancelled" | "failed" | "bounced";
export interface OutreachMessage {
  id: number; partner_id: number; step: number; delay_days: number; subject: string; body: string; status: OutreachStatus;
  lint_status: string; lint_findings: string | null; approved_by: string | null; approved_at: string | null;
  sent_at: string | null; to_email: string | null; error: string | null; replied_at: string | null;
  partner_name?: string; property_id?: string; partner_kind?: string; partner_stage?: string; contact_email?: string | null;
  contact_name?: string | null; priority_score?: number | null; priority?: string | null;
  transport?: string | null; pm_message_id?: string | null; delivered_at?: string | null; opened_at?: string | null;
  campaign_id?: number | null; campaign_name?: string | null;
}
export interface OutreachStats {
  draft: number; approved: number; sent: number; replied: number; cancelled: number; failed: number; bounced: number;
  ever_sent: number; blocked: number; partners_contacted: number; partners_replied: number; reply_rate: number | null;
  sent_today: number; suppressed: number;
  email: EmailStatus;
}
export interface Interaction {
  id: number; partner_id: number; date: string; type: string; summary: string; outcome: string;
  next_step: string | null; created_by: number | null; by_name?: string; partner_name?: string; property_id?: string;
}
export type TaskStatus = "Not started" | "In progress" | "Done" | "Blocked";
export interface Task {
  id: number; run_id: string; property_id: string; task_id: string; day: number; priority: "P0" | "P1" | "P2";
  owner: string; tool?: string | null; status: TaskStatus; description: string; category: string; kpi: string;
  dependencies: string[]; assignee_id: number | null; assignee_name: string | null; due_date: string | null;
  notes: string | null;
}
export interface PropertyDash {
  property_id: string; name: string; track: string; arr_target_usd: number; monthly_conversions_target: number;
  revenue_to_date_usd: number; arr_run_rate_usd: number; funnel: Record<string, number>;
  campaigns: { total: number; active: number }; partners: Record<string, number>;
  tasks: { total: number; done: number }; playbook: { lint_status: string; approved_by: string | null } | null;
  agreements: Record<AgreementStatus, number>; outreach: { drafts: number; approved: number; sent: number; replied: number };
}
export interface Dashboard {
  properties: PropertyDash[]; weekly: { week: string; start: string; revenue_usd: number; conversions: number;
    meetings: number; signups: number }[];
  latest_run: string | null; recent_interactions: Interaction[];
  my_open_tasks: { id: number; property_id: string; task_id: string; status: string; priority: string; description: string }[];
}
export interface Run {
  id: string; created_at: string; finished_at: string | null; status: string; property_ids: string[];
  errors: Record<string, string>; usage: Record<string, number | string>;
  playbooks?: { property_id: string; lint_status: string; approved_by: string | null }[];
}

export type TripStatus = "not_yet_due" | "green" | "amber" | "tripped";
export interface TripwireRow {
  id: string; failure_mode: string; signal: string; unit: string; basis: string; action: string; status: TripStatus;
  latest_value: number | null; latest_date: string | null; next_check: string | null; next_check_week: number | null;
  schedule: string; due_checks: { week: number; date: string; rule: string; value: number | null; result: string }[];
}
export interface GateRow {
  id: string; name: string; verify: string; walk_away_if: string; deadline: string; deadline_week: number;
  blocks: string[]; status: "open" | "passed" | "failed"; overdue: boolean; note: string; updated_by: string;
}
export interface FailproofProperty {
  property_id: string; owner: string | null; interim_owner?: boolean; focus: "primary" | "founder" | "delegated"; one_sentence: string;
  tripwires: TripwireRow[]; gates: GateRow[]; tripped: number; amber: number; gates_passed: number; gates_overdue: number;
  halt: boolean; focus_issues: string[]; blocked_classes: Record<string, string[]>;
  failure_modes: { id: string; name: string; cause: string; assumption: string; first_warning: string }[];
}
export interface Failproof { as_of: string; week: number; program_start: string; properties: FailproofProperty[] }

const TOKEN = "vanguard.token";
export const session = {
  get token() { try { return localStorage.getItem(TOKEN); } catch { return null; } },
  set(t: string) { try { localStorage.setItem(TOKEN, t); } catch { /* private mode */ } },
  clear() { try { localStorage.removeItem(TOKEN); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  const r = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (r.status === 401 && path !== "/auth/login") {
    session.clear();
    window.dispatchEvent(new Event("vanguard:logout"));
  }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { loc?: string[]; msg: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ")
        : msg;
    } catch { /* not JSON */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

const qs = (o: Record<string, string | number | boolean | undefined>) => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== "" && v !== false);
  return p.length ? "?" + new URLSearchParams(p.map(([k, v]) => [k, String(v)])).toString() : "";
};

export const api = {
  login: (email: string, password: string) => req<{ token: string; user: User }>("POST", "/auth/login", { email, password }),
  me: () => req<User>("GET", "/me"),
  properties: () => req<Property[]>("GET", "/properties"),
  dashboard: () => req<Dashboard>("GET", "/dashboard"),
  setTarget: (pid: string, b: { arr_target_usd: number; monthly_conversions_target: number; notes?: string }) =>
    req("PUT", `/targets/${pid}`, b),

  campaigns: (f: { property_id?: string; status?: string } = {}) => req<Campaign[]>("GET", `/campaigns${qs(f)}`),
  campaign: (id: number) => req<Campaign>("GET", `/campaigns/${id}`),
  createCampaign: (b: Partial<Campaign>) => req<{ id: number }>("POST", "/campaigns", b),
  updateCampaign: (id: number, b: Partial<Campaign>) => req("PATCH", `/campaigns/${id}`, b),
  deleteCampaign: (id: number) => req("DELETE", `/campaigns/${id}`),
  addResult: (id: number, b: Partial<Result>) => req<{ id: number }>("POST", `/campaigns/${id}/results`, b),
  deleteResult: (id: number) => req("DELETE", `/results/${id}`),
  attachPartners: (id: number, partner_ids: number[]) =>
    req<{ attached: { id: number; name: string }[]; moved: { id: number; name: string; from: string }[]; refused: { id: number; name?: string; reason: string }[] }>("POST", `/campaigns/${id}/partners`, { partner_ids }),
  detachPartner: (id: number, pid: number) => req("DELETE", `/campaigns/${id}/partners/${pid}`),

  partners: (f: { property_id?: string; kind?: string } = {}) => req<Partner[]>("GET", `/partners${qs(f)}`),
  partner: (id: number) => req<Partner & { interactions: Interaction[] }>("GET", `/partners/${id}`),
  createPartner: (b: Partial<Partner>) => req<{ id: number }>("POST", "/partners", b),
  updatePartner: (id: number, b: Partial<Partner>) => req("PATCH", `/partners/${id}`, b),
  deletePartner: (id: number) => req("DELETE", `/partners/${id}`),
  addInteraction: (id: number, b: Partial<Interaction> & { stage?: PartnerStage }) =>
    req<{ id: number }>("POST", `/partners/${id}/interactions`, b),
  deleteInteraction: (id: number) => req("DELETE", `/interactions/${id}`),
  importLinkedIn: (csv: string) => req<{ connections: number; added: number; refreshed: number; partners_with_connections: number;
    contacts_connected: string[]; emails_filled: string[] }>("POST", "/linkedin/connections", { csv }),
  importLinkedInZip: (zip_b64: string) => req<{ connections: number; added: number; refreshed: number; partners_with_connections: number;
    contacts_connected: string[]; emails_filled: string[]; with_messages?: number; warm?: number }>("POST", "/linkedin/export", { zip_b64 }),
  suggestIntros: (property_ids?: string[]) => req<{ targets: number; suggested: number; direct: number; error?: string }>("POST", "/intros/suggest", { property_ids }),
  intros: (f: { status?: string; partner_id?: number; kind?: string } = {}) => req<Intro[]>("GET", `/intros${qs(f as Record<string, string | undefined>)}`),
  draftIntro: (id: number) => req("POST", `/intros/${id}/draft`),
  editIntro: (id: number, b: { subject?: string; body?: string }) => req<{ lint_status: string; lint_findings: string | null }>("PATCH", `/intros/${id}`, b),
  approveIntros: (ids: number[]) => req<{ approved: number[]; refused: { id: number; reason: string }[] }>("POST", "/intros/approve", { ids }),
  sendIntros: () => req<{ sent: { id: number; to: string; email: string; target: string }[]; skipped: { id: number; to: string; reason: string }[]; mode: string; error?: string }>("POST", "/intros/send"),
  introSentLinkedIn: (id: number) => req("POST", `/intros/${id}/sent-linkedin`),
  introOutcome: (id: number, outcome: string, note?: string) => req("POST", `/intros/${id}/outcome`, { outcome, note }),
  linkedInSummary: () => req<{ by_user: { owner_id: number | null; owner_name: string | null; n: number; last_import: string }[]; partners_with_connections: number }>("GET", "/linkedin/connections"),
  deleteMyLinkedIn: () => req<{ deleted: number }>("DELETE", "/linkedin/connections"),

  importResearch: () => req<{ properties: Record<string, { created: number; updated: number }>; errors: string[]; without_email: number;
    investors?: { created: number; updated: number; by_priority: Record<string, number> } }>("POST", "/partners/import-research"),
  recommendPartners: (b: { property_id: string; mode: "offline" | "model"; provider?: string }) =>
    req<{ partners: number; updated: number; messages: number; recommendations: { rank: number; name: string; kind: string; score: number; priority: string; lint_status: string }[] }>("POST", "/partners/recommend", b),
  addTarget: (segmentId: number, b: { name: string; contact_name?: string; contact_email?: string; website?: string }) =>
    req<{ id: number }>("POST", `/partners/${segmentId}/targets`, b),
  recordReply: (pid: number, b: { date: string; summary: string; outcome?: string; kind: string }) =>
    req<{ classification: string; outcome: string; cancelled_steps: number; stage: string }>("POST", `/partners/${pid}/reply`, b),
  outreach: (f: { status?: string; property_id?: string; partner_id?: number; campaign_id?: number } = {}) =>
    req<OutreachMessage[]>("GET", `/outreach${qs(f as Record<string, string | undefined>)}`),
  outreachStats: () => req<OutreachStats>("GET", "/outreach/stats"),
  editOutreach: (id: number, b: { subject?: string; body?: string }) =>
    req<{ ok: boolean; lint_status: string; lint_findings: { rule_id: string; message: string; excerpt: string; severity: string }[] }>("PATCH", `/outreach/${id}`, b),
  approveOutreach: (ids: number[]) => req<{ approved: number[]; refused: { id: number; reason: string }[] }>("POST", "/outreach/approve", { ids }),
  cancelOutreach: (id: number) => req("POST", `/outreach/${id}/cancel`),
  sendDue: () => req<{ sent: { id: number; partner: string; step: number; to: string; transport?: string }[]; skipped: { id: number; partner: string; step: number; reason: string }[]; mode: string }>("POST", "/outreach/send-due"),
  syncReplies: () => req<{ matched: number; bounces: number; unmatched: number; duplicates: number }>("POST", "/outreach/sync-replies"),
  sendDigest: () => req<{ sent: number; transport?: string; reason?: string }>("POST", "/outreach/digest"),
  postmarkSync: () => req<{ stream: string; pulled: number; pushed: number; remote_total: number }>("POST", "/outreach/postmark-sync"),
  postmarkStatus: () => req<{ ok: boolean; streams: Record<string, string>; missing: string[]; not_transactional: string[]; error?: string;
    used_this_month: number; monthly_cap: number }>("GET", "/email/postmark"),

  tasks: (f: { property_id?: string; status?: string; mine?: boolean } = {}) => req<Task[]>("GET", `/tasks${qs(f)}`),
  createTask: (b: Record<string, unknown>) => req<{ task_id: string }>("POST", "/tasks", b),
  updateTask: (id: number, b: Partial<Task>) => req("PATCH", `/tasks/${id}`, b),
  deleteTask: (id: number) => req("DELETE", `/tasks/${id}`),

  users: () => req<(User & { active?: number; last_login?: string | null; created_at?: string })[]>("GET", "/users"),
  createUser: (b: { email: string; name: string; role: Role; password: string }) => req("POST", "/users", b),
  updateUser: (id: number, b: Partial<{ name: string; role: Role; active: boolean; password: string }>) =>
    req("PATCH", `/users/${id}`, b),
  deleteUser: (id: number) => req("DELETE", `/users/${id}`),

  agentStatus: () => req<AgentStatus>("GET", "/agent/status"),
  runs: () => req<Run[]>("GET", "/runs"),
  run: (id: string) => req<Run>("GET", `/runs/${id}`),
  playbook: <T,>(run: string, pid: string) => req<T>("GET", `/runs/${run}/playbooks/${pid}`),
  startRun: (b: { properties: string[]; dry_run: boolean; provider?: string }) =>
    req<{ run_id: string }>("POST", "/runs", b),
  approve: (run: string, pid: string) => req("POST", `/runs/${run}/approve/${pid}`),
  importRun: (run: string) => req<{ campaigns: number; partners: number; messages: number; skipped: number }>("POST", `/runs/${run}/import`),
  syncRun: (run: string) => req<{ playbooks: number; tasks: number }>("POST", `/runs/${run}/sync`),
  failproof: (f: { as_of?: string; property_id?: string } = {}) => req<Failproof>("GET", `/failproof${qs(f)}`),
  recordReading: (pid: string, b: { tripwire_id: string; value: number; date?: string; note?: string }) =>
    req("POST", `/failproof/${pid}/readings`, b),
  setGate: (pid: string, gid: string, b: { status: "open" | "passed" | "failed"; note?: string }) =>
    req<{ ok: boolean; walk_away_if: string | null }>("PUT", `/failproof/${pid}/gates/${gid}`, b),
  audit: () => req<{ id: number; at: string; user_name: string | null; action: string; entity: string; entity_id: string; detail: string | null }[]>("GET", "/audit"),
};
