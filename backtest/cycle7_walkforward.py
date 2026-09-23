#!/usr/bin/env python3
"""Cycle 7 (walk-forward addendum): does adding an ATR trailing stop help the 4h
Donchian 30/20 out-of-sample across MULTIPLE folds, not just one 70/30 split?

Anchored folds over the full verified 4h series; on each test fold we compare the
fixed base (30/20, no trail) vs +ATRtrail k3 / k5 — the question is whether the
trailing stop is a net OOS improvement to a fixed Donchian, so channels are held
fixed (we are testing the exit, not re-optimising entries).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_backtest as sb  # noqa
import cycle6 as c6  # noqa


def ev(bars, **kw):
    t, e, c, tr, p = c6.run_variant(bars, **kw)
    return c6.metrics_from(t, e, c, tr, p, bars)


def main():
    h = sb.load("../data/krw_btc_4h_full.csv")
    n_folds, min_train = 5, 3000
    start = min_train
    fold = (len(h) - start) // n_folds
    print(f"4H full {h[0]['t'][:10]}..{h[-1]['t'][:10]} ({len(h)} bars), "
          f"{n_folds} folds\n")
    print(f"{'fold':<5}{'test window':<26}{'base cal/ret':>16}"
          f"{'k3 cal/ret':>16}{'k5 cal/ret':>16}")
    wins = {"k3": 0, "k5": 0}
    n = 0
    for k in range(n_folds):
        te0 = start + k * fold
        te1 = te0 + fold if k < n_folds - 1 else len(h)
        test = h[te0:te1]
        if len(test) < 200:
            continue
        n += 1
        b = ev(test, n_in=30, n_out=20)
        k3 = ev(test, n_in=30, n_out=20, atr_k=3.0)
        k5 = ev(test, n_in=30, n_out=20, atr_k=5.0)
        if k3["calmar"] > b["calmar"]:
            wins["k3"] += 1
        if k5["calmar"] > b["calmar"]:
            wins["k5"] += 1
        print(f"{k+1:<5}{test[0]['t'][:10]+'..'+test[-1]['t'][:10]:<26}"
              f"{b['calmar']:>7.2f}/{b['cagr']:>+6.0f}"
              f"{k3['calmar']:>8.2f}/{k3['cagr']:>+6.0f}"
              f"{k5['calmar']:>8.2f}/{k5['cagr']:>+6.0f}")
    print(f"\nfolds where trail beat base (Calmar): k3={wins['k3']}/{n}, "
          f"k5={wins['k5']}/{n}")
    print("=> ATR-trail is a net OOS improvement only if it beats base in a clear "
          "majority of folds.")


if __name__ == "__main__":
    main()
