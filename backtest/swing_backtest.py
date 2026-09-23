#!/usr/bin/env python3
"""Cycle 3: swing trend-following, validated with a train/test split on multi-
year data (guards against the short-window, uptrend-only bias of Cycle 2).

Strategy families (long-only spot, act at next bar's open, 0.05%/side fee):
  * SMA cross: long while SMA(fast) > SMA(slow), else flat.
  * Donchian:  long on break above prior-N-bar high, exit below prior-M-bar low.

Method: optimize parameters on the TRAIN split by CALMAR ratio (CAGR / maxDD,
a risk-adjusted measure), then report the chosen config's TRAIN and TEST
metrics. A real edge should stay clearly positive and beat buy&hold on TEST.
"""
import argparse
import csv
import itertools
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import config  # noqa

FEE = config.UPBIT_FEE


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({"t": r["time_utc"], "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"])})
    return rows


def bars_per_year(bars):
    # infer from timestamps (daily ~365, 4h ~ 6*365)
    n = len(bars)
    if n < 3:
        return 365.0
    # crude: use count over span
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S"
    t0 = datetime.strptime(bars[0]["t"], fmt)
    t1 = datetime.strptime(bars[-1]["t"], fmt)
    yrs = (t1 - t0).total_seconds() / (365.25 * 86400)
    return n / yrs if yrs > 0 else 365.0


def backtest(bars, want_long, capital=1_000_000.0):
    closes = [b["close"] for b in bars]
    cash, coin, in_pos, entry = capital, 0.0, False, 0.0
    trades, pnls, eq = 0, [], []
    for i in range(len(bars)):
        if i < len(bars) - 1:
            desired = want_long(i, bars)
            nxt = bars[i + 1]["open"]
            if desired and not in_pos:
                coin = (cash * (1 - FEE)) / nxt; entry = nxt; cash = 0.0
                in_pos = True; trades += 1
            elif not desired and in_pos:
                cash = coin * nxt * (1 - FEE); coin = 0.0; in_pos = False
                pnls.append((nxt - entry) / entry)
        eq.append(cash + coin * closes[i])
    return metrics(eq, pnls, trades, closes, bars)


def metrics(eq, pnls, trades, closes, bars):
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    total = (eq[-1] - eq[0]) / eq[0]
    bpy = bars_per_year(bars)
    yrs = len(bars) / bpy
    cagr = ((eq[-1] / eq[0]) ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1
    bh = (closes[-1] - closes[0]) / closes[0]
    bh_cagr = ((closes[-1] / closes[0]) ** (1 / yrs) - 1) if yrs > 0 else 0
    wins = [p for p in pnls if p > 0]
    calmar = (cagr / mdd) if mdd > 0 else 0.0
    return {"total_pct": total * 100, "cagr_pct": cagr * 100,
            "maxdd_pct": mdd * 100, "calmar": calmar, "trades": trades,
            "closed": len(pnls),
            "win_rate": (len(wins) / len(pnls) * 100) if pnls else 0.0,
            "avg_trade_pct": (sum(pnls) / len(pnls) * 100) if pnls else 0.0,
            "bh_total_pct": bh * 100, "bh_cagr_pct": bh_cagr * 100}


def sma_at(closes, n, i):
    return sum(closes[i + 1 - n:i + 1]) / n if i + 1 >= n else None


def make_sma_cross(fast, slow, closes):
    def f(i, bars):
        sf, ss = sma_at(closes, fast, i), sma_at(closes, slow, i)
        return sf is not None and ss is not None and sf > ss
    return f


def make_donchian(n_in, n_out, highs, lows, state):
    def f(i, bars):
        if i < max(n_in, n_out):
            return False
        if highs[i] >= max(highs[i - n_in:i]):
            state[0] = True
        elif lows[i] <= min(lows[i - n_out:i]):
            state[0] = False
        return state[0]
    return f


def fmt(tag, m):
    return (f"{tag:<16} total={m['total_pct']:+8.1f}%  CAGR={m['cagr_pct']:+6.1f}%  "
            f"maxDD={m['maxdd_pct']:5.1f}%  Calmar={m['calmar']:5.2f}  "
            f"trades={m['trades']:>3}  win={m['win_rate']:4.0f}%  "
            f"avg/trade={m['avg_trade_pct']:+5.2f}%")


def optimize_and_validate(bars, label, train_frac=0.70):
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    split = int(len(bars) * train_frac)
    train, test = bars[:split], bars[split:]
    tc = closes[:split]
    print(f"\n########## {label} ##########")
    print(f"TRAIN {train[0]['t'][:10]}..{train[-1]['t'][:10]} ({len(train)})  "
          f"TEST {test[0]['t'][:10]}..{test[-1]['t'][:10]} ({len(test)})")

    # --- SMA cross grid, optimized on TRAIN by Calmar ---
    grid = [(f, s) for f in (3, 5, 8, 10, 15, 20, 30)
            for s in (20, 30, 50, 60, 100, 150, 200) if f < s]
    best = None
    for f, s in grid:
        m = backtest(train, make_sma_cross(f, s, tc))
        if m["trades"] >= 3 and (best is None or m["calmar"] > best[2]["calmar"]):
            best = (f, s, m)
    if best:
        f, s, mtr = best
        # re-evaluate on the FULL series' closes for test slice indices
        mte = backtest(test, make_sma_cross(f, s, closes[split:]))
        print(f"\n[SMA cross] best-on-train = {f}/{s}")
        print("  TRAIN:", fmt(f"sma{f}/{s}", mtr))
        print("  TEST :", fmt(f"sma{f}/{s}", mte))
        print("  B&H  : TRAIN CAGR {:+.1f}%  TEST CAGR {:+.1f}%".format(
            mtr["bh_cagr_pct"], mte["bh_cagr_pct"]))
        sma_result = (f, s, mtr, mte)
    else:
        sma_result = None

    # --- Donchian grid, optimized on TRAIN by Calmar ---
    dgrid = [(a, b) for a in (10, 20, 30, 55) for b in (5, 10, 20)]
    dbest = None
    for a, b in dgrid:
        st = [False]
        m = backtest(train, make_donchian(a, b, highs[:split], lows[:split], st))
        if m["trades"] >= 3 and (dbest is None or m["calmar"] > dbest[2]["calmar"]):
            dbest = (a, b, m)
    if dbest:
        a, b, mtr = dbest
        st = [False]
        mte = backtest(test, make_donchian(a, b, highs[split:], lows[split:], st))
        print(f"\n[Donchian] best-on-train = in{a}/out{b}")
        print("  TRAIN:", fmt(f"don{a}/{b}", mtr))
        print("  TEST :", fmt(f"don{a}/{b}", mte))
        don_result = (a, b, mtr, mte)
    else:
        don_result = None
    return sma_result, don_result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", default="../data/krw_btc_1d.csv")
    ap.add_argument("--fourh", default="../data/krw_btc_4h_full.csv")
    args = ap.parse_args()
    d = load(args.daily)
    h = load(args.fourh)
    print(f"daily: {len(d)} bars {d[0]['t'][:10]}..{d[-1]['t'][:10]}")
    print(f"4h   : {len(h)} bars {h[0]['t'][:10]}..{h[-1]['t'][:10]}")
    print(f"fee = {FEE*100}%/side")
    optimize_and_validate(d, "DAILY")
    optimize_and_validate(h, "4H")


if __name__ == "__main__":
    main()
