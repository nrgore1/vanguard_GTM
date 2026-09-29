# Changelog

## 0.7.2 — 2026-09-28

- **Interim owners:** WeddingOS, Jodibana, JodiUSA, OratoPlus and Atmakosh are marked
  `interim_owner: true` — founder-supervised through AI agents from Naren@atmakosh.com until a
  CEO is named. Their plans carry an `INTERIM_OWNER` note.
- **CEO gate:** each of the five has a `G-CEO` gate due week 16 (Jan 15, 2027). Paid
  acquisition stays blocked until it passes.
- The tracker and the Tripwires page show interim status.

## 0.7.1 — 2026-09-28

- **Owners assigned:** WeddingOS, Jodibana, JodiUSA, OratoPlus and Atmakosh are owned by
  Naren@atmakosh.com (`config/failproof.yaml`), so their plans no longer carry FOCUS_LOCK notes.
- Tests still check the focus lock, using a copy of the config with an owner removed.

## 0.7.0 — 2026-09-28

### Added: fail-proof layer (premortem, gates, tripwires, focus lock)
- **Engine 0, forensic premortem:** `vanguard premortem <property> [--plan FILE]` writes the
  autopsy of a failed plan: 7 ranked causes, verdict, adversary and tripwires. `--dry-run` is $0.
- **Engine 5, readiness gates:** each property has gates with a verification test and a
  walk-away condition. Open gates remove the task classes they block (investor outreach, cold
  investor outreach, paid acquisition, public launch) from every plan, with a `GATE_BLOCKED` note.
- **Engine 6, tripwire monitor:** one measurable signal per failure mode, checked on Fridays.
  Missing evidence is amber. Three tripped on a property raises HALT (`vanguard tripwires` exits 2).
- **Focus lock:** delegated properties must name an owner; otherwise every playbook carries a
  `FOCUS_LOCK` note.
- **`config/failproof.yaml`:** all 8 properties. LiqMint Institutional carries the full
  seven-cause premortem of the $3M raise.
- **Where:** CLI `tripwires`, `record`, `gate`, `premortem`; web API `/api/failproof…`; machine
  API `GET /failproof`; UI **Tripwires** page.
- **Tests:** E2E-29–31, WEB-28, `tests/test_failproof.py`.

## 0.6.0 — 2026-09-28

### Added: researched partners (real organisations)
- **`config/partner_targets.yaml`:** 117 real organisations across all 8 properties, each with a
  source link, why it fits, location, contact page or partner program, generic inbox where one
  is published, priority hint and confidence.
  - Design partners, for example: U.S. Bank, BNY, UnitedHealth/Optum, Ameriprise, ABN AMRO,
    Zurich, MN Cup, gener8tor, India Association of Minnesota, TANA, The Simply Elegant Group.
  - Co-sell and channel partners, for example: Fireblocks, Anchorage, Kyriba, Credo AI,
    LangChain, CrewAI, Toastmasters, Koinly, CoinLedger, Maharani Weddings.
  - An independent re-check confirmed the recent claims. One slip was corrected: it is
    Securitize Capital, the subsidiary, that is SEC-registered.
- **Import:** `vanguard partners import`, `POST /api/partners/import-research` and a "Load
  researched partners" button (admin).
  - Each organisation becomes a named partner under its category, with its own 3 draft emails.
  - Playbook examples (Fireblocks, KPMG and so on) are enriched rather than duplicated.
  - Re-runs are idempotent and keep hand-entered emails.
  - Scores are clamped into the priority band.
- **UI:** "researched" badges; clickable website, source and contact links on the partner page.
- **Tests:** WEB-26, WEB-27, UI-15.

## 0.5.1 — 2026-09-28

### Fixed
- **Windows:** `vanguard demo-data`, `run` and `serve` crashed with `UnicodeDecodeError: 'charmap'
  codec…` because text files were read in Windows' default cp1252 encoding. Every file read and
  write now uses UTF-8 explicitly, and CLI output is forced to UTF-8 so names with special
  characters print on any console.

### Added
- `start.ps1`: a one-command start on Windows (finds Python, sets up `.venv`, seeds users,
  serves).
- **E2E-28:** runs demo-data, partner recommendations, a dry run and outreach status under a
  non-UTF-8 locale, and fails if any source file reads or writes text without
  `encoding="utf-8"`.

