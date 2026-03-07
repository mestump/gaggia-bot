#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f /home/michael/gaggia-bot/.env ] || { echo "ERROR: .env not found at /home/michael/gaggia-bot/.env. Copy .env.example and fill in values first."; exit 1; }
sudo cp "$SCRIPT_DIR/gaggia-bot.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gaggia-bot
sudo systemctl start gaggia-bot
echo "Service installed. Check: systemctl status gaggia-bot"
