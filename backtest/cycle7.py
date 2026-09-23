#!/usr/bin/env python3
"""Cycle 7 — ONE hypothesis: the ATR(14) trailing stop that improved the DAILY
Donchian (Cycle 6) also improves the 4h Donchian 30/20 co-best.

Test on the integrity-verified full-history 4h data (Cycle 5), train/test 70/30,
measure vs the current-best base (4h Donchian 30/20 with no trailing stop).
Reuses the Cycle-6 engine (run_variant / metrics_from).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_backtest as sb  # noqa
import cycle6 as c6  # noqa


def evalv(bars, **kw):
    t, e, c, tr, p = c6.run_variant(bars, **kw)
    return c6.metrics_from(t, e, c, tr, p, bars)


def main():
    h = sb.load("../data/krw_btc_4h_full.csv")
    split = int(len(h) * 0.70)
    train, test = h[:split], h[split:]
    print(f"4H full {h[0]['t'][:10]}..{h[-1]['t'][:10]} ({len(h)} bars)")
    print(f"TRAIN ..{train[-1]['t'][:10]}  /  TEST {test[0]['t'][:10]}..\n")
    # ATR(14) on 4h = 56h lookback; same k grid as the daily refinement
    variants = {
        "base 30/20 (current best 4h)": dict(n_in=30, n_out=20),
        "+ATRtrail k3":                 dict(n_in=30, n_out=20, atr_k=3.0),
        "+ATRtrail k4":                 dict(n_in=30, n_out=20, atr_k=4.0),
        "+ATRtrail k5":                 dict(n_in=30, n_out=20, atr_k=5.0),
    }
    print(f"{'variant':<30}{'TRAIN cagr/cal/dd/n':>26}{'TEST cagr/cal/dd/n':>26}")
    res = {}
    for name, kw in variants.items():
        mtr, mte = evalv(train, **kw), evalv(test, **kw)
        res[name] = (mtr, mte)
        print(f"{name:<30}"
              f"{mtr['cagr']:>8.0f}/{mtr['calmar']:>4.2f}/{mtr['mdd']:>3.0f}/{mtr['trades']:>4}"
              f"{mte['cagr']:>11.0f}/{mte['calmar']:>4.2f}/{mte['mdd']:>3.0f}/{mte['trades']:>4}")
    base = res["base 30/20 (current best 4h)"]
    print(f"\nbase TEST: Calmar {base[1]['calmar']:.2f}, maxDD {base[1]['mdd']:.0f}%, "
          f"CAGR {base[1]['cagr']:.0f}%")
    winner = max(res.items(), key=lambda kv: kv[1][1]["calmar"])
    print(f"best by TEST Calmar: {winner[0]} -> Calmar {winner[1][1]['calmar']:.2f}, "
          f"maxDD {winner[1][1]['mdd']:.0f}%, CAGR {winner[1][1]['cagr']:.0f}%")


if __name__ == "__main__":
    main()
