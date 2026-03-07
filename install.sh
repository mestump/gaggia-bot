#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Set this to the user that will run the service
USER_TO_INSTALL="${USER_TO_INSTALL:-$(whoami)}"
[ -f "$SCRIPT_DIR/.env" ] || { echo "ERROR: .env not found at $SCRIPT_DIR/.env. Copy .env.example and fill in values first."; exit 1; }
# Substitute placeholders in service file and install
sed \
  -e "s|REPLACE_WITH_YOUR_USER|$USER_TO_INSTALL|g" \
  -e "s|REPLACE_WITH_INSTALL_PATH|$SCRIPT_DIR|g" \
  "$SCRIPT_DIR/gaggia-bot.service" | sudo tee /etc/systemd/system/gaggia-bot.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable gaggia-bot
sudo systemctl start gaggia-bot
echo "Service installed. Check: systemctl status gaggia-bot"