## 0.5.0 — 2026-09-27

### Postmark message streams
- **New `postmark` email mode** (`vanguard/postmark.py`), sending through a transactional
  outreach stream (`VANGUARD_POSTMARK_STREAM_OUTREACH`, `partners` recommended). Each email
  carries:
  - `Tag` (the property) and `Metadata` (outreach id, partner id, property, step);
  - `Reply-To` `local+o<id>@inbound` for exact reply matching;
  - `List-Unsubscribe`, pointed at the same inbound address;
  - threading headers;
  - open and link tracking off by default.
- **Permission policy:** new partner field `email_consent` (none, opted_in,
  existing_relationship, replied, opted_out).
  - Cold first touches never go through Postmark by default. They use your SMTP mailbox if
    set, or are held.
  - Replies set `replied` automatically.
  - `VANGUARD_POSTMARK_ALLOW_COLD=1` overrides the policy.
  - Setting `opted_out` suppresses the address and cancels queued messages.
- **Monthly cap:** `VANGUARD_POSTMARK_MONTHLY_CAP`, default 100 (the free plan), counts
  outreach and alerts.
- **Webhook `POST /hooks/postmark`** (Basic Auth; 503 until configured):
  - Delivery, Open;
  - Bounce: hard bounces are suppressed;
  - SpamComplaint: opted out, suppressed, sequence stopped;
  - SubscriptionChange;
  - Inbound replies, matched by `MailboxHash`, then headers, then sender, and deduplicated.
- **Team notifications on a notify stream:**
  - reply alerts to admins and the partner owner (`VANGUARD_NOTIFY_REPLIES`);
  - the approval digest.

  Both fall back to SMTP or the outbox and are logged in `notification_log`.
- **Suppression and stream tools:** two-way suppression sync with the outreach stream; a
  stream check (missing or non-transactional streams).
- **API:** `POST /api/outreach/digest`, `POST /api/outreach/postmark-sync`,
  `GET /api/email/postmark`. `/outreach/stats` reports Postmark usage. Partner `PATCH` accepts
  `email_consent`. `/agent/status` includes the email configuration.
- **CLI:** `vanguard outreach digest | postmark-sync | postmark-check`. `outreach status` and
  `doctor` report Postmark.
- **UI:**
  - Outreach page: a Postmark streams banner (streams, usage against the cap, cold-routing
    policy, suppression sync), transport and delivered/opened indicators, and an "Email
    approval digest" button. "Check replies" is shown only when IMAP is configured.
  - Partner page: an email permission select.
  - Admin: an email configuration row.
- **Data:** `outreach_messages` gains transport, pm_message_id, delivered_at and opened_at;
  `partners` gains email_consent; new table `notification_log`.
- **Tests:** WEB-23..25, with a fake Postmark via `httpx.MockTransport`, and UI-14. The
  docs-sync check now also catches env vars read through `g = os.getenv`, across `vanguard/**`.
