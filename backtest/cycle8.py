#!/usr/bin/env python3
"""Cycle 8 — ONE hypothesis: volatility-targeted position sizing improves the
risk-adjusted return of the current best (DAILY Donchian 20/20 + ATR(14) trail
k=3) out-of-sample vs trading full exposure.

Sizing: at each ENTRY, invest a fraction f = clip(target_vol / realized_vol, 0, 1)
of current equity (long-only, NO leverage), held to exit. realized_vol =
stdev of the last VOL_N daily log-ish returns. Rest stays in cash. This trims
exposure in high-volatility regimes; the question is whether that raises Calmar /
cuts maxDD enough to be worth the CAGR given up.

Compared against the current-best baseline (f = 1.0, full exposure). Train/test
70/30 on the integrity-verified daily data.
"""
import os
import sys
from statistics import pstdev
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_backtest as sb  # noqa

FEE = sb.FEE
VOL_N = 20


def atr(bars, n, i):
    if i < n:
        return None
    s = 0.0
    for j in range(i - n + 1, i + 1):
        h, l, pc = bars[j]["high"], bars[j]["low"], bars[j - 1]["close"]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / n


def realized_vol(closes, i):
    if i < VOL_N:
        return None
    rets = [(closes[j] / closes[j - 1] - 1) for j in range(i - VOL_N + 1, i + 1)]
    return pstdev(rets)


def run(bars, n_in=20, n_out=20, atr_k=3.0, atr_bars=14, target_vol=None,
        capital=1_000_000.0):
    """target_vol=None -> full exposure baseline; else vol-targeted fraction."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    equity = capital
    coin = 0.0
    cash = capital
    in_pos, entry, hi_since = False, 0.0, 0.0
    trades, pnls, eq = 0, [], []
    warm = max(n_in, n_out, atr_bars, VOL_N)
    for i in range(len(bars)):
        if i < len(bars) - 1 and i >= warm:
            breakout_up = highs[i] >= max(highs[i - n_in:i])
            breakdown = lows[i] <= min(lows[i - n_out:i])
            trail_hit = False
            if in_pos and atr_k:
                a = atr(bars, atr_bars, i)
                if a is not None:
                    trail_hit = closes[i] <= hi_since - atr_k * a
            nxt = bars[i + 1]["open"]
            if not in_pos and breakout_up:
                E = cash  # flat, so equity is all cash
                if target_vol is None:
                    f = 1.0
                else:
                    rv = realized_vol(closes, i)
                    f = 1.0 if not rv else max(0.0, min(1.0, target_vol / rv))
                invest = f * E
                coin = invest * (1 - FEE) / nxt
                cash = E - invest
                entry, in_pos, hi_since, trades = nxt, True, closes[i], trades + 1
            elif in_pos and (breakdown or trail_hit):
                cash += coin * nxt * (1 - FEE)
                pnls.append((nxt - entry) / entry)
                coin, in_pos = 0.0, False
        if in_pos:
            hi_since = max(hi_since, closes[i])
        eq.append(cash + coin * closes[i])
    # metrics
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    bpy = sb.bars_per_year(bars)
    yrs = len(bars) / bpy
    cagr = ((eq[-1] / eq[0]) ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1
    return {"cagr": cagr * 100, "mdd": mdd * 100,
            "calmar": (cagr / mdd) if mdd > 0 else 0,
            "total": (eq[-1] - eq[0]) / eq[0] * 100, "trades": trades}


def main():
    d = sb.load("../data/krw_btc_1d.csv")
    split = int(len(d) * 0.70)
    train, test = d[:split], d[split:]
    print(f"DAILY {d[0]['t'][:10]}..{d[-1]['t'][:10]}  "
          f"TRAIN..{train[-1]['t'][:10]} / TEST {test[0]['t'][:10]}..  "
          f"(vol_N={VOL_N})\n")
    variants = [("baseline full-exposure", None)]
    for tv in (0.02, 0.03, 0.04, 0.05):
        variants.append((f"voltarget {tv:.0%}/day", tv))
    print(f"{'variant':<24}{'TRAIN cagr/cal/dd':>22}{'TEST cagr/cal/dd':>22}")
    base_test = None
    for name, tv in variants:
        mtr = run(train, target_vol=tv)
        mte = run(test, target_vol=tv)
        if tv is None:
            base_test = mte
        tag = ""
        if base_test and tv is not None:
            tag = " *" if mte["calmar"] > base_test["calmar"] else ""
        print(f"{name:<24}"
              f"{mtr['cagr']:>8.0f}/{mtr['calmar']:>5.2f}/{mtr['mdd']:>4.0f}"
              f"{mte['cagr']:>10.0f}/{mte['calmar']:>5.2f}/{mte['mdd']:>4.0f}{tag}")
    print("\n(* = TEST Calmar beats full-exposure baseline)")


if __name__ == "__main__":
    main()
