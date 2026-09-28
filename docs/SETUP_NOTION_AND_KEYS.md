# Setup guide: Notion, keys, and keeping it at $0

Version 0.6.0 · updated 2026-09-28

## What costs money, and what doesn't

| Piece | Cost | Notes |
|---|---|---|
| Vanguard-GTM itself | $0 | Runs on your laptop or on your existing Hostinger VPS |
| Notion API and connection | $0 | Notion doesn't charge for API use. On a single-member Free workspace, block storage is unlimited. If you add members on the Free plan, Notion's block limit can apply; check notion.com/pricing. |
| `vanguard run --dry-run` | $0 | Placeholder content, useful for testing the plumbing |
| **Local model (Ollama + Qwen/Llama)**, the default provider | $0 | Runs on your own GPU/CPU. Nothing leaves your machine. Needs disk space and enough memory (Part 3). |
| `vanguard prompt` → Claude chat → `vanguard import` | $0 extra | Uses the Claude plan you already have. Real strategy content, pasted in by you. |
| Partner emails (outbox mode, the default) | $0 | Approved emails are saved to `output/outbox/`; nothing is sent |
| Partner emails (SMTP mode) | $0 extra | Sent through a mailbox you already have (Google Workspace, Gmail, Hostinger mail…) |
| Partner emails and team alerts via **Postmark** (optional) | $0 up to 100 emails/month | Postmark's free Developer plan. Vanguard stops at `VANGUARD_POSTMARK_MONTHLY_CAP` (default 100), so it never creates overage. Inbound reply processing needs a paid plan; IMAP reply sync stays free. |
| `vanguard run` with the Claude API | **Paid**, pay-as-you-go | **Off by default.** API usage is billed separately from a Claude.ai subscription. Roughly $1.50 (Haiku, no research) to $4.20 (Sonnet, with research) for all 8 properties. It stays off until you set `VANGUARD_MAX_COST_USD` above 0. |

The shipped `.env.example` has `VANGUARD_MAX_COST_USD=0`. At that setting a paid run is
refused before anything is sent, and `vanguard doctor` shows `paid API runs: OFF ($0 mode)`.

---

## Part 1: Install (Windows, about 5 minutes)

The program lives **directly** in `C:\Users\NAREN\vireoka-dev\Vanguard_GTM\`. That folder
itself holds `vanguard\`, `ui\`, `config\`, `docs\`, `pyproject.toml` and `.env.example`.
**Don't unzip `vanguard-gtm.zip` there.** It's only a backup copy, and extracting it would
create a second, nested `vanguard-gtm` folder. Updates are written straight into this folder.

**Quickest way:** in PowerShell, run
```powershell
cd C:\Users\NAREN\vireoka-dev\Vanguard_GTM
powershell -ExecutionPolicy Bypass -File .\start.ps1          # add -Demo the first time for sample data
```
`start.ps1` does the following:
- finds Python 3.11+ (the `py` launcher, `python`, Anaconda, or a standard install);
- creates `.venv` and installs Vanguard, and creates `.env`;
- creates your two sign-ins (it prints the passwords once);
- opens http://localhost:8080.

After the first time, the same command just starts the app. The manual steps below do the same
thing by hand.

1. Check Python is 3.11 or newer: `python --version`. If it isn't, run
   `winget install Python.Python.3.12`, then reopen PowerShell.
2. Open **PowerShell** in the program folder (one-time setup):
   ```powershell
   cd C:\Users\NAREN\vireoka-dev\Vanguard_GTM
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   copy .env.example .env
   pytest -q                      # should end with "... passed, 3 skipped" and no failures
   vanguard run --dry-run         # 8 properties, offline, $0
   ```
   If `Activate.ps1` says running scripts is disabled, run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer **Y**, and try again.
3. **Every later session** only needs:
   ```powershell
   cd C:\Users\NAREN\vireoka-dev\Vanguard_GTM
   .\.venv\Scripts\Activate.ps1
   vanguard serve                 # then open http://localhost:8080
   ```
   If you prefer WSL, use the same commands with `python3 -m venv .venv && source .venv/bin/activate`
   and `cp .env.example .env`.

---

## Part 2: Connect Notion (free, about 10 minutes)

You need to be a **Workspace Owner** in Notion to create a connection.

### Step 1: Make a home page for Vanguard
In Notion, create a new page called **Vanguard-GTM**. Both databases will be created inside it.

### Step 2: Create the internal connection
1. Go to **https://app.notion.com/developers/connections**.
2. In the sidebar under **Build**, click **Internal connections**, then **Create a new
   connection**.
3. Name it `Vanguard-GTM` and choose your workspace. Save.
4. Open the **Configuration** tab and turn on these capabilities:
   - **Read content**
   - **Update content**
   - **Insert content**

   Vanguard doesn't need user information.
5. On the same tab, copy the **Installation access token**. It usually starts with `ntn_`.
   Treat it like a password.

### Step 3: Give the connection access to your page
1. Open the **Vanguard-GTM** page.
2. Click **•••** at the top right, then **Connections**, then **+ Add connection**.
3. Pick **Vanguard-GTM** and confirm. This also gives it access to child pages, which is where
   the databases will go.

(Or: in the developer portal, open the connection, go to the **Content access** tab, click
**Edit access** and select the page.)

### Step 4: Copy the page ID
Click **Share → Copy link** on the page. The link looks like
`https://www.notion.so/Vanguard-GTM-1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6?pvs=4`.
The page ID is the 32 characters after the last dash and before `?`, in this case
`1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6`.

