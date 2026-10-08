#!/usr/bin/env python3
"""End-of-period evaluation of every paper book -> paper_trading/PERIOD_REPORT.md.

The official ~1-month paper period started 2026-09-25 (first candle 2026-09-24)
and is due for a final verdict around 2026-10-24. This report is regenerated on
every daily paper tick, so the final numbers are ready the moment the period
ends; no leader turn has to compute anything.

Read-only on every ledger. Deterministic. Books compared:
  * official long_flat dd 20%/10%           (paper_log.jsonl, official=true)
  * shadow dd 12.5%/5%                      (shadow_exit_book/, official=false)
  * ensemble shadow books                   (ensemble_books/<book>/, official=false;
                                             these start later, 2026-10-04)
  * BTC buy-and-hold benchmark over the same candles, same fee+slippage.

SAFETY: research/PAPER only; reads files, no network, no orders.
Usage: python3 paper_trading/period_report.py
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "PERIOD_REPORT.md")
CAPITAL = 1_000_000.0
COST = 0.001                      # fee 0.05% + slippage 0.05%, entry side
PERIOD_START = "2026-09-24"       # first official candle
PERIOD_END = "2026-10-24"         # planned verdict date (~1 month)


def _jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _mdd(equity):
    peak, worst = None, 0.0
    for e in equity:
        peak = e if peak is None else max(peak, e)
        worst = max(worst, 1 - e / peak)
    return worst


def stats(name, official, days, equity, trades, note=""):
    """days/equity are aligned end-of-day series (equity in KRW)."""
    if not equity:
        return {"name": name, "official": official, "days": 0, "note": note or "no records yet"}
    return {"name": name, "official": official, "days": len(days), "first": days[0],
            "last": days[-1], "equity": equity[-1], "ret": equity[-1] / CAPITAL - 1,
            "mdd": _mdd([CAPITAL] + equity), "trades": trades, "note": note}


def daily_book(name, path, official):
    recs = _jsonl(path)
    days = [r["candle_t"][:10] for r in recs]
    eq = [r["equity_krw"] for r in recs]
    trades = sum(1 for r in recs if r.get("action") in ("BUY", "SELL"))
    flat = sum(1 for r in recs if r.get("position_after") == "FLAT")
    return stats(name, official, days, eq, trades, f"FLAT on {flat}/{len(recs)} days"), recs


def ensemble_book(path, name):
    recs = _jsonl(path)
    return stats(name + " (d0)", False, [r["day"] for r in recs], [r["equity_d0_krw"] for r in recs],
                 sum(len(r["trades_d0"]) for r in recs),
                 "d5 equity %s KRW; launched 2026-10-04" % (
                     f"{recs[-1]['equity_d5_krw']:,.0f}" if recs else "-"))


def buy_and_hold(path, first_day, last_day):
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            next(f)
            for line in f:
                t, o, h, l, c = line.strip().split(",")
                if first_day <= t[:10] <= last_day:
                    rows.append((t[:10], float(o), float(c)))
    if not rows:
        return stats("BTC buy-and-hold", False, [], [], 0)
    units = CAPITAL * (1 - COST) / rows[0][1]       # buy at the first candle's open
    return stats("BTC buy-and-hold (benchmark)", False, [r[0] for r in rows],
                 [units * r[2] for r in rows], 1, "bought at first candle open, never sold")


def divergences(off, sh):
    s = {r["candle_t"]: r for r in sh}
    return [r["candle_t"][:10] for r in off if r["candle_t"] in s and
            (r["target"], r["action"]) != (s[r["candle_t"]]["target"], s[r["candle_t"]]["action"])]


def build(now=None):
    now = now or datetime.now(timezone.utc)
    off, off_recs = daily_book("official long_flat dd 20%/10%", os.path.join(HERE, "paper_log.jsonl"), True)
    sh, sh_recs = daily_book("shadow exit dd 12.5%/5%",
                             os.path.join(HERE, "shadow_exit_book", "paper_log.jsonl"), False)
    rows = [off, sh]
    eb = os.path.join(HERE, "ensemble_books")
    if os.path.isdir(eb):
        for name in sorted(os.listdir(eb)):
            p = os.path.join(eb, name, "paper_log.jsonl")
            if os.path.exists(p):
                rows.append(ensemble_book(p, name))
    last = off.get("last", PERIOD_START)
    rows.append(buy_and_hold(os.path.join(HERE, "market_data_daily.csv"), PERIOD_START, last))
    div = divergences(off_recs, sh_recs)

    done = last >= PERIOD_END
    L = ["# Paper period report (all books)", "",
         f"Generated {now:%Y-%m-%dT%H:%MZ} by period_report.py (read-only, deterministic).",
         f"Period: {PERIOD_START} .. {PERIOD_END} (planned). Latest official candle: {last}. "
         + ("**PERIOD COMPLETE: these are the final numbers.**" if done else
            f"In progress: day {off.get('days', 0)} of ~31; numbers are interim."), "",
         "| book | official | days | first..last | equity KRW | return | max DD | trades | note |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["days"]:
            L.append(f"| {r['name']} | {str(r['official']).lower()} | 0 | - | - | - | - | - | {r['note']} |")
            continue
        L.append(f"| {r['name']} | {'**true**' if r['official'] else 'false'} | {r['days']} | "
                 f"{r['first']}..{r['last']} | {r['equity']:,.0f} | {r['ret']:+.2%} | {r['mdd']:.2%} | "
                 f"{r['trades']} | {r['note']} |")
    L += ["", f"Official vs 12.5/5 decision divergences: {len(div)}"
          + (f" ({', '.join(div)})" if div else " (identical decisions so far)"), "",
          "Reading guide:",
          "- The ensemble books start 2026-10-04, so their returns cover fewer days than the official book.",
          "- One month is far too short to separate skill from luck (Cycle 11 power analysis). "
          "Use this as an operations check, not as proof of edge.",
          "- Max DD is measured on end-of-day equity from the 1,000,000 KRW start.", ""]
    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    return rows, div


def main():
    rows, div = build()
    for r in rows:
        if r["days"]:
            print(f"{r['name']}: {r['equity']:,.0f} KRW ({r['ret']:+.2%}, mdd {r['mdd']:.2%}, {r['days']}d)")
    print(f"divergences official vs 12.5/5: {len(div)} -> {OUT}")


if __name__ == "__main__":
    main()
