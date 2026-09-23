#!/usr/bin/env python3
"""Integrity verification for the historical candle datasets (mission: data
must be TRUSTWORTHY before use).

Checks, per file:
  1. Parse + schema: every row parses, OHLCV numeric.
  2. Ordering: timestamps strictly increasing (=> no duplicates, no out-of-order).
  3. Gaps: consecutive timestamps differ by exactly one granularity; any larger
     delta is a gap (Upbit omits candles for intervals with zero trades or
     exchange downtime) — we list them and their sizes.
  4. OHLC sanity: low <= min(open,close), high >= max(open,close), low<=high,
     all prices > 0.
  5. Volume sanity: volume >= 0 (column present in these files).
  6. Extreme moves: |close/prev_close - 1| above a threshold, flagged (not
     necessarily errors — crypto gaps happen — but surfaced for eyeballing).
Timezone + lookahead are verified separately (see verify_timezone / notes).
"""
import csv
import os
import sys
from datetime import datetime

FMT = "%Y-%m-%dT%H:%M:%S"
# Resolve data paths relative to this file, not the caller's cwd, so the check
# works whether run standalone from backtest/ or as a subprocess (refresh_data.py
# invokes it from the repo root — the canonical Cycle-16 data-gathering path).
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def verify(path, gran_sec, extreme):
    print(f"\n===== {path}  (granularity {gran_sec}s) =====")
    rows = load(path)
    n = len(rows)
    ts = []
    bad_ohlc = []
    bad_num = 0
    neg_vol = 0
    for i, r in enumerate(rows):
        try:
            t = datetime.strptime(r["time_utc"], FMT)
            o, h, l, c = (float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"]))
            v = float(r.get("volume", 0) or 0)
        except Exception as e:
            bad_num += 1
            continue
        ts.append(t)
        if not (l <= min(o, c) and h >= max(o, c) and l <= h and l > 0):
            bad_ohlc.append((r["time_utc"], o, h, l, c))
        if v < 0:
            neg_vol += 1

    # ordering / duplicates
    dups = sum(1 for a, b in zip(ts, ts[1:]) if b == a)
    ooo = sum(1 for a, b in zip(ts, ts[1:]) if b < a)
    strictly_inc = dups == 0 and ooo == 0

    # gaps
    gaps = []
    for a, b in zip(ts, ts[1:]):
        d = (b - a).total_seconds()
        if d != gran_sec:
            gaps.append((a, b, d))
    missing_candles = sum(int(d / gran_sec) - 1 for _, _, d in gaps)

    # extreme moves
    closes = [float(r["close"]) for r in rows]
    ext = [(rows[i]["time_utc"], closes[i-1], closes[i])
           for i in range(1, len(closes))
           if closes[i-1] > 0 and abs(closes[i]/closes[i-1]-1) > extreme]

    print(f"rows={n}  range {rows[0]['time_utc']} .. {rows[-1]['time_utc']}")
    print(f"[1] schema/parse   : {'OK' if bad_num==0 else 'FAIL'} "
          f"(unparseable rows={bad_num})")
    print(f"[2] strictly increasing: {'OK' if strictly_inc else 'FAIL'} "
          f"(duplicates={dups}, out-of-order={ooo})")
    print(f"[3] gaps           : {len(gaps)} gap-intervals, "
          f"{missing_candles} missing candles "
          f"({missing_candles/max(n,1)*100:.3f}% of series)")
    for a, b, d in gaps[:8]:
        print(f"      gap {a} -> {b}  = {int(d/gran_sec)} intervals "
              f"({int(d/3600)}h)")
    if len(gaps) > 8:
        print(f"      ... and {len(gaps)-8} more")
    print(f"[4] OHLC sanity    : {'OK' if not bad_ohlc else 'FAIL'} "
          f"(violations={len(bad_ohlc)})")
    for row in bad_ohlc[:5]:
        print("      bad:", row)
    print(f"[5] volume >= 0    : {'OK' if neg_vol==0 else 'FAIL'} "
          f"(negatives={neg_vol})")
    print(f"[6] extreme moves  : {len(ext)} bars move >{extreme*100:.0f}% "
          f"vs prev close (flagged for review)")
    for row in ext[:5]:
        print(f"      {row[0]}: {row[1]:.0f} -> {row[2]:.0f} "
              f"({(row[2]/row[1]-1)*100:+.1f}%)")
    return {"rows": n, "strictly_inc": strictly_inc, "gaps": len(gaps),
            "missing": missing_candles, "bad_ohlc": len(bad_ohlc),
            "extreme": len(ext)}


if __name__ == "__main__":
    verify(os.path.join(DATA, "krw_btc_1d.csv"), 86400, 0.30)
    verify(os.path.join(DATA, "krw_btc_4h_full.csv"), 14400, 0.20)
