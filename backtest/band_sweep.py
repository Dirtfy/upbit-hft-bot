#!/usr/bin/env python3
"""Cycle 28 — regime hysteresis-band sweep (research/backtest only).

The Cycle 27 shadow replay showed the live `long_flat` regime filter whipsawing
around SMA200 (6 of 10 round trips since 2023 were small losses), with config
BEAR.band = 0 (a plain cross). This sweeps the band, i.e. require
close > SMA*(1+band) to turn bull and close < SMA*(1-band) to turn bear, and
judges each value on robustness, not on the single best in-sample number:
  * full-sample CAGR / maxDD / Sharpe / trades / win rate,
  * per-calendar-year returns (how often a band beats band=0),
  * the two historical bear windows (the band must not weaken the defence).

Same engine as backtest/bear_backtest.py (src/regime + bear_strategy.run_book):
fills at next-bar OPEN, 0.05%/side, no lookahead. Does NOT change config.
Usage: python3 backtest/band_sweep.py [--data data/krw_btc_1d.csv]
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
                           BEAR_WINDOWS)

BANDS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08)


def yearly(bars, eq):
    out = {}
    for y in sorted({b["t"][:4] for b in bars}):
        r = window_return(bars, eq, f"{y}-01-01", f"{y}-12-31")
        if r is not None:
            out[y] = r
    return out


def sweep(bars, bands=BANDS, capital=1_000_000.0):
    res = []
    for band in bands:
        p = dict(config.BEAR, band=band)
        eq, held, trades = bs.replay(bars, p, "long_flat", capital)
        m = metrics(f"band={band:.0%}", eq, held, trades, bars)
        m.update(band=band, years=yearly(bars, eq),
                 bears={w: window_return(bars, eq, s, e) for w, s, e in BEAR_WINDOWS},
                 small_losses=sum(1 for t in trades if -0.10 < t["ret"] <= 0))
        res.append(m)
    base = res[0]["years"]
    for r in res:
        r["years_beat_base"] = sum(1 for y, v in r["years"].items() if v > base[y] + 1e-9)
        r["years_lose_base"] = sum(1 for y, v in r["years"].items() if v < base[y] - 1e-9)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "krw_btc_1d.csv"))
    args = ap.parse_args()
    bars = load(args.data)
    print(f"bars {len(bars)} {bars[0]['t'][:10]}..{bars[-1]['t'][:10]}  mode=long_flat\n")
    res = sweep(bars)
    print(f"{'band':>6}{'CAGR%':>8}{'maxDD%':>8}{'Sharpe':>8}{'inMkt%':>8}{'trades':>7}"
          f"{'win%':>6}{'smallL':>7}{'yrs+':>6}{'yrs-':>6}"
          + "".join(f"{w[:10]:>12}" for w, _, _ in BEAR_WINDOWS))
    for r in res:
        print(f"{r['band']:>6.0%}{r['cagr']*100:>8.1f}{r['mdd']*100:>8.1f}{r['sharpe']:>8.2f}"
              f"{r['time_in_mkt']*100:>8.0f}{r['trades']:>7}{r['win_rate']*100:>6.0f}"
              f"{r['small_losses']:>7}{r['years_beat_base']:>6}{r['years_lose_base']:>6}"
              + "".join(f"{(v or 0)*100:>11.1f}%" for v in r["bears"].values()))
    years = sorted(res[0]["years"])
    print("\nper-year return %:")
    print(f"{'band':>6}" + "".join(f"{y:>8}" for y in years))
    for r in res:
        print(f"{r['band']:>6.0%}" + "".join(f"{r['years'][y]*100:>8.1f}" for y in years))
    return res


if __name__ == "__main__":
    main()
