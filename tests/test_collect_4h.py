#!/usr/bin/env python3
"""Tests for the 4h candle accumulator (paper_trading/collect_4h.py).

Covers bootstrap, idempotency, gap-free backfill of a multi-candle window, and
integrity detection (dups / out-of-order / 4h gaps). No network/keys —
fetch_closed_4h is monkeypatched with a synthetic contiguous 4h series and the
committed trail goes to a temp file.

Plain asserts (no pytest): run with `python3 tests/test_collect_4h.py`.
"""
import csv
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import paper_trading.collect_4h as c4           # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def make_bars(n, start=datetime(2026, 1, 1)):
    """n contiguous CLOSED 4h bars (already ex-forming)."""
    out = []
    for i in range(n):
        t = (start + timedelta(hours=4 * i)).strftime("%Y-%m-%dT%H:%M:%S")
        out.append({"t": t, "open": 100 + i, "high": 101 + i, "low": 99 + i,
                    "close": 100 + i, "volume": 1.0 + i})
    return out


tmp = tempfile.mkdtemp()
c4.TRAIL_PATH = os.path.join(tmp, "market_data_4h.csv")

bars = make_bars(50)
c4.fetch_closed_4h = lambda client, count=200: bars

# ---- first run bootstraps the trailing N ----
n = c4.collect(bootstrap=10)
check("bootstrap appends exactly N", n == 10)
rows, dups, ooo, gaps, _ = c4.integrity()
check("bootstrap trail has N rows", rows == 10)
check("bootstrap trail is gap-free / clean", dups == 0 and ooo == 0 and gaps == 0)

# ---- idempotent: nothing new ----
n2 = c4.collect(bootstrap=10)
check("re-run appends 0 (idempotent)", n2 == 0)
check("row count unchanged after re-run", c4.integrity()[0] == 10)

# ---- backfill a multi-candle window (a day passes = +6 4h candles) ----
bars2 = make_bars(56)                            # 6 more contiguous candles
c4.fetch_closed_4h = lambda client, count=200: bars2
n3 = c4.collect(bootstrap=10)
check("backfills all newly-closed candles since last run", n3 == 6)
rows, dups, ooo, gaps, _ = c4.integrity()
check("trail still contiguous after backfill (gaps=0)", gaps == 0)
check("trail grew to 16 rows", rows == 16)
check("no dups / out-of-order after backfill", dups == 0 and ooo == 0)

# ---- integrity DETECTS a genuine gap ----
gap_trail = os.path.join(tmp, "gap.csv")
c4.TRAIL_PATH = gap_trail
with open(gap_trail, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(c4.HEADER)
    w.writerow(["2026-02-01T00:00:00", 1, 1, 1, 1, 1])
    w.writerow(["2026-02-01T04:00:00", 1, 1, 1, 1, 1])
    w.writerow(["2026-02-01T16:00:00", 1, 1, 1, 1, 1])   # skipped 08:00 & 12:00
rows, dups, ooo, gaps, gap_list = c4.integrity()
check("integrity reports the 2 missing candles as gaps", gaps == 2)
check("integrity lists the gap location", len(gap_list) == 1)

# ---- summary -------------------------------------------------------------
failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