### Step 5: Put the token in `.env`
Open `.env` in Notepad or VS Code and set:
```
NOTION_TOKEN=ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
Save. Don't commit `.env`; it's already in `.gitignore`.

### Step 6: Load `.env` and check the connection
PowerShell:
```powershell
Get-Content .env | % { if ($_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), ($matches[2] -replace '\s+#.*$','').Trim()) } }
vanguard doctor
```
WSL/bash: `set -a; source .env; set +a; vanguard doctor`

You should see `OK Notion token accepted`. The Anthropic line will say not set, which is fine
in $0 mode.

### Step 7: Create the databases and do a first sync
```powershell
vanguard notion-setup --parent-page 1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6
vanguard run --dry-run --sync
vanguard doctor          # now also checks both databases are reachable
```
Two databases now sit under your page:
- **Vanguard-GTM · Playbooks**: 8 rows, each page holding the full playbook.
- **Vanguard-GTM · Tasks**: 240 rows.

Dry-run content is placeholder text marked `[mock]`. Delete those rows, or keep them to see
the layout.

---

## Part 3: Run the engines on a free local model (recommended)

Vanguard's default provider is `local`: every engine call goes to a model on your machine. Claude
is used only as a backup, and only once you switch paid runs on in Part 5.

### Step 1: Pick a model that fits your machine

| Your hardware | Model | `ollama pull` | Download |
|---|---|---|---|
| NVIDIA GPU with 24 GB (RTX 3090/4090), or a Mac with 32 GB+ | Qwen 3.6 27B, the default and best quality | `ollama pull qwen3.6:27b` | about 18 GB |
| GPU with about 12 GB | 14B-class | `ollama pull qwen3:14b` | about 9 GB |
| Laptop GPU with 8 GB, or CPU only | 8B-class | `ollama pull llama3.1:8b` | about 5 GB |

- If you have a Qwen 3.8 27B tag available, `ollama pull qwen3.8:27b` works too. Set
  `VANGUARD_LOCAL_MODEL` to whatever you pulled.
- Models larger than your GPU memory still run, but on CPU they are very slow: minutes per
  engine call.
- To check your GPU in PowerShell: `nvidia-smi` (look at "Memory-Usage" for the total).

### Step 2: Install Ollama and pull the model
1. Install from **https://ollama.com/download** (Windows installer). You already have a
   `.ollama` folder in your home directory, so it may be installed; `ollama --version` checks.
2. In PowerShell: `ollama pull qwen3.6:27b`, or the tag you picked.
3. Test it: `ollama run qwen3.6:27b "Say hello in five words"`, then `/bye`.

### Step 3: Point Vanguard at it
In `.env` (these are already the defaults):
```
VANGUARD_PROVIDER=local
VANGUARD_LOCAL_MODEL=qwen3.6:27b
```
Then reload `.env` and run:
```powershell
vanguard doctor                         # expect: OK local model: qwen3.6:27b ready at http://localhost:11434
vanguard run --properties oratoplus     # one property first; $0
vanguard status                         # shows local calls and fallbacks
vanguard run                            # all 8 when you're happy
```
The eight pipelines run in parallel, but their calls queue for your GPU one at a time. On a
24 GB GPU a 27B model takes very roughly 1–4 minutes per engine call, so a full run is an hour
or two. Let it run.

**Using LM Studio or llama.cpp instead of Ollama.** Set `VANGUARD_LOCAL_API=openai` and
`VANGUARD_LOCAL_URL=http://localhost:1234/v1` (LM Studio's default) or your `llama-server` URL.

