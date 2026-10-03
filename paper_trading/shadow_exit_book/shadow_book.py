#!/usr/bin/env python3
"""SHADOW paper book — candidate exit speed dd_enter=12.5% / dd_exit=5%
(owner decision "option B", 2026-10-04). NOT the official paper ledger.

Runs forward alongside the official book (paper_trading/paper_log.jsonl, live
setting 20% / 10%) so the owner can choose at the end of the official period
(~2026-10-24) with real forward data. Everything except dd_enter/dd_exit is
identical, because this file does not reimplement anything. It runs the
official `paper_trader.process()` unchanged, with only these differences:
  * every output path is redirected into this directory (own ledger, journal,
    summary, market-data copy), so the two books can never mix;
  * the strategy params are config.BEAR with dd_enter/dd_exit overridden;
  * every record is labelled book="shadow_exit_12.5_5", official=false.
Same data source (closed Upbit daily candles, public read-only), fees, fill
rule, sizing and 1,000,000 KRW cap. paper_trader.py itself is not modified.
The patches are local to this process and are restored on exit.

This is also distinct from the COUNTERFACTUAL shadow REPLAY in
paper_trading/shadow/ (historical stress replay, not a forward book).

First run backfills from the official book's first candle, so both cover the same
period. Each backfilled record uses only data up to its own candle (no
lookahead) and is flagged backfilled_at_launch=true. After that, it appends
idempotently one record per new closed candle, driven by daemon_paper.sh
(token-free). It then regenerates COMPARE.md (official vs shadow).

SAFETY: research/PAPER only. No keys, no account, no orders.
Usage:  python3 paper_trading/shadow_exit_book/shadow_book.py
"""
import contextlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PT = os.path.dirname(HERE)
ROOT = os.path.dirname(PT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, PT)
import config                      # noqa: E402
import paper_trader as pt          # noqa: E402
import tick_lock                   # noqa: E402
import compare                     # noqa: E402  (this directory)

BOOK = "shadow_exit_12.5_5"
OVERRIDE = {"dd_enter": 0.125, "dd_exit": 0.05}
OFFICIAL_JSONL = os.path.join(PT, "paper_log.jsonl")
PATHS = {  # every *_PATH global of paper_trader -> this directory
    "JSONL_PATH": os.path.join(HERE, "paper_log.jsonl"),
    "JOURNAL_PATH": os.path.join(HERE, "JOURNAL.md"),
    "SUMMARY_PATH": os.path.join(HERE, "SUMMARY.md"),
    "DATA_PATH": os.path.join(HERE, "market_data_daily.csv"),
}


def _journal_header():
    return (
        "# SHADOW 모의투자 저널 — 후보 청산속도 (dd_enter 12.5% / dd_exit 5%)\n\n"
        "*공식 원장이 아님 (오너 결정 option B, 2026-10-04). 공식 북(20%/10%)과 "
        "동일한 데이터·수수료·체결·사이징·1,000,000 KRW 상한을 쓰고, "
        "dd_enter/dd_exit만 다르다. 공식 대비 비교는 `COMPARE.md`.*\n"
    )


def _regime_reason(close, sl, dd, p, regime):
    reason, trigger = _orig_reason(close, sl, dd, p, regime)
    trigger = (trigger.replace("낙폭≥20%", f"낙폭≥{p['dd_enter']:.1%}")
               .replace("(≤10%)", f"(≤{p['dd_exit']:.0%})"))
    return reason, trigger


_orig_reason = pt._regime_reason


@contextlib.contextmanager
def shadow_patches(backfill=False):
    """Point paper_trader at this book for the duration, then restore."""
    saved = {k: getattr(pt, k) for k in list(PATHS) + ["_journal_header", "_regime_reason",
                                                      "_append_jsonl"]}
    saved_bear = config.BEAR
    orig_append = pt._append_jsonl

    def append(rec):
        rec = dict(rec, book=BOOK, official=False, params=dict(OVERRIDE))
        if backfill:
            rec["backfilled_at_launch"] = True
        orig_append(rec)

    try:
        for k, v in PATHS.items():
            setattr(pt, k, v)
        pt._journal_header = _journal_header
        pt._regime_reason = _regime_reason
        pt._append_jsonl = append
        config.BEAR = dict(saved_bear, **OVERRIDE)
        yield
    finally:
        config.BEAR = saved_bear
        for k, v in saved.items():
            setattr(pt, k, v)


def _official_first_candle():
    if not os.path.exists(OFFICIAL_JSONL):
        return None
    with open(OFFICIAL_JSONL) as f:
        first = f.readline().strip()
    return json.loads(first)["candle_t"] if first else None


def run(mode="long_flat"):
    if not os.path.exists(PATHS["JSONL_PATH"]):
        anchor = _official_first_candle()
        if anchor:
            # backfill: anchor at the official first candle (data up to it only)
            fetch = pt.le.fetch_closed_daily
            pt.le.fetch_closed_daily = lambda c, count=600: [
                b for b in fetch(c, count + 40) if b["t"] <= anchor][-count:]
            try:
                with shadow_patches(backfill=True):
                    pt.process(mode)
            finally:
                pt.le.fetch_closed_daily = fetch
            with shadow_patches(backfill=True):     # rest of the period so far
                pt.process(mode)
    with shadow_patches():
        n = pt.process(mode)
    compare.write()
    return n


def main():
    with tick_lock.exclusive("shadow_exit_book"):
        run()


if __name__ == "__main__":
    main()
