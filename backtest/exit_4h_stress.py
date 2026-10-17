#!/usr/bin/env python3
"""Cycle 39 — 4h stress test of the exit-speed candidate (research/backtest only).

Cycle 29 judged dd 12.5%/5% against the live 20%/10% on DAILY bars only: decide
on the daily close, fill at the next daily open, mark equity at daily closes.
This replays both configs on the 4h path (data/krw_btc_4h_full.csv; the 00:00
UTC 4h bar opens with the Upbit daily candle) under three stresses:

  1. FILL-TIME JITTER — same daily decisions, but filled at the open of the
     k-th 4h bar of the next day (k=0..5 → +0h..+20h). k=0 is the backtest;
     an edge that only exists at one fill hour is a timing artefact.
  2. INTRADAY DRAWDOWN — equity marked at every 4h close, so maxDD includes the
     intraday dips the daily marks hide.
  3. 4h-CHECKED BREAKER — the same rule evaluated at every 4h close as if the
     day closed now (SMA200 and the 365-day high use completed daily closes +
     the current price), filled at the next 4h open. At each day's last 4h
     close this is exactly the daily rule; in between it can react sooner,
     and also whipsaw more.

The candidate passes if it keeps beating live on CAGR and maxDD for every fill
hour, and under the 4h-checked breaker. Same fee as the engine. Does NOT change
config. The baseline is pinned to 20/10, so the comparison survives a switch.
Usage: python3 backtest/exit_4h_stress.py [--daily data/krw_btc_1d.csv] [--h4 data/krw_btc_4h_full.csv]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)
import config                                     # noqa: E402
import bear_strategy as bs                        # noqa: E402
from bear_backtest import load, metrics, max_drawdown  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%S"
CONFIGS = {"base 20/10": (0.20, 0.10),           # Cycle 29 reference, pinned (not config.BEAR)
           "cand 12.5/5": (0.125, 0.05)}
FEE = bs.FEE


def _params(de, dx):
    return dict(config.BEAR, dd_enter=de, dd_exit=dx)


def simulate(h4, switches, capital=1_000_000.0, fee=FEE):
    """All-in/flat book on 4h bars. `switches` = sorted [(fill_time_str, target)];
    each fills at the OPEN of the first 4h bar at or after its time. Returns
    (equity at each 4h close, trades)."""
    cash, coin, pos, entry = capital, 0.0, 0, None
    eq, trades, j = [], [], 0
    for b in h4:
        target = None
        while j < len(switches) and switches[j][0] <= b["t"]:
            target = switches[j][1]
            j += 1
        if target is not None and target != pos:
            px = b["open"]
            if target == 1:
                coin, cash, entry, pos = cash * (1 - fee) / px, 0.0, px, 1
            else:
                cash, coin, pos = coin * px * (1 - fee), 0.0, 0
                trades.append({"ret": px / entry - 1})
        eq.append(cash + coin * b["close"])
    return eq, trades


def daily_switches(dbars, p, k):
    """Daily long_flat decisions, filled k 4h bars into the next day."""
    des = bs.targets(dbars, p, "long_flat")
    out, prev = [], 0
    for i, d in enumerate(des):
        if d != prev:
            t = datetime.strptime(dbars[i]["t"], FMT) + timedelta(days=1, hours=4 * k)
            out.append((t.strftime(FMT), d))
            prev = d
    return out


def intraday_switches(dbars, h4, p):
    """The regime rule checked at every 4h close as if the day closed there.
    Fills at the next 4h bar's open (time = this bar's start + 4h)."""
    closes = [b["close"] for b in dbars]
    day_idx = {b["t"][:10]: i for i, b in enumerate(dbars)}
    pre = [0.0]
    for c in closes:
        pre.append(pre[-1] + c)
    n, w = p["sma_long"], p["dd_window"]
    state, out, prev = "bear", [], 0
    for b in h4:
        i = day_idx.get(b["t"][:10])
        if i is None or i + 1 < n:
            continue
        c = b["close"]                            # provisional close of day i
        sl = (pre[i] - pre[i - n + 1] + c) / n
        peak = max(max(closes[max(0, i - w + 1):i], default=c), c)
        dd = max(0.0, 1 - c / peak)
        if state == "bull":
            if c < sl or dd >= p["dd_enter"]:
                state = "bear"
        elif c > sl and dd <= p["dd_exit"]:
            state = "bull"
        d = 1 if state == "bull" else 0
        if d != prev:
            t = datetime.strptime(b["t"], FMT) + timedelta(hours=4)
            out.append((t.strftime(FMT), d))
            prev = d
    return out


def report(name, h4, dbars, eq, trades):
    """Metrics on day-end marks (CAGR/Sharpe comparable to the daily backtest)
    plus maxDD on every 4h mark."""
    day_end = {}
    for b, v in zip(h4, eq):
        day_end[b["t"][:10]] = v
    days = [d for d in dbars if d["t"][:10] in day_end]
    deq = [day_end[d["t"][:10]] for d in days]
    m = metrics(name, deq, [0] * len(deq), trades, days)
    m["mdd_4h"] = max_drawdown(eq)
    return m


def run(dbars, h4):
    rows = []
    for name, (de, dx) in CONFIGS.items():
        p = _params(de, dx)
        for k in range(6):
            eq, tr = simulate(h4, daily_switches(dbars, p, k))
            rows.append(dict(report(name, h4, dbars, eq, tr), cfg=name, test=f"fill +{4 * k}h"))
        eq, tr = simulate(h4, intraday_switches(dbars, h4, p))
        rows.append(dict(report(name, h4, dbars, eq, tr), cfg=name, test="4h-checked"))
    return rows


def verdict(rows):
    """Per test: does the candidate beat live on CAGR and on 4h maxDD?"""
    by = {(r["cfg"], r["test"]): r for r in rows}
    out = []
    for t in dict.fromkeys(r["test"] for r in rows):
        lv, cd = by[("base 20/10", t)], by[("cand 12.5/5", t)]
        out.append((t, cd["cagr"] > lv["cagr"], cd["mdd_4h"] < lv["mdd_4h"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily", default=os.path.join(ROOT, "data", "krw_btc_1d.csv"))
    ap.add_argument("--h4", default=os.path.join(ROOT, "data", "krw_btc_4h_full.csv"))
    a = ap.parse_args()
    dbars, h4 = load(a.daily), load(a.h4)
    last = min(dbars[-1]["t"][:10], h4[-1]["t"][:10])
    dbars = [b for b in dbars if b["t"][:10] < last]   # complete days only
    h4 = [b for b in h4 if b["t"][:10] < last]
    print(f"daily {len(dbars)} bars, 4h {len(h4)} bars, {h4[0]['t'][:10]}..{h4[-1]['t'][:10]}, long_flat\n")
    rows = run(dbars, h4)
    print(f"{'config':<13}{'test':<12}{'CAGR%':>7}{'Sharpe':>7}{'trd':>5}{'maxDD% day':>11}{'maxDD% 4h':>10}")
    for r in rows:
        print(f"{r['cfg']:<13}{r['test']:<12}{r['cagr'] * 100:>7.1f}{r['sharpe']:>7.2f}{r['trades']:>5}"
              f"{r['mdd'] * 100:>11.1f}{r['mdd_4h'] * 100:>10.1f}")
    print("\ncandidate vs base:")
    for t, c, d in verdict(rows):
        print(f"  {t:<11} CAGR {'better' if c else 'WORSE'}, 4h maxDD {'better' if d else 'WORSE'}")
    return rows


if __name__ == "__main__":
    main()
