# Vanguard-GTM — Test Case Catalogue

Version 0.15.0 · updated 2026-10-02

Run with `pytest -q`. Everything below except the `L` cases runs offline and costs $0.
Each automated test's docstring starts with its ID. `tests/test_docs_sync.py` checks that
every E2E ID in this file exists in the code, and every one in the code exists here.

## End-to-end cases (`tests/test_e2e.py`)

| ID | Scenario | Steps | Expected result |
|---|---|---|---|
| E2E-01 | Registry reflects the repo refresh | Load `properties.yaml` | 8 properties. 5 confirmed, each with sources. Banned terms present. $19.99 retail price. 8 unique task prefixes. |
| E2E-02 | Full offline CLI cycle | `run --dry-run` → `show` → `export` (unapproved) → `approve` → `export` | All 8 complete. Track B flagged NEEDS_POSITIONING_REVIEW. Export is skipped until approval. The CSV has 5 steps in order. Task CSV has 240 rows. |
| E2E-03 | Subset and bad input | `run --properties oratoplus,jodibana`; then `--properties nope` | Only 2 run. An unknown id exits non-zero with "unknown property ids". |
| E2E-04 | Zero-cost tooling | `estimate` (local), `estimate --provider claude` (default model, then Haiku without research), `doctor` with no local server or keys | Local $0 with worst case $0. Claude estimate plausible and Haiku cheaper. `doctor` exits 1 with local FAIL and Notion missing, and a missing Anthropic key reported as fine. |
| E2E-05 | $0 default, then confirmation | Claude-only `run` with no cap; then with cap 5 answered "n"; a local `run` with no server; `doctor` | Claude with no cap: refused, "nothing was spent". With a cap: estimate and cap shown, then cancelled. Local with no server and fallback off: stops, "nothing was run or spent". `doctor` shows "$0 mode" and "Notion API: free". |
| E2E-06 | Blocked copy can't ship | Vireoka copy keeps "AtmaSphere" | `lint_status=blocked` with a property-banned-term finding. `approve` is refused. |
| E2E-07 | Real `ClaudeLLM` path across the portfolio | 8 properties, concurrency 8, fake Anthropic client | All complete. 8 research calls. Metered calls and 16 searches match. Cost is recorded on the run. |
| E2E-08 | Schema-violation retry | First Engine-1 answer is malformed | The error is sent back, the second answer validates, and the run completes |
| E2E-09 | Web research resumes | First research turn returns `pause_turn` | The turn is resumed and notes from both turns are kept |
| E2E-10 | Spend cap | Cap $0.05, each call $0.014 | No calls after the cap. Run is `failed` or `partial` with `BudgetExceeded`. Spend stays at most one call past the cap. |
| E2E-11 | Cost arithmetic | Meter with known usage; unknown model | $3.30 exactly. Zero cap raises. An unknown model is priced at or above Opus. |
| E2E-12 | Notion setup, sync, re-sync | `setup` → sync 8 properties → change a Status in Notion → re-sync | 2 databases. 8 playbook pages and 240 task pages. Re-sync creates nothing new. The Status changed by a human survives. Properties map correctly. Page bodies are written. |
| E2E-13 | Local cache lost | Sync, clear cached page ids, sync again | Pages are found by query and not duplicated (30 tasks, 1 playbook) |
| E2E-14 | Notion rate limit | First 3 requests return 429 | Retried, and the sync completes |
| E2E-15 | Bad Notion token | Every request returns 401 | A clear error containing Notion's message |
| E2E-16 | HTTP API cycle | health → auth check → bad property → start run → poll → playbook → approve → sync | 401 without token, 400 for an unknown id. The run completes. `needs_review` is surfaced. Approval is visible in Notion. |
| E2E-17 | $0 manual path | `prompt oratoplus --out` → chat reply with fenced JSON → `import` | The prompt includes the schemas and the ORA prefix. Import passes lint with 30 tasks. Status shows `$0.00` and `model=manual`. |
| E2E-18 | Manual path still linted | Import a LiqMint reply that claims yield and customers | `blocked` with liqmint-not-yield and no-customer-claims. `approve` is refused. |
| E2E-19 | Design partner and co-sell are required | Engine-2 plan without `design_partner`, then without `co_sell` | Each is rejected by the schema with the missing kind named |
| E2E-20 | $0 path for the whole portfolio | `prompt all --out DIR`; replies for 7 of 8, one of them missing its design partner; `import all DIR` | 8 prompts written, WeddingOS at its jodibana URL. 6 imported, jodiusa FAILED (design_partner), jodibana reported missing. Run is partial. |
| E2E-21 | Real client refuses at cap 0 | `ClaudeLLM()` with the cap unset | `BudgetExceeded` before any API call. The fake client records zero calls. |

