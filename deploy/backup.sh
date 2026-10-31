#!/usr/bin/env bash
# Daily DB backup. Cron example:  0 4 * * * /opt/telegram-order-bot/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
sqlite3 data/bot.db ".backup 'backups/bot-$(date +%F).db'"
find backups -name 'bot-*.db' -mtime +14 -delete
