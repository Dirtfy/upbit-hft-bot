#!/usr/bin/env python3
"""Cycle 37: the cross-coin exit check resamples 1h -> UTC-day OHLC correctly
(drops the forming last day and sparse days), its live row equals the plain
live-config replay, and the live config is unchanged. Synthetic data."""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import config                # noqa: E402
import bear_strategy as bs   # noqa: E402
import exit_cross_coin as xc  # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "KRW-TEST.csv")
with open(path, "w") as f:
    f.write("time_utc,open,high,low,close,volume\n")
    # day 1: full 24h, day 2: only 5h (sparse), day 3: full, day 4: 3h (forming)
    for day, hours in ((1, 24), (2, 5), (3, 24), (4, 3)):
        for h in range(hours):
            px = day * 100 + h
            f.write(f"2024-01-{day:02d}T{h:02d}:00:00,{px},{px + 0.5},{px - 0.5},{px + 0.25},1\n")
d = xc.daily_from_1h(path)
check("forming last day and sparse day dropped", [b["t"][:10] for b in d] == ["2024-01-01", "2024-01-03"])
b = d[0]
check("daily OHLC = first open / max high / min low / last close",
      (b["open"], b["high"], b["low"], b["close"]) == (100, 123.5, 99.5, 123.25))

bars, px = [], 10_000_000.0
for i in range(1500):
    px *= 1 + 0.003 * math.sin(i / 60) + 0.008 * math.sin(i * 1.7)
    d = f"{2019 + i // 365}-{(i % 365) // 31 + 1:02d}-{(i % 31) + 1:02d}T00:00:00"
    bars.append({"t": d, "open": px, "high": px * 1.01, "low": px * 0.99, "close": px})
r = xc.coin_report(bars)
eq0, _, tr0 = bs.replay(bars, dict(config.BEAR), "long_flat", 1_000_000.0)
check("live row equals the live-config replay",
      abs(r["base"]["final"] - eq0[-1]) < 1e-6 and r["base"]["trades"] == len(tr0))
check("plateau is the Cycle 29 region (6 x 3)", r["plateau_n"] == 18)
check("live config unchanged (proposal, not a switch)",
      (config.BEAR["dd_enter"], config.BEAR["dd_exit"]) == (0.20, 0.10))

ok = all(c for _, c in checks)
print(f"\n{sum(c for _, c in checks)}/{len(checks)} passed")
sys.exit(0 if ok else 1)