| E2E-22 | Whole portfolio on a local model | 8 properties, concurrency 8, fake Ollama | Completes at $0. provider=local. 37 local calls (32 engine calls + 5 lint repairs). At most 1 generation in flight. JSON Schema passed as `format` with `num_ctx`. |
| E2E-23 | Local invalid output retried | First reply is `<think>` plus bad JSON | The error is sent back, and the second reply (with think block and code fence) parses |
| E2E-24 | Local down, fallback off | Server refuses connections, cap unset | Properties fail with "Claude fallback is OFF". Zero Claude calls. $0. |
| E2E-25 | Fallback to Claude | Local always invalid, cap $5 and key set | Completes. provider=local+claude. 5 fallbacks (4 engines + 1 repair). Metered under the cap. |
| E2E-26 | OpenAI-compatible servers | `api=openai` (LM Studio / llama.cpp / vLLM) | `/v1/models` check passes. The request carries `response_format.json_schema`. Design partner and co-sell are present. |
| E2E-27 | Model not pulled | Server up with a different model; server down | The message names the exact `ollama pull qwen3.6:27b`; the down case says "not reachable" |
| E2E-28 | Works on a non-UTF-8 (Windows cp1252-style) locale | `demo-data`, `partners recommend jodibana`, a dry run and `outreach status` all exit 0 with `LC_ALL=C`/`PYTHONUTF8=0`. A static check fails if any `read_text`/`write_text`/`open("w…")` in `vanguard/` lacks `encoding=`. |
| E2E-29 | Fail-proof CLI flow | `record`, `gate` and `tripwires` from the CLI | A reading shows GREEN; `gate pass` without `--by` is refused; `gate fail` prints the walk-away condition; three tripped tripwires make `tripwires` exit 2 with HALT; `--json` covers all 8 properties; an unknown tripwire is refused. |
| E2E-30 | Gates remove blocked tasks from a run | Dry run where one institutional task emails seed investors | That task is gone, dependants no longer point at it, a `GATE_BLOCKED` note names it, and a WeddingOS playbook run with its owner removed carries a `FOCUS_LOCK` note. |
| E2E-31 | Premortem at $0 | `premortem liqmint-institutional --dry-run --plan plan.md --out pm.md` | The markdown has 7 ranked causes, a verdict, an adversary and a tripwire table. |
| E2E-32 | Move SQLite data into the configured database | Old SQLite file with two users and a tripwire reading; `db copy-from-sqlite` into the configured database | Every table is copied; a second run skips tables that already hold rows; `db info` shows 2 users; the next new user gets id 3; the command without a file is refused. On PostgreSQL this is a real SQLite-to-PostgreSQL copy. |
| E2E-33 | Campaign by CLI and LinkedIn export | Import partners; `campaign attach` by name (an unknown name is refused); `linkedin import` a Connections.csv with LinkedIn's notes preamble, twice; `linkedin matches`; `campaign show` | Partners attached; 3 connections loaded then refreshed, not duplicated; "Eleni S." at "Lead" recognised as Lead Bank's named contact; Protiviti's empty email filled from the export; "Bank" matches nothing; `show` lists 2 partners with the email; a missing file exits non-zero. |
| E2E-34 | Investor targets from the CLI | `investors import` twice; `investors list --priority P0`; import a file without an investors list | Added, then 0 added on re-run, "No emails drafted"; the P0 list holds only P0 rows in descending score; the bad file exits non-zero. |
| E2E-35 | Introductions from the CLI | `linkedin import export.zip`, `intros suggest`, `intros draft`, `intros list --status draft`, `intros send` | Tie strength reported ("warm ties"); new paths found; asks drafted; Lead Bank listed as an insider path; nothing sent before approval. |

