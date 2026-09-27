# =============================================================================
# daemon_lib.sh — shared machinery for autonomous, Claude-free background daemons.
#
# WHY (owner directive 2026-09-27): every "code" artifact — data collection AND
# the trading loop — must run as its own OS process, independent of any leader
# (Claude) turn, so it costs ZERO tokens. Claude only READS a daemon's output/log
# when the owner commands a turn. This library is the reusable pattern so each new
# daemon (4h collector, paper trader, …) is just a thin config on top.
#
# A caller script sources this, sets a few variables / functions, then calls
# `daemon_main "$@"`:
#   DAEMON_NAME        short id -> logs/${DAEMON_NAME}_daemon.{pid,log}
#   DAEMON_DESC        one-line human description (for status/usage)
#   daemon_tick        REQUIRED fn: run one unit of work (idempotent; must not die
#                      the loop — wrap risky bits; non-zero exit is tolerated)
#   daemon_next_sleep  REQUIRED fn: echo seconds to sleep until the next tick
#   daemon_status_extra OPTIONAL fn: print extra status lines (e.g. integrity)
#
# Guarantees provided here: detached launch (setsid, reparents to PID 1, survives
# turns, 0 tokens), crash-resilient loop, prompt stop via `sleep & wait` traps,
# idempotent `ensure` self-heal, PID-reuse-safe liveness check.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
PY="$(command -v python3)"

_dl_pidfile() { echo "logs/${DAEMON_NAME}_daemon.pid"; }
_dl_log()     { echo "logs/${DAEMON_NAME}_daemon.log"; }
_dl_self()    { echo "$SELF"; }              # caller sets SELF="$0"
_dl_tag()     { basename "$SELF"; }          # cmdline marker for PID-reuse guard

_dl_is_alive() {
  local pidfile; pidfile="$(_dl_pidfile)"
  [ -f "$pidfile" ] || return 1
  local pid; pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # confirm it is really OUR loop (guard against PID reuse)
  grep -q "$(_dl_tag)" "/proc/$pid/cmdline" 2>/dev/null
}

_dl_loop() {
  local pidfile; pidfile="$(_dl_pidfile)"
  echo "$$" > "$pidfile"
  trap 'echo "[$(date -u +%FT%TZ)] daemon stopping (signal)"; rm -f "'"$pidfile"'"; exit 0' TERM INT
  echo "[$(date -u +%FT%TZ)] daemon started pid=$$ ppid=$PPID name=${DAEMON_NAME}"
  # First tick runs immediately so any downtime gap is backfilled on start.
  while true; do
    echo "[$(date -u +%FT%TZ)] --- ${DAEMON_NAME} tick ---"
    if ! ( daemon_tick ); then
      echo "[$(date -u +%FT%TZ)] WARN ${DAEMON_NAME} tick exited non-zero; will retry next tick"
    fi
    local sleep_for; sleep_for="$(daemon_next_sleep)"
    echo "[$(date -u +%FT%TZ)] sleeping ${sleep_for}s until next tick"
    # `sleep & wait` (not a bare sleep) so a TERM/INT trap fires promptly.
    sleep "$sleep_for" &
    wait $! || true
  done
}

daemon_main() {
  local pidfile log; pidfile="$(_dl_pidfile)"; log="$(_dl_log)"
  local cmd="${1:-status}"
  case "$cmd" in
    __loop)
      _dl_loop
      ;;
    start|ensure)
      if _dl_is_alive; then
        echo "${DAEMON_NAME} daemon already running (pid=$(cat "$pidfile")) — nothing to do (idempotent)"
        return 0
      fi
      setsid "$SELF" __loop </dev/null >>"$log" 2>&1 &
      disown 2>/dev/null || true
      sleep 1
      if _dl_is_alive; then
        echo "${DAEMON_NAME} daemon launched (pid=$(cat "$pidfile")); log=$log"
      else
        echo "ERROR: ${DAEMON_NAME} daemon failed to start; see $log" >&2
        tail -n 20 "$log" 2>/dev/null || true
        return 1
      fi
      ;;
    stop)
      if _dl_is_alive; then
        local pid; pid="$(cat "$pidfile")"
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        rm -f "$pidfile"
        echo "${DAEMON_NAME} daemon stopped (was pid=$pid)"
      else
        echo "${DAEMON_NAME} daemon not running"
        rm -f "$pidfile"
      fi
      ;;
    restart)
      "$SELF" stop || true
      "$SELF" start
      ;;
    status)
      if _dl_is_alive; then
        local pid; pid="$(cat "$pidfile")"
        echo "STATUS: RUNNING  pid=$pid  uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
      else
        echo "STATUS: NOT running"
      fi
      echo "--- last 8 log lines ($log) ---"
      tail -n 8 "$log" 2>/dev/null || echo "(no log yet)"
      if declare -f daemon_status_extra >/dev/null; then
        daemon_status_extra
      fi
      ;;
    logs)
      tail -n "${2:-40}" "$log" 2>/dev/null || echo "(no log yet)"
      ;;
    *)
      echo "usage: $SELF {start|ensure|stop|restart|status|logs}   # ${DAEMON_DESC:-}" >&2
      return 2
      ;;
  esac
}
