#!/bin/bash
set -e
sudo cp gaggia-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gaggia-bot
sudo systemctl start gaggia-bot
echo "Service installed. Check: systemctl status gaggia-bot"
