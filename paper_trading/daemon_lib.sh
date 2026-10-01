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
# idempotent `ensure` self-heal, PID-reuse-safe liveness check, and outage
# detection: the loop writes a heartbeat every HEARTBEAT_SECS while sleeping, so
# when `ensure` finds a dead daemon whose pidfile is still there (= killed without
# a clean stop, e.g. a container restart SIGKILLs everything) it records the
# outage window to logs/daemon_outages.log instead of silently relaunching.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
PY="$(command -v python3)"
HEARTBEAT_SECS="${HEARTBEAT_SECS:-300}"
OUTAGE_LOG="logs/daemon_outages.log"

_dl_pidfile() { echo "logs/${DAEMON_NAME}_daemon.pid"; }
_dl_log()     { echo "logs/${DAEMON_NAME}_daemon.log"; }
_dl_hbfile()  { echo "logs/${DAEMON_NAME}_daemon.heartbeat"; }
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

_dl_beat() { date -u +%s > "$(_dl_hbfile)"; }

# Called by start/ensure when the daemon is NOT alive. A pidfile left behind means
# the previous loop died without its TERM/INT trap running (SIGKILL / host or
# container restart): record when it was last seen alive and how long it was down.
_dl_record_outage() {
  local pidfile hb now last down line
  pidfile="$(_dl_pidfile)"
  [ -f "$pidfile" ] || return 0
  now=$(date -u +%s)
  last="$(cat "$(_dl_hbfile)" 2>/dev/null || true)"
  if [ -n "${last:-}" ]; then
    down=$(( now - last ))
    line="$(date -u +%FT%TZ) ${DAEMON_NAME} UNCLEAN_EXIT pid=$(cat "$pidfile" 2>/dev/null) last_heartbeat=$(date -u -d "@$last" +%FT%TZ) down_at_most=${down}s (~$(( down / 60 ))min)"
  else
    line="$(date -u +%FT%TZ) ${DAEMON_NAME} UNCLEAN_EXIT pid=$(cat "$pidfile" 2>/dev/null) last_heartbeat=unknown"
  fi
  echo "$line" >> "$OUTAGE_LOG"
  echo "[$(date -u +%FT%TZ)] OUTAGE detected on relaunch: $line" >> "$(_dl_log)"
  echo "OUTAGE: $line"
  rm -f "$pidfile"
}

_dl_loop() {
  local pidfile; pidfile="$(_dl_pidfile)"
  echo "$$" > "$pidfile"
  trap 'echo "[$(date -u +%FT%TZ)] daemon stopping (signal)"; rm -f "'"$pidfile"'"; exit 0' TERM INT
  echo "[$(date -u +%FT%TZ)] daemon started pid=$$ ppid=$PPID name=${DAEMON_NAME}"
  _dl_beat
  # First tick runs immediately so any downtime gap is backfilled on start.
  while true; do
    echo "[$(date -u +%FT%TZ)] --- ${DAEMON_NAME} tick ---"
    if ! ( daemon_tick ); then
      echo "[$(date -u +%FT%TZ)] WARN ${DAEMON_NAME} tick exited non-zero; will retry next tick"
    fi
    local sleep_for; sleep_for="$(daemon_next_sleep)"
    echo "[$(date -u +%FT%TZ)] sleeping ${sleep_for}s until next tick"
    # Sleep in HEARTBEAT_SECS chunks, stamping a heartbeat after each, so an
    # unclean death can later be dated to within one chunk. `sleep & wait` (not a
    # bare sleep) so a TERM/INT trap fires promptly.
    local left=$sleep_for chunk
    while [ "$left" -gt 0 ]; do
      chunk=$(( left < HEARTBEAT_SECS ? left : HEARTBEAT_SECS ))
      sleep "$chunk" &
      wait $! || true
      left=$(( left - chunk ))
      _dl_beat
    done
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
      _dl_record_outage
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
        local hb; hb="$(cat "$(_dl_hbfile)" 2>/dev/null || echo "")"
        echo "STATUS: RUNNING  pid=$pid  uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')  heartbeat_age=$([ -n "$hb" ] && echo "$(( $(date -u +%s) - hb ))s" || echo n/a)"
      else
        echo "STATUS: NOT running"
      fi
      echo "--- recorded outages ($OUTAGE_LOG): $(cat "$OUTAGE_LOG" 2>/dev/null | grep -c " ${DAEMON_NAME} UNCLEAN_EXIT" || true) ---"
      grep " ${DAEMON_NAME} UNCLEAN_EXIT" "$OUTAGE_LOG" 2>/dev/null | tail -n 3 || true
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
