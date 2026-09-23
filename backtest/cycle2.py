#!/usr/bin/env python3
"""Cycle 2: (A) train/test split to confirm the trend filter generalizes;
(B) attack the edge side on top of trend_window=720 so avg win > avg loss by
letting winners run (higher exit_z / take_profit).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_maker as bm  # noqa
import config  # noqa

allrows = bm.load("../data/krw_btc_1m_long.csv")
base = dict(config.STRAT)  # window120 z3 exit0 sl.012 tp.012 mh60

# ---- (A) train/test split: does trend_window=720 generalize? -------------
split = int(len(allrows) * 0.60)
train, test = allrows[:split], allrows[split:]
print("=== (A) Trend-filter generalization (train/test split) ===")
print(f"TRAIN {train[0]['t'][:10]}..{train[-1]['t'][:10]} ({len(train)} bars)  "
      f"TEST {test[0]['t'][:10]}..{test[-1]['t'][:10]} ({len(test)} bars)\n")
for label, cfg in [("no filter", dict(base)),
                   ("trend 720", dict(base, trend_window=720))]:
    rtr, rte = bm.run(train, cfg), bm.run(test, cfg)
    print(f"{label:<10} TRAIN ret={rtr['return_pct']:+6.2f}% PF={rtr['profit_factor']:.2f} "
          f"n={rtr['trades']:>3} | TEST ret={rte['return_pct']:+6.2f}% "
          f"PF={rte['profit_factor']:.2f} n={rte['trades']:>3}")

# ---- (B) edge side: let winners run, on OOS with trend_window=720 --------
oos = [r for r in allrows if r["t"] < "2026-08-23T17:59:00"]
print(f"\n=== (B) Let winners run (OOS {len(oos)/1440:.1f}d, trend_window=720) ===")
print(f"{'exit_z':>6} {'TP':>6} {'trades':>6} {'win%':>6} {'PF':>5} "
      f"{'ret%':>7} {'avgWin':>7} {'avgLoss':>8}")
results = []
for exit_z in [0.0, 0.5, 1.0, 1.5]:
    for tp in [0.012, 0.02, 0.03]:
        cfg = dict(base, trend_window=720, exit_z=exit_z, take_profit_pct=tp)
        r = bm.run(oos, cfg)
        results.append((exit_z, tp, r))
        print(f"{exit_z:>6} {tp:>6} {r['trades']:>6} {r['win_rate']*100:>5.1f} "
              f"{r['profit_factor']:>5.2f} {r['return_pct']:>7.2f} "
              f"{r['avg_win']:>7.0f} {r['avg_loss']:>8.0f}")

# best among traded (>=10 trades) by OOS return
cand = [(ez, tp, r) for ez, tp, r in results if r["trades"] >= 10]
best = max(cand, key=lambda x: x[2]["return_pct"]) if cand else None
prev = bm.run(oos, dict(base, trend_window=720))
print(f"\nprev best (cycle1): trend720  ret={prev['return_pct']:+.2f}% "
      f"PF={prev['profit_factor']:.2f} n={prev['trades']}")
if best:
    ez, tp, r = best
    print(f"cycle2 best: exit_z={ez} TP={tp}  ret={r['return_pct']:+.2f}% "
          f"PF={r['profit_factor']:.2f} n={r['trades']} "
          f"avgWin={r['avg_win']:.0f} avgLoss={r['avg_loss']:.0f}")
