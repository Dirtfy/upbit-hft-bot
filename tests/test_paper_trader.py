#!/usr/bin/env python3
"""Tests for the official paper-trading logger (paper_trading/paper_trader.py).

Protects the committed, month-long paper record from silent regressions: account
transitions (BUY/SELL/HOLD), P&L accounting, idempotency, the mode-consistency
guard, and the SUMMARY rollup. No network, no keys — le.fetch_closed_daily is
monkeypatched with a synthetic candle series and outputs go to a temp dir.

Plain asserts (no pytest): run with `python3 tests/test_paper_trader.py`.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
import live_engine as le                          # noqa: E402
import paper_trading.paper_trader as pt           # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def synthetic_bars():
    """A long steady uptrend (-> bull, triggers entry) then a deep crash
    (-> bear, triggers the protective exit). ~520 daily bars > 365 warmup."""
    closes = [1_000_000 + i * 10_000 for i in range(400)]      # uptrend
    closes += [closes[-1] * (1 - 0.03 * j) for j in range(1, 121)]  # crash
    base = datetime(2019, 1, 1)
    return [{"t": (base + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00"),
             "open": c, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]


def _point_paths(tmp):
    pt.JSONL_PATH = os.path.join(tmp, "paper_log.jsonl")
    pt.JOURNAL_PATH = os.path.join(tmp, "JOURNAL.md")
    pt.SUMMARY_PATH = os.path.join(tmp, "SUMMARY.md")
    pt.DATA_PATH = os.path.join(tmp, "market_data_daily.csv")


def _records():
    return [json.loads(l) for l in open(pt.JSONL_PATH) if l.strip()]


bars = synthetic_bars()
le.fetch_closed_daily = lambda client, count=600: bars

# ---- full replay from a mid-series anchor: enter uptrend, exit before crash ----
tmp = tempfile.mkdtemp()
_point_paths(tmp)
seed = {"cycle": 0, "candle_t": bars[250]["t"], "mode": "long_flat",
        "cash_krw": 1_000_000.0, "btc_qty": 0.0, "entry_price": None,
        "realized_cum_krw": 0.0, "equity_krw": 1_000_000.0}
open(pt.JSONL_PATH, "w").write(json.dumps(seed) + "\n")

appended = pt.process("long_flat")
recs = _records()[1:]   # drop the seed
buys = [r for r in recs if r["action"] == "BUY"]
sells = [r for r in recs if r["action"] == "SELL"]

check("replayed the new candles", appended == len(bars) - 251)
check("entered exactly once (BUY)", len(buys) == 1)
check("exited exactly once (SELL)", len(sells) == 1)
check("BUY precedes SELL", buys[0]["cycle"] < sells[0]["cycle"])
check("position is LONG after the entry", buys[0]["position_after"] == "LONG")
check("position is FLAT after the exit", sells[0]["position_after"] == "FLAT")
check("protective exit locked in a positive realized pnl",
      sells[0]["realized_cum_krw"] > 0)
check("no position re-opened after the crash exit",
      recs[-1]["position_after"] == "FLAT")

# equity accounting identity: equity == cash + btc*close on the last record
lastb = bars[-1]["close"]
r = recs[-1]
check("equity == cash + btc*close (mark-to-market identity)",
      abs(r["equity_krw"] - (r["cash_krw"] + r["btc_qty"] * lastb)) < 1e-6)
check("cum_pnl == equity - start_capital",
      abs(r["cum_pnl_krw"] - (r["equity_krw"] - 1_000_000.0)) < 1e-6)

# ---- idempotency: a second run appends nothing ----
before = len(_records())
again = pt.process("long_flat")
check("re-run is idempotent (appends 0)", again == 0 and len(_records()) == before)

# ---- mode-consistency guard: refuse a different mode on an existing record ----
switched = pt.process("breakout_regime")
check("refuses to continue an existing record under a different mode",
      switched == 0 and len(_records()) == before)

# ---- SUMMARY.md rollup ----
pt.write_summary()
check("SUMMARY.md written", os.path.exists(pt.SUMMARY_PATH))
summary = open(pt.SUMMARY_PATH).read()
check("SUMMARY names current position and cumulative return",
      "현재 포지션" in summary and "누적 손익" in summary)
check("SUMMARY reports a max-drawdown figure", "최대낙폭(MDD)" in summary)

# ---- fresh-start anchor: no prior record -> only the newest candle logged ----
tmp2 = tempfile.mkdtemp()
_point_paths(tmp2)
fresh = pt.process("long_flat")
check("fresh start logs exactly one cycle (anchor, no backfill)", fresh == 1)
check("fresh start begins at the latest closed candle",
      _records()[-1]["candle_t"] == bars[-1]["t"])

# ---- summary -------------------------------------------------------------
failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
