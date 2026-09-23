#!/usr/bin/env python3
"""Cycle 6: refine the Donchian breakout — can a regime filter and/or an ATR
trailing stop improve risk-adjusted return / cut the bull-market lag, without
hurting the bear-market protection? Validated with a train/test split on the
trustworthy full-history daily data (verified in Cycle 5).

Variants (daily, long-only, 0.05%/side, act next-bar open):
  base        : Donchian in20/out20
  +regime     : only enter when close > SMA(regime_n)   (trend regime gate)
  +atrtrail   : exit also if close <= running-high(since entry) - k*ATR
  +both

Reports TRAIN/TEST CAGR, Calmar, maxDD, trades; then a per-year strat-vs-B&H
breakdown for the winner to check bull-lag.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_backtest as sb  # noqa
FEE = sb.FEE


def atr_series(bars, n=14):
    tr = [0.0] * len(bars)
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * len(bars)
    run = 0.0
    for i in range(len(bars)):
        run += tr[i]
        if i >= n:
            run -= tr[i - n]
        if i >= n:
            atr[i] = run / n
    return atr


def run_variant(bars, n_in=20, n_out=20, regime_n=0, atr_k=0.0, atr_n=14,
                capital=1_000_000.0):
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    atr = atr_series(bars, atr_n) if atr_k else None
    cash, coin, in_pos, entry = capital, 0.0, False, 0.0
    hi_since = 0.0
    times, eq, pnls, trades = [], [], [], 0
    warm = max(n_in, n_out, regime_n, (atr_n if atr_k else 0))
    for i in range(len(bars)):
        if i < len(bars) - 1 and i >= warm:
            regime_ok = True
            if regime_n:
                sma = sum(closes[i + 1 - regime_n:i + 1]) / regime_n
                regime_ok = closes[i] > sma
            breakout_up = highs[i] >= max(highs[i - n_in:i])
            breakdown = lows[i] <= min(lows[i - n_out:i])
            trail_hit = False
            if in_pos and atr_k and atr[i] is not None:
                trail_hit = closes[i] <= (hi_since - atr_k * atr[i])
            nxt = bars[i + 1]["open"]
            if not in_pos and breakout_up and regime_ok:
                coin = (cash * (1 - FEE)) / nxt; entry = nxt; cash = 0.0
                in_pos = True; trades += 1; hi_since = closes[i]
            elif in_pos and (breakdown or trail_hit):
                cash = coin * nxt * (1 - FEE); coin = 0.0; in_pos = False
                pnls.append((nxt - entry) / entry)
        if in_pos:
            hi_since = max(hi_since, closes[i])
        times.append(bars[i]["t"]); eq.append(cash + coin * closes[i])
    return times, eq, closes, trades, pnls


def metrics_from(times, eq, closes, trades, pnls, bars):
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    bpy = sb.bars_per_year(bars)
    yrs = len(bars) / bpy
    cagr = ((eq[-1] / eq[0]) ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1
    wins = [p for p in pnls if p > 0]
    return {"cagr": cagr * 100, "mdd": mdd * 100,
            "calmar": (cagr / mdd) if mdd > 0 else 0,
            "trades": trades,
            "win": (len(wins)/len(pnls)*100) if pnls else 0,
            "total": (eq[-1]-eq[0])/eq[0]*100}


def evalv(bars, **kw):
    t, e, c, tr, p = run_variant(bars, **kw)
    return metrics_from(t, e, c, tr, p, bars)


def main():
    d = sb.load("../data/krw_btc_1d.csv")
    split = int(len(d) * 0.70)
    train, test = d[:split], d[split:]
    print(f"DAILY {d[0]['t'][:10]}..{d[-1]['t'][:10]}  "
          f"TRAIN..{train[-1]['t'][:10]} / TEST {test[0]['t'][:10]}..\n")
    variants = {
        "base 20/20":        dict(n_in=20, n_out=20),
        "+regime SMA100":    dict(n_in=20, n_out=20, regime_n=100),
        "+regime SMA200":    dict(n_in=20, n_out=20, regime_n=200),
        "+ATRtrail k3":      dict(n_in=20, n_out=20, atr_k=3.0),
        "+ATRtrail k4":      dict(n_in=20, n_out=20, atr_k=4.0),
        "+both(SMA200,k3)":  dict(n_in=20, n_out=20, regime_n=200, atr_k=3.0),
    }
    print(f"{'variant':<20}{'TRAIN cagr/cal/dd/n':>30}{'TEST cagr/cal/dd/n':>30}")
    rows = {}
    for name, kw in variants.items():
        mtr, mte = evalv(train, **kw), evalv(test, **kw)
        rows[name] = (mtr, mte)
        print(f"{name:<20}"
              f"{mtr['cagr']:>8.0f}/{mtr['calmar']:>4.2f}/{mtr['mdd']:>4.0f}/{mtr['trades']:>3}"
              f"{mte['cagr']:>13.0f}/{mte['calmar']:>4.2f}/{mte['mdd']:>4.0f}/{mte['trades']:>3}")

    # per-year for base vs best-by-TEST-calmar
    best = max(rows.items(), key=lambda kv: kv[1][1]["calmar"])
    print(f"\nbest by TEST Calmar: {best[0]}  (TEST Calmar {best[1][1]['calmar']:.2f})")
    print("\nPer-year strat vs B&H — base 20/20 vs", best[0])
    for label, kw in [("base", variants["base 20/20"]), (best[0], variants[best[0]])]:
        t, e, c, tr, p = run_variant(d, **kw)
        years = sorted({x[:4] for x in t})
        line = []
        for y in years:
            idx = [i for i, x in enumerate(t) if x[:4] == y]
            a, b = idx[0], idx[-1]
            s = (e[b]-e[a])/e[a]*100
            line.append(f"{y}:{s:+.0f}%")
        print(f"  {label:<18} " + "  ".join(line))
    # buy&hold per year
    t = [x["t"] for x in d]; c = [x["close"] for x in d]
    years = sorted({x[:4] for x in t}); line = []
    for y in years:
        idx = [i for i, x in enumerate(t) if x[:4] == y]
        a, b = idx[0], idx[-1]; line.append(f"{y}:{(c[b]-c[a])/c[a]*100:+.0f}%")
    print(f"  {'buy&hold':<18} " + "  ".join(line))


if __name__ == "__main__":
    main()
