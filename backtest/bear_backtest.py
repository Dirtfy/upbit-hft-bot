#!/usr/bin/env python3
"""Bear-market strategy backtest — one command, reproducible, inspectable.

Backtests the bear-defense regime filter (src/bear_strategy.py + src/regime.py)
on the integrity-verified daily KRW-BTC history and compares it to buy-and-hold,
with an explicit focus on how each strategy behaves DURING the two historical
BTC bear markets (2018 and 2021-22). Prints summary metrics, a trade log, an
ASCII equity chart, and the bear-window breakdown — no third-party deps.

Usage:
    python3 backtest/bear_backtest.py                     # daily data, all modes
    python3 backtest/bear_backtest.py --data data/krw_btc_1d.csv
    python3 backtest/bear_backtest.py --mode long_flat    # just one variant
    python3 backtest/bear_backtest.py --capital 1000000
    python3 backtest/bear_backtest.py --no-chart

Honesty: fills at next-bar OPEN (no lookahead), Upbit fee 0.05%/side, full-book
compounding for an apples-to-apples comparison with buy-and-hold. The LIVE
engine deploys within the 1,000,000 KRW cap; this backtest measures the
strategy's return SERIES / drawdown profile, which the cap does not change.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import config  # noqa: E402
import bear_strategy as bs  # noqa: E402
from regime import compute_regimes  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%S"
# Well-known BTC bear markets to spotlight (peak-to-trough-ish windows).
BEAR_WINDOWS = [
    ("2018 bear", "2018-01-01", "2018-12-31"),
    ("2021-22 bear", "2021-11-10", "2022-12-31"),
]


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({"t": r["time_utc"], "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"])})
    return rows


def max_drawdown(equity):
    peak, mdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    return mdd


def cagr(equity, bars):
    days = (datetime.strptime(bars[-1]["t"], FMT)
            - datetime.strptime(bars[0]["t"], FMT)).days or 1
    return (equity[-1] / equity[0]) ** (365.0 / days) - 1


def sharpe(equity):
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity))]
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    sd = var ** 0.5
    return 0.0 if sd == 0 else mean / sd * (365 ** 0.5)


def metrics(name, equity, held, trades, bars):
    tot = equity[-1] / equity[0] - 1
    tim = sum(held) / len(held) if held else 0.0
    wins = [t for t in trades if t["ret"] > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    return {
        "name": name, "total_ret": tot, "cagr": cagr(equity, bars),
        "mdd": max_drawdown(equity), "sharpe": sharpe(equity),
        "time_in_mkt": tim, "trades": len(trades), "win_rate": win_rate,
        "final": equity[-1],
    }


def window_return(bars, equity, start, end):
    """Strategy return over [start, end] using the marked equity curve."""
    idx = [i for i, b in enumerate(bars) if start <= b["t"][:10] <= end]
    if len(idx) < 2:
        return None
    return equity[idx[-1]] / equity[idx[0]] - 1


def ascii_chart(series, labels, height=18, width=90):
    """Log-scale ASCII overlay of several equity curves (first char per series)."""
    import math
    n = min(len(s) for s in series)
    step = max(1, n // width)
    cols = list(range(0, n, step))
    logs = [[math.log(max(s[c], 1e-9)) for c in cols] for s in series]
    lo = min(min(l) for l in logs)
    hi = max(max(l) for l in logs)
    rng = (hi - lo) or 1.0
    grid = [[" "] * len(cols) for _ in range(height)]
    marks = "#*+."
    for si, l in enumerate(logs):
        ch = marks[si % len(marks)]
        for x, v in enumerate(l):
            y = height - 1 - int((v - lo) / rng * (height - 1))
            grid[y][x] = ch
    out = ["  (log equity)"]
    for row in grid:
        out.append("  " + "".join(row))
    out.append("  " + "-" * len(cols))
    legend = "  ".join(f"{marks[i % len(marks)]}={labels[i]}"
                       for i in range(len(labels)))
    out.append("  " + legend)
    return "\n".join(out)


def run(args):
    data_path = args.data if os.path.isabs(args.data) else os.path.join(ROOT, args.data)
    bars = load(data_path)
    p = dict(config.BEAR)
    print(f"Bear-market backtest — {config.MARKET}")
    print(f"data: {data_path}")
    print(f"bars: {len(bars)}  {bars[0]['t']} .. {bars[-1]['t']}")
    print(f"regime params: SMA{p['sma_long']} trend + drawdown breaker "
          f"(enter>={p['dd_enter']:.0%}, exit<={p['dd_exit']:.0%}); "
          f"Donchian {p['n_in']}/{p['n_out']} for breakout variants")
    print(f"fee: {config.UPBIT_FEE:.2%}/side  capital: {args.capital:,.0f} KRW\n")

    regimes = compute_regimes(bars, p)
    bear_frac = sum(1 for r in regimes if r == "bear") / len(regimes)
    print(f"regime coverage: {bear_frac:.0%} of bars classified BEAR "
          f"(flat/cash), {1 - bear_frac:.0%} bull\n")

    modes = [args.mode] if args.mode else list(bs.MODES)
    results, curves, labels = [], [], []

    bh = bs.buy_and_hold(bars, args.capital)
    results.append(metrics("buy_and_hold", bh, [1] * len(bars), [], bars))
    curves.append(bh); labels.append("buy_and_hold")

    per_mode_trades = {}
    for m in modes:
        eq, held, trades = bs.replay(bars, p, m, args.capital)
        results.append(metrics(m, eq, held, trades, bars))
        per_mode_trades[m] = trades
        curves.append(eq); labels.append(m)

    # ---- summary table ----
    hdr = (f"{'strategy':<18}{'totRet%':>10}{'CAGR%':>8}{'maxDD%':>8}"
           f"{'Sharpe':>8}{'inMkt%':>8}{'trades':>7}{'win%':>6}{'final KRW':>14}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r['name']:<18}{r['total_ret']*100:>10.1f}{r['cagr']*100:>8.1f}"
              f"{r['mdd']*100:>8.1f}{r['sharpe']:>8.2f}{r['time_in_mkt']*100:>8.0f}"
              f"{r['trades']:>7}{r['win_rate']*100:>6.0f}{r['final']:>14,.0f}")

    # ---- bear-window breakdown (the whole point) ----
    print("\nBEAR-WINDOW performance (return within each historical bear market):")
    wh = f"  {'window':<16}{'dates':<26}" + "".join(f"{lb[:12]:>14}" for lb in labels)
    print(wh)
    for wname, ws, we in BEAR_WINDOWS:
        line = f"  {wname:<16}{ws+'..'+we:<26}"
        for eq in curves:
            wr = window_return(bars, eq, ws, we)
            line += (f"{wr*100:>13.1f}%" if wr is not None else f"{'n/a':>14}")
        print(line)
    print("  (buy_and_hold shows the drawdown the filter is designed to avoid.)")

    # ---- trade log (per active mode) ----
    for m in modes:
        trades = per_mode_trades[m]
        if not trades:
            continue
        print(f"\nTRADE LOG [{m}] — {len(trades)} round trips "
              f"(showing {'all' if len(trades) <= 40 else 'last 40'}):")
        print(f"  {'entry':<12}{'exit':<12}{'entry px':>13}{'exit px':>13}{'ret%':>9}")
        for t in trades[-40:]:
            print(f"  {t['entry_t'][:10]:<12}{t['exit_t'][:10]:<12}"
                  f"{t['entry']:>13,.0f}{t['exit']:>13,.0f}{t['ret']*100:>8.1f}%")

    # ---- ascii chart ----
    if not args.no_chart:
        print("\nEQUITY CURVES:")
        print(ascii_chart(curves, labels))

    print("\nTakeaway: the regime filter trades return for drawdown protection — "
          "compare maxDD% and the bear-window rows above vs buy_and_hold.")
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/krw_btc_1d.csv",
                    help="daily OHLC csv (default: data/krw_btc_1d.csv)")
    ap.add_argument("--mode", choices=list(bs.MODES), default=None,
                    help="run only one variant (default: all)")
    ap.add_argument("--capital", type=float, default=config.BASE_TRADABLE_CAPITAL_KRW)
    ap.add_argument("--no-chart", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
