#!/usr/bin/env python3
"""Cycle 28: the band sweep runs, band=0 reproduces the live config exactly, and
a band never weakens the bear-window defence. Synthetic data (no files/network)."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import config                # noqa: E402
import bear_strategy as bs   # noqa: E402
import band_sweep as sw      # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


# ~3 years of a noisy up/down cycle around a trend so the SMA gets crossed often
bars, px = [], 10_000_000.0
for i in range(1100):
    px *= 1 + 0.004 * math.sin(i / 40) + 0.01 * math.sin(i * 1.7)
    d = f"{2018 + i // 365}-{(i % 365) // 31 + 1:02d}-{(i % 31) + 1:02d}T00:00:00"
    bars.append({"t": d, "open": px, "high": px * 1.01, "low": px * 0.99, "close": px})

res = sw.sweep(bars, bands=(0.0, 0.02, 0.05))
eq0, _, tr0 = bs.replay(bars, dict(config.BEAR), "long_flat", 1_000_000.0)
check("band=0 row equals the live-config replay", res[0]["trades"] == len(tr0)
      and abs(res[0]["final"] - eq0[-1]) < 1e-6)
check("wider band never trades more than a plain cross",
      res[2]["trades"] <= res[1]["trades"] <= res[0]["trades"])
check("live config still has band=0 (sweep result: no robust gain)",
      config.BEAR["band"] == 0.0)

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
