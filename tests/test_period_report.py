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
    # re-entry price is exact against the real regime rule (synthetic history)
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import random
    import regime
    import config
    rng = random.Random(4)
    hist = [100.0]
    for _ in range(499):
        hist.append(hist[-1] * (1 + rng.gauss(0, 0.03)))
    ok = True
    for p_ in (config.BEAR, dict(config.BEAR, dd_enter=0.125, dd_exit=0.05)):
        for k in (1, 15):
            need = pr.reentry_price(hist, k, p_)
            for mult, want in ((1.001, "bull"), (0.999, None)):
                seq = hist + [need * mult] * k
                got = regime.compute_regimes([{"close": c} for c in seq], p_)[-1]
                # just below the bar the k-th day cannot be a fresh flip to bull
                prev = regime.compute_regimes([{"close": c} for c in seq[:-1]], p_)[-1]
                if want and got != want or (not want and prev != "bull" and got == "bull"):
                    ok = False
    check("re-entry price is the exact regime.py threshold", ok)
    md = open(pr.OUT).read()
    check("report has the re-entry outlook", "Re-entry outlook" in md)
    check("report states interim vs final", ("interim" in md) != ("PERIOD COMPLETE" in md))
    # ---- Cycle 41: operational-integrity section
    import tempfile
    def rec(d, close=100.0, logged=None):
        return {"candle_t": f"{d}T00:00:00", "close": close,
                "logged_at_utc": logged or f"{d[:8]}{int(d[8:]) + 1:02d}T00:05:00+00:00"}
    off_s = [rec("2026-10-01"), rec("2026-10-02"), rec("2026-10-02"), rec("2026-10-05")]
    sh_s = [rec("2026-10-01"), rec("2026-10-02", close=99.0),
            dict(rec("2026-10-05", logged="2026-10-09T00:00:00+00:00"), backfilled_at_launch=True)]
    tmpd = tempfile.mkdtemp()
    olog = os.path.join(tmpd, "outages.log")
    open(olog, "w").write(
        "2026-10-01T10:40:02Z paper UNCLEAN_EXIT pid=1 last_heartbeat=x down_at_most=210s (~3min)\n"
        "# NOTE: a comment line\n"
        "2026-10-04T03:30:02Z collect_4h UNCLEAN_EXIT owner=h/1:2 last_heartbeat=x down_at_most=720s (~12min)\n"
        "2026-09-01T00:00:00Z paper UNCLEAN_EXIT pid=3 last_heartbeat=x down_at_most=9999s\n")
    h4 = os.path.join(tmpd, "h4.csv")
    open(h4, "w").write("time_utc,close\n2026-10-01T00:00:00,1\n2026-10-01T04:00:00,1\n2026-10-01T12:00:00,1\n")
    txt = "\n".join(pr.integrity(off_s, sh_s, olog, h4))
    check("integrity: duplicate and gap in the official ledger are reported",
          "4 candles, 1 duplicates, 1 gaps (2026-10-02..2026-10-05)" in txt)
    check("integrity: close mismatch between books is reported", "1 close mismatches (2026-10-02)" in txt)
    check("integrity: launch backfill is not 'late'; 4h gap counted",
          "3 candles, 0 duplicates, 1 gaps (2026-10-02..2026-10-05) | 0 late" in txt
          and "3 candles in period, 1 gaps" in txt)
    check("integrity: false positives and pre-period outages excluded, downtime is 12 min upper bound",
          "1 real (last 2026-10-04), 1 logged false positives excluded; downtime upper bound ~0.2 h" in txt)
    check("report has the integrity section", "## Operational integrity" in md)
finally:
    if out_before is not None:
        open(pr.OUT, "wb").write(out_before)

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} ({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
