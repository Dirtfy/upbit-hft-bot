#!/usr/bin/env python3
"""Cycle 4: stress-test the Cycle-3 winner (DAILY Donchian breakout).

Two robustness checks the single 70/30 split can't give:
  (A) Anchored walk-forward: step through time in folds; on each fold RE-OPTIMISE
      the Donchian (in,out) on all prior data (by Calmar), then trade the next
      fold out-of-sample. Aggregates a realistic "always trading OOS" record and
      shows whether the best parameters are stable.
  (B) Per-calendar-year breakdown of a fixed Donchian 20/20 run continuously,
      strategy vs buy&hold — the key question is bear years (2018, 2022): does
      trend-following protect capital, i.e. is this more than long-BTC beta?
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing_backtest as sb  # noqa
FEE = sb.FEE

DGRID = [(a, b) for a in (10, 15, 20, 30, 40, 55) for b in (5, 10, 15, 20)]


def run_donchian(bars, n_in, n_out, capital=1_000_000.0):
    """Continuous long-only Donchian; returns (times, equity, closes)."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    cash, coin, in_pos, entry = capital, 0.0, False, 0.0
    state = [False]
    times, eq, pnls, trades = [], [], [], 0
    for i in range(len(bars)):
        if i < len(bars) - 1:
            if i >= max(n_in, n_out):
                if highs[i] >= max(highs[i - n_in:i]):
                    state[0] = True
                elif lows[i] <= min(lows[i - n_out:i]):
                    state[0] = False
            desired = state[0]
            nxt = bars[i + 1]["open"]
            if desired and not in_pos:
                coin = (cash * (1 - FEE)) / nxt; entry = nxt; cash = 0.0
                in_pos = True; trades += 1
            elif not desired and in_pos:
                cash = coin * nxt * (1 - FEE); coin = 0.0; in_pos = False
                pnls.append((nxt - entry) / entry)
        times.append(bars[i]["t"]); eq.append(cash + coin * closes[i])
    return times, eq, closes, trades, pnls


def best_on(train):
    best = None
    for a, b in DGRID:
        st = [False]
        m = sb.backtest(train, sb.make_donchian(
            a, b, [x["high"] for x in train], [x["low"] for x in train], st))
        if m["trades"] >= 3 and (best is None or m["calmar"] > best[2]["calmar"]):
            best = (a, b, m)
    return best


def walk_forward(bars, n_folds=5, min_train=400):
    print("=== (A) Anchored walk-forward (re-optimise each fold) ===")
    start = min_train
    fold_size = (len(bars) - start) // n_folds
    picks = {}
    oos_rets = []
    for k in range(n_folds):
        tr_end = start + k * fold_size
        te_end = tr_end + fold_size if k < n_folds - 1 else len(bars)
        train, test = bars[:tr_end], bars[tr_end:te_end]
        if len(test) < 30:
            continue
        b = best_on(train)
        if not b:
            continue
        a, o, _ = b
        st = [False]
        mte = sb.backtest(test, sb.make_donchian(
            a, o, [x["high"] for x in test], [x["low"] for x in test], st))
        picks[(a, o)] = picks.get((a, o), 0) + 1
        oos_rets.append(mte["total_pct"])
        print(f"fold {k+1}: train..{train[-1]['t'][:10]} -> "
              f"test {test[0]['t'][:10]}..{test[-1]['t'][:10]}  "
              f"pick=in{a}/out{o}  OOS total={mte['total_pct']:+7.1f}%  "
              f"CAGR={mte['cagr_pct']:+6.1f}%  DD={mte['maxdd_pct']:.1f}%  "
              f"B&H={mte['bh_total_pct']:+7.1f}%")
    print(f"param picks across folds: {dict(picks)}")
    beat = sum(1 for r in oos_rets if r > 0)
    print(f"folds OOS-positive: {beat}/{len(oos_rets)}\n")


def per_year(bars, n_in=20, n_out=20):
    print(f"=== (B) Per-year: DAILY Donchian {n_in}/{n_out} vs buy&hold ===")
    times, eq, closes, trades, pnls = run_donchian(bars, n_in, n_out)
    years = sorted({t[:4] for t in times})
    print(f"{'year':<6}{'strat%':>9}{'B&H%':>9}{'edge%':>9}")
    for y in years:
        idx = [i for i, t in enumerate(times) if t[:4] == y]
        if len(idx) < 2:
            continue
        a, b = idx[0], idx[-1]
        s = (eq[b] - eq[a]) / eq[a] * 100
        h = (closes[b] - closes[a]) / closes[a] * 100
        print(f"{y:<6}{s:>9.1f}{h:>9.1f}{s-h:>+9.1f}")
    tot_s = (eq[-1] - eq[0]) / eq[0] * 100
    tot_h = (closes[-1] - closes[0]) / closes[0] * 100
    print(f"{'ALL':<6}{tot_s:>9.1f}{tot_h:>9.1f}{tot_s-tot_h:>+9.1f}  "
          f"(trades={trades})")


def main():
    d = sb.load("../data/krw_btc_1d.csv")
    print(f"daily: {len(d)} bars {d[0]['t'][:10]}..{d[-1]['t'][:10]}, "
          f"fee={FEE*100}%/side\n")
    walk_forward(d, n_folds=5)
    per_year(d, 20, 20)


if __name__ == "__main__":
    main()
