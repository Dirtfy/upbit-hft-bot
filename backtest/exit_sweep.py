#!/usr/bin/env python3
"""Cycle 29 — faster-exit sweep (research/backtest only).

The live `long_flat` maxDD (~47%) runs from the 2021-04 equity peak to 2023-10:
profit handed back before the 2021-04 exit, a -18% trade in late 2021, then the
2023 whipsaws. The exit-speed lever already in the regime filter is the
drawdown breaker: dd_enter (drawdown from the trailing 365-bar high that forces
bear, i.e. a trailing stop) and dd_exit (how close to the high price must
recover before bull is allowed again). This sweeps both and judges each pair on
robustness, the same bar as backtest/band_sweep.py:
  * full-sample CAGR / maxDD / Sharpe / trades,
  * per-calendar-year returns vs the live config (years better / worse),
  * both halves of the sample separately (2017-2021, 2022-today) — a change
    must help in BOTH halves, not just in-sample overall,
  * the two historical bear windows (the defence must not weaken).

Same engine as backtest/bear_backtest.py (fills at next-bar OPEN, fees, no
lookahead). Does NOT change config.
Usage: python3 backtest/exit_sweep.py [--data data/krw_btc_1d.csv]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)
import config                                     # noqa: E402
import bear_strategy as bs                        # noqa: E402
from bear_backtest import (load, metrics, window_return,  # noqa: E402
                           max_drawdown, BEAR_WINDOWS)
from band_sweep import yearly                     # noqa: E402

DD_ENTER = (0.10, 0.125, 0.15, 0.175, 0.20, 0.25)
DD_EXIT = (0.05, 0.10)
SPLIT = "2022-01-01"                              # first / second half boundary


def half(bars, eq, first):
    """(return, maxDD) of the equity curve restricted to one half of the sample."""
    seg = [v for b, v in zip(bars, eq) if (b["t"][:10] < SPLIT) == first]
    return seg[-1] / seg[0] - 1, max_drawdown(seg)


def sweep(bars, dd_enter=DD_ENTER, dd_exit=DD_EXIT, capital=1_000_000.0):
    live = (config.BEAR["dd_enter"], config.BEAR["dd_exit"])
    res = []
    for de in dd_enter:
        for dx in dd_exit:
            if dx >= de:
                continue
            p = dict(config.BEAR, dd_enter=de, dd_exit=dx)
            eq, held, trades = bs.replay(bars, p, "long_flat", capital)
            m = metrics(f"enter={de:.1%} exit={dx:.0%}", eq, held, trades, bars)
            (r1, d1), (r2, d2) = half(bars, eq, True), half(bars, eq, False)
            m.update(dd_enter=de, dd_exit=dx, live=(de, dx) == live,
                     years=yearly(bars, eq), h1_ret=r1, h1_mdd=d1, h2_ret=r2, h2_mdd=d2,
                     bears={w: window_return(bars, eq, s, e) for w, s, e in BEAR_WINDOWS})
            res.append(m)
    base = next(r for r in res if r["live"])
    for r in res:
        r["years_beat_base"] = sum(1 for y, v in r["years"].items() if v > base["years"][y] + 1e-9)
        r["years_lose_base"] = sum(1 for y, v in r["years"].items() if v < base["years"][y] - 1e-9)
        # robust = no worse on return AND drawdown in BOTH halves, bear defence intact
        r["robust"] = (not r["live"]
                       and r["h1_ret"] >= base["h1_ret"] - 1e-9 and r["h2_ret"] >= base["h2_ret"] - 1e-9
                       and r["h1_mdd"] <= base["h1_mdd"] + 1e-9 and r["h2_mdd"] <= base["h2_mdd"] + 1e-9
                       and all((r["bears"][w] or 0) >= (base["bears"][w] or 0) - 1e-9
                               for w in r["bears"]))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "krw_btc_1d.csv"))
    args = ap.parse_args()
    bars = load(args.data)
    print(f"bars {len(bars)} {bars[0]['t'][:10]}..{bars[-1]['t'][:10]}  mode=long_flat  "
          f"halves split at {SPLIT}\n")
    res = sweep(bars)
    print(f"{'enter':>6}{'exit':>5}{'CAGR%':>7}{'maxDD%':>7}{'Shrp':>6}{'trd':>5}"
          f"{'H1ret%':>8}{'H1dd%':>7}{'H2ret%':>8}{'H2dd%':>7}{'yrs+':>5}{'yrs-':>5}"
          + "".join(f"{w[:10]:>12}" for w, _, _ in BEAR_WINDOWS) + "  note")
    for r in res:
        note = "LIVE" if r["live"] else ("robust" if r["robust"] else "")
        print(f"{r['dd_enter']:>6.1%}{r['dd_exit']:>5.0%}{r['cagr']*100:>7.1f}{r['mdd']*100:>7.1f}"
              f"{r['sharpe']:>6.2f}{r['trades']:>5}{r['h1_ret']*100:>8.0f}{r['h1_mdd']*100:>7.1f}"
              f"{r['h2_ret']*100:>8.0f}{r['h2_mdd']*100:>7.1f}{r['years_beat_base']:>5}"
              f"{r['years_lose_base']:>5}"
              + "".join(f"{(v or 0)*100:>11.1f}%" for v in r["bears"].values()) + f"  {note}")
    print(f"\nrobust improvements over LIVE: {sum(r['robust'] for r in res)}")
    return res


if __name__ == "__main__":
    main()
