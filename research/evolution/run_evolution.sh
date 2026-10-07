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
# Be a polite guest on a shared, small host (owner 2026-10-05: heavy jobs may
# hurt the server). A busy host just DEFERS the run to a later 4h tick.
MIN_MEM_MB="${EVOLVE_MIN_MEM_MB:-400}"      # MemAvailable needed to start
MAX_LOAD="${EVOLVE_MAX_LOAD:-$(nproc)}"     # 1-min loadavg ceiling to start
VMEM_KB="${EVOLVE_VMEM_KB:-1048576}"        # hard address-space cap (1 GB; peak RSS ~70 MB)
mkdir -p logs

host_busy() {  # prints a reason and returns 0 when the host is too busy
  local mem load
  mem=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
  load=$(cut -d' ' -f1 /proc/loadavg)
  if [ "${mem:-0}" -lt "$MIN_MEM_MB" ]; then echo "MemAvailable ${mem}MB < ${MIN_MEM_MB}MB"; return 0; fi
  if awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l > m)}'; then echo "loadavg $load > $MAX_LOAD"; return 0; fi
  return 1
}

case "${1:-status}" in
  run)
    exec 9>"$LOCK"
    if ! flock -n 9; then echo "[$(date -u +%FT%TZ)] evolution already running — skip"; exit 0; fi
    echo "[$(date -u +%FT%TZ)] evolution run START"
    if why=$(host_busy); then echo "[$(date -u +%FT%TZ)] host busy ($why) — deferred to a later tick"; exit 0; fi
    ulimit -v "$VMEM_KB"
    LOW="nice -n 19"; command -v ionice >/dev/null && LOW="ionice -c3 $LOW"
    $LOW "$PY" research/evolution/data_1h.py || echo "WARN: 1h refresh failed; using stored data"
    $LOW "$PY" research/evolution/evolve.py
    rc=$?
    echo "[$(date -u +%FT%TZ)] evolution run END rc=$rc"
    exit $rc
    ;;
  maybe)
    if [ -f "$LATEST" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$LATEST") ))
      [ "$age" -lt $(( EVERY_DAYS * 86400 )) ] && exit 0
    fi
    if why=$(host_busy); then echo "evolution due but host busy ($why) — deferred"; exit 0; fi
    setsid nohup "$0" run >>"$LOG" 2>&1 </dev/null &
    echo "spawned detached evolution run (log $LOG)"
    ;;
  status)
    [ -f "$LATEST" ] && echo "last results: $(stat -c %y "$LATEST")" || echo "no results yet"
    if why=$(host_busy); then echo "host now: busy ($why) — a due run would defer"; else echo "host now: OK to run"; fi
    tail -n 5 "$LOG" 2>/dev/null
    ;;
  *) echo "usage: $0 {run|maybe|status}"; exit 2 ;;
esac