## Live smoke cases (opt-in)

| ID | Scenario | How to run | Cost |
|---|---|---|---|
| E2E-L1 | One property against the real Claude API | `VANGUARD_LIVE=1 pytest -k live_01 -s` (Haiku, no research, cap $0.50) | about $0.10–0.20 |
| E2E-L3 | One property on your real local model | Ollama running, then `VANGUARD_LIVE_LOCAL=1 pytest -k live_03 -s` | $0 |
| E2E-L2 | Real Notion round trip | `VANGUARD_LIVE=1 NOTION_TEST_PARENT_PAGE=<id> pytest -k live_02` | $0 |

## Web API cases (`tests/test_web.py`)

| ID | Scenario | Expected result |
|---|---|---|
| WEB-01 | Sign-in and tokens | Wrong password 401. Email is case-insensitive. Tampered or expired tokens 401. A disabled user is rejected on both login and existing token. Passwords are stored as PBKDF2 hashes. |
| WEB-02 | Everything needs a sign-in | 11 representative `/api` routes answer 401 without a token |
| WEB-03 | General user vs admin functions | 403 on user admin, targets, task create, runs, audit, agent status, partner delete. Users list shows names only. |
| WEB-04 | Campaign CRUD and ownership | A user creates it; another user edits it but can't delete; creator and admin can delete. 422 for unknown property, negative budget, bad status, end before start, too-short name. 404 for a missing id. |
| WEB-05 | Results → dashboard | Campaign totals across entries. Property funnel. Run-rate uses only the last 30 days × 12. Weekly series sums. Only the creator deletes an entry. Admin changes the target and the dashboard reflects it. |
| WEB-06 | Partner pipeline | 422 for a bad email, 409 for a duplicate. An interaction with `stage` moves the partner and sets the next step. Stage patch. Kind filter and interaction counts. 422 for an unknown interaction type. Only the creator deletes an interaction; admin deletes the partner. |
| WEB-07 | Task permissions | User 403 on unassigned tasks and on priority changes. Admin assigns, sets P0 and a due date. The assignee updates status and notes. It appears in "mine" and on the dashboard. Admin creates `ORA-M001`. Only admin deletes. |
| WEB-08 | Run → approve → import | Dry run from the API completes. Approve works; approving a blocked playbook is 409. Import creates 2 draft campaigns (5-step email content) and 3 partners including the design partner and co-sell, skips the blocked playbook, and is idempotent. Sync without a Notion token is 409. |
| WEB-09 | $0 default from the UI | A real local run with no local model and fallback off is 409 "nothing was started". Claude-only at cap 0 is 409. No run is created. Agent status reports it. |
| WEB-10 | User administration | Short password 422, duplicate email 409 (case-insensitive). Role change takes effect at sign-in. Password reset. An admin can't demote, disable or delete themselves. Delete works. |
| WEB-11 | Audit log | Create, update, delete and login entries appear with the acting user's name |
| WEB-12 | Demo data | Everything is `[DEMO]` or `demo-`. `--purge` removes all demo records, results and runs and leaves real campaigns untouched. |
| WEB-13 | Serving | SPA routes serve `index.html`, assets are served, unknown `/api` paths stay JSON 404, and `/health` and `/machine/health` answer |
| WEB-14 | CLI user commands | `seed-users` prints working random passwords once and refuses a second time. `create-user` adds an admin and refuses duplicates. |
| WEB-15 | Login throttling | 8 failures for one email and client lead to 429, even with the right password. Other accounts are unaffected. |
| WEB-16 | Partnerships expert for Jodibana | Recommends wedding planners, photographers, destination resorts, banquet venues, temples/community organisations and bridal/jewellery; covers design partner, co-sell and referral. Scores descending with a P0 on top. No blocked drafts. 6 partners and 18 drafts. Idempotent. Users get 403. Detail has how-to-find, factors and 3 steps with merge tags. |
| WEB-17 | Approval gates every send | A segment can't be approved. A named target inherits 3 drafts. Users get 403 on approve/send. Sending before approval sends nothing. After approval only step 1 goes (step 2 "due …"). The `.eml` has the right To and Subject, "Hi Meera", the postal address, unsubscribe text and List-Unsubscribe, with no raw merge tags. Stage becomes contacted and the send is logged. Step 2 goes after its delay, threaded (In-Reply-To). |
| WEB-18 | Edit → re-approval; lint blocks | Editing an approved message returns it to draft. Copy with a guaranteed match is blocked (`no-guaranteed-match`) and approval is refused. |
| WEB-19 | Reply tracking (IMAP) | A threaded positive reply is matched, the quoted text stripped, the other steps cancelled, stage → in_conversation. A duplicate is ignored. An opt-out matched by address is suppressed. A bounce matched by Message-ID is suppressed. A stranger is unmatched. Stats: 3 contacted, 2 replied, 2 suppressed. Sync without IMAP is 409. |
| WEB-20 | Manual reply + agreement → dashboard | A phone reply is recorded by a user (positive, 3 steps stopped, in_conversation). Negotiating → signed moves the stage to signed and sets the date. The dashboard counts 1 signed. An invalid status is 422. |
| WEB-21 | SMTP safety | SMTP without sender and postal details returns 409 naming the missing variable. A daily cap of 0 blocks sending. A mailer exception marks the message failed and doesn't crash. |
| WEB-22 | CLI partners recommend | `partners recommend jodibana` prints the ranked plan (P0 first, planners) and stores 6 segments with 18 drafts. `outreach status` shows outbox mode and 0 in the sending queue. |
| WEB-23 | Postmark streams: consent routing and payload | Postmark mode with no SMTP holds cold first touches ("permission-based") and calls Postmark 0 times. Marking a partner opted in sends step 1 on the `partners` stream: MessageID stored, transport postmark, From, To, Tag = property, Metadata outreach/partner ids, Reply-To `reply+o<id>@inbound…`, TrackOpens false, TrackLinks None, postal footer, List-Unsubscribe to the inbound hash, server token header. A cold partner goes through the SMTP cold mailer instead. A monthly cap of 1 holds step 2. `ALLOW_COLD` sends a cold partner via Postmark. Stats show mode, live, stream and usage. |
| WEB-24 | Postmark webhooks | No or wrong Basic Auth → 401. Delivery and Open set the timestamps. An Inbound reply with MailboxHash `o<id>` → positive, in_conversation, consent replied, steps 2–3 cancelled, a duplicate ignored, and an alert on the notify stream to the admin and partner owner (logged). A SpamComplaint → opted_out, remaining cancelled, suppressed. A soft bounce leaves it sent; a hard bounce → bounced and suppressed. SubscriptionChange adds or removes a suppression. Unknown types are ignored. Unset credentials → 503. |
| WEB-25 | Postmark admin: streams, suppression sync, digest | Users get 403. The stream check is OK, and flags a Broadcasts notify stream. A manual opted_out consent cancels all steps. Sync pulls 1 remote suppression (`postmark:HardBounce`) and pushes 1 local one. The digest emails the admin on the notify stream (3 awaiting, top partner listed, Metadata kind) and counts toward monthly usage. Without a token: stream check 409, and the digest falls back to the outbox. |
| WEB-26 | Import researched partners | Users get 403. The admin import has no errors and creates or updates every organisation in the YAML (`source=research`). Fireblocks and KPMG enrich the playbook examples with no duplicates. India Association of Minnesota sits under the community_orgs segment as a P0 design partner with website, contact URL and 3 draft emails (merge tags kept). No message leaves draft. A re-run creates nothing and keeps a hand-entered email. |
| WEB-27 | Targets file quality | Every item has a known property and category, https evidence, contact and website links, a valid inbox format, a why, a priority hint and a confidence. No duplicate names; at least 10 per property. `vanguard partners import` runs at $0 with no problems. |
| WEB-28 | Tripwires and gates in the web API | Users see the tracker for all 8 properties (week 3 on Oct 16) and record readings; unknown tripwires get 422; users get 403 on gates; admins fail G1 and get its walk-away condition; unknown gates 404; no premortem yet 404. |
| WEB-29 | Contacts, new categories and merge tags | Import the researched file, then re-import after removing a category's partners | Lead Bank gets contact_name Eleni Steinman, a Route and Person line, a timely hook and P0 in stablecoin_banks; drafts keep `{{company}}` and none contain a bare `{company}`; BNY is P1; a hand-entered name survives re-import; the removed category's segment and partners come back; `render` fills both `{{company}}` and `{company}`. WEB-27 also checks every named contact has an https source and no email. |
| WEB-30 | Campaign linked to outreach | Attach Lead Bank (and a partner of another property), a segment to a second campaign, then move Protiviti; log LinkedIn and X touches, approve and send Protiviti's step 1, record a reply and a meeting, hand-log 10 sent / 1 reply; read the campaign and the list; filter Outreach; detach; delete | Other property refused; segment brings its named organisations; the move reports where from; totals 2 partners, 1 email, 2 LinkedIn/X touches, 2 touched, 1 replied, 1 meeting, 1 in conversation, 1 missing email; list shows 11 sent, 2 replies, 1 meeting; Outreach filter returns only that campaign; a second detach is 404; deleting the campaign leaves the partner with no campaign. |
| WEB-31 | LinkedIn connections import | A file that isn't the export; the export as a user, twice; partner page and list; a campaign with Lead Bank; summary; delete as admin, then as the user | 400 for the wrong file; 3 added; Lead Bank's named contact gets one "Connected on LinkedIn" entry dated 2026-10-02 (not repeated, not counted as a touch); partner page lists Eleni as named contact via Uma User; Known counts 1 for Lead Bank and U.S. Bank, 0 for BNY; admin deletes 0 rows, the user deletes 3. |
| WEB-32 | Investor contacts | Create "Robert Fabbio" as kind investor under Vireoka, log a note that moves the stage, filter by kind, try an unknown kind | Created with no drafted emails; stage contacted; the investor filter returns only him; an unknown kind is 422. |
| WEB-33 | Investor targets | Check the YAML; Load researched partners as admin; set the top investor to contacted with an email; load again | Ranks 1..N, priorities match scores, five factors each, https sources, no published email; every investor created as kind investor under Vireoka with "Rank #1 of", key considerations and sources; no outreach drafts; the re-load refreshes all and keeps the stage and email. |
| WEB-34 | Introductions | A bad zip; a synthetic export with messages and an endorsement; Find paths; draft; approve as user then admin; send; mark sent on LinkedIn; record introduced | 400 for the bad zip; message counts 6 and 13, one endorsement, strength ordered, no message text stored; Sam (at Lead) is an insider path for Lead Bank, Eleni (the target) is not proposed, only Andrea (TA Ventures) bridges to investors and for at most 4 of them; the draft names Eleni, is double opt-in and has a note to forward; user approval is 403; the email goes only to the connector who shared an address, the other is held for LinkedIn; marking an emailed ask as sent on LinkedIn is 409; the outcome and the ask are on the partner timeline. |
| WEB-35 | One-off email to an investor | Write an email to an investor partner with a bad address, an unknown partner, then a good address; a second with an unsourced market figure; approve as user then admin; send only that id; record a reply; write and send a follow-up | 422 and 404; the draft is step 101, `one_off`, lint pass (the raise sentence needs no source) and the address is saved lower-cased; the market figure is blocked and can't be approved; user approval is 403; only Andrew's email is sent while another approved message stays queued; he moves to contacted with an email on the timeline; the follow-up after his reply still sends. |
| WEB-36 | A mailbox per property | Default mailbox atmakosh, a `vireoka` mailbox for vireoka, liqmint and liqmint-institutional with a daily cap of 1; one-off emails to a Vireoka, a LiqMint and a Jodibana partner; send; read stats; sync replies; then a missing password in smtp mode and a property in two mailboxes | The mailbox inherits host, name and address and uses its own user and password; Vireoka's email goes from vireoka and Jodibana's from atmakosh (From headers and `from_email`), LiqMint's is held by the vireoka cap; stats list both mailboxes and the LiqMint sender with no password in the response; reply sync reads both inboxes; both config errors are reported and sending returns 409. |
| WEB-37 | A copy in the Sent folder | smtp mode with fake SMTP and IMAP servers and a vireoka mailbox; send a one-off; make the IMAP append fail and send another; set `VANGUARD_SAVE_SENT=0` and send a third | The first is appended, marked read, to `INBOX.Sent` (found by its `\\Sent` flag) under the vireoka login and the report says so; the second is still sent and the report says the copy wasn't saved and why; the third makes no copy. |
| WEB-38 | Replies and unsubscribes | Send a one-off; replies that quote our footer in Gmail (`>`), Outlook (From:/Sent:) and HTML (gmail_quote) form; then an Unsubscribe-button email (subject "unsubscribe", no threading headers); then another send; then a plain reply "Please unsubscribe me" | The sent email has a List-Unsubscribe mailto and the footer; all three quoted replies are positive and nothing is suppressed; the button email opts the address out, marks the partner opted out with next step "Opted out - do not contact", and the next approved email is cancelled; the plain unsubscribe reply also suppresses the address. |
| WEB-39 | Scheduled sending | Write an email with a bad time, a time without a zone, then 9:00 -04:00 in 2099; approve; send; reschedule as user; send at a simulated later time; schedule five drafts from Fri 9:00 Eastern, 2 a day, 10 min apart, weekdays only; a Saturday start; clear; reschedule a sent one | 422, 422; stored as 13:00 UTC; held with "scheduled for …"; user refused for an approved email; sent once its time passes; Fri 9:00, 9:10, Mon 9:00, 9:10, Tue 9:00 (UTC); still drafts; Saturday moves to Monday; cleared; a sent email is refused; stats report automatic sending off. |
| WEB-40 | LinkedIn and X sequences | A named partner with a 3-step sequence: switch to LinkedIn with no profile; bad profile link and handle; good ones; approve, then switch; approve again; send due; by-hand list; mark step 1 sent; age it; reply; a one-off on X; mark an email sent by hand; a LinkedIn one-off with no profile | 422 (no profile), 422, 422; profile and handle normalised; all three steps move to LinkedIn as drafts, step 1 warned over 200 characters; mark-sent before approval is 409; no email is sent and the email cap is untouched; step 1 due with the profile link, step 2 waiting for step 1; after marking, a LinkedIn touch is logged and the partner is contacted; step 2 due after its delay; the reply cancels steps 2-3; the X one-off links x.com/handle and logs "Sent message on X"; the email is refused ("Send due now"); the LinkedIn one-off is 422. |