**Quality note.** Local models write weaker strategy than Claude. Everything still goes through
the schema checks and the lint gate, but review before approving.

---

## Part 4: Real playbooks at $0 without a GPU (the manual chat path)

```powershell
vanguard prompt all --out prompts
```
1. Open `prompts\liqmint.prompt.txt` and paste the whole text into a new Claude chat.
2. Save Claude's reply as `prompts\liqmint.json`. The reply can include text around the JSON
   and code fences; import ignores them.
3. Repeat for the other seven. You can have several chats open at once.
4. Import and sync:
   ```powershell
   vanguard import all prompts
   vanguard status
   vanguard sync
   ```
   A reply that fails validation, for example one missing its design partner or co-selling
   partner, is reported. Fix that chat and import again with `--run <id>` to add it to the
   same run.

---

## Part 5 (optional, paid): add an Anthropic API key as a backup

With a key and a cap, Claude becomes the **backup**: it's used only for calls the local model
can't complete (server down, or invalid output three times). Alternatively, set
`VANGUARD_PROVIDER=claude` to use Claude for everything.

1. Go to **console.anthropic.com**, then **Settings → API keys → Create key**. Copy it; it's
   shown only once.
2. Under **Billing**, add prepaid credits. A $5–10 top-up covers several full runs. Also set a
   **spend limit** in the Console, as a second safety net on Anthropic's side.
3. In `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   VANGUARD_MAX_COST_USD=5        # hard cap per run; set back to 0 to return to $0 mode
   VANGUARD_MODEL=claude-haiku-4-5
   VANGUARD_WEB_SEARCH=0
   ```
   The last two are the cheapest settings to start with.
4. Reload `.env`, then:
   ```powershell
   vanguard doctor                         # "Anthropic key accepted"; listing models is free
   vanguard estimate                       # shows the expected spend
   vanguard run --properties oratoplus     # shows the estimate and asks y/N
   vanguard status                         # shows the actual spend for the run
   ```

---

## Part 6: Open the web app ($0)

```powershell
vanguard seed-users      # creates admin@vireoka.com and team@vireoka.com; prints both passwords ONCE - save them
vanguard demo-data       # optional: [DEMO] sample records so the screens aren't empty (remove later with --purge)
vanguard serve           # then open http://localhost:8080
```
- Sign in as the admin. **Admin → Users** is where you add your team.
- On the VPS, `docker compose up -d --build` builds the UI into the image. Add a
  `VANGUARD_JWT_SECRET=<long random string>` line to `.env` so sign-ins survive restarts.
- With the Traefik route in `deploy/`, the app is at `https://gtm.vireoka.com`.

How to use each screen is in `docs/USER_GUIDE.md`.

