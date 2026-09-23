#!/usr/bin/env bash
# Convenience launcher. Loads secrets.env if present (gitignored) and starts the
# bot. Defaults to PAPER mode. Pass --live to trade for real (you will be asked
# to confirm), --once for a single iteration.
set -euo pipefail
cd "$(dirname "$0")"
[ -f secrets.env ] && set -a && . ./secrets.env && set +a
exec python3 src/bot.py "$@"
