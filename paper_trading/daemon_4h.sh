#!/usr/bin/env bash
# =============================================================================
# 4h data-accumulation DAEMON — autonomous, Claude-free (owner directive 2026-09-27).
#
# Loops collect_4h.py every 4h and appends the closed candle(s) to the committed
# trail market_data_4h.csv. Runs detached (setsid -> reparents to PID 1), so it
# survives every leader turn and costs ZERO Claude tokens. The leader only READS
# the trail/log and commits on command (daemon appends locally only).
#
# SAFETY — RESEARCH / PAPER ONLY. Read-only public candle endpoint; NO keys, NO
# account, NO orders. All plumbing (detach, self-heal, crash-resilient loop,
# prompt stop) lives in daemon_lib.sh; this file is just the 4h config.
#
# USAGE: paper_trading/daemon_4h.sh {start|ensure|stop|restart|status|logs}
#   ensure = launch ONLY if not already running (idempotent reboot self-heal).
# =============================================================================
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
DAEMON_NAME="collect_4h"
DAEMON_DESC="4h candle accumulator (read-only public API)"
STEP=$((4 * 3600))          # 4h candle spacing (seconds)
OFFSET=90                   # wake this many seconds AFTER each 4h boundary

# shellcheck source=paper_trading/daemon_lib.sh
source "$(dirname "$SELF")/daemon_lib.sh"

daemon_tick() {
  local rc
  "$PY" paper_trading/collect_4h.py
  rc=$?
  # Cycle 31 (owner mission 2026-10-04), both AFTER the collector and unable to
  # change its result: (1) the evolved-ensemble SHADOW books (official=false)
  # catch up on closed 1h candles; (2) a detached strategy-evolution run is
  # spawned iff the last one is older than 7 days. Failures are logged, ignored.
  "$PY" paper_trading/ensemble_books/ensemble_book.py \
    || echo "ensemble_books tick FAILED (collector unaffected)"
  research/evolution/run_evolution.sh maybe \
    || echo "evolution spawn FAILED (collector unaffected)"
  return $rc
}

daemon_next_sleep() {
  local now next s
  now=$(date -u +%s)
  next=$(( ( now / STEP + 1 ) * STEP + OFFSET ))
  s=$(( next - now ))
  [ "$s" -lt 30 ] && s=$(( s + STEP ))       # guard tiny sleeps
  echo "$s"
}

daemon_status_extra() {
  echo "--- trail integrity ---"
  "$PY" - <<'PYEOF'
import sys
sys.path.insert(0, "paper_trading")
import collect_4h
rows, dups, ooo, gaps, gl = collect_4h.integrity()
print(f"rows={rows} dups={dups} out_of_order={ooo} gaps={gaps}")
PYEOF
}

daemon_main "$@"
