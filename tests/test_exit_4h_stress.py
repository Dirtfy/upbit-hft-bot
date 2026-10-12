#!/usr/bin/env python3
"""Cycle 39: the 4h stress replay reproduces the daily backtest when filled at
the daily open (k=0), later fill hours fill later, the 4h-checked breaker runs,
and the live config is unchanged. Synthetic data (daily bars built from 4h)."""
import math
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import config                 # noqa: E402
import bear_strategy as bs    # noqa: E402
import exit_4h_stress as st   # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


t0, px, h4 = datetime(2019, 1, 1), 10_000_000.0, []
for i in range(1500 * 6):
    o = px
    px *= 1 + 0.0012 * math.sin(i / 300) + 0.004 * math.sin(i * 1.7)
    h4.append({"t": (t0 + timedelta(hours=4 * i)).strftime(st.FMT), "open": o,
               "high": max(o, px) * 1.002, "low": min(o, px) * 0.998, "close": px})
dbars = []
for d in range(1500):
    seg = h4[d * 6:(d + 1) * 6]
    dbars.append({"t": seg[0]["t"], "open": seg[0]["open"], "high": max(b["high"] for b in seg),
                  "low": min(b["low"] for b in seg), "close": seg[-1]["close"]})

p = st._params(0.125, 0.05)
eq_d, _, tr_d = bs.replay(dbars, p, "long_flat", 1_000_000.0)
eq0, tr0 = st.simulate(h4, st.daily_switches(dbars, p, 0))
check("fill +0h on the 4h path == daily backtest (final equity, trades)",
      abs(eq0[-1] - eq_d[-1]) < 1e-3 and len(tr0) == len(tr_d) and len(tr_d) > 0)
sw0, sw3 = st.daily_switches(dbars, p, 0), st.daily_switches(dbars, p, 3)
check("fill +12h = same decisions, 12h later",
      [s[1] for s in sw0] == [s[1] for s in sw3]
      and all(datetime.strptime(b[0], st.FMT) - datetime.strptime(a[0], st.FMT) == timedelta(hours=12)
              for a, b in zip(sw0, sw3)))
swi = st.intraday_switches(dbars, h4, p)
check("4h-checked breaker reacts at least as often as the daily rule", len(swi) >= len(sw0) > 0)
rows = st.run(dbars, h4)
check("7 tests x 2 configs, 4h maxDD >= day-end maxDD",
      len(rows) == 14 and all(r["mdd_4h"] >= r["mdd"] - 1e-12 for r in rows))
check("live config unchanged (proposal, not a switch)",
      (config.BEAR["dd_enter"], config.BEAR["dd_exit"]) == (0.20, 0.10))

ok = all(c for _, c in checks)
print(f"\n{sum(c for _, c in checks)}/{len(checks)} passed")
sys.exit(0 if ok else 1)