## Browser end-to-end cases (`ui/e2e/app.spec.ts`, Playwright)

Run with `cd ui && npm run build && npm run test:e2e`. The tests use an isolated server with a
temp database, users `admin@`, `uma@` and `otto@vireoka.com`, and a dry run for OratoPlus and
Atmakosh.

| ID | Flow | Expected result |
|---|---|---|
| UI-01 | Sign-in guard | Protected route → /login. A wrong password shows "wrong email or password". |
| UI-02 | General user's dashboard | 8 property cards. No Admin nav. /admin redirects home. No target-edit buttons. |
| UI-03 | Campaign create + results | The form creates an active OratoPlus campaign. Logged results show a 7.5% reply rate and 4/20 meetings (20.0%). A status change to paused shows in the filtered list. |
| UI-04 | Ownership in the UI | Another user sees Edit but no Delete on Uma's campaign |
| UI-05 | Partner workflow | Add a design partner, log a positive call that moves it to In conversation, move it to Pilot on the board, and it persists after reload |
| UI-06 | Task assignment | Admin assigns ORA-001 to Uma as P0. Otto can't change it. Uma sees it on her dashboard and marks it Done, which persists. |
| UI-07 | Manual task | Admin creates ORA-M001, finds it, deletes it through the confirm dialog |
| UI-08 | Dashboard admin | Admin sets OratoPlus's target to $1.5M and the card shows "$1.5M ARR target" |
| UI-09 | Agent from the UI | Status shows the local model not ready and Claude off ($0). A dry run for Vireoka is started and its playbook viewed (with design partner). Approve, then import 2 campaigns and 3 partners, which appear in Campaigns. |
| UI-10 | User admin | Admin adds a user and disables them; the disabled user can't sign in; the audit log lists user changes |
| UI-12 | Partner outreach, end to end (admin) | Recommend Jodibana partners (planners, resorts, photographers listed). The priority list starts with P0. Open the planner segment (why and how-to-find shown) and add "Mandap & Co Planners" with an email. Its sequence is personalised. Approve 3. The outreach queue is in outbox mode; Send due now → 1 sent to the right address, step 2 "due". Record a phone reply → positive, 2 stopped, In conversation. Mark agreement signed → stage Signed, and the dashboard's Jodibana card shows 1 signed. |
| UI-13 | General user limits | No Send/Check replies/Recommend buttons. Can add a named target and edit a draft, which saves as "needs admin approval". No approve buttons. |
| UI-14 | Email permission + digest | Uma opens Shaadi Squad Events: permission "none" with the cold-routing note. She sets "Opted out", sees the toast, and all 3 messages show cancelled. The admin clicks "Email approval digest" and gets "Digest emailed to 1 admin (outbox)". |
| UI-15 | Load researched partners | The admin clicks "Load researched partners" and gets a toast. India Association of Minnesota opens with the "researched organisation" badge, a clickable iamn.org website and contact link, and 3 drafts titled "… + Jodibana: a small pilot idea". |
| UI-16 | LinkedIn campaign in the browser | A user imports a Connections.csv on Partners, creates a LiqMint Institutional campaign and adds Lead Bank. The import reports Lead Bank's named contact; the campaign funnel shows 1 partner; Lead Bank shows "People you know here" with the named contact, a link to the campaign and a "Connected on LinkedIn" timeline entry. |
| UI-17 | Introductions in the browser | Import a LinkedIn .zip on Partners; Introductions, Find paths; open the Lead Bank path; draft; admin approves; send approved emails | The import reports warm ties; an insider path to Lead Bank appears with a 2nd-degree search link; the drafted ask shows the note to forward; after approval the send report shows the email to the connector. |
| UI-11 | Theme + sign-out | The toggle switches to the light theme; sign-out returns to /login |
| UI-18 | One-off email in the browser | Open the investor Andrew Brackin; Write email; fill To, Subject, Message; Approve & save to outbox | The dialog warns that email isn't connected; the report says it was saved to the outbox; the partner shows a one-off email to the new address. |
| UI-19 | Scheduling in the browser | Write email to Andrew Brackin on a date and time; Approve & schedule; open Outreach, Queued; select it; Schedule from a Saturday | The dialog warns that automatic sending is off; the toast and partner page show the scheduled Friday; the queue shows it; rescheduling from Saturday moves it to Monday. |
| UI-20 | LinkedIn by hand in the browser | Add Andrew Brackin's LinkedIn profile; Write email as a LinkedIn message; Approve; Outreach → By hand; Send on LinkedIn; I sent it | The profile link is normalised and shown; the To field fills from it; the item is due now with an Open profile link and the 200-character note hint; after I sent it the partner's timeline shows "Sent message on LinkedIn: Hi Andrew…". |

