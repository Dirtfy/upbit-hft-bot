#!/usr/bin/env python3
"""Cycle 37 — cross-coin check of the exit-speed candidate (research/backtest only).

Cycle 29 picked dd_enter 12.5% / dd_exit 5% on ONE asset (daily KRW-BTC). The
caveat was "one asset, ~10 trades". The forward paper run cannot settle it
before ~10/24 either: both books stay FLAT unless BTC rallies >35% (Cycle 36).
So the next-best evidence is out-of-asset: run the same long_flat rule with
the live 20/10 and the candidate 12.5/5 on the other KRW coins we already hold
1h history for (data/1h/, from the Cycle 31 lab), resampled to Upbit daily
candles (00:00 UTC = 09:00 KST boundary, same label as the official ledger).
Nothing here was tuned on these coins, so they are a genuine out-of-sample
test of the *parameter choice*.

Per coin: CAGR / maxDD / Sharpe / trades for both configs and the candidate's
win/loss on each metric; plus the Cycle 29 plateau (dd_enter 11-16%, dd_exit
4-6%) to show whether a neighbour region also beats live, not just one point.
Same engine as backtest/bear_backtest.py (next-bar OPEN fills, fees, no
lookahead). Does NOT change config.
Usage: python3 backtest/exit_cross_coin.py [--dir data/1h]
"""
import argparse
import csv
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)
import config                                     # noqa: E402
import bear_strategy as bs                        # noqa: E402
from bear_backtest import metrics                 # noqa: E402

CANDIDATE = (0.125, 0.05)
PLATEAU = [(de, dx) for de in (0.11, 0.12, 0.13, 0.14, 0.15, 0.16) for dx in (0.04, 0.05, 0.06)]
MIN_DAYS = 600                                    # 365-bar dd window + 200 SMA need history
MIN_HOURS = 20                                    # drop a day with too few 1h bars


def daily_from_1h(path):
    """Resample 1h rows to UTC-day OHLC. Returns closed days only (the last,
    possibly still-forming day is dropped) and skips sparse days."""
    days = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            d = r["time_utc"][:10]
            o, h, lo, c = (float(r[k]) for k in ("open", "high", "low", "close"))
            if d not in days:
                days[d] = {"t": d + "T00:00:00", "open": o, "high": h, "low": lo,
                           "close": c, "n": 1}
            else:
                b = days[d]
                b["high"], b["low"], b["close"] = max(b["high"], h), min(b["low"], lo), c
                b["n"] += 1
    out = [days[d] for d in sorted(days)]
    if out:
        out.pop()                                 # last day may still be forming
    return [b for b in out if b["n"] >= MIN_HOURS]


def run(bars, de, dx, capital=1_000_000.0):
    p = dict(config.BEAR, dd_enter=de, dd_exit=dx)
    eq, held, trades = bs.replay(bars, p, "long_flat", capital)
    m = metrics(f"{de:.1%}/{dx:.0%}", eq, held, trades, bars)
    bh = bars[-1]["close"] / bars[0]["close"] - 1
    m.update(dd_enter=de, dd_exit=dx, bh=bh)
    return m


def coin_report(bars):
    live = (config.BEAR["dd_enter"], config.BEAR["dd_exit"])
    base, cand = run(bars, *live), run(bars, *CANDIDATE)
    plateau = [run(bars, de, dx) for de, dx in PLATEAU]
    return {
        "base": base, "cand": cand,
        "cagr_win": cand["cagr"] > base["cagr"] + 1e-9,
        "mdd_win": cand["mdd"] < base["mdd"] - 1e-9,
        "sharpe_win": cand["sharpe"] > base["sharpe"] + 1e-9,
        "plateau_sharpe_beats": sum(r["sharpe"] > base["sharpe"] + 1e-9 for r in plateau),
        "plateau_mdd_beats": sum(r["mdd"] < base["mdd"] - 1e-9 for r in plateau),
        "plateau_n": len(plateau),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(ROOT, "data", "1h"))
    args = ap.parse_args()
    rows = []
    for path in sorted(glob.glob(os.path.join(args.dir, "KRW-*.csv"))):
        coin = os.path.basename(path)[:-4]
        bars = daily_from_1h(path)
        if len(bars) < MIN_DAYS:
            print(f"{coin}: only {len(bars)} days, skipped")
            continue
        r = coin_report(bars)
        r.update(coin=coin, n=len(bars), start=bars[0]["t"][:10], end=bars[-1]["t"][:10])
        rows.append(r)
    print(f"long_flat, live {config.BEAR['dd_enter']:.1%}/{config.BEAR['dd_exit']:.0%} "
          f"vs candidate {CANDIDATE[0]:.1%}/{CANDIDATE[1]:.0%}; daily from 1h, next-open fills, fees\n")
    print(f"{'coin':<9}{'days':>5} {'span':<23}{'B&H%':>8} | {'CAGR% L/C':>13}{'maxDD% L/C':>13}"
          f"{'Sharpe L/C':>12}{'trd L/C':>9} | {'plateau Shrp+':>13}{'MDD+':>6}")
    for r in rows:
        b, c = r["base"], r["cand"]
        print(f"{r['coin']:<9}{r['n']:>5} {r['start']}..{r['end']} {b['bh']*100:>8.0f} | "
              f"{b['cagr']*100:>6.1f}/{c['cagr']*100:<6.1f}{b['mdd']*100:>6.1f}/{c['mdd']*100:<6.1f}"
              f"{b['sharpe']:>5.2f}/{c['sharpe']:<6.2f}{b['trades']:>4}/{c['trades']:<4} | "
              f"{r['plateau_sharpe_beats']:>9}/{r['plateau_n']:<3}{r['plateau_mdd_beats']:>3}/{r['plateau_n']}")
    others = [r for r in rows if r["coin"] != "KRW-BTC"]
    print(f"\ncandidate beats live on non-BTC coins ({len(others)}): "
          f"CAGR {sum(r['cagr_win'] for r in others)}, maxDD {sum(r['mdd_win'] for r in others)}, "
          f"Sharpe {sum(r['sharpe_win'] for r in others)}")
    return rows


if __name__ == "__main__":
    main()
