#!/usr/bin/env python3
"""4-hour candle accumulator (owner Option A, 2026-09-26).

Accumulates KRW-BTC 4h candles into a COMMITTED, gap-free trail
(`paper_trading/market_data_4h.csv`) alongside the existing daily trail. Runs the
same storage convention as the daily pipeline: the full 9y 4h history stays in the
gitignored `data/krw_btc_4h_full.csv` (via backtest/refresh_data.py); only this
small forward accumulation trail is committed.

SAFETY — RESEARCH / PAPER ONLY. Read-only public candle endpoint only; NO API
keys, NO account, NO orders. Nothing here can place a trade.

GAP-FREE BY DESIGN (self-healing): each run pulls a wide recent window and appends
EVERY 4h candle that closed since the last recorded one — so completeness does not
depend on being invoked exactly every 4h. Even the once-a-day leader turn captures
all 6 of that day's 4h candles by backfill. A true 4h cadence only improves
freshness, not completeness (see README / report for the schedule options).

Idempotent: appends only candles strictly newer than the last recorded one.
First run bootstraps the trail with the trailing `--bootstrap` closed candles.

Usage:  python3 paper_trading/collect_4h.py [--bootstrap 180]
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import config                                   # noqa: E402
from upbit_client import UpbitClient            # noqa: E402

TRAIL_PATH = os.path.join(HERE, "market_data_4h.csv")
STEP_SEC = 4 * 3600                             # 4h candle spacing
HEADER = ["time_utc", "open", "high", "low", "close", "volume"]


def fetch_closed_4h(client, count=200):
    """Recent CLOSED 4h candles (oldest->newest); drops the forming candle."""
    raw = client.candles_history(config.MARKET, kind="minutes", unit=240,
                                 count=count)
    bars = [{"t": c["candle_date_time_utc"],
             "open": c["opening_price"], "high": c["high_price"],
             "low": c["low_price"], "close": c["trade_price"],
             "volume": c["candle_acc_trade_volume"]} for c in raw]
    return bars[:-1]                            # drop the still-forming candle


def _last_recorded_t():
    if not os.path.exists(TRAIL_PATH):
        return None
    last = None
    with open(TRAIL_PATH) as f:
        for row in csv.reader(f):
            if row and row[0] != "time_utc":
                last = row[0]
    return last


def _append(bars):
    new = not os.path.exists(TRAIL_PATH)
    with open(TRAIL_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for b in bars:
            w.writerow([b["t"], b["open"], b["high"], b["low"], b["close"],
                        b["volume"]])


def integrity():
    """Check the committed trail: duplicates, out-of-order, and 4h gaps.
    Returns (rows, dups, out_of_order, gaps, gap_list)."""
    if not os.path.exists(TRAIL_PATH):
        return 0, 0, 0, 0, []
    ts = []
    with open(TRAIL_PATH) as f:
        for row in csv.reader(f):
            if row and row[0] != "time_utc":
                ts.append(datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc))
    dups = len(ts) - len(set(ts))
    ooo = sum(1 for i in range(1, len(ts)) if ts[i] <= ts[i - 1])
    gaps, gap_list = 0, []
    for i in range(1, len(ts)):
        step = (ts[i] - ts[i - 1]).total_seconds()
        if step != STEP_SEC and ts[i] > ts[i - 1]:
            missing = int(step // STEP_SEC) - 1
            gaps += max(0, missing)
            if len(gap_list) < 5:
                gap_list.append(f"{ts[i-1].isoformat()} -> {ts[i].isoformat()} "
                                f"({int(step//STEP_SEC)} steps)")
    return len(ts), dups, ooo, gaps, gap_list


def collect(bootstrap):
    client = UpbitClient("", "")                # public, keyless
    last_t = _last_recorded_t()
    # pull enough to backfill any gap since last run (>= a few days of 4h bars)
    bars = fetch_closed_4h(client, count=max(bootstrap + 10, 200))
    if not bars:
        print("no closed 4h candles returned; nothing to do")
        return 0
    if last_t is None:
        take = bars[-bootstrap:]                 # first run: bootstrap window
        print(f"first run: bootstrapping trail with {len(take)} closed 4h candles")
    else:
        take = [b for b in bars if b["t"] > last_t]  # only strictly-newer
    if not take:
        print(f"no new closed 4h candle since {last_t}; nothing to do (idempotent)")
    else:
        _append(take)
        print(f"appended {len(take)} 4h candle(s); latest {take[-1]['t']} "
              f"-> {os.path.relpath(TRAIL_PATH, ROOT)}")

    rows, dups, ooo, gaps, gap_list = integrity()
    span = ""
    if rows:
        with open(TRAIL_PATH) as f:
            data = [r for r in csv.reader(f) if r and r[0] != "time_utc"]
        span = f"{data[0][0]} .. {data[-1][0]}"
    print(f"integrity: rows={rows} dups={dups} out_of_order={ooo} gaps={gaps} "
          f"[{span}]")
    for g in gap_list:
        print(f"  gap: {g}")
    if dups or ooo:
        print("WARNING: trail integrity violated (dups/out-of-order) — investigate.")
    return len(take)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bootstrap", type=int, default=180,
                    help="on first run, seed the trail with the trailing N closed "
                         "4h candles (~30 days at 6/day). Default 180.")
    args = ap.parse_args()
    collect(args.bootstrap)


if __name__ == "__main__":
    main()
