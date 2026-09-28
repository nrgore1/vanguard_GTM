#!/usr/bin/env bash
# Starts an isolated Vanguard web app for the browser tests: fresh temp database, three known users,
# one offline dry run (oratoplus + atmakosh) so there are playbooks and tasks. Never touches your real data.
set -euo pipefail
PY="${VANGUARD_PYTHON:-python3}"
D="$(mktemp -d)"
export VANGUARD_DB="$D/v.db" VANGUARD_OUTPUT="$D/out" VANGUARD_JWT_SECRET="e2e-secret" VANGUARD_LOCAL_URL="http://127.0.0.1:9"
unset VANGUARD_MAX_COST_USD ANTHROPIC_API_KEY NOTION_TOKEN POSTMARK_SERVER_TOKEN SMTP_HOST IMAP_HOST || true
export VANGUARD_EMAIL_MODE=outbox
cd "$(dirname "$0")/../.."
"$PY" -m vanguard create-user --email admin@vireoka.com --name "Ada Admin" --role admin --password admin-pass-123 >/dev/null
"$PY" -m vanguard create-user --email uma@vireoka.com --name "Uma User" --password user-pass-1234 >/dev/null
"$PY" -m vanguard create-user --email otto@vireoka.com --name "Otto Other" --password user-pass-1234 >/dev/null
"$PY" -m vanguard run --dry-run --properties oratoplus,atmakosh >/dev/null 2>&1
exec "$PY" -m uvicorn vanguard.web.app:app --host 127.0.0.1 --port "${VANGUARD_E2E_PORT:-8765}" --log-level warning
