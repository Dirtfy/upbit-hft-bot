#!/usr/bin/env python3
"""Fetch Upbit daily or N-minute candles back as far as the API allows.

Daily candles go back years (across bull/bear/chop regimes) — exactly what we
need to validate a swing strategy out-of-sample. Pure stdlib, paginates via the
`to` param, dedups, writes OHLC CSV.

Usage:
    python3 fetch_candles.py --kind days --count 3000 --out ../data/krw_btc_1d.csv
    python3 fetch_candles.py --kind minutes --unit 240 --count 8000 --out ../data/krw_btc_4h.csv
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error


def endpoint(kind, unit):
    if kind == "days":
        return "https://api.upbit.com/v1/candles/days"
    return f"https://api.upbit.com/v1/candles/minutes/{unit}"


def fetch_page(url_base, market, to=None, count=200):
    url = f"{url_base}?market={market}&count={count}"
    if to:
        url += "&to=" + urllib.parse.quote(to)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["days", "minutes"], default="days")
    ap.add_argument("--unit", type=int, default=240)
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--count", type=int, default=3000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    url_base = endpoint(args.kind, args.unit)

    rows = {}
    to = None
    while len(rows) < args.count:
        page = fetch_page(url_base, args.market, to=to, count=200)
        if not page:
            break
        for c in page:
            rows[c["candle_date_time_utc"]] = c
        oldest = page[-1]["candle_date_time_utc"]
        new_to = oldest + "Z"
        if new_to == to:  # no progress -> reached the start of history
            break
        to = new_to
        sys.stderr.write(f"\r{len(rows)} candles, back to {oldest}   ")
        sys.stderr.flush()
        time.sleep(0.15)
    sys.stderr.write("\n")

    ordered = sorted(rows.values(), key=lambda c: c["candle_date_time_utc"])
    with open(args.out, "w") as f:
        f.write("time_utc,open,high,low,close,volume\n")
        for c in ordered:
            f.write(",".join(str(x) for x in [
                c["candle_date_time_utc"], c["opening_price"],
                c["high_price"], c["low_price"], c["trade_price"],
                c["candle_acc_trade_volume"]]) + "\n")
    print(f"wrote {len(ordered)} rows to {args.out}")
    if ordered:
        print("range:", ordered[0]["candle_date_time_utc"], "->",
              ordered[-1]["candle_date_time_utc"])


if __name__ == "__main__":
    main()
