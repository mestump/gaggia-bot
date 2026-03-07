#!/bin/bash
# Auto-resume gaggia-bot build session after usage limit resets.
# Installed by cron: see /home/michael/gaggia-bot/scripts/install-cron.sh

set -euo pipefail

SESSION_ID="c181e180-2fcf-4fe1-adfb-ca822bc625d3"
RESUME_PROMPT_FILE="/home/michael/gaggia-bot/docs/resume-prompt.md"
LOG_FILE="/home/michael/gaggia-bot/data/auto-resume.log"
LOCK_FILE="/tmp/gaggia-bot-resume.lock"
WORK_DIR="/home/michael/gaggia-bot"
CLAUDE_BIN="/home/michael/.local/bin/claude"

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    echo "[$(date)] Lock file exists — skipping (previous run still active?)" >> "$LOG_FILE"
    exit 0
fi

# Check if claude is available
if [ ! -x "$CLAUDE_BIN" ]; then
    echo "[$(date)] Claude CLI not found at $CLAUDE_BIN" >> "$LOG_FILE"
    exit 1
fi

# Check if checkpoint says we're done
if grep -q "ALL COMPLETE" "$RESUME_PROMPT_FILE" 2>/dev/null; then
    echo "[$(date)] Build complete — removing cron job" >> "$LOG_FILE"
    crontab -l | grep -v "auto-resume.sh" | crontab -
    exit 0
fi

touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

RESUME_PROMPT=$(cat "$RESUME_PROMPT_FILE")

echo "[$(date)] Resuming session $SESSION_ID..." >> "$LOG_FILE"

cd "$WORK_DIR"

# Try to resume the existing session first; fall back to --continue
if $CLAUDE_BIN \
    --dangerously-skip-permissions \
    --resume "$SESSION_ID" \
    --print \
    "$RESUME_PROMPT" \
    >> "$LOG_FILE" 2>&1; then
    echo "[$(date)] Session resumed and completed successfully" >> "$LOG_FILE"
else
    EXIT_CODE=$?
    echo "[$(date)] Resume failed (exit $EXIT_CODE) — trying --continue" >> "$LOG_FILE"
    $CLAUDE_BIN \
        --dangerously-skip-permissions \
        --continue \
        --print \
        "$RESUME_PROMPT" \
        >> "$LOG_FILE" 2>&1 || echo "[$(date)] --continue also failed (exit $?)" >> "$LOG_FILE"
fi