- **Docs:**
  - Setup guide Part 1 now uses a flat layout: the program lives directly in `Vanguard_GTM\`,
    and the zip is a backup that shouldn't be extracted there, which avoids a nested folder.
    The manual's set-up block and the test count are corrected.
  - New `start.ps1`, a one-command Windows start. It finds Python 3.11+ (including Anaconda),
    creates `.venv`, installs, creates `.env`, seeds users on the first run, then serves and
    opens the browser.
  - DESIGN §16, with the change log moved to §17;
  - manual env vars, CLI, API and §6.9a;
  - setup guide Part 8, the Postmark step-by-step;
  - user guide;
  - test catalogue and the Postmark acceptance checklist.

## 0.4.0 — 2026-09-27
- **Partnerships expert:** `config/partner_playbooks.yaml` covers all 8 properties with partner
  categories, deal structures, where to find contacts, scoring factors and message angles.
- **Engine 2B:** recommends, scores and ranks (P0–P2) design partners, B2B co-selling partners
  and channels, and drafts a 3-step email sequence for each.
  - Offline ($0) or model-driven.
  - Runs inside every agent run.
- **Segments → named targets:** the team adds specific businesses under a recommended segment,
  and each inherits the segment's priority and drafts.
- **Admin-approved sending:**
  - Outbox mode by default (nothing leaves the machine); SMTP optional, through your own mailbox.
  - Compliance footer and List-Unsubscribe header; suppression list; daily cap.
  - Messages go out in priority order, with step delays, threaded follow-ups and failure
    isolation.
- **Reply tracking:** read-only IMAP matching (thread headers → sender), bounce detection, opt-out
  handling, and a manual "Record reply". A reply stops the sequence and moves the partner to
  in conversation.
- **Agreements:** proposed → negotiating → signed or declined, with the signed date and terms.
  The dashboard shows agreements and partner email reply rates.
- **UI:** a new Outreach page (queue, bulk approve, send, check replies); a partner priority list
  and "Recommend partners"; cards on the partner page for why this partner, named targets, the
  outreach sequence, reply recording and the agreement.
- **CLI:** `partners recommend`, `outreach status|approve|send|sync-replies`, and an optional
  scheduler in `serve`.
- **Tests:** WEB-16…22 and UI-12…13.

## 0.3.0 — 2026-09-27
- **Web app:** a React UI served by `vanguard serve`, with admin and general-user roles.
  - Campaigns: create, edit and delete; log results; goal progress.
  - Partners: a pipeline board with drag-and-drop, and an interaction timeline.
  - Tasks: filters and paging. Admins assign, reprioritise, create and delete.
  - Dashboard: ARR run-rate against targets (admins edit the targets), funnel, partner pipeline
    and weekly charts.
  - Admin: agent status, runs, playbook review, approval, import to campaigns and partners,
    Notion sync, users, and the audit log.
- Sessions use HS256 tokens and PBKDF2 passwords. Sign-in is throttled. Every change is written
  to the audit log.
- **New CLI commands:** `seed-users`, `create-user`, `demo-data [--purge]`. `serve` now runs the
  web app, and the machine API moved to `/machine`.
- **Local LLM provider:**
  - Ollama or any OpenAI-compatible server; default model `qwen3.6:27b`.
  - Local model first, with Claude as a capped fallback (`VANGUARD_PROVIDER`).
  - `doctor` and `estimate` know about the local model.
- **Tests:** 15 web API tests (WEB-01…15), 11 Playwright browser tests (UI-01…11), and local
  and fallback end-to-end tests (E2E-22…27).
- **Fixes:**
  - Compact currency rounded $1.5M to "$2M".
  - Form labels are now linked to their controls by id (accessibility).
- The Docker build is multi-stage and now builds the UI.

## 0.2.0 — 2026-09-27
- **$0 by default:** paid Claude API runs are off until `VANGUARD_MAX_COST_USD` is set above 0.
  Added `estimate`, `doctor`, confirmation before paid runs, a hard cap per run, and metered
  spend stored on each run.
- **$0 manual path:** `vanguard prompt all --out DIR`, then Claude chats, then
  `vanguard import all DIR`.
- **Engine 2** must now include a design partner (a scoped co-build pilot) and a B2B co-selling
  partner (`Partnership.kind`).
- **Registry refreshed from vireoka-dev:**
  - LiqMint R0 retail, LiqMint Institutional, Vireoka, OratoPlus and Atmakosh are confirmed from
    their repo docs.
  - WeddingOS, Jodibana and JodiUSA are drafts.
  - WeddingOS URL is now weddingos.jodibana.com.
  - Added the `pricing_facts`, `banned_terms` and `sources` fields.
- **Bug fix:** each property now has its own `task_prefix`. liqmint and liqmint-institutional,
  and jodibana and jodiusa, previously produced the same task ids, which merged their tasks in
  Notion. Notion task lookup is now also scoped by Property.
- Lint gate supports banned terms for each property (Vireoka internal names; the fictional
  "Meridian Crest").
- Web research resumes on `pause_turn`.
- **Tests:** 21 end-to-end cases plus a stateful fake Notion. `tests/test_docs_sync.py` keeps
  the docs aligned with the code.
- **Docs:** Design Document, Programmer's Manual, Test Case Catalogue, Setup guide
  (Notion and keys).

## 0.1.0 — 2026-09-27
- First build: four-engine orchestrator, lint gate with repair loop, SQLite store, Notion sync,
  approval-gated exports, CLI, HTTP API, Docker and Traefik deploy.
