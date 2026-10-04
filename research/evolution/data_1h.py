#!/usr/bin/env python3
"""1h candle store for the strategy-evolution lab (Cycle 31).

Incrementally fetches CLOSED 1h candles for a small KRW universe from Upbit's
PUBLIC candle endpoint (read-only, no keys, no orders) into data/1h/<MKT>.csv
(gitignored). Re-running only fetches hours newer than the last stored one, so
it is safe on any cadence. The forming (unclosed) hour is always dropped.

Usage:
    python3 research/evolution/data_1h.py                # update all markets
    python3 research/evolution/data_1h.py --markets KRW-BTC
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

DATA_DIR = os.path.join(ROOT, "data", "1h")
UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA"]
FIELDS = ["time_utc", "open", "high", "low", "close", "volume"]
EPOCH = datetime(2017, 9, 25, tzinfo=timezone.utc)   # Upbit KRW market launch


def path_for(market, data_dir=DATA_DIR):
    return os.path.join(data_dir, f"{market}.csv")


def _last_t(path):
    if not os.path.exists(path):
        return None
    last = None
    with open(path) as f:
        for r in csv.DictReader(f):
            last = r["time_utc"]
    return last


def update(market, client, data_dir=DATA_DIR, now=None):
    """Append every closed 1h candle newer than the stored tail. Returns #new."""
    os.makedirs(data_dir, exist_ok=True)
    path = path_for(market, data_dir)
    last = _last_t(path)
    now = now or datetime.now(timezone.utc)
    closed_cut = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    stop = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else EPOCH
    rows, to = {}, None
    while True:
        params = {"market": market, "count": 200}
        if to:
            params["to"] = to
        page = client._request("GET", "/v1/candles/minutes/60", params)
        if not page:
            break
        done = False
        for c in page:
            t = datetime.fromisoformat(c["candle_date_time_utc"]).replace(tzinfo=timezone.utc)
            if t <= stop:
                done = True
                continue
            if t <= closed_cut:
                rows[c["candle_date_time_utc"]] = c
        new_to = page[-1]["candle_date_time_utc"] + "Z"
        if done or new_to == to:
            break
        to = new_to
    new = sorted(rows.values(), key=lambda c: c["candle_date_time_utc"])
    write_header = not os.path.exists(path)
    with open(path, "a") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(FIELDS)
        for c in new:
            w.writerow([c["candle_date_time_utc"], c["opening_price"], c["high_price"],
                        c["low_price"], c["trade_price"], c["candle_acc_trade_volume"]])
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="*", default=UNIVERSE)
    ap.add_argument("--data-dir", default=DATA_DIR)
    a = ap.parse_args()
    from upbit_client import UpbitClient
    client = UpbitClient("", "")          # PUBLIC read-only; no keys, no orders
    for m in a.markets:
        n = update(m, client, a.data_dir)
        print(f"{m}: +{n} closed 1h candles -> {os.path.relpath(path_for(m, a.data_dir), ROOT)}",
              flush=True)


if __name__ == "__main__":
    main()
