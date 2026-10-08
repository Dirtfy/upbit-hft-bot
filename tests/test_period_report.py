#!/usr/bin/env python3
"""Cycle 35: period_report.py reads every ledger without modifying any, matches
the ledgers' own equity, and computes buy-and-hold / max DD correctly.
Plain asserts: `python3 tests/test_period_report.py`."""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "paper_trading"))
import period_report as pr  # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


PT = os.path.join(ROOT, "paper_trading")
ledgers = [os.path.join(PT, "paper_log.jsonl"), os.path.join(PT, "shadow_exit_book", "paper_log.jsonl"),
           os.path.join(PT, "market_data_daily.csv")] + glob.glob(os.path.join(PT, "ensemble_books", "*", "paper_log.jsonl"))
before = [open(p, "rb").read() for p in ledgers]
out_before = open(pr.OUT, "rb").read() if os.path.exists(pr.OUT) else None
try:
    rows, div = pr.build()
    check("ledgers byte-identical after build", before == [open(p, "rb").read() for p in ledgers])
    off = pr._jsonl(ledgers[0])
    check("official row matches the ledger's last equity", rows[0]["official"] is True
          and rows[0]["equity"] == off[-1]["equity_krw"] and rows[0]["days"] == len(off))
    check("only the official book is labelled official", sum(r["official"] for r in rows) == 1)
    check("buy-and-hold benchmark present", rows[-1]["name"].startswith("BTC buy-and-hold") and rows[-1]["days"] > 0)
    check("max DD: 100 -> 120 -> 90 is 25%", abs(pr._mdd([100, 120, 90, 110]) - 0.25) < 1e-12)
    check("max DD of a flat book is 0", pr._mdd([1e6] * 5) == 0)
    md = open(pr.OUT).read()
    check("report states interim vs final", ("interim" in md) != ("PERIOD COMPLETE" in md))
finally:
    if out_before is not None:
        open(pr.OUT, "wb").write(out_before)

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} ({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
