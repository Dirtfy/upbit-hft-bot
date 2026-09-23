#!/usr/bin/env python3
"""Walk-forward validation of the maker strategy: optimize on TRAIN, judge on
an untouched TEST holdout. This is the honest test for whether any parameter
set has a real (non-curve-fit) edge after fees.

Split: first 60% of the 83-day series = TRAIN, last 40% = TEST.
Rank TRAIN configs by profit factor (require >=30 trades), then report how the
top TRAIN configs actually do on TEST.
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_maker as bm  # noqa: E402

rows = bm.load("../data/krw_btc_1m_long.csv")
split = int(len(rows) * 0.60)
train, test = rows[:split], rows[split:]
print(f"TRAIN {train[0]['t']} -> {train[-1]['t']} ({len(train)} bars)")
print(f"TEST  {test[0]['t']} -> {test[-1]['t']} ({len(test)} bars)\n")

grid = itertools.product(
    [60, 90, 120, 180],       # window
    [2.5, 3.0, 3.5, 4.0],     # entry_z
    [0.008, 0.012, 0.02],     # stop_loss
    [0.008, 0.012, 0.02],     # take_profit
    [30, 60, 120],            # max_hold
    [0.0, -0.5],              # exit_z (0 = mean; -0.5 = exit a bit before mean)
)
train_results = []
for w, ez, sl, tp, mh, xz in grid:
    p = dict(window=w, entry_z=ez, exit_z=xz, stop_loss_pct=sl,
             take_profit_pct=tp, max_hold=mh, min_std_bps=5.0)
    r = bm.run(train, p)
    if r["trades"] >= 30:
        train_results.append((p, r))

train_results.sort(key=lambda x: x[1]["profit_factor"], reverse=True)
print(f"{len(train_results)} configs with >=30 TRAIN trades. "
      f"Top 8 by TRAIN profit factor, with their TEST result:\n")
print(f"{'W':>3} {'eZ':>3} {'SL':>5} {'TP':>5} {'MH':>3} {'xZ':>4} | "
      f"{'TRAIN pf/ret%/n':>22} | {'TEST pf/ret%/n':>22}")
for p, r in train_results[:8]:
    rt = bm.run(test, p)
    print(f"{p['window']:>3} {p['entry_z']:>3} {p['stop_loss_pct']:>5} "
          f"{p['take_profit_pct']:>5} {p['max_hold']:>3} {p['exit_z']:>4} | "
          f"{r['profit_factor']:>5.2f}/{r['return_pct']:>6.2f}/{r['trades']:>4} | "
          f"{rt['profit_factor']:>5.2f}/{rt['return_pct']:>6.2f}/{rt['trades']:>4}")

# how many of ALL train-profitable configs stay profitable on test?
prof_train = [(p, r) for p, r in train_results if r["return_pct"] > 0]
stayed = 0
for p, r in prof_train:
    if bm.run(test, p)["return_pct"] > 0:
        stayed += 1
print(f"\nconfigs profitable on TRAIN: {len(prof_train)} / {len(train_results)}")
print(f"of those, also profitable on TEST: {stayed} "
      f"({(stayed/len(prof_train)*100 if prof_train else 0):.0f}%)")
print("(random noise would give ~50% carry-over; a real edge would give a "
      "clear majority and positive TEST returns.)")
