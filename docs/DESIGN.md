# Vanguard-GTM — Detailed Design Document

| | |
|---|---|
| **System** | Vanguard-GTM, the go-to-market orchestration agent for the Vireoka portfolio |
| **Version** | 0.13.0 |
| **Owner** | Narendra Gore, Vireoka LLC |
| **Last updated** | 2026-10-02 |
| **Companion docs** | [Programmer's Manual](PROGRAMMERS_MANUAL.md) · [Test Cases](TEST_CASES.md) · [Setup: Notion & keys](SETUP_NOTION_AND_KEYS.md) · [User Guide](USER_GUIDE.md) · [Changelog](../CHANGELOG.md) |

> **Keeping this current.** Every change to behaviour, configuration, the CLI, the API or the
> data model updates this document and the Programmer's Manual in the same change, and adds a
> line to the change log (§18). `tests/test_docs_sync.py` fails the build if a CLI command,
> environment variable, config field or test ID is missing from the docs.

---

## 1. Purpose

Vanguard-GTM turns each portfolio property into a US go-to-market playbook and a 30-day task
backlog aimed at **$2M ARR per property**. It works through four fixed stages, then pushes the
results into Notion so the work can be tracked. It is a **planning and tracking system**. It
never sends email, publishes posts or spends ad money on its own.

### 1.1 Goals

1. **Grounded in the real products.** Plans are written from each product's own repo docs
   (§4), not from generic category descriptions.
2. **Claim discipline by construction.** No customer, traction or revenue claims. No unsourced
   numbers, and none of the phrasing a property has ruled out. This is enforced in code (§7),
   not only in prompts.
3. **Execution-ready output.** Typed JSON goes into Notion databases and dispatcher-ready CSVs.
4. **Parallel across the portfolio.** All eight properties run at once. If one fails, the rest
   still finish.
5. **$0 by default.** Paid Claude API calls are off until you set a spend cap. The dry run, the
   manual chat path (`prompt`/`import`) and Notion cost nothing. When paid runs are on, every
   run is estimated beforehand, metered while it runs and capped (§9).

### 1.2 Non-goals

- Autonomous sending or publishing. Human approval gates every export (§8).
- A CRM or an email dispatcher. Vanguard hands off to Smartlead, Instantly or SendGrid as files.
- Legal or compliance sign-off. The lint gate is a first filter, not a lawyer.

---

## 2. Context

```mermaid
flowchart LR
  U[Narendra] -->|CLI / HTTP API| V[Vanguard-GTM]
  R[(vireoka-dev repos<br/>PRDs · positioning)] -.refresh.-> CFG[config/properties.yaml]
  CFG --> V
  V -->|Messages API<br/>forced tool use| C[(Claude API)]
  V -->|REST 2022-06-28| N[(Notion<br/>Playbooks · Tasks)]
  V -->|CSV files| D[Smartlead / Instantly / Linear / Jira]
  CH[Claude chat<br/>subscription] -.manual $0 path.-> V
```

| External system | Direction | Contract | Cost |
|---|---|---|---|
| Claude API | outbound HTTPS | Messages API, forced `tool_choice`, optional `web_search_20250305` server tool | Pay per token (§9) |
| Notion | outbound HTTPS | REST API, `Notion-Version: 2022-06-28`, internal-connection bearer token | $0 for API use |
| Claude chat | manual copy/paste | `vanguard prompt` → chat → `vanguard import` | Covered by your Claude plan |
| Dispatchers / backlogs | files | CSV (sequence steps; tasks) | n/a |

---

## 3. Architecture

```mermaid
flowchart TB
  subgraph Entry
    CLI[cli.py]:::e
    API[api.py FastAPI]:::e
  end
  CLI & API --> ORC[orchestrator.py<br/>asyncio.gather + Semaphore]
  ORC -->|per property| PIPE
  subgraph PIPE[engines.run_property]
    E1[Engine 1 Market & ICP<br/>+ optional web research] --> E2[Engine 2 Partnerships]
    E2 --> E2B[Engine 2B Partner outreach<br/>recommend · score · draft]
    E2 --> E3[Engine 3 Campaigns<br/>social + 5-step email]
    E3 --> LG{lint_gate.py}
    LG -- blocking findings, ≤2 passes --> E3
    LG --> E4[Engine 4 30-day tasks]
    E4 --> ASM[assemble → Playbook + notes]
  end
  PIPE <--> LLM[llm.py ClaudeLLM / MockLLM]
  LLM --> MET[cost.py Meter + cap]
  ASM --> ST[(store.py SQLite)]
  ST --> NS[notion_sync.py] --> NOTION[(Notion)]
  ST --> EX[exporters.py] --> FILES[CSV / JSON]
  REG[registry.py ← properties.yaml] --> PIPE
  LGC[lint_gate.yaml] --> LG
  classDef e fill:#eef,stroke:#88a
```

### 3.1 Module responsibilities

| Module | Responsibility | Key types / functions |
|---|---|---|
| `registry.py` | Load and validate `properties.yaml`, render the per-property brief | `Property`, `load_properties`, `get_properties`, `Property.brief()` |
| `schema.py` | Pydantic contracts for every engine and the final playbook | `MarketIntel`, `PartnershipPlan`, `CampaignPlan`, `TaskPlan`, `Playbook` |
| `partners.py` | Engine 2B: expert playbooks, deterministic scoring, offline plan, model plan with lint repair | `offline_plan`, `plan_partners`, `score` |
| `targets.py` | Loads researched, real organisations (`config/partner_targets.yaml`) as named partners under their category, idempotently | `import_targets`, `load` |
| `outreach.py` | Approval-gated sending (outbox/SMTP/Postmark), consent routing, compliance footer, suppression, IMAP reply matching, reply classification, team notifications | `send_due`, `approve`, `record_reply`, `sync_replies`, `notify_reply`, `send_digest`, `EmailConfig` |
| `postmark.py` | Postmark Email API client, stream payloads, webhook event handling (bounce, spam, delivery, open, subscription, inbound), suppression sync, stream check | `PostmarkClient`, `PostmarkMailer`, `handle_event`, `sync_suppressions`, `check_streams` |
| `providers.py` | Local models (Ollama or any OpenAI-compatible server) and the local-first chain with Claude as fallback | `LocalLLM`, `FallbackLLM`, `LocalUnavailable`, `extract_json` |
| `llm.py` | Claude client: structured output through forced tool use, validation retry, web research, metering | `ClaudeLLM`, `MockLLM`, `inline_schema` |
| `engines.py` | Prompts and the four-engine pipeline, the lint repair loop, assembly, the manual prompt and import | `run_property`, `assemble`, `manual_prompt`, `import_playbook` |
| `lint_gate.py` | Rule engine over outward-facing copy | `LintGate`, `copy_fields` |
| `cost.py` | Price table, usage meter, spend cap, estimate | `Meter`, `BudgetExceeded`, `estimate` |
| `orchestrator.py` | Parallel fan-out, per-property error isolation, run bookkeeping, then the fail-proof layer | `run_portfolio` |
| `failproof.py` | Engine 0 premortem, Engine 5 readiness gates, Engine 6 tripwire monitor, focus lock (§17) | `load_failproof`, `evaluate_tripwire`, `tracker`, `apply_to_playbook`, `run_premortem`, `FailproofStore` |
| `store.py` | Persistence: runs (with usage), playbooks, tasks, approvals, Notion ids | `Store` |
| `db.py` | SQLite or PostgreSQL connections, SQL translation for PostgreSQL, SQLite-to-PostgreSQL copy (§10) | `Database`, `copy_from_sqlite` |
| `notion_sync.py` | Database setup, idempotent upsert, rate limiting, playbook page body | `Notion`, `playbook_blocks` |
| `exporters.py` | Approval-gated sequence CSVs; task backlog CSV/JSON | `export_sequences`, `export_tasks` |
| `web/app.py` | Web app: `/api` for the UI (auth, roles, CRUD, dashboard, agent actions), serves `ui/dist`, mounts `/machine` | `create_app`, `current_user`, `admin_user` |
| `web/db.py` | Web tables and queries: users, campaigns, results, partners, interactions, targets, audit; import from runs; dashboard aggregation | `WebStore` |
| `web/security.py` | PBKDF2 password hashing, HS256 session tokens | `hash_password`, `make_token`, `read_token` |
| `web/demo.py` | `[DEMO]` data load and purge | `load_demo`, `purge_demo` |
| `ui/` | React front end (Vite + TypeScript + Tailwind) and Playwright browser tests | see §14.5 |
| `cli.py` / `api.py` | Entry points (`api.py` is the machine API, mounted at `/machine`) | see Programmer's Manual §4–5 |

---

## 4. Property registry (source of truth)

`config/properties.yaml` holds one entry per property. It overrides the one-line descriptions in
the original Vanguard-GTM prompt, several of which were wrong. For example, LiqMint is not a
"stablecoin yield platform".

**Refresh of 2026-09-27** from `C:\Users\NAREN\vireoka-dev`:

| Property | Status | Refreshed from | What changed |
|---|---|---|---|
| liqmint.com | confirmed | `liqmint-institutional-canton/docs/LiqMint_R0_Launch_Plan.md`, `R0_Funnel_Tracking.md`, R0 billing docs | Now **R0 retail**: the non-custodial stablecoin safety layer, $19.99/mo. The activation event is the first completed safety check. The growth model is a content-to-conversion loop. |
| institutional.liqmint.com | confirmed | `docs/positioning/liqmint-treasury-os-positioning.md`, Institutional Master PRD v1.1 | Governed stablecoin treasury OS. Reference package $175k/yr. Customer-signed and provider-neutral. "Meridian Crest" is fictional and banned from copy. |
| vireoka.com | confirmed | `vireoka_final_website/DECISION_LEDGER.md` | Positioned as "Cognitive Governance". Approved vocabulary is set. Internal names are banned from public copy. |
| oratoplus.com | confirmed | `oratoplus-monorepo/docs/03-prd.md`, `11-gtm-marketing-plan.md`, `21-design-document.md` | "A gym for your voice". Adds hostile Q&A and the pause timeline. Tiers are Free/Growth/Enterprise. PRD KPIs are kept internal. |
| atmakosh.com | confirmed | `atmakosh-platform/README.md`, `docs/DESIGN.md`, `docs/STRIPE_BILLING_PLAN.md` | Governance-as-a-service for AI agents: an eight-worldview council, a deny-wins verdict, hash-chained audit. Tiers are Free/Starter/Pro/Enterprise. |
| weddingos.jodibana.com (planned: weddingos.pro), jodibana.com, jodiusa.com | needs_review | No product repos under vireoka-dev. Drafted from the matchmaking analysis in `oratoplus-monorepo/Oratoplus.docx` | Invite-only AI matchmaking plus wedding commerce. Draft pricing only. |

Fields: `id`, `task_prefix` (unique, 2–5 capital letters), `url`, `name`, `track`, `motion`,
`lint_profile`, `positioning_status`, `positioning`, `not_this`, `capability_facts`,
`pricing_facts`, `icp_seeds`, `partner_seeds`, `channels`, `known_pipeline_context` (private,
never used in copy), `banned_terms` (property-specific lint rules), `sources`. The loader refuses
a registry with duplicate ids or duplicate task prefixes.

---

## 5. The four engines

Each engine is one Claude call. It returns an object that must validate against its Pydantic
schema (§6), and each engine receives the outputs of the ones before it.

| Engine | Input | Output | Notes |
|---|---|---|---|
| (research) | property brief | cited notes (text) | Optional `web_search` server tool with a maximum of 6 searches. Resumes on `pause_turn`. Off with `--no-research`. |
| 1 Market & ICP | brief + research | `MarketIntel` | Two ICP tiers, unit economics with ACV × units ≥ target, conversion path, competitors, sources |
| 2 Partnerships | + E1 | `PartnershipPlan` (≥3) | **Must include ≥1 `design_partner`** (scoped co-build pilot, what each side gets, exit criteria that convert it to a paid contract) **and ≥1 `co_sell`** (joint target accounts, deal registration or margin split, enablement). The rest are distribution, referral/affiliate or integration partners. Each has a value-sharing model, the first ask and a success metric. The schema rejects a plan missing either required kind, and the rejection goes back to Claude to fix. |
| 3 Campaigns | + E1, E2 | `CampaignPlan` | Social campaigns (≥2 hooks each) and 5-step email sequences in fixed order |
| lint + repair | E1 narrative + E3 copy | findings | Blocking findings in E3 are sent back with the violations listed, up to 2 passes |
| 4 Tasks | + E1–E3 | `TaskPlan` (≥10) | Days 1–30. `{PREFIX}-NNN` ids. P0/P1/P2, owner, tool, dependencies, KPI. Any send or publish task needs a human approval task before it. |

**Assembly** (`engines.assemble`) turns the outputs into the prompt's section-4 schema and adds
notes. `NEEDS_POSITIONING_REVIEW` marks a draft registry entry. `ECONOMICS_GAP` means
ACV × units falls short of the target. The `TASKS:` notes flag duplicate ids, dependencies that
point nowhere and tasks scheduled past day 30.

**System prompt rules** (in `engines.SYSTEM`):
- Every property is treated as pre-commercial.
- No testimonials. The social-validation email step uses attributed third-party evidence.
- Every number in copy names its source in the same sentence.
- Capabilities are described as design intent.
- The property's positioning and its "what it is not" list are respected.
- Pipeline context stays private.
- The economics are honest.

---

## 6. Data contracts

`Playbook` is a superset of the JSON schema in the original prompt. Its top-level keys are:

| Key | Type |
|---|---|
| `property` | string, the URL |
| `property_id` | string |
| `run_id` | string |
| `track` | string |
| `positioning_status` | string |
| `revenue_roadmap` | target_acv, required_active_units, primary_conversion_path, target_cac, target_ltv, months_to_target_estimate |
| `icp_matrix` | tier_1_icp, tier_2_icp |
| `market_intel` | full `MarketIntel` |
| `partnership_playbook` | list of `Partnership` |
| `campaign_blueprints` | social_campaigns, email_sequences with 5 `EmailStep`s each |
| `daily_task_registry` | list of `Task` |
| `lint_findings` | list of findings |
| `lint_status` | pass, warn or blocked |
| `notes` | list of strings |

`EmailSequence.steps` must be exactly five steps, numbered 1..5 in this order: trigger_hook,
pain_amplification, solution_proof, social_validation, low_friction_cta. Tool input schemas are
generated from these models with `$ref`s inlined (`llm.inline_schema`), so prompts and validation
can never drift apart.

---

## 7. Lint gate

The gate scans only outward-facing copy (`lint_gate.copy_fields`):

- the US market narrative
- the differentiation points
- the social hooks
- every email subject and body

Each finding carries a severity. `block` means the item can't be approved or exported. `warn`
means it can, with a flag.

| Layer | Source | Examples |
|---|---|---|
| Profile rules | `config/lint_gate.yaml` → `institutional`, `standard`, `consumer` | customer/traction claims, testimonials, "guaranteed", yield/APY for LiqMint, "supports Canton", pre-built country rule packs, fabricated member counts, guaranteed matches, caste/colorism language |
| Attribution | `attribution` block | Any $, %, x or bps figure without "Source:", "according to", "per X", "(Org, 2025)" in the same sentence |
| Property terms | `banned_terms` in the registry | Vireoka: AtmaSphere, Decision Management, HKDF… · Institutional: Meridian Crest |

Status resolution: any `block` → `blocked`; otherwise any finding → `warn`; otherwise `pass`.

---

## 8. Human approval and exports

```mermaid
stateDiagram-v2
  [*] --> generated
  generated --> blocked: lint block remains
  generated --> reviewable: lint pass/warn
  reviewable --> approved: vanguard approve --by NAME
  approved --> exported: vanguard export
  blocked --> generated: fix registry/prompt, re-run
```

- `store.approve` refuses blocked playbooks at the SQL level
  (`WHERE lint_status != 'blocked'`).
- `export_sequences` raises `NotApproved` unless the playbook is approved and not blocked.
- The task backlog export is not gated, because it contains no outward-facing copy.

---

## 9. Cost model

| Item | Price used (2026-09-27 list) |
|---|---|
| Claude Sonnet 5 (default) | $2 in / $10 out per million tokens |
| Claude Haiku 4.5 | $1 / $5 |
| Claude Opus 5.5 | $4 / $20 |
| Web search | $10 per 1,000 searches |
| Cache read / 5-min cache write | 0.1× / 1.25× input |
| Notion API | $0 |

Estimates come from `vanguard estimate`, which uses the typical token volumes in
`cost.TYPICAL`:

| Model, research | 8 properties |
|---|---|
| Sonnet 5, with research | about $4.20 |
| Haiku 4.5, without research | about $1.50 |

Controls:

0. **Off by default.** `VANGUARD_MAX_COST_USD` defaults to **0**, which means paid runs are
   disabled. The CLI refuses a real run before creating it. `ClaudeLLM` raises `BudgetExceeded`
   before its first API call. `doctor` reports "$0 mode".
1. **Estimate plus confirmation** before any real CLI run. `-y` skips the prompt.
2. **Hard cap.** When `VANGUARD_MAX_COST_USD` is set above 0, it is the spend limit per run. The meter checks it before
   every API call and raises `BudgetExceeded`. Properties already finished are kept, and the run
   is marked `partial` or `failed`.
3. **Metered actuals** stored on the run (`runs.usage`) and shown by `vanguard status`.
4. **The $0 path.** `vanguard prompt all --out prompts/` writes one self-contained prompt per
   property. Paste each into its own Claude chat; these can run in parallel under your Claude
   plan. Save the replies as `prompts/<id>.json`, then run `vanguard import all prompts/`. Each
   reply is validated, linted and stored with a cost of $0. Missing or malformed replies are
   reported, and the rest are still imported.
5. **Unknown models** are priced as the most expensive model, so the estimate is never low.

---

### 9.1 Model providers: local first, Claude as backup

```mermaid
flowchart LR
  E[engine call] --> L{LocalLLM<br/>Ollama / LM Studio / llama.cpp / vLLM}
  L -- valid JSON --> OK[result, $0]
  L -- server down / 3 invalid replies --> F{Claude fallback on?<br/>cap > 0 and key set}
  F -- no --> ERR[property fails:<br/>"fallback is OFF, nothing spent"]
  F -- yes --> C[ClaudeLLM, metered + capped] --> OK2[result, paid]
```

| `VANGUARD_PROVIDER` | Behaviour | Cost |
|---|---|---|
| `local` (default) | Every engine call goes to the local model first. Only a call that fails goes to Claude, and only when `VANGUARD_MAX_COST_USD` > 0 and `ANTHROPIC_API_KEY` is set. | $0, or up to the cap |
| `claude` | Claude only | Paid, capped |

**How local calls work:**
- **Same contract.** The local model gets the same Pydantic-generated JSON Schema as Claude:
  - Ollama receives it through `format` (structured outputs).
  - OpenAI-compatible servers receive it through `response_format: json_schema`.
- **Same checks.** The output passes through the same validation-retry loop (3 attempts) and the
  same lint gate. `<think>` blocks and code fences are stripped before parsing.
- **Queued on the GPU.** Calls go through `VANGUARD_LOCAL_CONCURRENCY` (default 1). The eight
  pipelines still run in parallel, but their calls queue for one GPU instead of thrashing it.
- **No web research.** Local models have no web access, so Engine 1 works from the registry
  facts. `VANGUARD_RESEARCH_WITH_CLAUDE=1` sends only the research step to Claude (paid, capped).
- **Metering.** Usage records `provider`, `local_calls`, `local_failures` and `fallback_calls`.
  `status` prints them.

**Model choice** (default `qwen3.6:27b`, verified on ollama.com on 2026-09-27):

| Model | Download | Memory needed |
|---|---|---|
| `qwen3.6:27b` (Q4_K_M) | about 17–18 GB | a 24 GB GPU, or a 32 GB+ Apple-silicon Mac |
| 14B-class (e.g. Qwen3 14B) | about 9 GB | about 12 GB |
| 8B-class (e.g. `llama3.1:8b`) | about 5 GB | about 8 GB |

Any Ollama tag works through `VANGUARD_LOCAL_MODEL`, including `qwen3.8:27b` if `ollama pull`
finds it. Smaller models more often fail the schema on Engine 4, which has the largest output,
so those calls use the Claude fallback when it's enabled.

**Quality caveat.** Local 8–32B models write weaker strategy and copy than Claude. The lint gate
and schema checks catch format and claim problems, not weak thinking. Review local output before
approving it.

## 10. Persistence

One database holds the agent's tables (below), the web tables (§14.3) and the fail-proof tables (§17.2).

- **SQLite** at `VANGUARD_DB` (default `data/vanguard.db`) unless `VANGUARD_DATABASE_URL` is set. Used by
  tests and local runs.
- **PostgreSQL** when `VANGUARD_DATABASE_URL` is a `postgresql://` URL. `docker-compose.yml` runs its own
  PostgreSQL 16 (`vanguard-db`, data in `./pgdata`) on a private network only the app can reach, and
  sets the URL from `VANGUARD_DB_PASSWORD`.

Application SQL is written once, with `?` placeholders, in the subset both engines accept (upserts use
`ON CONFLICT … DO UPDATE`; date arithmetic is done in Python; `SUM(CASE WHEN …)` instead of summing a
boolean). `db.py` adapts the rest for PostgreSQL: placeholders and `%` escaping, `BIGSERIAL` for
auto-increment keys, `DOUBLE PRECISION` for `REAL`, an explicit `rowid` column on `runs`, `playbooks`
and `tasks`, `RETURNING *` for inserted ids, `information_schema` for column checks, and `PRAGMA`
statements skipped. `vanguard db copy-from-sqlite FILE` moves an existing SQLite database across
(tables that already hold rows are skipped unless `--replace`; id sequences are advanced past the
copied ids). The test suite runs on either engine (`VANGUARD_TEST_DATABASE_URL`, fresh database per
test).

| Table | Key | Columns |
|---|---|---|
| `runs` | id | created_at, finished_at, status (running/completed/partial/failed), property_ids, errors (JSON), usage (JSON) |
| `playbooks` | (run_id, property_id) | lint_status, body (Playbook JSON), approved_by, approved_at, notion_page_id |
| `tasks` | (run_id, property_id, task_id) | day, priority, owner, status, body, notion_page_id |

The `usage` column is added automatically to databases created by v0.1. Each run also writes
`output/<run_id>/<property>.json`.

---

## 11. Notion integration

| Database | Title property | Other properties |
|---|---|---|
| **Vanguard-GTM · Playbooks** | Property | Property ID, Track, Target ACV, Units needed, Conversion path, Months to target, Lint, Positioning, Approved by, Run |
| **Vanguard-GTM · Tasks** | Task ID | Property, Day, Priority, Owner, Tool, Category, Description, Dependencies, KPI, Status, Run, Playbook lint |

**Upsert.** The sync first uses the cached `notion_page_id`. If that's missing, it queries by
title + Run (+ Property for tasks). Only if nothing matches does it create a page. That makes
re-syncs idempotent, even if the local database is lost.

**Status column.** `Status` is set only when a page is created and never overwritten on update.
It belongs to whoever works the task.

**Limits handled:**
- About 3 requests per second (serialised, 0.34 s apart).
- 429 and 5xx responses are retried with backoff and `Retry-After`.
- Text is split into 2,000-character runs.
- Page children go up in batches of 100.
- Commas are removed from select values.

**Page body.** Each playbook page contains, in order:
- revenue roadmap
- notes
- lint findings
- partnerships
- every email step
- social hooks
- the raw JSON, chunked

---

## 12. Security

| Area | Handling |
|---|---|
| Secrets | Secrets live only in `.env`, which is git-ignored, or in container env. Nothing is logged or stored in SQLite, and Notion receives only playbook content. |
| HTTP API | A bearer token (`VANGUARD_API_TOKEN`) is required on every route except `/health`. The API returns 503 if the token isn't configured. |
| Blast radius | The Notion connection only sees pages you share with it. Vanguard never posts. Email goes out only for messages an admin approved, and only in `smtp` or `postmark` mode (§15.4, §16). |
| Postmark webhook | `/hooks/postmark` requires HTTP Basic Auth (constant-time compare) and answers 503 until credentials are configured. Events only update email status, suppression and reply records; they can't approve or send anything. Team alerts go only to active admins and the partner owner. |
| Postmark token | Use a server token created for Vanguard (`POSTMARK_SERVER_TOKEN`), never the one found in the atmakosh notes below. A server token can only act on that one Postmark server. |
| Data minimisation | Pipeline context stays out of prompts' copy fields and out of exports. |

**Finding from the 2026-09-27 refresh:** `vireoka-dev/atmakosh-platform/important_details_atmakosh.md`
contains live-looking API keys, a Postmark server token and a password in plain text. Vanguard
does not read or store it; the staged copy was deleted. Rotate those credentials and move them
to a secret manager.

---

## 13. Deployment

Local use: `pip install -e .`, then the CLI, or `vanguard serve` for the web app at
http://localhost:8080. The zip ships a prebuilt `ui/dist`; `cd ui && npm install && npm run build`
rebuilds it after UI changes.

The Docker image is multi-stage: Node builds the UI, then the Python image serves it.

Server use (Hostinger VPS):
- Docker Compose under `/opt/vanguard-gtm` on the external Traefik network.
- File-provider route in `deploy/traefik-vanguard.yml`. Restart Traefik after adding it, because
  the file provider's `watch` is off.
- Volumes: `data/`, `output/`, and a read-only `config/`, so you can edit positioning and lint
  rules without a rebuild.

---

## 14. Web application (v0.3.0)

A React UI and a JSON API sit on the same SQLite database as the agent. One process
(`vanguard serve`) serves three things:

| Path | What | Auth |
|---|---|---|
| `/` | The built React app (`ui/dist`). Client-side routes fall back to `index.html`. | Sign-in page |
| `/api/*` | JSON API for the UI (`vanguard/web/app.py`) | Session token (HS256 JWT) |
| `/machine/*` | The machine API from v0.1 (`vanguard/api.py`) | `VANGUARD_API_TOKEN` bearer |

```mermaid
flowchart LR
  B[Browser<br/>React + Vite + Tailwind] -->|/api JWT| W[FastAPI web app]
  W --> DB[(SQLite<br/>users · campaigns · results · partners<br/>interactions · targets · audit_log<br/>+ runs · playbooks · tasks)]
  W -->|admin: start run| O[Orchestrator] --> DB
  W -->|admin: import| DB
  W -->|admin: sync| N[(Notion)]
```

### 14.1 Roles

| Capability | General user | Admin |
|---|---|---|
| View dashboard, campaigns, partners, tasks, playbooks | ✔ | ✔ |
| Create and edit campaigns; log results | ✔ | ✔ |
| Delete a campaign or result entry | only their own | ✔ all |
| Add or edit partners, move stages, log interactions | ✔ | ✔ |
| Delete a partner | ✘ | ✔ |
| Delete an interaction | only their own | ✔ all |
| Change task status and notes | only tasks assigned to them | ✔ all |
| Create, delete, assign, reprioritise tasks; set due dates | ✘ | ✔ |
| Set ARR targets (dashboard admin) | ✘ | ✔ |
| Start agent runs, approve playbooks, import to campaigns/partners, sync Notion | ✘ | ✔ |
| Manage users; read the audit log and agent status | ✘ | ✔ |

- **Enforced on the server.** Every rule is checked in the API. The UI only hides controls a
  user can't use.
- **Users can't see emails.** A general user's `GET /api/users` returns names and roles only.
- **Admins can't lock themselves out.** An admin can't demote, disable or delete their own
  account.

### 14.2 Security

| Area | Handling |
|---|---|
| Passwords | PBKDF2-SHA256 with 240k iterations and a per-user salt. At least 10 characters. |
| Sessions | HS256 tokens signed with `VANGUARD_JWT_SECRET`. If that's unset, a random secret is written once to `data/jwt_secret` (mode 0600). Sessions last 12 h (`VANGUARD_SESSION_HOURS`). A disabled user's token stops working immediately, because every request re-reads the user. |
| Login throttling | 8 failures per client and email in 15 minutes returns 429 |
| Audit | Every create, update, delete, login, run, approval, import and sync goes to `audit_log` with the acting user |
| Transport | TLS is terminated by Traefik (`deploy/traefik-vanguard.yml`) |

### 14.3 Data model (web tables)

| Table | Key columns |
|---|---|
| `users` | email (unique), name, role (`admin`/`user`), password_hash, active, last_login |
| `campaigns` | property_id, name, kind, channel, status (draft/scheduled/active/paused/completed), dates, budget_usd, goal_metric, goal_value, description, content (the email steps or hooks from the agent, as JSON), owner_id, source_run_id, created_by |
| `campaign_results` | campaign_id (cascade), date, sent, opens, clicks, replies, meetings, signups, conversions, revenue_usd, spend_usd, notes, created_by |
| `partners` | property_id + name (unique), kind (design_partner/co_sell/distribution/referral_affiliate/integration), stage (identified → contacted → in_conversation → pilot → signed, or declined), contact, value_sharing_model, mutual_value, first_ask, next_step, next_step_date, owner_id, source_run_id |
| `partner_interactions` | partner_id (cascade), date, type (email/call/meeting/demo/proposal/note), summary, outcome, next_step, created_by |
| `targets` | property_id, arr_target_usd (default $2M), monthly_conversions_target |
| `audit_log` | at, user_id, action, entity, entity_id, detail (JSON) |

`tasks` gains `assignee_id`, `due_date`, `notes` and `updated_at`, migrated in place.
Tasks the admin creates by hand use `run_id='manual'` and ids like `ORA-M001`.

### 14.4 From agent to execution

1. Admin → **Start run**. Dry runs are always $0. Real runs follow §9's provider and cap rules,
   and the API returns 409 with nothing started if they can't run at $0.
2. Review each playbook: the modal shows the revenue roadmap, ICP, partnerships, notes and lint
   findings. **Approve** is refused for blocked playbooks.
3. **Import**:
   - Every email sequence becomes a draft `email` campaign carrying its 5 steps.
   - Every social campaign becomes a draft `social` campaign carrying its hooks.
   - Every target entity in the partnership playbook becomes an `identified` partner with its
     kind, value-sharing model and first ask.
   - Import is idempotent per run, and blocked playbooks are skipped.
4. The team runs the campaigns outside Vanguard (Smartlead, LinkedIn…), logs results weekly, and
   works partners through the board.
5. **Dashboard figures:**
   - ARR run-rate = last 30 days of logged revenue × 12, against each property's target.
   - The funnel sums sent → replies → meetings → conversions.
   - The partner pipeline is shown by stage.
   - Task completion counts the current plan plus manual tasks.

### 14.5 Front end

| Item | Detail |
|---|---|
| Stack | React 19, Vite 7, TypeScript, Tailwind 4, React Router 7, Recharts, lucide-react |
| Fonts | Self-hosted through `@fontsource`, so nothing loads from Google at runtime |
| Visual system | The Vireoka ledger look: dark by default with a light theme, vireo green `#3ddc97`, Source Serif 4 for headings, Inter for UI text, IBM Plex Mono for numbers |
| Charts | Single-hue bars with a chart/table toggle. Partner stages use one hue from light to dark because they're ordinal. |
| Accessibility | Every form control is linked to its label by id. Dialogs trap Escape and have ARIA names. Focus rings are visible. |
| Pages | Sign-in · Dashboard · Campaigns (list, detail with results log and goal progress) · Partners (drag-and-drop pipeline board, detail with stage stepper and timeline) · Tasks (filters, paging, inline status; admin assignment, priority and due dates) · Admin (agent status, runs, approvals, import, Notion sync; users; audit log) |

### 14.6 Demo data

`vanguard demo-data` loads synthetic records so the UI can be explored:
- a `demo-` run;
- 24 campaigns and 24 partners, all named `[DEMO] …`;
- 8 weeks of results.

`vanguard demo-data --purge` removes exactly those records. The figures are made up and must
never be reported.

## 15. Partner outreach: the partnerships expert (v0.4.0)

The agent recommends which **design partners**, **B2B co-selling partners** and channels each
property should pursue. It ranks them, drafts a prioritised 3-step email sequence for each, and
sends only what an admin approves. It then tracks replies and follows each partner through to a
signed agreement.

```mermaid
flowchart LR
  PB[config/partner_playbooks.yaml<br/>expert categories · deal terms · where to find] --> E2B
  E1[Engine 1 ICP] --> E2B[Engine 2B Partner Outreach<br/>offline expert or model]
  E2B --> SC[Deterministic score<br/>fit·reach·access·strategic·speed → 0-100, P0/P1/P2]
  SC --> LG{Lint gate<br/>per message}
  LG --> DB[(partners + outreach_messages<br/>drafts)]
  DB --> T[Team adds named targets<br/>+ contact emails]
  T --> A{Admin approves}
  A --> S[send_due: order, delays, cap,<br/>suppression, footer]
  S --> MB[Outbox .eml or SMTP]
  IN[IMAP inbox / manual reply] --> R[record_reply:<br/>stop sequence, move stage,<br/>honour opt-out]
  R --> AG[Agreement: proposed → negotiating → signed]
  AG --> D[Dashboard]
```

### 15.1 Expert layer
`config/partner_playbooks.yaml` defines 4–6 partner categories for each property. Each category
records:
- its kind (`design_partner`, `co_sell`, `referral_affiliate`, `distribution`, `integration`);
- why it fits, and the value each side gets;
- the typical deal structure;
- where to find the right contact;
- default scoring factors;
- the angle and offer used in the drafts.

Examples of categories:

| Property | Categories |
|---|---|
| Jodibana | South Asian wedding planners (co-sell); wedding photographers and videographers (referral); destination wedding resorts and hotels (co-sell); banquet halls and venues in diaspora hubs (co-sell); temples, cultural associations and community centres (design partner); bridal wear and jewellers (referral) |
| LiqMint Institutional | Digital-asset desks (design partner); qualified custodians (co-sell; named examples such as Fireblocks, Coinbase Prime, Anchorage Digital, BitGo); Big-4 advisory (co-sell); tokenization platforms and treasury systems (integration) |
| OratoPlus | Accelerators and sales enablement (design partners); coaches (co-sell); Toastmasters clubs and career centres (distribution) |

The other properties follow the same pattern.

### 15.2 Engine 2B and scoring
- **Offline mode ($0, instant).** `partners.offline_plan` turns each category into a
  recommendation. Categories with named examples produce one recommendation per organisation;
  the rest become segments. Every recommendation gets a 3-step draft built from kind-specific
  templates.
- **Model mode.** `engine2b_partner_outreach` has the local model (or the capped Claude fallback)
  name 8–12 specific organisations, grounded in the playbook and Engine 1's ICP.
  - Rules: never invent emails or people; never claim a relationship; score factors honestly.
  - The output must include at least one design partner and one co-sell partner (schema
    validator), and gets one lint-repair pass.
- **Every run includes it.** Engine 2B also runs inside every `vanguard run`, and the output is
  stored as `Playbook.partner_outreach`.
- **Score.** Each factor is rated 1–5 and weighted: fit 30%, reach 25%, strategic 20%, access
  15%, speed 10%. The result maps to 0–100. P0 ≥ 75, P1 ≥ 55, otherwise P2. The same inputs
  always produce the same priority.

### 15.3 From segment to named target
- **Segments.** A recommendation such as "South Asian wedding planners in NJ/NY" is stored with
  `is_segment=1`. Its drafts are templates and can never be approved or sent.
- **Named targets.** The team adds specific businesses under a segment, with a contact name,
  email and website (`POST /partners/{segment}/targets`). Each one inherits the segment's kind,
  scores, rationale and a copy of the drafts.
- **Queue.** Segment templates are left out of the outreach queue and its counts.

### 15.4 Sending (`vanguard/outreach.py`)

| Rule | Implementation |
|---|---|
| Admin approval per message | Only `approved` messages send. Editing a message resets it to `draft`. Lint-blocked copy can't be approved. |
| Safe default | `VANGUARD_EMAIL_MODE=outbox` writes RFC-822 `.eml` files to `output/outbox/`. `smtp` really sends, through your own mailbox, at no cost. `postmark` sends warm contacts through Postmark streams (§16). |
| Compliance | SMTP mode refuses to start without the sender name, email and postal address. Every email gets a footer with identity, postal address and an opt-out line, plus a `List-Unsubscribe` header. |
| Order and timing | Step n goes out only after step n-1 was sent and `delay_days` have passed. Follow-ups are threaded (`In-Reply-To`). |
| Stop conditions | The sequence stops on any reply, a suppressed address (opt-out or bounce), or a partner marked signed or declined |
| Limits | Daily cap (`VANGUARD_EMAIL_DAILY_CAP`, default 20). Messages go out in priority order. A failed send is recorded and the rest of the queue continues. |
| Triggers | Admin "Send due now" (UI or API), `vanguard outreach send`, or the scheduler in `serve` (`VANGUARD_OUTREACH_EVERY_MIN`) |

### 15.5 Replies
- **Automatic (IMAP).** The inbox is read-only (`BODY.PEEK`, nothing marked read). Mail is
  matched by `In-Reply-To`/`References` to our Message-IDs, then by sender address. Bounces from
  mailer-daemon are matched by the quoted Message-ID. Inbound Message-IDs are stored, so nothing
  is processed twice.
- **Manual.** "Record reply" on the partner page covers phone, LinkedIn or other inboxes.
- **What a reply does:**
  1. Marks the message `replied` and cancels the remaining steps.
  2. Logs the reply text, with the quoted original stripped.
  3. Classifies it as positive, neutral, negative or opt-out.
  4. Moves the partner from identified or contacted to `in_conversation`. An opt-out instead
     adds the address to `email_suppression` permanently.

### 15.6 Agreements and dashboard
- Each partner has `agreement_status` (none → proposed → negotiating → signed or declined), a
  signed date and key terms.
- Marking an agreement signed or declined moves the stage and cancels queued outreach.
- The dashboard shows agreements signed and in talks for each property and for the portfolio,
  along with partner emails sent, replies and reply rate.

### 15.7 Researched partner targets (v0.6.0)
`config/partner_targets.yaml` lists **real organisations** for each property, 13–16 per property
and 117 in the first release. They were found by web research and checked against each
organisation's own site or recent news.

**Fields per organisation:**
- `category`, which must be a category id from `partner_playbooks.yaml`;
- `name`, `website`, `location`;
- `why`, one or two sentences grounded in the evidence;
- `evidence_url`;
- `contact_email`: only a generic inbox published on the organisation's own site, otherwise
  empty;
- `contact_url`: a contact page, partner program or application form;
- `priority_hint` (P0–P2) and `confidence` (high or medium).

Optional (v0.8.1): `how_to_reach` (the best route in), `contacts` (people who **publicly** hold
the relevant role, each with the `source` that shows it and a `confidence`), and `recent_hook` +
`recent_hook_url` (why now). On import the first named person becomes `contact_name` unless one
was entered by hand; the route and people go into `how_to_find`, the hook into `rationale`.

**Privacy:** the file holds no personal emails, phone numbers or home details. `contact_email`
is only an inbox the organisation itself publishes; named contacts are public role holders with a
source, and their emails are never guessed.

**Mid-market first (v0.8.1).** LiqMint Institutional has four categories aimed at partners that can
sign a paid proof-of-value within about 90 days: `stablecoin_banks`, `stablecoin_fintechs`,
`wallet_compliance_infra` and `midsize_advisory`. Their higher access and speed factors rank them
above tier-1 banks and the Big Four, which remain as relationship targets (P1/P2). A category can
override the design-partner wording with `middle` / `follow` (for example a paid proof-of-value
instead of "no cost"). Import creates segments for categories added after the first import.

**Import:** `import_targets` (`vanguard partners import`, `POST /api/partners/import-research`,
or the "Load researched partners" button) works as follows:
1. **Finds the template** for each category. That is the category's segment, or for categories
   the playbook lists by name (custodians, Big-4 and so on) its named example. If the
   property has no segments yet, the $0 expert plan is created first.
2. **Matches existing partners.** A target whose name matches an existing partner, including a
   playbook example contained in the research name (for example "KPMG" in "KPMG US - Digital
   Assets Advisory"), enriches that partner instead of duplicating it.
3. **Creates the rest** as named partners (`source='research'`, `parent_id` = segment) with
   their own copy of the template's 3 draft emails (merge tags intact).
4. **Sets the fields:**
   - `rationale` = why + source + confidence;
   - `how_to_find` = contact URL + location;
   - `priority` = the hint;
   - `priority_score` = the template score nudged by the hint, then clamped into the hint's
     band (P0 ≥ 75, P1 55–74, P2 < 55), so score and priority never disagree.
5. **Keeps your work on re-runs.** Re-running refreshes the research fields only. It never
   changes stage, outreach status, agreements or a contact email entered by hand.

Nothing is approved or sent. Targets without a public inbox show "needs contact email" in the
queue until someone adds a business contact.

### 15.8 Data (new or changed)
| Table | Columns |
|---|---|
| `partners` (new columns) | category, is_segment, parent_id, priority_score, priority, factors, rationale, deal_structure, how_to_find, website, source, agreement_status, agreement_signed_date, agreement_notes |
| `outreach_messages` | partner_id + step (unique), delay_days, subject, body, status (draft/approved/sent/replied/cancelled/failed/bounced), lint_status, lint_findings, approved_by/at, sent_at, message_id, to_email, error, replied_at |
| `email_suppression` | email, reason (opt-out/bounce), at |
| `inbound_emails` | message_id, partner_id, outreach_id, from_addr, subject, received_at, classification |

### 15.9 Campaign link and LinkedIn connections (v0.9.0)

**Campaign link.** A partner belongs to at most one campaign (`partners.campaign_id`, same property
only). Attaching a segment attaches the named organisations under it; attaching a partner that is
in another campaign moves it. Everything that happens to an attached partner counts towards the
campaign without being stored twice: `campaign_link.campaign_outreach` computes, on every read,

| Measure | From |
|---|---|
| Partners | partners with this `campaign_id` |
| Emails sent | `outreach_messages.sent_at` set |
| LinkedIn/X touches | `partner_interactions` of type `linkedin` or `x`, except "Connected on LinkedIn" events |
| Touched | partners with an email sent or a LinkedIn/X touch |
| Replied | partners with a replied message, or `email_consent` `replied`/`opted_out` |
| Meetings | interactions of type `meeting` or `demo` |
| In conversation / pilot / signed | partner stage (in conversation counts everyone at or past it) |
| Queue | drafts awaiting approval, approved messages, partners with drafts but no email, next due date |

The campaign's displayed sent, replies and meetings are hand-logged `campaign_results` **plus**
these, so hand logging is for what the app cannot see (opens and clicks from another tool, signups,
revenue, spend). Goal progress uses the combined figure. `GET /outreach` filters by `campaign_id`.
Deleting a campaign clears `campaign_id` on its partners; partners and their history stay.

**LinkedIn connections.** LinkedIn's API does not give third-party apps a member's connections or
messaging, and scraping or browser automation breaks its terms, so Vanguard-GTM never touches
LinkedIn. It reads the member's own export instead (Settings → Data privacy → Get a copy of your
data → Connections.csv). `linkedin.import_connections` parses the file (skipping LinkedIn's
"Notes" preamble), keys rows by profile URL and importing user, and refreshes on re-import.
Companies are normalised (case, punctuation, legal suffixes) and matched to partner names, the
text in brackets, and the part before " - "; a prefix match needs four or more characters and a
non-generic word ("Bank" alone never matches). People match on first name plus last name or last
initial ("Eleni S." = "Eleni Steinman"). When a partner's named contact is found, the partner gets
one `linkedin` timeline entry "Connected on LinkedIn: …" dated with the connection date, which is
how an accepted request shows up after the next export; and if the connection shared an email and
the partner has none, it becomes the contact email. Each user may delete their own imported rows.

**Data.** `partners.campaign_id INTEGER` (migration); new table `linkedin_connections` (owner_id,
profile_url, first_name, last_name, email, company, company_norm, position, connected_on,
imported_at, updated_at). Interaction types gain `linkedin` and `x`.

### 15.10 Investor targets (v0.10.0)

Fundraising contacts are partners of kind `investor` (v0.9.1). `config/investor_targets.yaml` holds the
ranked target list for the Vireoka / LiqMint raise; `investors.import_investors` loads it (CLI
`vanguard investors import`, or the admin's **Load researched partners** button), creating or refreshing one
partner per investor under the file's `property_id` (Vireoka). It never creates outreach drafts: first
contact with an investor is personal.

The file is built from three inputs: the attendee list of the Sep 17, 2026 Virtual 1:1 VC Pitch Conf (only
investors listing Fintech, Crypto or AI; fund-of-funds-only LPs dropped), investor speakers from the March
2026 conference transcript whose stated thesis fits, and public-web research on the top of the list (every
fact with a source URL, a `confidence` for whether the person was confirmed at the firm, and no guessed
email). Each entry carries `rank`, `score`, `priority` and five `factors` (0-5):

| Factor | Weight | Rule |
|---|---|---|
| thesis | 25% | Fintech 2, Crypto 2.5, AI 1, Cybersecurity or SaaS 0.5, capped at 5 |
| stage | 15% | pre-seed + seed 5, seed 4.5, pre-seed 3, Series A only 2 |
| check | 15% | able to anchor part of a $3M round 5, down to under $100K 1 |
| geo | 5% | US 5, US among several or global 4, elsewhere 1.5 |
| research | 40% | researched fit 0-5; 2 when not researched yet |

Score = 20 × weighted sum, +3 for the event's own top-20 match or the 10 most responsive investors, −6
when research could not confirm the person; P0 ≥ 75, P1 ≥ 55. The importer writes `rationale` (rank,
profile, why, their thesis, likely concern, opening hook, signals, the conference "key considerations",
source and confidence), `how_to_find` (title, location, LinkedIn, contact route, portfolio, recent deals,
sources), `deal_structure` (check size and stages), `partner_type`, `website`, `factors`. Re-import refreshes
these and leaves the stage, a hand-entered email or contact name and an existing next step alone. The
partner page labels the factors for investors and explains the investor formula.

### 15.11 Introductions (v0.11.0)

`vanguard/intros.py` finds people you already know who can introduce you to a target (investor or partner),
drafts the ask, and tracks it.

**Data.** The full LinkedIn export (.zip, "Download larger data archive") is read by `import_export_zip`:
`Connections.csv` as before (§15.9), plus `messages.csv` (count and last date per person; message text is
never stored), `Endorsement_Received_Info.csv` and `Endorsement_Given_Info.csv`. Each connection gets
`msg_count`, `last_message_at`, `endorsements`, `strength` (0-5: up to 2 for messages, 1.5 for recency,
1 for endorsements, 0.5 for years connected) and `tags` (investor, bank, fintech, compliance, consulting, ibm,
senior) from title and company.

**Paths.** LinkedIn's export has 1st-degree connections only, so 2nd/3rd-degree paths cannot be read from it.
`suggest` proposes, per target (investors and partners of the founder's properties by default):

| Path | Rule | Score |
|---|---|---|
| insider (`direct`) | connection's company matches the target organisation (the firm for an investor); every priority | 60 + 7×strength (+8 senior) |
| bridge, named in background | connection's employer (5+ letters, not an everyday word) appears in the target's researched title, thesis, portfolio or deals; P0/P1 | 35 + 8×strength (+6 senior) |
| bridge, same world | connection tagged for the target's kind (investor: investor/fintech; design partner: bank/fintech/compliance; integration, distribution: fintech/bank), strength ≥ 1.5, senior or an investor; none for co-sell (competing firms); P0/P1 | 20 + 9×strength (+6 senior, +4 investor to investor) |

The target person themselves is never proposed. Up to 3 paths per target; a connector is proposed for at most
4 targets, assigned best-first across all targets. Each target carries a LinkedIn people-search link filtered
to the 2nd-degree network (`network=["S"]`) so the user confirms who they share before asking a bridge.

**Asks.** `intro_requests` holds one row per (target, connector) with status suggested, draft, approved,
sent, then accepted / introduced / declined / cancelled. `draft` writes a double opt-in note (say no if it
isn't a fit; introduce me only if they agree) plus a forwardable blurb, linted with the target property's claim
rules. Only an admin approves. `send_approved` emails approved asks when the connector shared an email with
LinkedIn (same mailer, footer and daily cap as outreach; opted-out addresses are cancelled); others are sent by
hand on LinkedIn and marked sent. Sending logs "Asked X for an introduction" on the target's timeline; outcomes
log there too, and "introduced" moves an identified target to contacted.

### 15.12 One-off emails (v0.12.0)

Sequences come from recommendations; investors and ad-hoc follow-ups have none. `outreach.compose` writes a
single email to one partner as an ordinary `outreach_messages` draft with `one_off = 1` and a step number from
101 up (`ONE_OFF_BASE`), so it never collides with sequence steps 1-5 and keeps the `(partner_id, step)` key.
An address typed in the dialog is validated and saved as the partner's `contact_email`.

Everything else is the existing path: the claim rules (the property's lint profile) run on save and edit, only
an admin approves, and it leaves only through `send_due` with the daily cap, opt-out list, footer, Postmark
consent policy (§16.2: a cold first touch in postmark mode needs SMTP), timeline entry and move to contacted.
Two sequence rules don't apply to a one-off: it doesn't wait for an earlier step, and a recorded reply
neither stops it in `send_due` nor cancels it in `record_reply` (a one-off is often the answer to that reply).

`send_due(only=[ids])` sends just the named approved messages; "Approve & send" uses it so one email doesn't
release the rest of the queue. `POST /outreach/send-due` takes an optional `{ids}`.

**Attribution exemption.** `lint_gate.yaml` `attribution.exempt_pattern` skips the source-required rule for a
sentence about our own raise ("We're raising a $3M seed"): a fact about Vireoka, not a market claim. Any other
figure in the same email still needs a source.

### 15.13 A mailbox per property (v0.13.0)

Vireoka, LiqMint and LiqMint Institutional email from a vireoka.com address; the five delegated properties
from the default (atmakosh.com) one. `EmailConfig` keeps the default mailbox (SMTP_*, IMAP_*,
VANGUARD_SENDER_*) plus `mailboxes` read from `VANGUARD_MAILBOXES` and `VANGUARD_MAILBOX_<NAME>_*`, and a
`property_mailbox` map. `for_property(pid)` returns the config to send with: the default itself, or a copy
with that mailbox's sender, reply-to, SMTP, IMAP and daily cap. Unset keys fall back to the default (host,
port, name, postal address); user names default to the mailbox's sender; a password is never inherited.

`MailRouter` (used by `send_due` and `intros.send_approved`) picks the mailbox per message, opens at most one
connection per mailbox, and gives each mailbox its own daily allowance: `_sent_today(ws, cfg)` counts sent
outreach emails and intro asks by `from_email` (a column on both tables; rows sent before v0.13.0 count for the
default). Mailbox reputation is per address, so caps are too. `sync_replies` reads every mailbox that has IMAP.
In postmark mode the cold first touch goes through the property's mailbox SMTP; warm mail uses the Postmark
stream with that mailbox's sender, which must be a verified sender in Postmark. Team notifications always use
the default mailbox. `problems()` refuses to send if a mailbox lists no properties, a property sits in two
mailboxes, or (smtp/postmark) a mailbox has no sender, or (smtp) no password. Status output names each mailbox
and the sender per property and never includes a password.

## 16. Postmark message streams (v0.5.0)

Postmark is an optional sending, tracking and inbound provider for partner email
(`vanguard/postmark.py`). It is off unless `VANGUARD_EMAIL_MODE=postmark` and
`POSTMARK_SERVER_TOKEN` are set. The default stays `outbox`, so nothing leaves the machine.

### 16.1 Streams

| Stream (env var, default) | Type | Carries |
|---|---|---|
| `VANGUARD_POSTMARK_STREAM_OUTREACH` (`outbound`) | Transactional | One-to-one partner emails to warm contacts |
| `VANGUARD_POSTMARK_STREAM_NOTIFY` (`outbound`) | Transactional | Team alerts: reply notifications and the approval digest |
| The server's inbound stream | Inbound | Partner replies, posted to `/hooks/postmark` |

Recommended setup: create a transactional stream called `partners` for outreach, so its
reputation, suppressions and statistics stay separate from team alerts. `vanguard outreach
postmark-check` and `GET /api/email/postmark` flag streams that are missing or not
transactional. Broadcast streams are refused, because partner emails are one-to-one.

### 16.2 Consent policy (why cold email doesn't go through Postmark)
Postmark's terms require permission-based email and prohibit unsolicited messages. Each
partner therefore carries `email_consent`:
- `none`: cold, the default.
- `opted_in`, `existing_relationship`, `replied`: warm. `replied` is set automatically when
  they answer.
- `opted_out`: set by an opt-out reply, a spam complaint or by hand. It also adds the address
  to `email_suppression` and cancels queued messages.

In postmark mode, `send_due` routes each approved, due message as follows:

| Partner | Route |
|---|---|
| Warm | Postmark outreach stream |
| Cold, and SMTP configured | Your own mailbox (hybrid: first touch from you, follow-ups after a reply via Postmark) |
| Cold, no SMTP | Held, with the reason shown in the send report. It stays `approved`. |
| Cold, `VANGUARD_POSTMARK_ALLOW_COLD=1` | Postmark. This is your decision and your responsibility under Postmark's terms. |

Every other rule from §15.4 still applies: admin approval per message, lint gate, daily cap,
suppression, delays, stop-on-reply.

### 16.3 Sending
- Each message is sent with `POST /email` and carries:
  - `MessageStream`;
  - `Tag` (the property id);
  - `Metadata` (`outreach_id`, `partner_id`, `property_id`, `step`);
  - `TextBody`, with the compliance footer;
  - `Headers` (`List-Unsubscribe`, and `In-Reply-To`/`References` for threading);
  - `TrackOpens=false` and `TrackLinks=None`, which stay off unless
    `VANGUARD_POSTMARK_TRACK_OPENS=1`.
- `Reply-To` is `local+o<outreach id>@<inbound domain>` when
  `VANGUARD_POSTMARK_INBOUND_ADDRESS` is set. Postmark returns the part after `+` as
  `MailboxHash`, which gives exact reply matching. The one-click `List-Unsubscribe` mailto uses
  the same address, so unsubscribes are processed automatically.
- Postmark's `MessageID` is stored as `pm_message_id` and `transport` records
  postmark/smtp/outbox.
- **Monthly cap:** `VANGUARD_POSTMARK_MONTHLY_CAP` (default 100, the free Developer plan
  volume) counts outreach and notifications sent through Postmark this calendar month. When
  it's reached, messages wait for the next month instead of creating overage.

### 16.4 Webhooks (`POST /hooks/postmark`)
- **Authentication:** HTTP Basic Auth (`VANGUARD_POSTMARK_WEBHOOK_USER`/`_PASSWORD`, put in the
  webhook URL as `https://user:pass@host/hooks/postmark`), compared in constant time.
  - Without credentials configured, the route answers 503.
  - With wrong credentials, it answers 401.
- **Matching:** events are matched to a message by `Metadata.outreach_id`, then by
  `MessageID`. Unknown record types are acknowledged and ignored.

| RecordType | Effect |
|---|---|
| Delivery | `delivered_at` |
| Open | `opened_at` (first open only; only if tracking is on) |
| Bounce | Hard (`HardBounce`, `BadEmailAddress`, `ManuallyDeactivated`, `SpamNotification`, or `Inactive`): status `bounced`, address suppressed. Soft: error noted, status unchanged. |
| SpamComplaint | Remaining steps cancelled, partner `email_consent=opted_out`, address suppressed |
| SubscriptionChange | `SuppressSending` true adds a `postmark-suppression`; false removes it |
| Inbound (no RecordType, has `FromFull`/`MailboxHash`) | Matched by `MailboxHash o<id>`, then `In-Reply-To`/`References`, then sender. Runs the §15.5 reply logic (stop the sequence, classify, move the stage, opt-out suppresses), sets `email_consent=replied`, and alerts admins plus the partner owner on the notify stream. Deduplicated by MessageID. |

Inbound processing needs a Postmark plan that includes inbound; the free plan doesn't. IMAP
sync (§15.5) remains the free option, and both can run.

### 16.5 Suppressions, digest, health
- **Suppression sync:** `sync_suppressions` pulls the outreach stream's suppression dump into
  `email_suppression`, and pushes local opt-outs and bounces to Postmark, 50 per call.
- **Approval digest:** `send_digest` emails admins the count and top 10 drafts awaiting approval,
  on the notify stream. Without Postmark it goes via SMTP, or to the outbox.
- **Reply alerts:** `notify_reply` never breaks reply processing, and
  `VANGUARD_NOTIFY_REPLIES=0` turns it off.
- **Logging:** all team emails are logged in `notification_log`.
- **Health:** `doctor` checks the token and streams, and reports the cap and cold-routing
  policy.

### 16.6 Data (new or changed)
| Table | Columns |
|---|---|
| `partners` | + `email_consent` (none/opted_in/existing_relationship/replied/opted_out) |
| `outreach_messages` | + `transport`, `pm_message_id`, `delivered_at`, `opened_at` |
| `notification_log` (new) | at, transport, to_addr, subject, kind (reply/digest) |

## 17. Fail-proof layer (v0.7.0)

Added after a forensic premortem of the Vireoka / LiqMint $3M raise (Sep 28, 2026). The
premortem found that the plan failed on evidence, channel, focus and structure long before it
failed on reach, so the agent now checks those first and keeps checking them every week.

### 17.1 What it adds

| Part | What it does | Where |
|---|---|---|
| Engine 0: forensic premortem | Assumes a plan failed at the horizon and writes the autopsy: 7 ranked causes of death (each traced to a stated fact), month-by-month unfolding, enabling assumption, first warning sign; the verdict (most likely vs most dangerous, the hidden assumption, fatal flaw); the adversary; one tripwire per cause. `--dry-run` builds a $0 premortem from the failure modes on file. | `failproof.run_premortem`, `vanguard premortem` |
| Engine 5: readiness gates | Each property has pre-launch gates with a verification test and a walk-away condition. A gate lists the task classes it blocks; while it is not passed, the agent removes tasks of those classes from every plan and says so (`GATE_BLOCKED` note). | `failproof.apply_to_playbook`, `vanguard gate` |
| Engine 6: tripwire monitor | One measurable signal per failure mode, checked on the Friday of a set week (or every week). Missing evidence is amber, never green. Three tripped tripwires on one property raise HALT: stop, do not adjust the plan, rerun the walk-away gates. | `failproof.evaluate_tripwire`, `tracker`, `vanguard tripwires`, UI Tripwires page |
| Focus lock | The founder's calendar holds LiqMint Institutional (primary), LiqMint retail and Vireoka. Every other property is delegated and must name an owner; a delegated property with no owner (or owned by the founder) carries a `FOCUS_LOCK` note on every playbook. A delegated property with `interim_owner: true` is founder-supervised through AI agents until a CEO is named: its playbooks carry an `INTERIM_OWNER` note with the due date of its `G-CEO` gate, which blocks paid acquisition until passed. | `failproof.focus_issues` |
| Claim discipline | Unchanged lint gate (§7); the website messaging and premortem both rely on it. | `lint_gate.py` |

### 17.2 Configuration and state

`config/failproof.yaml` is the plan: program start (a Monday, week 1), the 26-week horizon, the
meta tripwire, the focus list, task-class regexes (`investor_outreach`, `cold_investor_outreach`,
`paid_acquisition`, `public_launch`), and per property: owner, focus, one sentence, failure modes,
gates, tripwires. It must cover every registry property; the loader refuses unknown task classes,
tripwires pointing at unknown failure modes, check weeks past the horizon and a non-Monday start.

The evidence lives in SQLite (§10): `tripwire_readings` (value, reading date, note, who),
`gate_status` (open / passed / failed, note, who) and `premortems` (plan text + JSON body).

### 17.3 Evaluation rules

- A fixed check uses the latest reading dated on or before that check's Friday.
- A weekly check needs a reading dated inside that week (Saturday to Friday); last week's value does not carry over.
- Status is `tripped` if any due check breaks its rule, else `amber` if any due check has no reading, else `green`; `not_yet_due` before the first check.
- Passing a gate needs a named verifier (`--by`, or the admin's account in the UI). Failing a gate prints its walk-away condition.
- The gate filter runs after Engine 4 in live runs and on `vanguard import`, and strips removed task ids from dependants.

### 17.4 Where it shows

CLI (`tripwires`, `record`, `gate`, `premortem`), web API (`/api/failproof…`), machine API
(`GET /failproof`, `halt` per property for cron), and the UI Tripwires page (everyone records
readings; only admins pass or fail gates).

---

## 18. Change log

| Version | Date | Change |
|---|---|---|
| 0.13.0 | 2026-10-02 | **A mailbox per property** (§15.13): `VANGUARD_MAILBOXES` and `VANGUARD_MAILBOX_<NAME>_*` give listed properties their own sender, SMTP, IMAP and daily cap (Vireoka, LiqMint and LiqMint Institutional from vireoka.com); `EmailConfig.for_property`, `MailRouter` for outreach and intro asks, `from_email` on `outreach_messages` and `intro_requests`, reply sync over every inbox, per-mailbox status in `/outreach/stats` and `vanguard outreach status`. One-off sends log "Sent email from …". Test WEB-36. |
| 0.12.0 | 2026-10-02 | **One-off emails** (§15.12): "Write email" on any named partner (investors included) creates a single draft (`one_off`, steps 101+), saves the address as the contact email, runs the claim rules, needs admin approval and sends through the normal path; "Approve & send" sends only that message (`send_due(only=…)`, `POST /outreach/send-due {ids}`); a reply doesn't cancel a one-off. Lint: a sentence about our own raise is exempt from the attribution rule (`attribution.exempt_pattern`). Tests WEB-35, UI-18. |
| 0.11.0 | 2026-10-02 | **Introductions** (§15.11): full LinkedIn export import (message counts, endorsements, tie strength, role tags; no message text stored); path finder (insiders at the target, likely bridges named in the target's background or in the same world, a LinkedIn 2nd-degree search link per target, at most 4 asks per connector); double opt-in asks with a forwardable blurb, lint-checked, admin-approved, emailed or sent on LinkedIn by hand; outcomes on the partner timeline; Introductions page and a Paths in card on partners; `vanguard intros suggest/list/draft/send`. **Investor list:** 118 more Fintech/Crypto/AI investors from the full 80-page vcconf.com export (310 total), 15 more researched. Tests E2E-35, WEB-34, UI-17. |
| 0.10.0 | 2026-10-02 | **Investor targets** (§15.10): `config/investor_targets.yaml` ranks 192 investors for LiqMint (189 Fintech/Crypto/AI investors from the Sep 2026 VC Pitch Conf list plus 3 March 2026 conference speakers), with conference-derived considerations and sourced research on the top 28; `vanguard investors import/list`; the Load researched partners button also loads them; investor-specific factor labels on the partner page. Tests E2E-34, WEB-33. |
| 0.9.1 | 2026-10-02 | **Investor contacts:** partners can have kind `investor` (web API, UI type picker, filter, rose badge), so fundraising contacts sit in the same pipeline with stages, interactions and next steps. No drafts are generated for them; the agent playbook schema is unchanged. Test WEB-32. |
| 0.9.0 | 2026-10-01 | **Campaigns linked to outreach** (§15.9): partners attach to a campaign (UI "Add partners", `POST/DELETE /campaigns/{id}/partners`, `vanguard campaign attach/detach/show/list`); emails sent, LinkedIn/X touches, replies and meetings for attached partners count towards the campaign automatically and add to hand-logged results; campaign page shows the funnel, the send queue and per-partner progress; Outreach filters by campaign. **LinkedIn connections import** from LinkedIn's own data export (no API, no scraping): matched to partners by company, shown on partner pages and as a Known count, named contacts who connected get a timeline entry, shared emails fill empty contact emails (`vanguard linkedin import/matches`, `/linkedin/connections`). Interaction types `linkedin` and `x`. Tests E2E-33, WEB-30, WEB-31. |
| 0.8.1 | 2026-09-29 | **Partner contacts and mid-market targets** (§15.7): `partner_targets.yaml` gains `how_to_reach`, sourced `contacts` and `recent_hook`; contacts refreshed for 12 LiqMint Institutional partners; 24 new mid-market targets in four new categories (stablecoin banks, stablecoin fintechs, wallet/compliance infrastructure, mid-size advisory); tier-1 banks and Coinbase Prime moved to P1; categories may override draft wording (`middle`, `follow`); import creates segments for newly added categories. **Fix:** design-partner drafts contained `{company}` instead of the `{{company}}` merge tag (str.format collapsed the braces), so emails would have shown a literal placeholder; drafts now keep the tag and sending also fills `{company}` in drafts written earlier. Test WEB-29. |
| 0.8.0 | 2026-09-28 | **PostgreSQL** (§10): `VANGUARD_DATABASE_URL` switches every table to PostgreSQL through `db.py`; SQL made portable (upserts, dates, boolean sums, `GROUP BY`); Docker Compose runs PostgreSQL 16 on a private network; `vanguard db info` and `vanguard db copy-from-sqlite`; the suite runs on PostgreSQL with `VANGUARD_TEST_DATABASE_URL`. **Config path fix:** an installed package (Docker) looked for `config/` inside site-packages; now `VANGUARD_CONFIG_DIR`, else the repo, else `./config`. **Reply-date fix:** replies were dated by the server's local date while sends used UTC, so late-evening replies sorted before the email they answered (WEB-19 failed after midnight UTC); both now use UTC. `.dockerignore` added. Tests E2E-32 and `tests/test_db.py`. |
| 0.7.3 | 2026-09-28 | **Docker fix:** `pyproject.toml` listed only the `vanguard` package, so a non-editable install (the Docker image) left out `vanguard.web` and `vanguard serve` failed with `ModuleNotFoundError`. Both packages are now listed, and `tests/test_docs_sync.py` fails if a package under `vanguard/` is missing from the build list. |
| 0.7.2 | 2026-09-28 | **Interim owners and CEO gate:** the five delegated properties are marked `interim_owner: true` (founder-supervised through AI agents from Naren@atmakosh.com) and each gets a `G-CEO` gate due week 16 (Jan 15, 2027) that blocks paid acquisition until a CEO is named. Playbooks carry an `INTERIM_OWNER` note; the tracker and Tripwires page show the interim status. |
| 0.7.1 | 2026-09-28 | **Owners assigned:** WeddingOS, Jodibana, JodiUSA, OratoPlus and Atmakosh are owned by Naren@atmakosh.com in `config/failproof.yaml`, which clears their FOCUS_LOCK notes. Tests keep exercising the focus lock with an unowned copy of the config. |
| 0.7.0 | 2026-09-28 | **Fail-proof layer** (§17): Engine 0 forensic premortem (`vanguard premortem`, `--dry-run` at $0), Engine 5 readiness gates that remove blocked task classes (investor outreach, cold investor outreach, paid acquisition, public launch) from plans until passed, Engine 6 tripwire monitor with Friday checks and HALT at 3 tripped, and the focus lock for delegated properties. `config/failproof.yaml` covers all 8 properties; new tables `tripwire_readings`, `gate_status`, `premortems`; CLI `tripwires`, `record`, `gate`, `premortem`; `/api/failproof…` and machine `GET /failproof`; UI Tripwires page. Tests E2E-29–31, WEB-28 and `tests/test_failproof.py`. |
| 0.6.0 | 2026-09-28 | **Researched partners** (§15.7): `config/partner_targets.yaml` lists 117 real, source-cited organisations across all 8 properties. `targets.py` imports them idempotently as named partners with inherited 3-step drafts, enriching playbook examples rather than duplicating them, and clamps each score into its priority band. Adds `vanguard partners import`, `POST /api/partners/import-research`, the "Load researched partners" button, researched badges, and clickable source, contact and website links. Tests WEB-26, WEB-27 and UI-15. |
| 0.5.1 | 2026-09-28 | **Windows fix:** every text file is read and written as UTF-8 explicitly. Windows' default cp1252 crashed on the config files (`UnicodeDecodeError` in `demo-data`, `run`, `serve`). The CLI console is set to UTF-8 with replacement. Adds `start.ps1` (one-command Windows start) and a flat install layout in the setup guide. |
| 0.5.0 | 2026-09-27 | **Postmark message streams** (§16): `postmark` email mode sending through a transactional outreach stream with Tag, Metadata, a `+o<id>` Reply-To and List-Unsubscribe; per-partner `email_consent` with the permission-based policy (cold first touch via your own SMTP or held; `VANGUARD_POSTMARK_ALLOW_COLD` override); monthly cap (default 100); Basic-Auth webhook for Delivery, Open, Bounce, SpamComplaint, SubscriptionChange and Inbound replies; two-way suppression sync; stream check; reply alerts and approval digest on a notify stream (`notification_log`); UI Postmark banner, transport badges, consent select, digest button; CLI `outreach digest\|postmark-sync\|postmark-check`; `doctor` checks Postmark. Docs-sync now also catches env vars read through `g = os.getenv`. |
| 0.4.0 | 2026-09-27 | **Partner outreach** (§15): expert partner playbooks for all 8 properties; Engine 2B recommends, scores and prioritises design, co-sell and channel partners and drafts 3-step sequences; segments → named targets; admin-approved sending (outbox by default, SMTP optional) with compliance footer, suppression, cap and threading; IMAP and manual reply tracking; agreement tracking on the dashboard; Outreach page; `partners recommend` and `outreach` CLI. |
| 0.3.0 | 2026-09-27 | **Web app** (§14): React UI plus JSON API with admin and general-user roles; campaign CRUD with results logging; partner pipeline board with interactions; task assignment; dashboard with ARR targets; agent runs, approval, import and Notion sync from the UI; users and audit log; login throttling; `seed-users`, `create-user` and `demo-data`; multi-stage Docker build. **Local LLM provider**: Ollama or OpenAI-compatible (`qwen3.6:27b` default), local-first with Claude as a capped fallback (`providers.py`), `--provider`, and `doctor`/`estimate` aware of the local model. |
| 0.2.0 | 2026-09-27 | **$0 by default** (paid runs off until a cap is set). **Engine 2 requires a design partner and a B2B co-selling partner** (`Partnership.kind`). WeddingOS URL is now weddingos.jodibana.com. `prompt all` / `import all`. **Registry refreshed from vireoka-dev** (five confirmed, three drafts). **Explicit `task_prefix`**: fixes a bug where liqmint and liqmint-institutional, and jodibana and jodiusa, shared task ids and merged in Notion. Notion task lookup now also filters by Property. **Per-property `banned_terms`** in the lint gate. **Cost controls**: estimate, confirmation, hard cap, metered usage per run. **`doctor`**, **`estimate`**, **`prompt`/`import`** ($0 manual path). Web research resumes on `pause_turn`. End-to-end suite plus a stateful fake Notion. Design doc, Programmer's Manual, test catalogue, setup guide. |
| 0.1.0 | 2026-09-27 | First build: four-engine orchestrator, lint gate with repair loop, SQLite store, Notion sync, approval-gated exports, CLI, API, Docker/Traefik deploy. |
