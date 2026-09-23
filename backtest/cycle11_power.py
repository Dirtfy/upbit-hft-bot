#!/usr/bin/env python3
"""Cycle 11: power analysis — how many genuinely-FORWARD trades are needed before
realized paper PnL can be meaningfully compared to backtest expectation?

Reuses the EXACT paper-bot strategy (src/donchian_bot.replay) on the full
verified history, extracts per-trade net returns, and computes:
  * the per-trade return distribution (n, mean, std, win rate) per timeframe,
  * N* = trades needed for a 95% CI on the mean trade to exclude 0 (detect edge),
  * trade frequency -> wall-clock time to accumulate N* forward trades.
Research/analysis only; reads public-API-sourced CSVs, places no orders.
"""
import csv
import math
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import donchian_bot as d  # noqa: E402

DATA = {"daily": os.path.join(HERE, "..", "data", "krw_btc_1d.csv"),
        "4h":    os.path.join(HERE, "..", "data", "krw_btc_4h_full.csv")}
FMT = "%Y-%m-%dT%H:%M:%S"


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"t": r["time_utc"], "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"])})
    return bars


def trades_from_rows(rows):
    """Round-trip net returns (fraction) from replay rows (BUY open -> SELL open)."""
    out, entry = [], None
    for r in rows:
        if r["action"] == "BUY":
            entry = float(r["fill_price"])
        elif r["action"] == "SELL" and entry:
            x = float(r["fill_price"])
            out.append(x / entry * (1 - d.FEE) ** 2 - 1)
            entry = None
    return out


def stats(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else float("nan")
    wr = sum(1 for x in xs if x > 0) / n
    return n, m, sd, wr


def main():
    for tf in ("daily", "4h"):
        bars = load_bars(DATA[tf])
        p = d.PARAMS[tf]
        rows = d.replay(bars, p)
        tr = trades_from_rows(rows)
        n, m, sd, wr = stats(tr)
        yrs = (datetime.strptime(bars[-1]["t"], FMT)
               - datetime.strptime(bars[0]["t"], FMT)).total_seconds() / (365.25 * 86400)
        tpy = n / yrs
        # N* so that 95% CI half-width (1.96*sd/sqrt(N)) < |mean| -> excludes 0
        nstar = (1.96 * sd / m) ** 2 if m != 0 else float("inf")
        nstar = math.ceil(nstar)
        print(f"=== {tf}: full history {bars[0]['t'][:10]}..{bars[-1]['t'][:10]} "
              f"({yrs:.1f}y) ===")
        print(f"  trades={n}  mean/trade={m*100:+.2f}%  std={sd*100:.2f}%  "
              f"win_rate={wr*100:.0f}%  freq={tpy:.1f} trades/yr")
        print(f"  N* to exclude 0 at 95% CI = {nstar} trades "
              f"-> ~{nstar/tpy:.1f} yr of forward data")
        print(f"  (so far FORWARD-observed: see logs/paper_{tf}.csv — track was "
              f"warm-started 2026-09-12; genuinely-forward trades ~0 yet)")


if __name__ == "__main__":
    main()