## Database tests (`tests/test_db.py`)

`?` placeholders and `%` signs are translated for PostgreSQL without touching quoted text; DDL gets `BIGSERIAL`, `DOUBLE PRECISION` and the `rowid` column only where needed; the engine is chosen from `VANGUARD_DATABASE_URL`; passwords are hidden in `db info`.

**Running everything on PostgreSQL:** set `VANGUARD_TEST_DATABASE_URL` to a server where you can create databases. `tests/conftest.py` gives each test a fresh database and drops it afterwards. Verified on PostgreSQL 16: the full suite passes.

## Fail-proof unit tests (`tests/test_failproof.py`)

Config covers every property and refuses unknown task classes or a non-Monday start; the calendar maps weeks to Fridays; rules are validated; tripwire states (not yet due, amber with no reading, green, tripped); weekly checks need a reading inside their own week; open gates remove blocked tasks and passing them restores them; the task classifier and focus lock; interim-owned delegated properties each have a G-CEO gate due week 16 that blocks paid acquisition; HALT at 3 tripped; the offline premortem has 7 ranked causes.

## Component tests (`tests/test_vanguard.py`)

- Registry: all eight ids; unknown id rejected.
- Lint gate: 6 blocking cases, 3 allowed cases.
- Schemas: no `$ref` in tool schemas; five ordered email steps.
- Orchestration:
  - parallel run with the expected number of repair passes
  - repair notes
  - needs-review flag
  - failure isolation
  - persistent block