## Part 7: Send partner emails for real (optional, $0 extra)

Keep the default **outbox mode** until you've reviewed a few approved emails in
`output/outbox/`. You can open the `.eml` files in Outlook or Mail. When you're ready:

1. **Pick a sending mailbox on your own domain**, for example `partners@vireoka.com`. Make sure
   the domain's DNS has **SPF**, **DKIM** and **DMARC** records (your email provider's help pages
   list the exact rows). This keeps your emails out of spam.
2. **Get SMTP (and optionally IMAP) credentials:**

   | Provider | SMTP | IMAP (reply sync) | Password |
   |---|---|---|---|
   | Google Workspace / Gmail | `smtp.gmail.com`, port 587 | `imap.gmail.com`, port 993 | An **app password**. Needs 2-step verification: Google Account → Security → App passwords. |
   | Hostinger email | `smtp.hostinger.com`, port 465 | `imap.hostinger.com`, port 993 | The mailbox password |
   | Others | Your provider's SMTP settings | Their IMAP settings | As they document |

3. **Add them to `.env`:**
   ```
   VANGUARD_EMAIL_MODE=smtp
   VANGUARD_SENDER_NAME=Narendra Gore
   VANGUARD_SENDER_EMAIL=partners@vireoka.com
   VANGUARD_SENDER_ADDRESS=<your business postal address - required by US anti-spam law>
   VANGUARD_EMAIL_DAILY_CAP=20
   SMTP_HOST=smtp.hostinger.com
   SMTP_PORT=465
   SMTP_USER=partners@vireoka.com
   SMTP_PASSWORD=<mailbox or app password>
   IMAP_HOST=imap.hostinger.com
   IMAP_USER=partners@vireoka.com
   IMAP_PASSWORD=<same>
   VANGUARD_OUTREACH_EVERY_MIN=30       # optional: send due + check replies every 30 min while `serve` runs
   ```
4. **Test before emailing partners:**
   - run `vanguard outreach status` and check it reports no problems;
   - add yourself as a named target under any segment and approve that one email;
   - **Send due now**, then check it arrives, the footer looks right, and replying
     "unsubscribe" gets picked up by **Check replies**.
5. **Then approve real partners.** Start with a handful of P0 targets and keep the daily cap low
   for the first weeks.

Every email carries your name, company, postal address and a one-line opt-out. Opt-outs are
honoured automatically and permanently. The inbox connection is read-only: it never marks,
moves or deletes your mail.

## Part 8: Postmark message streams (optional, free up to 100 emails a month)

Postmark gives you delivery tracking, automatic bounce and spam-complaint handling, and (on a
paid plan) instant reply processing. **Postmark only accepts permission-based email**, so
Vanguard uses it for partners who have replied, opted in, or already know you. Cold first
touches go from your own mailbox (Part 7), or wait until you mark the partner "Opted in".

> Use a **new** server token made for Vanguard. Don't reuse the Postmark token in the atmakosh
> notes (see the Security note below). Rotate that one.

### Step 1: Create the server and verify your sender
1. Sign up at postmarkapp.com. The free Developer plan includes 100 emails a month.
2. **Servers → Create server:** name it `Vanguard-GTM`.
3. **Sender Signatures → Add Domain:** add `vireoka.com` (or the domain you send from). Add the
   **DKIM** and **Return-Path** DNS records it shows at your DNS host, then click **Verify**.
   A single confirmed sender signature for `partners@vireoka.com` also works.
4. New accounts start in **test mode** (they can only send to your own domain) until Postmark
   approves the account. Request approval from the server page, and describe the use honestly:
   "one-to-one partnership emails to contacts who've agreed to hear from us, plus internal alerts".

### Step 2: Create the streams
In the server, open **Message Streams**:
- `outbound` (Default Transactional) already exists. Vanguard uses it for team alerts.
- **Create message stream → Transactional**, with ID `partners`. Partner emails go here, with
  their own reputation and suppression list.
