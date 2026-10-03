#!/usr/bin/env python3
"""Cycle 29: the exit sweep runs, the live dd_enter/dd_exit row reproduces the
live config exactly, a tighter drawdown breaker exits no later, and the live
config is unchanged (the sweep is a proposal, not a switch). Synthetic data."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import config                # noqa: E402
import bear_strategy as bs   # noqa: E402
import exit_sweep as sw      # noqa: E402
import regime as rg          # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


# ~4 years spanning both halves: a rally then a -30% slide, repeated
bars, px = [], 10_000_000.0
for i in range(1500):
    px *= 1 + 0.003 * math.sin(i / 60) + 0.008 * math.sin(i * 1.7)
    d = f"{2019 + i // 365}-{(i % 365) // 31 + 1:02d}-{(i % 31) + 1:02d}T00:00:00"
    bars.append({"t": d, "open": px, "high": px * 1.01, "low": px * 0.99, "close": px})

res = sw.sweep(bars, dd_enter=(0.10, 0.20), dd_exit=(0.05, 0.10))
live = [r for r in res if r["live"]]
eq0, _, tr0 = bs.replay(bars, dict(config.BEAR), "long_flat", 1_000_000.0)
check("exactly one LIVE row and it equals the live-config replay",
      len(live) == 1 and live[0]["trades"] == len(tr0)
      and abs(live[0]["final"] - eq0[-1]) < 1e-6 and not live[0]["robust"])
check("pairs with dd_exit >= dd_enter are skipped",
      all(r["dd_exit"] < r["dd_enter"] for r in res) and len(res) == 3)
crash, px = [], 10_000_000.0                   # 300d steady rally, then -1%/day
for i in range(400):
    px *= 1.005 if i < 300 else 0.99
    crash.append({"t": f"2020-01-01T{i:05d}", "close": px})
first_bear = [next(i for i, r in enumerate(rg.compute_regimes(crash, q)) if i >= 300 and r == "bear")
              for q in (dict(config.BEAR, dd_enter=0.125, dd_exit=0.05), config.BEAR)]
check("a tighter breaker turns bear earlier in a crash (12.5% vs 20% off the high)",
      first_bear[0] < first_bear[1])
check("live config unchanged (exit sweep is a proposal pending owner approval)",
      (config.BEAR["dd_enter"], config.BEAR["dd_exit"]) == (0.20, 0.10))

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
