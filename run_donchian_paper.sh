#!/usr/bin/env bash
# Forward-run the PAPER-ONLY Donchian bot for both timeframes and append any
# newly-closed candles to logs/paper_<tf>.csv. Idempotent: safe to run on any
# cadence; it only appends candles newer than the last logged one.
#
# Intended cadence:
#   * daily : run once per day, shortly after 00:00 UTC (daily candle close)
#   * 4h    : run every 4h, shortly after 00/04/08/12/16/20:00 UTC
# This environment has no OS cron; the runner is invoked each research cycle
# (the accumulation is driven by dispatch). For a real deployment, add e.g.:
#   5 0   * * *  cd <repo> && ./run_donchian_paper.sh daily
#   5 */4 * * *  cd <repo> && ./run_donchian_paper.sh 4h
#
# Execution: defaults to Cycle-13 gap-robust RESTING stop orders (outage-immune);
# pass EXEC=market to use legacy next-open fills.
# PAPER ONLY — never places live orders, never uses API keys.
set -euo pipefail
cd "$(dirname "$0")"
tf="${1:-both}"
exec_mode="${EXEC:-resting}"
run_one() { python3 src/donchian_bot.py --tf "$1" --exec "$exec_mode"; }
case "$tf" in
  daily) run_one daily ;;
  4h)    run_one 4h ;;
  both)  run_one daily; run_one 4h ;;
  *) echo "usage: $0 [daily|4h|both]"; exit 1 ;;
esac