- The **inbound** stream exists by default. Copy its address (like
  `abc123@inbound.postmarkapp.com`) if you'll use inbound replies (paid plans).

Don't use a Broadcasts stream: partner emails are one-to-one.

### Step 3: Copy the server API token
Server → **API Tokens** → copy the **Server API token**.

### Step 4: Add it to `.env`
```
VANGUARD_EMAIL_MODE=postmark
POSTMARK_SERVER_TOKEN=<server api token>
VANGUARD_POSTMARK_STREAM_OUTREACH=partners
VANGUARD_POSTMARK_STREAM_NOTIFY=outbound
VANGUARD_SENDER_NAME=Narendra Gore
VANGUARD_SENDER_EMAIL=partners@vireoka.com          # must be on the verified domain / signature
VANGUARD_SENDER_ADDRESS=<your business postal address>
VANGUARD_POSTMARK_MONTHLY_CAP=100                   # stay inside the free plan
# optional - keep SMTP from Part 7 so cold first touches go from your own mailbox:
# SMTP_HOST=... SMTP_USER=... SMTP_PASSWORD=...
# optional (paid plans) - replies arrive instantly and are matched exactly:
# VANGUARD_POSTMARK_INBOUND_ADDRESS=abc123@inbound.postmarkapp.com
VANGUARD_POSTMARK_WEBHOOK_USER=pmhook
VANGUARD_POSTMARK_WEBHOOK_PASSWORD=<a long random string>
```
Then run `vanguard outreach postmark-check`. It should report `"ok": true` and list `partners`
as Transactional. `vanguard doctor` shows the same check.

### Step 5: Add the webhook (bounces, spam complaints, deliveries)
Vanguard must be reachable over HTTPS, for example `https://gtm.vireoka.com` behind Traefik
(Part 6). In the `partners` stream → **Webhooks → Add webhook**:
- **URL:** `https://pmhook:<password>@gtm.vireoka.com/hooks/postmark`. Postmark sends the
  user and password as HTTP Basic Auth.
- **Tick:** Delivery, Bounce, Spam Complaint, Subscription Change. Tick Open only if you set
  `VANGUARD_POSTMARK_TRACK_OPENS=1`.
- Click **Send test**: it should answer 200.

Add the same webhook to the `outbound` stream if you want bounces on team alerts tracked too.

**Inbound (paid plans):** in the inbound stream → **Settings → Webhook URL**, use the same
URL. Replies to `abc123+o42@inbound.postmarkapp.com` reach Vanguard with `MailboxHash o42`, so
they match message 42 exactly.

### Step 6: How sending works now
- **Warm partners** (email permission *Opted in*, *Existing relationship* or *Replied*) go
  through the `partners` stream. Set the permission on the partner page.
- **Cold partners** (*No permission yet*) go through your SMTP mailbox if Part 7 is set up.
  Otherwise **Send due now** lists them as "held". When they reply, they become *Replied*, and
  their next emails can go through Postmark.
- **Bounces and spam complaints** suppress the address and stop the sequence automatically.
  **Sync suppressions** on the Outreach page, or `vanguard outreach postmark-sync`, keeps
  Vanguard's list and Postmark's list the same.
- **Email approval digest** (Outreach page, or `vanguard outreach digest`) emails every admin
  the list of drafts waiting for approval. Reply alerts go to admins and the partner's owner.
- The banner on the Outreach page shows the streams and the month's usage (for example
  `12/100 this month`).

`VANGUARD_POSTMARK_ALLOW_COLD=1` exists if you have your own documented permission for a list,
but by default Vanguard keeps cold email off Postmark to protect your account.

## Security note

`vireoka-dev\atmakosh-platform\important_details_atmakosh.md` contains plain-text API keys
(Groq, Gemini, OpenRouter), a Postmark server token and a password. Vanguard doesn't use that
file.
- Rotate those credentials.
- Move them into Secret Manager, as the file itself suggests.
- Delete the file, or scrub it and the repo history.
