#!/usr/bin/env bash
# 4h candle accumulator wrapper — read-only public API, no keys, no orders.
#
# NOTE (2026-09-27): for standing accumulation prefer the autonomous DAEMON
# `paper_trading/daemon_4h.sh` (runs detached, zero Claude tokens). This wrapper
# is now just a single-shot manual/cron runner; the daemon is the superset.
#
# Gap-free by design: each run backfills every 4h candle closed since the last
# recorded one, so completeness holds at ANY cadence (even once/day). Intended
# uses:
#   * run once per daily leader turn (guarantees complete committed accumulation), OR
#   * schedule every 4h for intraday freshness (see the crontab line below).
#
# For a true 4h cadence on company infra (a persistent host with repo push
# access), add a crontab entry like (off-minute :07 to avoid the :00 stampede):
#
#   7 */4 * * * cd /workspace/upbit-hft-bot/leader && \
#     /usr/bin/python3 paper_trading/collect_4h.py >> logs/collect_4h.log 2>&1
#
# The high-frequency cron only APPENDS locally; the daily leader turn commits &
# pushes the accumulated rows (avoids 6 commits/day). Pass --commit here only if
# this wrapper itself should commit (needs the A_Company git credential helper).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
python3 paper_trading/collect_4h.py "$@"
