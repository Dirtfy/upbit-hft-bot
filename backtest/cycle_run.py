#!/usr/bin/env python3
"""One research cycle: test the TREND-FILTER hypothesis (cycle 1).

Hypothesis: only buying dips when price is above a long SMA (dips within
uptrends) removes the large losers from dip-buying into downtrends, improving
OOS return and profit factor vs. the no-filter baseline.

Evaluated on the out-of-sample window (bars before the original 14-day set).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_maker as bm  # noqa
import config  # noqa

rows = [r for r in bm.load("../data/krw_btc_1m_long.csv")
        if r["t"] < "2026-08-23T17:59:00"]
print(f"OOS: {rows[0]['t']} -> {rows[-1]['t']} ({len(rows)} bars, "
      f"{len(rows)/1440:.1f} days)\n")

base = dict(config.STRAT)
variants = [("baseline (no filter)", 0), ("SMA 240 (4h)", 240),
            ("SMA 480 (8h)", 480), ("SMA 720 (12h)", 720),
            ("SMA 1440 (24h)", 1440)]

print(f"{'variant':<22} {'trades':>6} {'win%':>6} {'PF':>5} "
      f"{'ret%':>7} {'avgWin':>7} {'avgLoss':>8} {'maxDD%':>6}")
results = []
for name, tw in variants:
    p = dict(base, trend_window=tw)
    r = bm.run(rows, p)
    results.append((name, tw, r))
    print(f"{name:<22} {r['trades']:>6} {r['win_rate']*100:>5.1f} "
          f"{r['profit_factor']:>5.2f} {r['return_pct']:>7.2f} "
          f"{r['avg_win']:>7.0f} {r['avg_loss']:>8.0f} {r['max_dd_pct']:>6.2f}")

bh = results[0][2]["buyhold_pct"]
print(f"\nbuy&hold over window: {bh:+.2f}%")
best = max(results, key=lambda x: x[2]["return_pct"])
print(f"best by OOS return: {best[0]}  ret={best[2]['return_pct']:+.2f}%  "
      f"PF={best[2]['profit_factor']:.2f}  trades={best[2]['trades']}")
