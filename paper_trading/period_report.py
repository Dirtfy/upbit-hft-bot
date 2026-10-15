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
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
from regime import dd_label  # noqa: E402
OUT = os.path.join(HERE, "PERIOD_REPORT.md")
CAPITAL = 1_000_000.0
COST = 0.001                      # fee 0.05% + slippage 0.05%, entry side
PERIOD_START = "2026-09-24"       # first official candle
PERIOD_END = "2026-10-24"         # planned verdict date (~1 month)


def in_period(day):
    """Only candles PERIOD_START..PERIOD_END count. The daemons keep appending
    after the period ends; those days must not move the FINAL numbers."""
    return PERIOD_START <= day[:10] <= PERIOD_END


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


def _ledger_label(path):
    """Breaker label of the ledger's latest record (records carry `params`)."""
    recs = _jsonl(path)
    return dd_label(recs[-1].get("params") if recs else None)


def daily_book(name, path, official):
    recs = [r for r in _jsonl(path) if in_period(r["candle_t"])]
    days = [r["candle_t"][:10] for r in recs]
    eq = [r["equity_krw"] for r in recs]
    trades = sum(1 for r in recs if r.get("action") in ("BUY", "SELL"))
    flat = sum(1 for r in recs if r.get("position_after") == "FLAT")
    return stats(name, official, days, eq, trades, f"FLAT on {flat}/{len(recs)} days"), recs


def ensemble_book(path, name):
    recs = [r for r in _jsonl(path) if in_period(r["day"])]
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


BTC_1H = os.path.join(os.path.dirname(HERE), "data", "1h", "KRW-BTC.csv")


def daily_closes_from_1h(path=BTC_1H):
    """UTC-day closes (= close of the 23:00 hourly candle), full days only."""
    out = {}
    if not os.path.exists(path):
        return []
    with open(path) as f:
        next(f)
        for line in f:
            t, _o, _h, _l, c = line.split(",")[:5]
            if t[11:13] == "23":
                out[t[:10]] = float(c)
    return sorted(out.items())


def reentry_price(closes, k, p):
    """Lowest constant BTC close P from tomorrow on that makes regime.py say
    "bull" (close > SMA and drawdown <= dd_exit) on the k-th future day. With
    every new close equal to P this is exact: SMA uses the known closes that are
    still in its window, and the trailing high is the known closes still in the
    dd window (P itself never makes a drawdown)."""
    n_sma, win = p["sma_long"], p["dd_window"]
    known_sma = closes[-(n_sma - k):] if k < n_sma else []
    sma_floor = sum(known_sma) / len(known_sma) if known_sma else 0.0
    known_hi = closes[-(win - k):] if k < win else []
    hi_floor = max(known_hi) * (1 - p["dd_exit"]) if known_hi else 0.0
    return max(sma_floor, hi_floor)


def reentry_outlook(books, horizon_to=PERIOD_END, closes=None):
    """How far BTC must rise (and stay) for each FLAT daily book to re-enter."""
    closes = closes if closes is not None else daily_closes_from_1h()
    if len(closes) < 400:
        return ["Re-entry outlook: n/a (data/1h/KRW-BTC.csv missing or too short)."]
    last_day, vals = closes[-1][0], [c for _, c in closes]
    d0 = date.fromisoformat(last_day)
    k_end = max(1, (date.fromisoformat(horizon_to) - d0).days)
    L = [f"## Re-entry outlook (from BTC close {vals[-1]:,.0f} on {last_day})", "",
         "Lowest BTC daily close that, held from tomorrow on, would switch a FLAT book to long "
         "(regime.py: close > SMA200 AND within dd_exit of the 365-day high).", "",
         "| book | dd_exit | needed by tomorrow | needed by " + horizon_to + " | rise needed by "
         + horizon_to + " |", "|---|---|---|---|---|"]
    for name, p in books:
        a, b = reentry_price(vals, 1, p), reentry_price(vals, k_end, p)
        L.append(f"| {name} | {p['dd_exit']:.0%} | {a:,.0f} | {b:,.0f} | {b / vals[-1] - 1:+.1%} |")
    # when does the 365-day high leave the window (the main reason the bar drops)
    win = books[0][1]["dd_window"]
    i_hi = max(range(len(vals) - win, len(vals)), key=lambda i: vals[i])
    out_day = date.fromisoformat(closes[i_hi][0]) + timedelta(days=win)
    L += ["", f"The 365-day high {vals[i_hi]:,.0f} ({closes[i_hi][0]}) leaves the window on {out_day}. "
          "The prices above already account for highs leaving the window.", ""]
    return L


OUTAGES = os.path.join(os.path.dirname(HERE), "logs", "daemon_outages.log")
LATE_S = 2 * 3600                 # a record logged >2h after its candle closed is "late"
# outage-ledger entries annotated in the log itself as FALSE positives (Cycle 27:
# cross-container PID-namespace mismatch, not downtime)
FALSE_OUTAGES = ("2026-10-01T10:40:02Z", "2026-10-01T13:19:30Z", "2026-10-01T13:19:31Z",
                 "2026-10-01T13:20:02Z")


