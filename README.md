# Vanguard-GTM

Go-to-market orchestration for the Vireoka portfolio, with a web app for the team. Eight properties run in parallel through
four engines:

1. **Market & ICP**
2. **Partnerships**, which must include a design partner and a B2B co-selling partner. The
   partnerships expert (Engine 2B) also ranks specific partner targets (P0–P2) and drafts their
   outreach emails.
3. **Campaigns**: social campaigns plus 5-step email sequences
4. **30-day task registry**

All outward-facing copy goes through a claim-discipline lint gate. The results sync to Notion.
Nothing sends or publishes without your approval.

**Web app** (`vanguard serve`, then http://localhost:8080):
- a dashboard against the ARR targets;
- campaigns with results logging;
- a partner pipeline board;
- tasks;
- an admin area for running the agent, approving and importing plans, managing users and reading the audit log;
- **partner outreach**: recommended partners, admin-approved emails, reply tracking, and signed
  agreements on the dashboard. Emails stay in a local outbox by default. They can go out through
  your own mailbox (SMTP) or through **Postmark message streams**, which add delivery, bounce and
  spam tracking and inbound replies (setup guide Part 8).

There are two roles: admin and team member.

**Local model first.** Engines run on Ollama (for example `qwen3.6:27b`) at $0. Claude is an
optional, capped backup.

**$0 by default.** Paid Claude API runs are off until you set `VANGUARD_MAX_COST_USD`. Dry runs,
the Claude-chat `prompt`/`import` path and Notion all cost nothing.

```bash
pip install -e ".[dev]" && cp .env.example .env
pytest -q                                  # offline, $0
vanguard run --dry-run                     # all 8 properties, placeholder content
vanguard prompt all --out prompts          # real content via your Claude chats ...
vanguard import all prompts                # ... validated + linted, $0
vanguard notion-setup --parent-page <id> && vanguard sync
vanguard seed-users && vanguard serve      # web app on :8080
```

| Doc | For |
|---|---|
| [docs/SETUP_NOTION_AND_KEYS.md](docs/SETUP_NOTION_AND_KEYS.md) | Step-by-step Notion connection, `.env`, costs |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture, engines, lint gate, cost model, data model, change log |
| [docs/PROGRAMMERS_MANUAL.md](docs/PROGRAMMERS_MANUAL.md) | Config, CLI and API reference, how-tos, testing, troubleshooting |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | How the team and admins use the web app |
| [docs/TEST_CASES.md](docs/TEST_CASES.md) | End-to-end test catalogue and manual acceptance checklist |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

Deploy on the Hostinger VPS: `docker compose up -d --build`, then add
`deploy/traefik-vanguard.yml` to the Traefik edge and restart Traefik.
