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
#
# Shared workspace, several containers (Cycle 27): the same checkout is mounted
# in more than one container, each with its own PID namespace, so a bare PID in
# the pidfile is meaningless to the other side (it always looked "dead", which
# produced false outages and duplicate daemons). The pidfile therefore records
# "<host>/<pidns>:<pid>". A loop owned by THIS namespace is checked with kill -0;
# one owned by another namespace counts as alive while the shared heartbeat is
# fresh. A loop exits by itself as soon as the pidfile no longer names it, so
# `stop` works across namespaces and a racing duplicate retires itself.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
PY="$(command -v python3)"
HEARTBEAT_SECS="${HEARTBEAT_SECS:-300}"
HEARTBEAT_GRACE="${HEARTBEAT_GRACE:-120}"    # slack on top of one chunk (tick time)
OUTAGE_LOG="logs/daemon_outages.log"

_dl_pidfile() { echo "logs/${DAEMON_NAME}_daemon.pid"; }
_dl_log()     { echo "logs/${DAEMON_NAME}_daemon.log"; }
_dl_hbfile()  { echo "logs/${DAEMON_NAME}_daemon.heartbeat"; }
_dl_self()    { echo "$SELF"; }              # caller sets SELF="$0"
_dl_tag()     { basename "$SELF"; }          # cmdline marker for PID-reuse guard

_dl_ns()    { echo "$(hostname)/$(readlink /proc/self/ns/pid 2>/dev/null | tr -dc '0-9')"; }
_dl_owner() { cat "$(_dl_pidfile)" 2>/dev/null || true; }

# PID of the recorded loop if it lives in THIS namespace (legacy bare PIDs are
# treated as local candidates), else empty.
_dl_local_pid() {
  local tok; tok="$(_dl_owner)"
  case "$tok" in
    "$(_dl_ns):"*) echo "${tok##*:}" ;;
    *:*)           ;;
    *)             echo "$tok" ;;
  esac
}

_dl_local_alive() {
  local pid; pid="$(_dl_local_pid)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # confirm it is really OUR loop (guard against PID reuse)
  grep -q "$(_dl_tag)" "/proc/$pid/cmdline" 2>/dev/null
}

_dl_hb_age() {
  local hb; hb="$(cat "$(_dl_hbfile)" 2>/dev/null || true)"
  [ -n "${hb:-}" ] && echo $(( $(date -u +%s) - hb )) || echo 999999999
}

_dl_is_alive() {
  local tok; tok="$(_dl_owner)"
  [ -n "${tok:-}" ] || return 1
  case "$tok" in
    "$(_dl_ns):"*) _dl_local_alive ;;
    *:*)           [ "$(_dl_hb_age)" -le $(( HEARTBEAT_SECS + HEARTBEAT_GRACE )) ] ;;
    *)             _dl_local_alive || \
                   [ "$(_dl_hb_age)" -le $(( HEARTBEAT_SECS + HEARTBEAT_GRACE )) ] ;;
  esac
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
    line="$(date -u +%FT%TZ) ${DAEMON_NAME} UNCLEAN_EXIT owner=$(_dl_owner) last_heartbeat=$(date -u -d "@$last" +%FT%TZ) down_at_most=${down}s (~$(( down / 60 ))min)"
  else
    line="$(date -u +%FT%TZ) ${DAEMON_NAME} UNCLEAN_EXIT owner=$(_dl_owner) last_heartbeat=unknown"
  fi
  echo "$line" >> "$OUTAGE_LOG"
  echo "[$(date -u +%FT%TZ)] OUTAGE detected on relaunch: $line" >> "$(_dl_log)"
  echo "OUTAGE: $line"
  rm -f "$pidfile"
}

_dl_loop() {
  local pidfile me; pidfile="$(_dl_pidfile)"; me="$(_dl_ns):$$"
  echo "$me" > "$pidfile"
  # only remove the pidfile if it still names this loop (never a successor's)
  trap 'echo "[$(date -u +%FT%TZ)] daemon stopping (signal)"; [ "$(_dl_owner)" = "'"$me"'" ] && rm -f "'"$pidfile"'"; exit 0' TERM INT
  echo "[$(date -u +%FT%TZ)] daemon started pid=$$ ppid=$PPID owner=$me name=${DAEMON_NAME}"
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
      if [ "$(_dl_owner)" != "$me" ]; then
        echo "[$(date -u +%FT%TZ)] superseded (pidfile now '$(_dl_owner)'); this loop ($me) exits"
        exit 0
      fi
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
        echo "${DAEMON_NAME} daemon already running (owner=$(_dl_owner), heartbeat $(_dl_hb_age)s ago) — nothing to do (idempotent)"
        return 0
      fi
      _dl_record_outage
      setsid "$SELF" __loop </dev/null >>"$log" 2>&1 &
      disown 2>/dev/null || true
      sleep 1
      if _dl_is_alive; then
        echo "${DAEMON_NAME} daemon launched (owner=$(_dl_owner)); log=$log"
      else
        echo "ERROR: ${DAEMON_NAME} daemon failed to start; see $log" >&2
        tail -n 20 "$log" 2>/dev/null || true
        return 1
      fi
      ;;
    stop)
      if _dl_local_alive; then
        local pid; pid="$(_dl_local_pid)"
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        rm -f "$pidfile"
        echo "${DAEMON_NAME} daemon stopped (was pid=$pid)"
      elif _dl_is_alive; then
        # owned by another namespace: we cannot signal it, but removing the
        # pidfile makes it retire itself at its next heartbeat check
        echo "${DAEMON_NAME} daemon is owned by $(_dl_owner) (another namespace);" \
             "pidfile removed — it exits within ${HEARTBEAT_SECS}s"
        rm -f "$pidfile"
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
        local pid; pid="$(_dl_local_pid)"
        echo "STATUS: RUNNING  owner=$(_dl_owner)$(_dl_local_alive && echo "  uptime=$(ps -o etime= -p "$pid" | tr -d ' ')" || echo "  (other namespace)")  heartbeat_age=$(_dl_hb_age)s"
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
