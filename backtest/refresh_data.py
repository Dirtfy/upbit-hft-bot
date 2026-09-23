#!/usr/bin/env python3
"""Canonical data-gathering entrypoint (Cycle 16) — refresh research datasets
from the LIVE Upbit public API via the shared UpbitClient.

Research and PAPER analysis run on these files; this pulls them fresh from
Upbit's public candle endpoints (read-only, no keys, no orders) so nothing is a
stale or static snapshot. Writes the same schema verify_data.py expects and runs
the integrity check afterwards.

Usage:
    python3 refresh_data.py                 # refresh daily + 4h to now
    python3 refresh_data.py --daily-count 4000 --h4-count 20000
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from upbit_client import UpbitClient  # noqa: E402

MARKET = "KRW-BTC"
DATA = os.path.join(HERE, "..", "data")


def write_csv(path, candles):
    with open(path, "w") as f:
        f.write("time_utc,open,high,low,close,volume\n")
        for c in candles:
            f.write(",".join(str(x) for x in [
                c["candle_date_time_utc"], c["opening_price"],
                c["high_price"], c["low_price"], c["trade_price"],
                c["candle_acc_trade_volume"]]) + "\n")
    rng = f"{candles[0]['candle_date_time_utc']} .. {candles[-1]['candle_date_time_utc']}" \
        if candles else "empty"
    print(f"wrote {len(candles):>6} rows -> {os.path.relpath(path)}  ({rng})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-count", type=int, default=4000)
    ap.add_argument("--h4-count", type=int, default=20000)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    client = UpbitClient("", "")             # PUBLIC read-only; no keys, no orders
    print("Refreshing from live Upbit public API (api.upbit.com), read-only ...")
    write_csv(os.path.join(DATA, "krw_btc_1d.csv"),
              client.candles_history(MARKET, kind="days", count=args.daily_count))
    write_csv(os.path.join(DATA, "krw_btc_4h_full.csv"),
              client.candles_history(MARKET, kind="minutes", unit=240,
                                     count=args.h4_count))
    if not args.no_verify:
        print("\nIntegrity check:")
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "verify_data.py")],
                       check=False)


if __name__ == "__main__":
    main()