def integrity(off, sh, outages_path=OUTAGES, h4_path=os.path.join(HERE, "market_data_4h.csv")):
    """Operational soundness of the period, read-only: candle coverage of both
    daily ledgers (one record per day, no gap/duplicate), identical data in both
    books, late records, 4h trail gaps, daemon outages inside the period."""
    def coverage(recs):
        d = [r["candle_t"][:10] for r in recs]
        days = sorted(date.fromisoformat(x) for x in set(d))
        gaps = [f"{a}..{b}" for a, b in zip(days, days[1:]) if (b - a).days != 1]
        late = [r["candle_t"][:10] for r in recs
                if (datetime.fromisoformat(r["logged_at_utc"][:19])
                    - datetime.fromisoformat(r["candle_t"][:19])).total_seconds() > 86400 + LATE_S
                and not r.get("backfilled_at_launch")]
        return len(d), len(d) - len(set(d)), gaps, late
    rows = []
    for name, recs in (("official", off), ("shadow 12.5/5", sh)):
        n, dup, gaps, late = coverage(recs)
        rows.append(f"| {name} daily ledger | {n} candles, {dup} duplicates, "
                    f"{len(gaps)} gaps{' (' + ', '.join(gaps) + ')' if gaps else ''} | "
                    f"{len(late)} late (>2h){': ' + ', '.join(late) if late else ''} |")
    s = {r["candle_t"]: r["close"] for r in sh}
    mism = sorted({r["candle_t"][:10] for r in off if r["candle_t"] in s and s[r["candle_t"]] != r["close"]})
    rows.append(f"| same data in both books | {len(mism)} close mismatches"
                f"{' (' + ', '.join(mism) + ')' if mism else ''} | |")
    t = []
    if os.path.exists(h4_path):
        with open(h4_path) as fh:
            next(fh, None)
            t = [datetime.fromisoformat(line.split(",", 1)[0][:19]) for line in fh if line.strip()]
    t = [x for x in t if in_period(x.isoformat())]
    g4 = sum((b - a) != timedelta(hours=4) for a, b in zip(t, t[1:]))
    rows.append(f"| 4h candle trail | {len(t)} candles in period, {g4} gaps | |")
    outs = []
    if os.path.exists(outages_path):
        outs = [line for line in open(outages_path)
                if line[:1].isdigit() and in_period(line) and "down_at_most=" in line]
    false = [x for x in outs if x.split()[0] in FALSE_OUTAGES]
    real = [x for x in outs if x not in false]
    mins = sum(int(x.split("down_at_most=")[1].split("s")[0]) for x in real) / 60
    last = max((x.split()[0][:10] for x in real), default="-")
    rows.append(f"| daemon outages (self-healed) | {len(real)} real (last {last}), "
                f"{len(false)} logged false positives excluded; downtime upper bound ~{mins / 60:.1f} h | "
                "no missed decision: ledgers above have no gaps |")
    return (["", "## Operational integrity (period to date)", "",
             "| check | result | note |", "|---|---|---|"] + rows +
            ["", "Late records before the daemons existed (Cycles 22-24) were run by hand; "
             "the shadow book's launch backfill is excluded. A late record still uses the closed candle "
             "of its day, so decisions are unaffected."])


def divergences(off, sh):
    s = {r["candle_t"]: r for r in sh}
    return [r["candle_t"][:10] for r in off if r["candle_t"] in s and
            (r["target"], r["action"]) != (s[r["candle_t"]]["target"], s[r["candle_t"]]["action"])]


def build(now=None):
    now = now or datetime.now(timezone.utc)
    off_path = os.path.join(HERE, "paper_log.jsonl")
    sh_path = os.path.join(HERE, "shadow_exit_book", "paper_log.jsonl")
    off, off_recs = daily_book(f"official long_flat dd {_ledger_label(off_path)}", off_path, True)
    sh, sh_recs = daily_book(f"shadow exit dd {_ledger_label(sh_path)}", sh_path, False)
    rows = [off, sh]
    eb = os.path.join(HERE, "ensemble_books")
    if os.path.isdir(eb):
        for name in sorted(os.listdir(eb)):
            p = os.path.join(eb, name, "paper_log.jsonl")
            if os.path.exists(p):
                rows.append(ensemble_book(p, name))
    last = off.get("last", PERIOD_START)
    rows.append(buy_and_hold(os.path.join(HERE, "market_data_daily.csv"), PERIOD_START, min(last, PERIOD_END)))
    post = sum(1 for r in _jsonl(off_path) if r["candle_t"][:10] > PERIOD_END)
    div = divergences(off_recs, sh_recs)

    done = last >= PERIOD_END
    L = ["# Paper period report (all books)", "",
         f"Generated {now:%Y-%m-%dT%H:%MZ} by period_report.py (read-only, deterministic).",
         f"Period: {PERIOD_START} .. {PERIOD_END} (planned). Latest official candle: {last}. "
         + ("**PERIOD COMPLETE: these are the final numbers.**"
            + (f" {post} later official candle(s) are excluded; the books keep running "
               "(see each book's SUMMARY.md)." if post else "") if done else
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
    try:
        L += integrity(off_recs, sh_recs)
    except Exception as e:  # informational; never fail the report
        L.append(f"Integrity section unavailable: {e!r}")
    try:
        import config
        if not done:  # after the period the outlook's horizon is in the past
            L += reentry_outlook([(f"official {dd_label(config.BEAR)}", config.BEAR),
                                  (f"shadow {_ledger_label(sh_path)}",
                                   dict(config.BEAR, dd_enter=0.125, dd_exit=0.05))])
    except Exception as e:  # the outlook is informational; never fail the report
        L.append(f"Re-entry outlook unavailable: {e!r}")
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