- Approval-gated export.
- Idempotent Notion sync (a stateless mock).

## Manual acceptance checklist: web app

1. `vanguard seed-users`, then `vanguard serve`, then sign in as the admin at http://localhost:8080.
2. Admin → Start run (dry) → view a playbook → Approve → Import. Drafts appear under Campaigns
   and Partners.
3. Create a campaign as the team user, log a week of results, and check the dashboard moves.
4. Drag a partner card between columns and log an interaction.
5. Assign a task to the team user as admin. As that user, mark it Done.
6. Try the phone layout (resize the browser) and the light theme.
7. Once you've seen the flow, remove any demo data with `vanguard demo-data --purge`.

## Manual acceptance checklist (before the first live run)

1. `vanguard doctor`: all OK.
2. `vanguard estimate`: accept the figure.
3. `vanguard run --properties oratoplus --no-research`: review the playbook with `show`.
4. `vanguard sync`: check both Notion databases and the playbook page body.
5. Change a task's Status in Notion, run `vanguard sync` again, and confirm the Status is kept.
6. `vanguard approve oratoplus --by <you>` then `vanguard export oratoplus`: open the CSV.
7. Only then run all 8.

## Manual acceptance checklist: Postmark (before the first live Postmark send)

1. `vanguard outreach postmark-check` reports `"ok": true` and your `partners` stream as Transactional.
2. `vanguard outreach status` shows postmark mode, no problems, and the cold-routing line you expect.
3. On one of your own test partners, set the email permission to *Opted in* with your own address,
   approve step 1, and click **Send due now**. It arrives with the postal footer, and Postmark's
   Activity shows it on the `partners` stream with the property tag.
4. In Postmark, check the webhook's **Send test** answers 200. Reply to the email: if inbound is on,
   the partner moves to *In conversation* and the alert email arrives.
5. Send to `hardbounce@bounce-testing.postmarkapp.com` from a test partner. It is marked
   *bounced* and suppressed.
6. `vanguard outreach postmark-sync`: the numbers match Postmark's Suppressions tab.
