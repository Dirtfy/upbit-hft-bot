#!/usr/bin/env python3
"""Targeted search: push per-trade edge above Upbit round-trip cost.

Realistic live assumption for a maker (limit-order) entry: fee 0.05%/side is
unavoidable, but crossing cost is small, so slip=1bp. We require the per-trade
gross move to clear ~12-15 bps of cost, so we bias toward rarer entries
(higher entry_z / longer window) and larger take-profits.
"""
import itertools, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from strategy import Params  # noqa
import backtest as bt  # noqa

rows = bt.load("../data/krw_btc_1m.csv")
combos = itertools.product(
    [60, 90, 120],            # window
    [3.0, 3.5, 4.0],          # entry_z
    [0.005, 0.008, 0.012],    # stop_loss
    [0.008, 0.012, 0.020],    # take_profit
    [40, 60, 90],             # max_hold
)
res = []
for w, ez, sl, tp, mh in combos:
    p = Params(window=w, entry_z=ez, stop_loss_pct=sl,
               take_profit_pct=tp, max_hold=mh)
    r = bt.run(rows, p, 1_000_000, slippage_bps=1.0, fee=0.0005)
    res.append((p, r))
ranked = sorted([x for x in res if x[1]["trades"] >= 12],
                key=lambda x: x[1]["total_pnl_krw"], reverse=True)
print(f"targeted grid, {len(res)} combos, fee=0.05%/side slip=1bp, "
      f"bh={res[0][1]['buyhold_pct']:+.2f}%\n")
print("TOP 12:")
for p, r in ranked[:12]:
    print(f"  W={p.window:>3} eZ={p.entry_z} SL={p.stop_loss_pct} "
          f"TP={p.take_profit_pct} MH={p.max_hold:>2} | {bt.fmt(r)}")
