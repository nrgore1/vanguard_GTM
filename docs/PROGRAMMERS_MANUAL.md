# Vanguard-GTM — Programmer's Manual

Version 0.15.1 · updated 2026-10-03 · see also [Design](DESIGN.md), [Test Cases](TEST_CASES.md), [User Guide](USER_GUIDE.md),
[Setup: Notion & keys](SETUP_NOTION_AND_KEYS.md)

> **Rule for every change:** update this manual, `DESIGN.md` (including its §18 change log) and
> `CHANGELOG.md` in the same commit. `pytest` includes `tests/test_docs_sync.py`, which fails
> when a CLI command, environment variable, registry field or test ID isn't documented.

---

## 1. Getting set up

```bash
# Python 3.11+
cd C:\Users\NAREN\vireoka-dev\Vanguard_GTM          # the repo root: vanguard/, ui/, config/ sit directly here
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                   # fill in later; not needed for dry runs
pytest -q                                              # offline suite (3 opt-in live tests skipped), ~40 s, $0
vanguard run --dry-run                                 # full 8-property offline run
vanguard seed-users                                    # admin + team accounts (passwords printed once)
vanguard demo-data                                     # optional [DEMO] records to explore the UI
vanguard serve                                         # web app on http://localhost:8080
```

Front-end development, with hot reload against the running API:
```bash
cd ui && npm install
npm run dev          # http://localhost:5173, proxies /api to :8080 (keep `vanguard serve` running)
npm run build        # writes ui/dist, which `vanguard serve` serves
```

Load `.env` into your shell before real runs:
- bash/zsh: `set -a; source .env; set +a`
- PowerShell: `Get-Content .env | % { if ($_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), ($matches[2] -replace '\s+#.*$','').Trim()) } }`
- Docker Compose reads `.env` for you.

## 2. Repository layout

```
vanguard-gtm/
├── config/
│   ├── properties.yaml      # property registry - the source of truth for positioning
│   ├── lint_gate.yaml       # claim rules by profile + attribution rule
│   └── partner_playbooks.yaml  # expert partner categories per property + scoring weights
├── vanguard/
│   ├── cli.py  api.py       # entry points
│   ├── orchestrator.py      # parallel fan-out
│   ├── engines.py           # prompts, the 4 engines, repair loop, assemble, prompt/import
│   ├── llm.py  cost.py      # Claude client, metering, spend cap
│   ├── schema.py            # pydantic contracts
│   ├── lint_gate.py  registry.py  store.py  notion_sync.py  exporters.py
│   ├── providers.py         # local models (Ollama / OpenAI-compatible) + Claude fallback
│   ├── partners.py          # Engine 2B: recommend, score, prioritise partners, draft sequences
│   ├── targets.py           # import researched real organisations (config/partner_targets.yaml)
│   ├── outreach.py          # approval-gated sending, consent routing, reply matching, opt-outs, team alerts
│   ├── postmark.py          # Postmark streams: send, webhooks, suppression sync, stream check
│   ├── mock_fixtures.py     # placeholder data for dry runs and tests
│   └── web/                 # web app: app.py (API), db.py, security.py, demo.py
├── ui/                      # React front end
│   ├── src/                 # main.tsx, lib/ (api, auth, format), components/, pages/
│   ├── e2e/                 # Playwright browser tests + isolated test server script
│   └── dist/                # built UI served by `vanguard serve`
├── tests/
│   ├── test_vanguard.py     # unit / component
│   ├── test_e2e.py          # end-to-end (CLI, API, ClaudeLLM path, Notion)
│   ├── test_web.py          # web API: auth, roles, CRUD, dashboard, runs from the UI
│   ├── test_docs_sync.py    # docs-coverage guard
│   └── fake_notion.py       # stateful Notion fake
├── docs/                    # DESIGN, PROGRAMMERS_MANUAL, TEST_CASES, SETUP_NOTION_AND_KEYS
├── deploy/traefik-vanguard.yml
├── Dockerfile  docker-compose.yml  .env.example  pyproject.toml  CHANGELOG.md  CLAUDE.md
```

## 3. Configuration reference

