#!/usr/bin/env python3
"""Owner option B (2026-10-04): the forward SHADOW book (dd 12.5%/5%) next to the
official paper book (20%/10%).

Guards: the official ledger is never written by the shadow book; paper_trader's
globals and config.BEAR are restored afterwards; every paper_trader output path
is redirected (so a future new *_PATH cannot leak into the official dir); the
backfill anchors on the official first candle with no lookahead; the books only
diverge through dd_enter/dd_exit; COMPARE.md flags divergences and data
mismatches; reruns are idempotent. Synthetic candles, no network.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "paper_trading"))
sys.path.insert(0, os.path.join(ROOT, "paper_trading", "shadow_exit_book"))
import config                      # noqa: E402
import paper_trader as pt          # noqa: E402
import shadow_book as sb           # noqa: E402
import compare as cmp              # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


# real official files: must stay byte-identical through everything below
REAL = [os.path.join(ROOT, "paper_trading", f) for f in
        ("paper_log.jsonl", "JOURNAL.md", "SUMMARY.md", "market_data_daily.csv")]
before = [open(p, "rb").read() if os.path.exists(p) else None for p in REAL]
real_globals = {k: getattr(pt, k) for k in dir(pt) if k.endswith("_PATH")}
real_bear = config.BEAR

check("every paper_trader *_PATH global is redirected by the shadow book",
      set(real_globals) == set(sb.PATHS)
      and all(os.path.dirname(v) == sb.HERE for v in sb.PATHS.values()))

# synthetic daily candles: 520-day rally, then -1%/day slide
bars, px, t0 = [], 10_000_000.0, datetime(2024, 1, 1)
for i in range(600):
    px *= 1.003 if i < 520 else 0.99
    bars.append({"t": (t0 + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "open": px, "high": px, "low": px, "close": px})
day = {"n": 510}
pt.le.fetch_closed_daily = lambda c, count=600: bars[:day["n"]][-count:]
pt.UpbitClient = lambda *a: None

tmp = tempfile.mkdtemp()
off_dir, sh_dir = os.path.join(tmp, "off"), os.path.join(tmp, "sh")
os.makedirs(off_dir)
os.makedirs(sh_dir)
for k in real_globals:                       # the test's "official" book -> temp
    setattr(pt, k, os.path.join(off_dir, os.path.basename(real_globals[k])))
sb.PATHS = {k: os.path.join(sh_dir, os.path.basename(v)) for k, v in sb.PATHS.items()}
sb.OFFICIAL_JSONL = cmp.OFFICIAL = pt.JSONL_PATH
cmp.SHADOW, cmp.OUT = sb.PATHS["JSONL_PATH"], os.path.join(sh_dir, "COMPARE.md")
off_paths = {k: getattr(pt, k) for k in real_globals}

pt.process("long_flat")                      # official day 1 (anchor bar 509)
for n in range(511, 516):                    # official runs 5 more days alone
    day["n"] = n
    pt.process("long_flat")
sb.run()                                     # shadow launches late -> backfill
off, sh = cmp._load(cmp.OFFICIAL), cmp._load(cmp.SHADOW)
check("backfill anchors on the official first candle and catches up to today",
      sh[0]["candle_t"] == off[0]["candle_t"] and sh[-1]["candle_t"] == off[-1]["candle_t"]
      and len(sh) == len(off) and all(r.get("backfilled_at_launch") for r in sh))
check("paper_trader globals and config.BEAR restored after a shadow run",
      {k: getattr(pt, k) for k in real_globals} == off_paths and config.BEAR is real_bear
      and pt._append_jsonl.__module__ == "paper_trader")
check("shadow records labelled (book, official=false, params 12.5/5)",
      all(r["book"] == "shadow_exit_12.5_5" and r["official"] is False
          and r["params"] == {"dd_enter": 0.125, "dd_exit": 0.05} for r in sh)
      and not any("book" in r for r in off))

check("rerun on the same day appends nothing (idempotent)",
      (sb.run(), len(cmp._load(cmp.SHADOW)))[1] == len(sh))
for n in range(516, 600):                    # then both run forward daily
    day["n"] = n
    pt.process("long_flat")
    sb.run()
off, sh = cmp._load(cmp.OFFICIAL), cmp._load(cmp.SHADOW)
first_sell = [next(r["candle_t"] for r in L if r["action"] == "SELL") for L in (off, sh)]
check("same entries, but the shadow exits the slide earlier (12.5% vs 20%)",
      [r["action"] for r in off][0] == [r["action"] for r in sh][0] == "BUY"
      and first_sell[1] < first_sell[0])
check("forward records after launch are not flagged backfilled",
      not sh[-1].get("backfilled_at_launch"))
check("identical data and sizing: same closes, same first notional",
      [r["close"] for r in off] == [r["close"] for r in sh]
      and off[0]["cash_krw"] == sh[0]["cash_krw"])
_, _, rows = cmp.joined()
md = open(cmp.OUT).read()
check("COMPARE.md lists the divergences and confirms identical data",
      sum(r["diverged"] for r in rows) >= 1 and "분기(divergence)" in md
      and "종가 불일치 0개" in md and first_sell[1][:10] in md)
check("a close mismatch between the books is flagged",
      "DATA MISMATCH 1" in cmp.headline(off, [dict(sh[0], close=1.0)] + sh[1:]))
check("shadow journal is labelled as not official",
      "공식 원장이 아님" in open(sb.PATHS["JOURNAL_PATH"]).read())

check("real official ledger files byte-identical",
      before == [open(p, "rb").read() if os.path.exists(p) else None for p in REAL])

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
