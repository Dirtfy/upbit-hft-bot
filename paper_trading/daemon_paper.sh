#!/usr/bin/env bash
# =============================================================================
# PAPER-TRADING DAEMON — autonomous, Claude-free (owner directive 2026-09-27).
#
# Runs the daily paper-trading cycle (paper_trader.py) once per closed daily
# candle, WITHOUT a leader (Claude) turn. Appends one record per closed daily
# candle to the committed paper record (paper_log.jsonl, JOURNAL.md,
# market_data_daily.csv) and regenerates SUMMARY.md. Runs detached (setsid ->
# reparents to PID 1), so it survives every leader turn and costs ZERO Claude
# tokens. The leader only READS the ledger/log and commits on command.
#
# The "decision" is deterministic strategy code (src/regime.py + bear_strategy.py),
# not an LLM — so this loop needs no Claude. paper_trader.py fetches candles from
# the read-only public API itself (keyless) and is idempotent (only appends
# candles newer than the last recorded), so any cadence / downtime self-heals.
#
# SAFETY — RESEARCH / PAPER ONLY. Paper book = 1,000,000 KRW, mode long_flat
# (defensive). NO keys, NO account, NO live orders. Shared plumbing is in
# daemon_lib.sh; this file is just the daily paper config.
#
# USAGE: paper_trading/daemon_paper.sh {start|ensure|stop|restart|status|logs}
#   ensure = launch ONLY if not already running (idempotent reboot self-heal).
# Optional mode override:  PAPER_MODE=breakout_regime paper_trading/daemon_paper.sh start
# =============================================================================
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
DAEMON_NAME="paper"
DAEMON_DESC="daily paper-trading cycle (read-only public API, 1M KRW, long_flat)"
DAY=86400                   # daily candle spacing (seconds)
OFFSET=300                  # wake 5 min after 00:00 UTC (candle closed by then)
PAPER_MODE="${PAPER_MODE:-long_flat}"

# shellcheck source=paper_trading/daemon_lib.sh
source "$(dirname "$SELF")/daemon_lib.sh"

daemon_tick() {
  local rc
  "$PY" paper_trading/paper_trader.py --mode "$PAPER_MODE"
  rc=$?
  # SHADOW book (owner option B, 2026-10-04): candidate dd 12.5%/5%, own ledger in
  # paper_trading/shadow_exit_book/. Runs AFTER the official tick and can never
  # change its result: a shadow failure is logged and ignored.
  if [ "$PAPER_MODE" = long_flat ]; then
    "$PY" paper_trading/shadow_exit_book/shadow_book.py \
      || echo "shadow_exit_book tick FAILED (official book unaffected)"
  fi
  return $rc
}

daemon_next_sleep() {
  local now next s
  now=$(date -u +%s)
  next=$(( ( now / DAY + 1 ) * DAY + OFFSET ))   # next 00:00 UTC + OFFSET
  s=$(( next - now ))
  [ "$s" -lt 60 ] && s=$(( s + DAY ))            # guard tiny sleeps
  echo "$s"
}

daemon_status_extra() {
  echo "--- paper record (last cycle) ---"
  "$PY" - <<'PYEOF'
import json, os
p = "paper_trading/paper_log.jsonl"
if not os.path.exists(p):
    print("(no paper_log yet)"); raise SystemExit
recs = [json.loads(l) for l in open(p) if l.strip()]
if not recs:
    print("(empty paper_log)"); raise SystemExit
r = recs[-1]
print(f"cycles={len(recs)} last_candle={r['candle_t']} mode={r['mode']} "
      f"regime={r['regime']} action={r['action']} pos={r['position_after']} "
      f"equity={r['equity_krw']:,.0f} KRW cum={r['cum_return_pct']:.2f}%")
PYEOF
  echo "--- shadow book (dd 12.5%/5%) vs official ---"
  "$PY" paper_trading/shadow_exit_book/compare.py 2>&1 | tail -1
}

daemon_main "$@"
