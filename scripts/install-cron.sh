#!/bin/bash
# Installs the auto-resume cron job.
# Usage: bash scripts/install-cron.sh [reset_hour] [reset_minute]
# Defaults to 5 hours from now (Claude's usage window).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESUME_SCRIPT="$SCRIPT_DIR/auto-resume.sh"
chmod +x "$RESUME_SCRIPT"

# Calculate reset time: 5 hours from now + 5 minute buffer
RESET_HOUR="${1:-}"
RESET_MINUTE="${2:-}"

if [ -z "$RESET_HOUR" ] || [ -z "$RESET_MINUTE" ]; then
    # Add 5h5m to current time
    RESET_EPOCH=$(( $(date +%s) + 5*3600 + 5*60 ))
    RESET_HOUR=$(date -d "@$RESET_EPOCH" +%H)
    RESET_MINUTE=$(date -d "@$RESET_EPOCH" +%M)
fi

echo "Scheduling auto-resume at ${RESET_HOUR}:${RESET_MINUTE} (local time)"

# Remove any existing gaggia-bot resume cron entry
(crontab -l 2>/dev/null | grep -v "auto-resume.sh") | crontab -

# Add new entry — run once at reset time, then remove itself if session complete
(crontab -l 2>/dev/null; echo "$RESET_MINUTE $RESET_HOUR * * * $RESUME_SCRIPT") | crontab -

echo "Cron job installed:"
crontab -l | grep "auto-resume"
echo ""
echo "To check logs after resume: tail -f /home/michael/gaggia-bot/data/auto-resume.log"
echo "To cancel: crontab -l | grep -v auto-resume.sh | crontab -"
