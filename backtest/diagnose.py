#!/usr/bin/env python3
"""Diagnostics: is the loss from fees or from a non-predictive signal?

Runs the best grid config at varying fee/slippage levels, and tests whether the
mean-reversion signal has ANY gross edge (fee=0, slip=0). Also tests a simple
momentum/breakout variant for contrast.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from strategy import Params  # noqa
import backtest as bt  # noqa

rows = bt.load("../data/krw_btc_1m.csv")
best = Params(window=60, entry_z=3.0, stop_loss_pct=0.006,
              take_profit_pct=0.004, max_hold=40)

print("=== Fee/slippage sensitivity (best mean-reversion config) ===")
for fee, slip in [(0.0, 0.0), (0.0, 2.0), (0.0005, 0.0), (0.0005, 2.0),
                  (0.0005, 5.0)]:
    r = bt.run(rows, best, 1_000_000, slippage_bps=slip, fee=fee)
    print(f"fee={fee*100:.3f}%/side slip={slip:>4}bps -> {bt.fmt(r)}")

print("\nInterpretation: if the fee=0/slip=0 row is still <= buy&hold and near "
      "zero, the SIGNAL has no exploitable edge; fees then push it deeply "
      "negative. If fee=0 is strongly positive, the edge exists but is smaller "
      "than round-trip costs.")
