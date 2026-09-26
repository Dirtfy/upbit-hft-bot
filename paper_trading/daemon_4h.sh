#!/usr/bin/env bash
# =============================================================================
# 4h data-accumulation DAEMON — runs INDEPENDENTLY of any Claude/leader turn.
#
# WHY THIS EXISTS (owner directive 2026-09-27): data accumulation must NOT be
# performed inside a leader (Claude) turn — that would spend tokens. This daemon
# is a plain OS process that loops on its own, calls collect_4h.py every 4h, and
# appends the closed candle(s) to the committed trail `market_data_4h.csv`.
# Claude only READS the daemon's output/log/trail when the owner commands a turn.
#
# SAFETY — RESEARCH / PAPER ONLY. collect_4h.py uses a read-only public candle
# endpoint. NO API keys, NO account, NO orders. Nothing here can place a trade.
#
# HOW IT STAYS ALIVE / RESTARTS / LOGS / IDEMPOTENT BACKFILL:
#   * It is launched with `setsid` + `</dev/null` so it detaches from the harness
#     and reparents to PID 1 (the host orchestrator). It therefore keeps running
#     across leader turns and consumes ZERO Claude tokens (verified: ppid=1).
#   * The host has multi-day uptime; the daemon survives every turn boundary.
#   * The loop is crash-resilient: collect_4h.py runs in a subshell; any error is
#     logged and the loop continues to the next 4h tick (never dies on one bad
#     fetch).
#   * A host REBOOT is the only thing that stops it (no system cron here to auto-
#     start). `daemon_4h.sh ensure` re-launches it if (and only if) it is not
#     already running — an idempotent, near-instant liveness check. Because
#     collect_4h.py backfills EVERY 4h candle closed since the last recorded one,
#     any downtime gap is filled automatically on the next run — completeness is
#     guaranteed by the backfill, not by perfect uptime.
#   * Log: logs/collect_4h_daemon.log   PID file: logs/collect_4h_daemon.pid
#
# COMMIT MODEL: the daemon only APPENDS locally (the accumulation itself, token-
# free). Publishing (git commit/push of market_data_4h.csv) is done by the leader
# during a commanded turn — it reads the daemon's accumulated trail and commits
# it. This keeps git history clean (no 6 commits/day) and avoids push races.
#
# USAGE:
#   paper_trading/daemon_4h.sh start     # launch the detached daemon (idempotent)
#   paper_trading/daemon_4h.sh ensure    # launch ONLY if not already running (self-heal)
#   paper_trading/daemon_4h.sh status    # alive? pid, last log lines, trail integrity
#   paper_trading/daemon_4h.sh stop      # stop the daemon
#   paper_trading/daemon_4h.sh restart   # stop + start
#   paper_trading/daemon_4h.sh logs      # tail the daemon log
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
PIDFILE="logs/collect_4h_daemon.pid"
LOG="logs/collect_4h_daemon.log"
STEP=$((4 * 3600))          # 4h candle spacing (seconds)
OFFSET=90                   # wake this many seconds AFTER each 4h boundary
PY="$(command -v python3)"

_is_alive() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # confirm it is really our loop (guard against PID reuse)
  grep -q "daemon_4h" "/proc/$pid/cmdline" 2>/dev/null
}

# The actual loop. Launched detached; not meant to be called by hand.
_loop() {
  echo "$$" > "$PIDFILE"
  trap 'echo "[$(date -u +%FT%TZ)] daemon stopping (signal)"; rm -f "$PIDFILE"; exit 0' TERM INT
  echo "[$(date -u +%FT%TZ)] daemon started pid=$$ ppid=$PPID step=${STEP}s offset=${OFFSET}s"
  # Run once immediately so any downtime gap is backfilled the moment we start.
  while true; do
    echo "[$(date -u +%FT%TZ)] --- collect tick ---"
    if ! ( "$PY" paper_trading/collect_4h.py ); then
      echo "[$(date -u +%FT%TZ)] WARN collect_4h.py exited non-zero; will retry next tick"
    fi
    # Sleep until just after the next 4h boundary (UTC-aligned), + OFFSET.
    now=$(date -u +%s)
    next=$(( ( now / STEP + 1 ) * STEP + OFFSET ))
    sleep_for=$(( next - now ))
    [ "$sleep_for" -lt 30 ] && sleep_for=$(( sleep_for + STEP ))   # guard tiny sleeps
    echo "[$(date -u +%FT%TZ)] sleeping ${sleep_for}s until next tick"
    # `sleep & wait` (not a bare `sleep`) so a TERM/INT trap fires promptly for a
    # clean stop/restart, instead of being deferred until the sleep elapses.
    sleep "$sleep_for" &
    wait $! || true
  done
}

cmd="${1:-status}"
case "$cmd" in
  __loop)                       # internal entry point (invoked by 'start')
    _loop
    ;;
  start|ensure)
    if _is_alive; then
      echo "daemon already running (pid=$(cat "$PIDFILE")) — nothing to do (idempotent)"
      exit 0
    fi
    # Detach: setsid + </dev/null + >>log so it survives the turn, reparents to
    # PID 1, and never re-invokes Claude.
    setsid "$0" __loop </dev/null >>"$LOG" 2>&1 &
    disown 2>/dev/null || true
    sleep 1
    if _is_alive; then
      echo "daemon launched (pid=$(cat "$PIDFILE")); log=$LOG"
    else
      echo "ERROR: daemon failed to start; see $LOG" >&2
      tail -n 20 "$LOG" 2>/dev/null || true
      exit 1
    fi
    ;;
  stop)
    if _is_alive; then
      pid="$(cat "$PIDFILE")"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "daemon stopped (was pid=$pid)"
    else
      echo "daemon not running"
      rm -f "$PIDFILE"
    fi
    ;;
  restart)
    "$0" stop || true
    "$0" start
    ;;
  status)
    if _is_alive; then
      pid="$(cat "$PIDFILE")"
      echo "STATUS: RUNNING  pid=$pid  uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
    else
      echo "STATUS: NOT running"
    fi
    echo "--- last 8 log lines ($LOG) ---"
    tail -n 8 "$LOG" 2>/dev/null || echo "(no log yet)"
    echo "--- trail integrity ---"
    "$PY" paper_trading/collect_4h.py --help >/dev/null 2>&1 || true
    "$PY" - <<'PYEOF'
import sys, os
sys.path.insert(0, "paper_trading")
import collect_4h
rows, dups, ooo, gaps, gl = collect_4h.integrity()
print(f"rows={rows} dups={dups} out_of_order={ooo} gaps={gaps}")
PYEOF
    ;;
  logs)
    tail -n "${2:-40}" "$LOG" 2>/dev/null || echo "(no log yet)"
    ;;
  *)
    echo "usage: $0 {start|ensure|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
