#!/usr/bin/env bash
# =============================================================================
# STRATEGY-EVOLUTION RUNNER — token-free (owner mission 2026-10-04, Cycle 31).
#
# One run = refresh the public 1h candles (data_1h.py) + walk-forward GA
# (evolve.py) -> research/evolution/results/{RESULTS.md,latest.json,history.jsonl}.
# No LLM in the loop; a leader turn only READS the results.
#
#   run_evolution.sh run     # one run in the foreground (flock: one at a time)
#   run_evolution.sh maybe   # spawn a detached run iff the last one is older than
#                            # EVOLVE_EVERY_DAYS (default 7). Called from the 4h
#                            # daemon tick, so the host cron that keeps that daemon
#                            # alive also keeps this loop going — no extra keep-alive.
#   run_evolution.sh status
#
# SAFETY — RESEARCH / PAPER ONLY. Public read-only candles; NO keys, NO account,
# NO orders. It never touches the official or shadow paper books.
# =============================================================================
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
PY="$(command -v python3)"
LOG="logs/evolution.log"
LOCK="logs/evolution.lock"
LATEST="research/evolution/results/latest.json"
EVERY_DAYS="${EVOLVE_EVERY_DAYS:-7}"
mkdir -p logs

case "${1:-status}" in
  run)
    exec 9>"$LOCK"
    if ! flock -n 9; then echo "[$(date -u +%FT%TZ)] evolution already running — skip"; exit 0; fi
    echo "[$(date -u +%FT%TZ)] evolution run START"
    nice -n 19 "$PY" research/evolution/data_1h.py || echo "WARN: 1h refresh failed; using stored data"
    nice -n 19 "$PY" research/evolution/evolve.py
    rc=$?
    echo "[$(date -u +%FT%TZ)] evolution run END rc=$rc"
    exit $rc
    ;;
  maybe)
    if [ -f "$LATEST" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$LATEST") ))
      [ "$age" -lt $(( EVERY_DAYS * 86400 )) ] && exit 0
    fi
    setsid nohup "$0" run >>"$LOG" 2>&1 </dev/null &
    echo "spawned detached evolution run (log $LOG)"
    ;;
  status)
    [ -f "$LATEST" ] && echo "last results: $(stat -c %y "$LATEST")" || echo "no results yet"
    tail -n 5 "$LOG" 2>/dev/null
    ;;
  *) echo "usage: $0 {run|maybe|status}"; exit 2 ;;
esac
