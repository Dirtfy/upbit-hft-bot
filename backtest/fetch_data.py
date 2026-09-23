#!/usr/bin/env python3
"""Download historical Upbit KRW-BTC minute candles into a CSV.

Pure stdlib. Paginates backwards using the `to` parameter. Upbit returns at
most 200 candles per request and rate-limits candle calls (~10 req/s); we
sleep between calls to stay well under the limit.

Usage:
    python3 fetch_data.py --unit 1 --count 20000 --out ../data/krw_btc_1m.csv
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE = "https://api.upbit.com/v1/candles/minutes"


def fetch_page(unit, market, to=None, count=200):
    url = f"{BASE}/{unit}?market={market}&count={count}"
    if to:
        url += f"&to={urllib.parse.quote(to)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.0 + attempt)
                continue
            raise
        except Exception:
            time.sleep(0.5 + attempt)
    raise RuntimeError("failed after retries: " + url)


def main():
    import urllib.parse  # noqa
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--count", type=int, default=20000, help="total candles to fetch")
    ap.add_argument("--out", default="../data/krw_btc_1m.csv")
    args = ap.parse_args()

    rows = {}  # utc_str -> row, dedup
    to = None
    fetched = 0
    while fetched < args.count:
        page = fetch_page(args.unit, args.market, to=to, count=200)
        if not page:
            break
        for c in page:
            rows[c["candle_date_time_utc"]] = c
        # oldest candle in this page becomes the next `to`
        oldest = page[-1]["candle_date_time_utc"]
        # Upbit `to` is exclusive-ish; format needs a trailing Z
        to = oldest + "Z" if not oldest.endswith("Z") else oldest
        fetched = len(rows)
        sys.stderr.write(f"\rfetched {fetched} candles, back to {oldest}   ")
        sys.stderr.flush()
        time.sleep(0.15)
    sys.stderr.write("\n")

    ordered = sorted(rows.values(), key=lambda c: c["candle_date_time_utc"])
    with open(args.out, "w") as f:
        f.write("time_utc,open,high,low,close,volume,value\n")
        for c in ordered:
            f.write(",".join(str(x) for x in [
                c["candle_date_time_utc"],
                c["opening_price"], c["high_price"], c["low_price"],
                c["trade_price"], c["candle_acc_trade_volume"],
                c["candle_acc_trade_price"],
            ]) + "\n")
    print(f"wrote {len(ordered)} rows to {args.out}")
    if ordered:
        print("range:", ordered[0]["candle_date_time_utc"], "->",
              ordered[-1]["candle_date_time_utc"])


if __name__ == "__main__":
    import urllib.parse
    main()