### 3.1 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VANGUARD_DATABASE_URL` | empty (SQLite) | `postgresql://user:pass@host:5432/db` to use PostgreSQL for every table. Docker Compose sets it. |
| `VANGUARD_DB_PASSWORD` | — | Compose only: password for the bundled PostgreSQL; the app's URL is built from it |
| `VANGUARD_CONFIG_DIR` | repo `config/`, else `./config` | Where `properties.yaml`, `lint_gate.yaml`, `failproof.yaml` and the partner files live. The Docker image sets `/app/config`. |
| `VANGUARD_PROVIDER` | `local` | `local`: local model first, Claude only as a capped fallback. `claude`: Claude only (paid). |
| `VANGUARD_LOCAL_MODEL` | `qwen3.6:27b` | Ollama tag or server model id (for example `qwen3.8:27b` or `llama3.1:8b`) |
| `VANGUARD_LOCAL_API` | `ollama` | `ollama`, or `openai` for LM Studio, llama.cpp `llama-server` or vLLM |
| `VANGUARD_LOCAL_URL` | `http://localhost:11434` (ollama) / `http://localhost:1234/v1` (openai) | Local server address |
| `VANGUARD_LOCAL_CTX` | `32768` | Context window requested from Ollama (`num_ctx`) |
| `VANGUARD_LOCAL_THINK` | `0` | `1` lets reasoning models "think". Slower; may improve Engine 1. |
| `VANGUARD_LOCAL_TIMEOUT` | `900` | Seconds per local call (big models on CPU are slow) |
| `VANGUARD_LOCAL_CONCURRENCY` | `1` | Simultaneous local generations. Raise it only with spare GPU memory. |
| `VANGUARD_RESEARCH_WITH_CLAUDE` | `0` | `1` sends only Engine 1 web research to Claude (paid, capped) |
| `ANTHROPIC_API_KEY` | — | Claude API key. Only needed for the fallback or `VANGUARD_PROVIDER=claude`. |
| `VANGUARD_MODEL` | `claude-sonnet-5` | Claude model, for the fallback or Claude-only runs. `claude-haiku-4-5` is the cheapest option; `claude-opus-5-5` is the strongest. |
| `VANGUARD_WEB_SEARCH` | `1` | `0` turns off Engine 1 web research, which saves about 40% |
| `VANGUARD_MAX_COST_USD` | `0` | **0 means paid API runs are off ($0 mode).** A positive value turns paid runs on and is the hard spend cap per run. |
| `VANGUARD_PRICE_INPUT` / `VANGUARD_PRICE_OUTPUT` | built-in table | Override $/MTok if list prices change |
| `VANGUARD_CONCURRENCY` | `4` | Properties processed at once |
| `VANGUARD_API_TOKEN` | — | Bearer token for the HTTP API. Every route except `/health` returns 503 without it. |
| `NOTION_TOKEN` | — | Notion internal-connection token |
| `VANGUARD_DB` | `data/vanguard.db` | SQLite path |
| `VANGUARD_OUTPUT` | `output` | Per-run JSON and exports |
| `VANGUARD_NOTION_CONFIG` | `data/notion.json` | Notion database ids written by `notion-setup` |
| `VANGUARD_JWT_SECRET` | random, saved to `data/jwt_secret` | Signs web sessions. Set it explicitly in production so sessions survive a volume reset. |
| `VANGUARD_SESSION_HOURS` | `12` | How long a web sign-in lasts |
| `VANGUARD_UI_DIST` | `ui/dist` | Folder of the built UI that `serve` serves |
| `VANGUARD_EMAIL_MODE` | `outbox` | `outbox` writes approved partner emails as `.eml` files to `output/outbox` and sends nothing. `smtp` really sends through your mailbox. `postmark` sends warm contacts through Postmark streams (cold first touches go via SMTP or are held). |
| `VANGUARD_SENDER_NAME` / `VANGUARD_SENDER_EMAIL` | — | From identity. Both required in smtp and postmark modes. In Postmark the email must be a confirmed sender signature or on a verified domain. |
| `VANGUARD_SENDER_ADDRESS` | — | Postal address for the compliance footer. Required in smtp and postmark modes. |
| `VANGUARD_REPLY_TO` | — | Optional Reply-To, also used for List-Unsubscribe |
| `VANGUARD_EMAIL_DAILY_CAP` | `20` | Maximum partner emails per day |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_STARTTLS` | — / `587` / — / — / `1` | Your mailbox's SMTP. Port 465 uses implicit SSL. |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_USER` / `IMAP_PASSWORD` / `IMAP_FOLDER` | — / `993` / — / — / `INBOX` | Optional reply sync. Read-only; nothing is marked read or deleted. |
| `VANGUARD_SAVE_SENT` / `IMAP_SENT_FOLDER` | `1` / found | After an SMTP send, append a copy (marked read) to the mailbox's Sent folder over IMAP, because SMTP keeps none. The folder is the one flagged `\Sent`, else one named Sent / Sent Items / Sent Messages; set `IMAP_SENT_FOLDER` to override. Needs that mailbox's IMAP login; a failed copy never fails the send (the send report's `copy` says why). v0.13.1. |
| `VANGUARD_MAILBOXES` | — | Comma list of extra mailbox names (v0.13.0). Each name `N` reads `VANGUARD_MAILBOX_<N>_PROPERTIES` (property ids that send from it), `_SENDER_EMAIL`, `_SMTP_PASSWORD`, and optionally `_SENDER_NAME`, `_SENDER_ADDRESS`, `_REPLY_TO`, `_DAILY_CAP`, `_SMTP_HOST`, `_SMTP_PORT`, `_SMTP_USER`, `_IMAP_HOST`, `_IMAP_PORT`, `_IMAP_USER`, `_IMAP_PASSWORD`, `_IMAP_SENT_FOLDER`. Unset keys inherit the default mailbox; SMTP/IMAP user default to the sender email; IMAP password defaults to the SMTP password; a password is never taken from another mailbox. Properties not listed use the default mailbox. See DESIGN §15.13. |
| `POSTMARK_SERVER_TOKEN` | — | Postmark server API token (`X-Postmark-Server-Token`). Required in postmark mode. Also enables team alerts on the notify stream in any mode. |
| `VANGUARD_POSTMARK_STREAM_OUTREACH` | `outbound` | Transactional stream for partner emails. Create one called `partners` and set it here. |
| `VANGUARD_POSTMARK_STREAM_NOTIFY` | `outbound` | Transactional stream for reply alerts and the approval digest |
| `VANGUARD_POSTMARK_INBOUND_ADDRESS` | — | The inbound stream's address (for example `abc123@inbound.postmarkapp.com`, or `reply@in.yourdomain.com` with inbound domain forwarding). Used as `Reply-To` with `+o<id>` for exact reply matching. Inbound needs a plan that includes it. |
| `VANGUARD_POSTMARK_ALLOW_COLD` | `0` | `1` lets cold first-touch emails go through Postmark. Off because Postmark only permits permission-based email. |
| `VANGUARD_POSTMARK_TRACK_OPENS` | `0` | `1` turns on open tracking (adds a pixel). Link tracking always stays off. |
| `VANGUARD_POSTMARK_MONTHLY_CAP` | `100` | Maximum Postmark sends (outreach + alerts) per calendar month. 100 matches the free Developer plan. |
| `VANGUARD_POSTMARK_WEBHOOK_USER` / `VANGUARD_POSTMARK_WEBHOOK_PASSWORD` | — | Basic Auth for `POST /hooks/postmark`. Without both, the webhook answers 503. |
| `VANGUARD_NOTIFY_REPLIES` | `1` | `0` stops the email alert to admins and the partner owner when a partner replies |
| `VANGUARD_OUTREACH_EVERY_MIN` | `0` (off) | When above 0, `serve` sends due approved messages and checks replies on this interval |
| `TRAEFIK_NETWORK` | `edge` | Docker network of the Traefik edge (compose only) |

### 3.2 `config/properties.yaml`

Top-level `defaults:` sets `revenue_target_usd`, `campaign_days` and `market`. Fields for each
property:

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique slug, used in the CLI and in Notion |
| `task_prefix` | yes | Unique, 2–5 capital letters. Task ids become `PREFIX-001`. |
| `url`, `name`, `track` (A/B/C), `motion` | yes | |
| `lint_profile` | yes | `institutional`, `standard` or `consumer` |
| `positioning_status` | yes | `confirmed` or `needs_review` |
| `positioning` | yes | What the engines must build from |
| `not_this` | no | Hard exclusions ("not a yield product") |
| `capability_facts` | no | Used verbatim. Keep claim-safe wording, such as "fully capable of supporting Canton integration". |
| `pricing_facts` | no | Real price points, plus any internal targets marked as internal |
| `icp_seeds`, `partner_seeds`, `channels` | no | Starting points the engines expand on |
| `known_pipeline_context` | no | Private. The prompt tells Claude never to cite it. |
| `banned_terms` | no | Words or phrases that block that property's copy |
| `sources` | confirmed entries | Repo docs the entry was written from |

### 3.3 `config/partner_playbooks.yaml`
- `scoring.weights` (fit, reach, access, strategic, speed), plus `p0_min` and `p1_min`.
- `message_rules.default_delays_days`.
- `properties.<id>.product_line`, and `categories[]`. Each category has:
  - `id`, `label`, `kind`;
  - `why`, `value_exchange`, `deal_structure`, `where_to_find`;
  - `factors` (1–5 each);
  - `angle`, which completes the sentence "I'm reaching out because…";
  - `offer`, the concrete proposal;
  - optional `examples`: named organisations to research, which become individual
    recommendations;
  - optional `middle` and `follow`: replace the default wording of the first email's pitch and
    the follow-up for that category. `{offer}` is filled in; keep merge tags as `{{company}}`.

Every property needs at least one `design_partner` and one `co_sell` category.

### 3.3a `config/partner_targets.yaml`
Researched, real organisations to approach, grouped by property id under `properties:`. Each item
has these fields:

| Field | What it holds |
|---|---|
| `category` | A category id from `partner_playbooks.yaml` for that property (validated) |
| `name` | The organisation's name |
| `website` | https, or null |
| `location` | City and state or country |
| `why` | Grounded in the evidence, with no guarantees or unsourced numbers |
| `evidence_url` | https link to the source |
| `contact_email` | A generic organisation inbox, or null. Never a person's address. |
| `contact_url` | https contact page, partner program or form |
| `priority_hint` | `P0`, `P1` or `P2` |
| `confidence` | `high` or `medium` |
| `kind` | Informational; the category decides the real kind |
| `how_to_reach` | Optional: the best route in (form, program, warm-intro angle, caveats) |
| `contacts` | Optional list of `{name, title, source, confidence}` for people who publicly hold the relevant role; `source` is the https page that shows it. No emails. The first becomes `contact_name` unless one was entered by hand. |
| `recent_hook`, `recent_hook_url` | Optional: a recent development that makes outreach timely, and its source |

Edit the file freely and re-run `vanguard partners import`. It is idempotent: existing partners
are refreshed, never duplicated, and hand-entered emails are kept. `tests/test_web.py::WEB-27`
validates the file.

### 3.3b `config/investor_targets.yaml`
`property_id` (default `vireoka`) and `investors`: a list in rank order. Each entry: `name`, `firm`, `types`,
`geography`, `check_size`, `stages`, `sectors`, `source`, `score`, `rank`, `priority`, `factors` (`thesis`,
`stage`, `check`, `geo`, `research`, each 0-5), `signals`, `considerations`, and optional `research`
(`title`, `website`, `location`, `linkedin`, `thesis`, `fund_size`, `relevant_portfolio`, `recent_deals`,
`leads_rounds`, `typical_check`, `contact_route`, `published_email`, `fit`, `concern`, `hook`, `confidence`,
`sources`). Only an email the investor's own site publishes may go in `published_email`. The scoring rules
are in the file header and DESIGN §15.10.

### 3.4 `config/lint_gate.yaml`

- `attribution`: `enabled_profiles`, `number_pattern`, `source_pattern`, `severity` and `exempt_pattern`
  (sentences matching it, such as "We're raising a $3M seed", need no source; since v0.12.0).
- `profiles.<name>`: a list of rules, each with `id`, `severity` (`block` or `warn`), `pattern`
  and `message`.
- Patterns are Python regexes, matched case-insensitively. The exception is `source_pattern`:
  its keywords are wrapped in `(?i:…)` so that "per X" still needs a capitalised name.

### 3.5 `config/failproof.yaml`

The fail-proof plan (DESIGN §17). Top-level keys:

- `program`: `start` (a Monday; week 1), `weeks` (default 26), `meta_tripwire` (`week`, `max_tripped`).
- `focus`: `founder` (property ids on the founder's calendar), `primary`, `founder_name`.
- `task_classes`: name → regex. Gates block these classes; the default set is `investor_outreach`,
  `cold_investor_outreach`, `paid_acquisition`, `public_launch`.
- `properties.<id>`: `owner` (null until delegated), `interim_owner` (true while the founder supervises the property through AI agents until a CEO is named; pair it with a `G-CEO` gate), `focus` (`primary`, `founder` or `delegated`),
  `one_sentence`, `failure_modes` (`id`, `name`, `cause`, `assumption`, `first_warning`),
  `gates` (`id`, `name`, `verify`, `walk_away_if`, `deadline_week`, `blocks`),
  `tripwires` (`id`, `failure_mode`, `signal`, `unit`, `checks: [{week, trips_if}]` and/or
  `every_week_from` + `trips_if`, `basis` = `premortem`/`prd`/`proposed`, `action`).
- Rules are `"<op> <number>"` with op `<`, `<=`, `>`, `>=`, `==`, `!=`.

To delegate a property, set its `owner`. To change a threshold, edit the tripwire and set
`basis: proposed` unless it came from the premortem or a PRD. Readings and gate results are in
the database, not this file.

## 4. CLI reference

| Command | What it does | Spends money? |
|---|---|---|
| `vanguard run [--properties a,b\|all] [--provider local\|claude] [--dry-run] [--no-research] [--concurrency N] [--sync] [-y]` | Generates playbooks. A real run is refused while the cap is 0. Otherwise it shows an estimate and asks for confirmation unless you pass `-y`. | Only when the cap is above 0 and it isn't `--dry-run` |
| `vanguard estimate [--properties …] [--provider local\|claude] [--model M] [--no-research]` | Prints a cost estimate. For `local` it's $0, plus the worst case the fallback cap allows. | No |
| `vanguard doctor` | Checks that the local model server is reachable and the model is pulled, then the Anthropic key (by listing models, which is free), the Notion token and database access | No |
| `vanguard status [--run ID]` | Shows the table (lint, ACV, units, months, tasks, approval, flags) and the run's spend | No |
| `vanguard show <property> [--run ID]` | Prints the full playbook JSON | No |
| `vanguard approve <property> --by NAME [--run ID]` | Human sign-off. Refused for blocked playbooks. | No |
| `vanguard export [property\|all] [--run ID] [--out DIR] [--format csv\|json]` | Writes sequence CSVs (approved only) and the task backlog | No |
| `vanguard prompt <property> [--out FILE]` · `vanguard prompt all --out DIR` | Writes a self-contained prompt, or one `<id>.prompt.txt` per property, to paste into Claude chats | No |
| `vanguard import <property> <reply.json> [--run ID]` · `vanguard import all DIR` | Validates, lints and stores playbooks from chat replies (`DIR/<id>.json`). Code fences and surrounding text are tolerated. Missing or invalid replies are reported, and the run is marked partial. | No |
| `vanguard notion-setup --parent-page ID` | Creates the two Notion databases and writes `data/notion.json` | No |
| `vanguard sync [--run ID]` | Pushes a run to Notion. Safe to repeat. | No |
| `vanguard serve [--host] [--port 8080]` | Starts the web app: UI at `/`, UI API at `/api`, machine API at `/machine` | No |
| `vanguard seed-users [--admin-email E] [--user-email E]` | First run only: creates one admin and one general user with random passwords, printed once | No |
| `vanguard partners import [FILE]` | Loads researched real organisations (default `config/partner_targets.yaml`) as named partners with their own 3 draft emails. Idempotent; prints added/refreshed counts and how many lack a public inbox. Nothing is approved or sent. | No |
| `vanguard partners recommend <property\|a,b\|all> [--model] [--provider local\|claude]` | The partnerships expert. Prints the ranked plan and stores partners with 3-step drafts. `--model` lets the local model name organisations; the default is the $0 playbook. | No (local) |
| `vanguard campaign list [--property P]` | Lists campaigns with their outreach totals (partners, emails, LinkedIn/X touches, replies, meetings) | No |
| `vanguard campaign show <id>` | Funnel, send queue and one line per attached partner (stage, email, emails sent of steps, LinkedIn/X touches, last touch) | No |
| `vanguard campaign attach <id> <partner…>` · `vanguard campaign detach <id> <partner…>` | Puts partners (ids or exact names, same property) into a campaign or takes them out; a segment brings its named organisations; a partner in another campaign is moved | No |
| `vanguard investors import [FILE]` | Loads the ranked investor targets (default `config/investor_targets.yaml`) as partners of kind investor under the file's property. Refreshes on re-run without touching stage, hand-entered email or next step. No emails drafted. | No |
| `vanguard investors list [--priority P0\|P1\|P2]` | Investors in score order with type, firm and stage | No |
| `vanguard intros suggest [--property a,b]` | Finds introducers for investors and partners (founder properties by default) from imported LinkedIn data: insiders and likely bridges, up to 3 per target, at most 4 asks per connector | No |
| `vanguard intros draft` · `vanguard intros list [--status S]` | Drafts every suggested ask (double opt-in note + forwardable blurb, lint-checked) · lists asks with path and tie strength | No |
| `vanguard intros send` | Emails admin-approved asks to connectors who shared an email; the rest wait to be sent on LinkedIn | No |
| `vanguard linkedin import Connections.csv\|export.zip [--by EMAIL]` | Loads LinkedIn's own connections export (or the full .zip archive, which adds message counts, endorsements and tie strength) (Settings → Data privacy → Get a copy of your data) for that user, matches companies to partners, logs "Connected on LinkedIn" for named contacts and fills empty contact emails the connection shared. Safe to re-run. | No |
| `vanguard linkedin matches [--property P]` | Who you know at each partner, from imported connections | No |
| `vanguard outreach status` | Email mode, problems, daily cap, Postmark streams and monthly usage, queue and reply stats | No |
| `vanguard outreach purge-general` | Removes general-inbox addresses (support@, info@ …) and imported unconfirmed ones from partners, keeps them as a note, cancels unsent emails to them; lists typed-in unconfirmed addresses. Also runs on every `vanguard serve` start | No |
| `vanguard outreach approve <ids…> [--by NAME]` | Approves messages from the CLI (the admin's call) | No |
| `vanguard outreach send` | Sends every approved message that is due (outbox, SMTP or Postmark, following the consent policy) | No |
| `vanguard outreach sync-replies` | Reads the IMAP inbox and applies replies, opt-outs and bounces | No |
| `vanguard outreach digest` | Emails admins the approval digest (Postmark notify stream, else SMTP, else outbox) | No (counts toward the Postmark monthly cap) |
| `vanguard outreach postmark-check` | Lists the server's streams, flags missing or non-transactional ones, and shows this month's usage against the cap | No |
| `vanguard outreach postmark-sync` | Two-way suppression sync with the outreach stream | No |
| `vanguard create-user --email E --name N [--role admin\|user] [--password P]` | Adds a web user (prompts for the password if omitted) | No |
| `vanguard tripwires [--property a,b] [--as-of YYYY-MM-DD] [--json] [--out FILE]` | Prints the tripwire tracker and gates per property. Exits 2 when any property is at HALT (3+ tripped), so cron can alert. | No |
| `vanguard record <property> <tripwire> <value> [--date D] [--note N] [--by NAME]` | Records a tripwire reading (default date today) | No |
| `vanguard gate <property> <gate> pass\|fail\|open [--by NAME] [--note N]` | Sets a readiness gate. `pass` needs `--by`. `fail` prints the walk-away condition. | No |
| `vanguard premortem <property> [--plan FILE] [--dry-run] [--provider local\|claude] [--out FILE]` | Engine 0: writes a forensic premortem (7 causes, verdict, adversary, tripwires) and stores it. `--dry-run` is $0 from the failure modes on file. | Only through the capped Claude fallback |
| `vanguard db info` | Shows which database is in use (PostgreSQL URL with the password hidden, or the SQLite file) and row counts | No |
| `vanguard db copy-from-sqlite FILE [--replace]` | Copies every table from an old SQLite file into the configured database. Tables that already hold rows are skipped unless `--replace`. | No |
| `vanguard demo-data [--purge]` | Loads, or removes, clearly labelled `[DEMO]` campaigns, partners, results and a demo run | No |

`--run` defaults to the latest run.

## 5. HTTP API reference

### 5.1 Web API (`/api`, used by the UI)
Sign in with `POST /api/auth/login {email, password}`, which returns `{token, user}`. Send
`Authorization: Bearer <token>` after that.

"Admin" in the table below means a user without the admin role gets 403.

| Area | Routes |
|---|---|
| Session | `POST /auth/login`, `GET /me` |
| Users | `GET /users` (names only for general users) · admin: `POST /users`, `PATCH /users/{id}` (name, role, active, password), `DELETE /users/{id}` |
| Portfolio | `GET /properties`, `GET /dashboard` · admin: `PUT /targets/{property}` |
| Campaigns | `GET /campaigns?property_id&status` (sent/replies/meetings include outreach for attached partners; `outreach_summary` per row), `POST /campaigns`, `GET/PATCH /campaigns/{id}` (`GET` adds `outreach`: partners, totals, queue), `DELETE /campaigns/{id}` (creator or admin; partners leave the campaign), `POST /campaigns/{id}/results`, `DELETE /results/{id}` (creator or admin), `POST /campaigns/{id}/partners {partner_ids}` (returns attached, moved, refused), `DELETE /campaigns/{id}/partners/{pid}` |
| Introductions | `POST /linkedin/export {zip_b64}` (the full LinkedIn archive; 400 if not a zip with Connections.csv), `POST /intros/suggest {property_ids?}`, `GET /intros?status&partner_id&kind` (rows carry `mutuals_url`), `POST /intros/{id}/draft`, `PATCH /intros/{id} {subject?, body?}` (back to draft, re-linted), `POST /intros/{id}/sent-linkedin` (approved only), `POST /intros/{id}/outcome {outcome: accepted\|introduced\|declined\|cancelled, note?}` · admin: `POST /intros/approve {ids}`, `POST /intros/send`. `GET /partners/{id}` adds `intros` and `mutuals_url`. |
| LinkedIn | `POST /linkedin/connections {csv}` (the user's own Connections.csv text; 400 if it isn't the export), `GET /linkedin/connections` (rows per user, partners with connections), `DELETE /linkedin/connections` (delete your own). `GET /partners` adds `connections` (count) and `campaign_name`; `GET /partners/{id}` adds `connections` (people) and `campaign_name`. |
| Partners | `GET /partners?property_id&kind` (kinds: design_partner, co_sell, distribution, referral_affiliate, integration, investor), `POST /partners`, `GET/PATCH /partners/{id}`, `POST /partners/{id}/interactions` (types email, linkedin, x, call, meeting, demo, proposal, note; optional `stage` moves the partner), `DELETE /interactions/{id}` (creator or admin) · admin: `DELETE /partners/{id}` |
| Partner outreach | admin: `POST /partners/import-research` (load `config/partner_targets.yaml` and `config/investor_targets.yaml`; returns per-property created/updated, `investors` {created, updated, by_priority}, errors, without_email) · admin: `POST /partners/recommend {property_id, mode: offline\|model, provider}` · all users: `POST /partners/{segment}/targets` (add a named organisation under a segment), `POST /partners/{id}/reply {date, summary, outcome?, kind}`, `GET /outreach?status&property_id&partner_id&campaign_id` (segments excluded unless partner_id; rows carry `campaign_name`), `GET /outreach/stats`, `PATCH /outreach/{id}` (edit; resets to draft; re-lints), `POST /partners/{id}/channel {channel}` (move unsent messages; back to draft; 422 without the profile/handle), `GET /outreach/by-hand` (approved LinkedIn/X messages with `due`, `held`, `profile_url`), `POST /outreach/{id}/mark-sent` (LinkedIn/X only; approved only; 409 otherwise), `POST /outreach/schedule {ids, send_at (ISO with offset, or null to clear), per_day?, gap_min?, weekdays_only?, tz_offset_min?}` (returns scheduled, refused; approved messages: admin only), `POST /partners/{id}/email {subject, body, contact_email?, send_at?, channel?: email|linkedin|x, linkedin_url?, x_handle?, named_confirmed?}` (422 for a general inbox, or an address not built from the contact's name unless `named_confirmed`) (one-off draft, steps 101+, `one_off`=1; 422 for a segment or a bad address) · admin: `POST /outreach/approve {ids}`, `POST /outreach/{id}/cancel`, `POST /outreach/send-due {ids?}` (only those ids when given; each sent row reports `from` and `copy`: the Sent folder it was saved to, null, or why it wasn't), `POST /outreach/sync-replies`, `POST /outreach/digest`, `POST /outreach/postmark-sync`, `GET /email/postmark` (stream check + usage; 409 without a token). Partner `POST`/`PATCH` take `linkedin_url` and `x_handle` (normalised; 422 if not a profile link or handle), and `email_named` (the contact email is confirmed as that person's own; reset when the address changes). A general-inbox `contact_email` (support@, info@ ...) is a 422. `GET /partners/{id}` adds `email_status` (none, role, named, unverified). Admin: `POST /partners/purge-general-inboxes` (returns removed, unverified). Partner `PATCH` also takes `agreement_status`, `agreement_signed_date`, `agreement_notes`, `website`, `email_consent` (`opted_out` also suppresses the address and cancels queued messages). `GET /outreach/stats` → `email.postmark` includes `used_this_month`; `by_hand_due` counts LinkedIn/X messages due to send by hand; `email.auto_every_min` is the scheduler interval (0 = off); `email.mailboxes` lists each mailbox (name, sender, properties, daily cap, IMAP on/off; never passwords) and `email.senders` maps property id → sender for properties with their own mailbox. |
| Tasks | `GET /tasks?property_id&status&mine`, `PATCH /tasks/{id}` (a user may change only status and notes, and only when assigned) · admin: `POST /tasks`, `DELETE /tasks/{id}` |
| Agent (admin) | `GET /agent/status`, `GET /runs`, `POST /runs {properties, dry_run, provider}` (409 if it can't run at $0), `GET /runs/{id}`, `GET /runs/{id}/playbooks/{pid}`, `POST /runs/{id}/approve/{pid}`, `POST /runs/{id}/import`, `POST /runs/{id}/sync` |
| Fail-proof | `GET /failproof?as_of&property_id` (tracker), `POST /failproof/{pid}/readings {tripwire_id, value, date?, note?}` (any user), `GET /failproof/{pid}/premortem` (latest; 404 if none) · admin: `PUT /failproof/{pid}/gates/{gid} {status: open\|passed\|failed, note?}` (returns `walk_away_if` when failed) |
| Audit (admin) | `GET /audit?limit=100` |

Validation errors return 422 with field paths. Conflicts return 409, and missing records 404.

**Postmark webhook** (outside `/api`, no bearer token): `POST /hooks/postmark` with HTTP Basic Auth
from `VANGUARD_POSTMARK_WEBHOOK_USER`/`_PASSWORD`. It accepts Delivery, Open, Bounce,
SpamComplaint, SubscriptionChange and Inbound JSON, and returns `{handled, matched, …}`. It
answers 401 for bad credentials and 503 when none are configured. See DESIGN §16.4.

### 5.2 Machine API (`/machine`, for cron / n8n)

Every route except `/health` needs the header `Authorization: Bearer $VANGUARD_API_TOKEN`. When
it's served through `vanguard serve`, prefix these paths with `/machine`.

| Method & path | Body | Returns |
|---|---|---|
| `GET /health` | — | `{"ok": true}` |
| `GET /properties` | — | id, url, name, track, motion, positioning_status for each property |
| `POST /runs` | `{"properties":["all"], "dry_run":false, "concurrency":null, "sync_notion":false}` | 202 `{"run_id", "properties"}`. The run happens in the background. |
| `GET /runs/{id}` | — | Run row, including `usage.cost_usd` and a playbook summary |
| `GET /runs/{id}/playbooks/{pid}` | — | Full playbook |
| `POST /runs/{id}/playbooks/{pid}/approve` | `{"approved_by":"narendra"}` | 409 if blocked |
| `POST /runs/{id}/sync` | — | `{"playbooks": n, "tasks": n}` |
| `GET /failproof?as_of=YYYY-MM-DD` | — | Tripwire + gate tracker for every property; `halt: true` when 3+ are tripped |

The API does not ask for cost confirmation. It relies on `VANGUARD_MAX_COST_USD`.

## 6. How-to

### 6.1 Add or update a property
1. Edit `config/properties.yaml`. Give the property a unique `id` and `task_prefix`, and list its
   `sources`.
2. Run `pytest -q`. `test_e2e_01` checks the registry.
3. Add a row to DESIGN §4 and a change-log line.
4. If the property needs its own track in Notion, nothing else changes: `track` flows through
   the playbook.

### 6.2 Refresh positioning from the repos
Read each product's PRD, positioning and design docs, and update `positioning`, `not_this`,
`capability_facts`, `pricing_facts` and `sources`. Set `positioning_status: confirmed` only when
the text comes from the product's own docs. Record the refresh in the DESIGN §4 table.

### 6.3 Add a lint rule
- Add it to a profile in `config/lint_gate.yaml`, or add it to one property's `banned_terms`.
- Add a parametrised case to `test_lint_blocks` / `test_lint_allows` in `tests/test_vanguard.py`,
  covering both a hit and a near-miss that should pass.

### 6.4 Change an engine's output
1. Edit the model in `schema.py`. Tool schemas update automatically.
2. Update `mock_fixtures.py` so dry runs still validate.
3. If the field is outward-facing copy, add it to `lint_gate.copy_fields`.
4. If it should show in Notion, update `notion_sync.playbook_blocks` or the database schema.
   Existing databases need the new property added by hand, or a fresh `notion-setup`.
5. Update DESIGN §6.

### 6.5 Add an integration (for example Smartlead API or Linear)
- Put it in its own module next to `notion_sync.py`, with an httpx client that accepts a
  `transport` argument so tests can inject a fake.
- Read only from `Store` and respect the approval gate: anything that sends must require
  `approved_by`.
- Add a CLI subcommand, an env var (documented in §3.1), a fake in `tests/`, and E2E cases in
  TEST_CASES.md.

### 6.6 Run on a local model
1. Install Ollama and pull a model (setup guide Part 3).
2. Run `vanguard doctor` and look for `OK local model: qwen3.6:27b ready`.
3. Run `vanguard run --properties oratoplus` to try one property. With fallback off it costs $0.
4. If `status` shows many `local_failures`:
   - try a larger model, or `VANGUARD_LOCAL_THINK=1`;
   - or enable the capped fallback (`VANGUARD_MAX_COST_USD=2` plus a key) so only failed calls
     go to Claude.
5. For other servers: LM Studio needs `VANGUARD_LOCAL_API=openai` and
   `VANGUARD_LOCAL_URL=http://localhost:1234/v1`. llama.cpp is the same with its port.

### 6.7 Add a page or field to the UI
1. API: add the route to `vanguard/web/app.py` with a Pydantic input model. Use
   `Depends(admin_user)` for admin-only routes, or `current_user` plus `can_modify` for
   creator-or-admin rules. Add any new column to `WEB_DDL`, with an `ALTER TABLE` migration in
   `WebStore.__init__` if the table already exists.
2. Client: add the call and types to `ui/src/lib/api.ts`.
3. Page: add it under `ui/src/pages/`, register the route in `main.tsx` (wrap admin pages in
   `<Guard admin>`) and add it to the nav in `components/Layout.tsx`. Build forms from
   `Field`/`Input`/`Select` in `components/ui.tsx`, which gives labelled, accessible controls.
4. Tests: add a `WEB-NN` API test (including the 403 case) and a `UI-NN` Playwright test, list
   them in TEST_CASES.md, then run `npm run build`.

### 6.8 Add or tune partner categories
1. Edit `config/partner_playbooks.yaml`. Keep `angle` and `offer` claim-safe: no customers,
   numbers without sources, guarantees or relationship claims.
2. Check it with `vanguard partners recommend <property>`. Every draft must show lint `pass`.
3. `test_web_16` checks Jodibana's categories. Add assertions for any property you change.
4. To change how priority is weighted, edit `scoring.weights`. Scores update on the next
   recommendation run.

### 6.9 Turn on real sending (SMTP)
See setup guide Part 7. In short:
- set `VANGUARD_EMAIL_MODE=smtp`, the sender name, email and postal address, and SMTP
  credentials;
- run `vanguard outreach status` and check it reports no problems;
- approve one message to yourself first.

### 6.9a Send through Postmark streams
See setup guide Part 8. In short:
1. Verify your sending domain, or add a sender signature.
2. Create a transactional stream `partners`.
3. Set `VANGUARD_EMAIL_MODE=postmark`, `POSTMARK_SERVER_TOKEN` and
   `VANGUARD_POSTMARK_STREAM_OUTREACH=partners`.
4. Add the webhook `https://user:pass@<host>/hooks/postmark` to the stream(s), with
   Delivery, Bounce, Spam Complaint and Subscription Change ticked.
5. Run `vanguard outreach postmark-check`.

Keep SMTP set too if you want cold first touches to go from your own mailbox. Code lives in
`vanguard/postmark.py`. Tests use `FakePostmark` via the `vanguard.postmark.TRANSPORT` hook
(an `httpx.MockTransport`), so they never call the real API.

### 6.10 Manage users
- **First run:** `vanguard seed-users`.
- **After that:** Admin → Users in the UI, or `vanguard create-user`.
- **Forgotten admin password:** create a new admin with `vanguard create-user --role admin`, then
  reset the old account in the UI.

### 6.11 Change the model or prices
- Model: set `VANGUARD_MODEL`.
- Prices: when list prices change, update `cost.PRICES` and DESIGN §9, and note the date.

## 7. Testing

```bash
pytest -q                                  # everything offline, $0 (SQLite)
VANGUARD_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest -q   # same suite on PostgreSQL
pytest tests/test_e2e.py -q                # end-to-end only
VANGUARD_LIVE_LOCAL=1 pytest -k live_03 -s  # one property on YOUR local model, $0
VANGUARD_LIVE=1 pytest -k live_01 -s       # real Claude smoke test: one property on Haiku, capped at $0.50
VANGUARD_LIVE=1 NOTION_TEST_PARENT_PAGE=<id> pytest -k live_02   # real Notion round trip, $0

# browser end-to-end tests (Playwright). Uses an isolated temp database, never your data.
cd ui && npm run build && npx playwright install chromium && npm run test:e2e
# Windows: run from Git Bash or WSL (the test server is a bash script); set VANGUARD_PYTHON=python if needed
```

- Browser tests: `ui/e2e/app.spec.ts`, 11 flows across both roles. `e2e/start-server.sh`
  creates a fresh temp database, three known users and a dry run, then starts the app on :8765.
  An HTML report goes to `ui/e2e-report/`.
- The fakes are `MockLLM` (placeholder data), `FakeAnthropic` (drives the real `ClaudeLLM` code
  path) and `FakeNotion` (a stateful fake that enforces Notion's request rules).
- Test IDs and what each proves are in [TEST_CASES.md](TEST_CASES.md). New tests start their
  docstring with the ID.

## 8. Operations

- **Logs.** Standard logging at INFO, one line per engine step per property.
- **Artifacts.** `output/<run_id>/*.json` and `output/<run_id>/exports/`.
- **Backups.** Copy `data/`, which holds `vanguard.db` and `notion.json`.
- **Upgrades.** The schema migrates itself (v0.1 → v0.2 adds `runs.usage`).

### 8.1 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `doctor` reports that Notion returned 401 | Wrong or revoked token. Copy the token again from the connection's Configuration tab. |
| Notion 404 "Could not find database" | The parent page isn't shared with the connection. Use ••• → Connections → add it. |
| Tasks from two properties merged in Notion | Duplicate `task_prefix`. The loader now refuses this, so fix the registry. |
| Outreach says "needs contact email" | Add the email on the partner (Edit), or add a named target under the segment |
| "segment template" refused on approve | Segments are research lists. Add a named organisation under it, then approve that one's messages. |
| SMTP auth fails | Gmail and Google Workspace need an app password (2-step verification on). Hostinger mail uses the mailbox password on `smtp.hostinger.com:465`. |
| Replies not picked up | Set the `IMAP_*` variables and run `vanguard outreach sync-replies`. Replies from another address match only if they quote our email; otherwise record them by hand. |
| Web sign-in returns 429 | Eight failed attempts for that email from this client. Wait 15 minutes, or restart the server. |
| Signed out after a redeploy | `VANGUARD_JWT_SECRET` changed or `data/` was reset. Set the secret explicitly in `.env`. |
| UI shows "API only" / 404 at `/` | `ui/dist` is missing. Run `cd ui && npm install && npm run build`, or set `VANGUARD_UI_DIST`. |
| "local model server not reachable" | Start Ollama (`ollama serve`, or the Ollama app), or fix `VANGUARD_LOCAL_URL` |
| "model … isn't installed" | Run `ollama pull <tag>` exactly as the message says |
| Local calls very slow or timing out | The model is too big for your GPU and is running on CPU. Use a smaller tag or raise `VANGUARD_LOCAL_TIMEOUT`. |
| "Paid API runs are OFF" | This is the intended $0 default. Use `--dry-run` or `prompt`/`import`, or set `VANGUARD_MAX_COST_USD=5` (for example). |
| `BudgetExceeded` | The cap was reached mid-run. Raise `VANGUARD_MAX_COST_USD`, or re-run only the failed properties with `--properties`. |
| Import says `design_partner` or `co_sell` missing | The chat reply left out a required partnership kind. Ask the chat to add one and import again. |
| `ECONOMICS_GAP` note | Engine 1's ACV × units falls short of $2M. Review the pricing facts or accept the gap. |
| Everything `blocked` | Read the lint findings in `vanguard show`. Tighten the registry wording or adjust rules that are misfiring. |
| `output never validated` | The model returned invalid JSON three times. Re-run that property, or switch to a stronger model. |
