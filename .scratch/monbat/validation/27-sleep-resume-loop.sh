#!/usr/bin/env bash
# Adapted from diagnosing-bugs/scripts/hitl-loop.template.sh.
# The agent relays these prompts and enters the user's reported observations.
set -euo pipefail

if [[ -f .env.local ]]; then
  set -a
  source .env.local
  set +a
fi

step() {
  printf '\n>>> %s\n' "$1"
  read -r -p "    [Enter when done] " _
}

capture() {
  local var="$1" question="$2" answer
  printf '\n>>> %s\n' "$question"
  read -r -p "    > " answer
  printf -v "$var" '%s' "$answer"
}

date -u '+PROMPTED_AT=%Y-%m-%dT%H:%M:%SZ'
dashboard_url="${MONBAT_DASHBOARD_URL:-http://127.0.0.1:8000}"
step "With Dashboard closed, sleep the Linux laptop for 1–2 minutes. Wake it and immediately open ${dashboard_url%/}/. Report when open."
date -u '+REPORTED_OPEN_AT=%Y-%m-%dT%H:%M:%SZ'
capture DISPLAY "What does the Dashboard show for each Battery?"
capture DURATION "How long was sleep, and did you perform any restart, scan or reset?"
printf '\nDISPLAY=%s\nDURATION=%s\n' "$DISPLAY" "$DURATION"
