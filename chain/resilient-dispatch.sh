#!/usr/bin/env bash
# Wraps parable-run.sh with auto-retry for instrument failures (the dispatch process
# gets killed by the OS before codex even records a session_id). parable's own docs
# state a run killed that early has "nothing to resume" — so blindly retrying loses
# no work and is safe. This exists because relying on a human/agent to notice a
# "killed" task-notification and manually redispatch doesn't scale and isn't durable.
#
# Usage: resilient-dispatch.sh <executor> <plan.md> <workdir> <slug> [max_attempts]
set -uo pipefail

EXECUTOR="${1:?executor required}"
PLAN="${2:?plan.md required}"
WORKDIR="${3:?workdir required}"
SLUG="${4:?slug required — always pass one explicitly, never rely on the plan file parent directory}"
MAX_ATTEMPTS="${5:-3}"
PR="$HOME/.claude/plugins/cache/unc-skills/parable/0.1.7/skills/parable/scripts/parable-run.sh"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "=== dispatch attempt $attempt/$MAX_ATTEMPTS (slug=$SLUG) ==="
  OUTPUT=$(bash "$PR" "$EXECUTOR" "$PLAN" "$WORKDIR" --slug "$SLUG" 2>&1)
  CODE=$?
  echo "$OUTPUT"
  if [ "$CODE" -eq 0 ] && echo "$OUTPUT" | grep -q "^STATUS   OK"; then
    echo "=== succeeded on attempt $attempt ==="
    exit 0
  fi
  echo "=== attempt $attempt did not report STATUS OK (exit=$CODE) — retrying in 5s ===" >&2
  sleep 5
done

echo "=== all $MAX_ATTEMPTS attempts failed — this is a genuine failure, not a transient kill; stop and diagnose by hand ===" >&2
exit 1
