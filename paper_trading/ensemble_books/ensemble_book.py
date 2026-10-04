#!/usr/bin/env python3
"""SHADOW paper books for EVOLVED ensemble candidates (owner mission
2026-10-04, Cycle 31). NOT the official paper ledger: every record is
official=false.

Each book in candidates.json is a FROZEN genome picked by
research/evolution/evolve.py (walk-forward + untouched holdout). It runs
forward from its launch hour on closed public 1h candles, with exactly the
backtest code (research/evolution/lab.py), so the forward record is directly
comparable to the backtest:
  * book capital 1,000,000 KRW, exposure capped at 1,000,000 KRW, long-only,
    no leverage (weights sum <= 1);
  * fee 0.05% + slippage 0.05% per side;
  * two fills tracked side by side: d0 = next-hour open after the signal bar
    closes, d5 = the repo's 5h blind window (config.MAX_BLIND_HOURS).
The book is recomputed deterministically from launch on every tick (no state
to corrupt) and one record per closed UTC day is appended to the book's
paper_log.jsonl. Re-running is idempotent.

Driven by daemon_4h.sh (token-free). Never touches the official book
(paper_trading/paper_log.jsonl) or the 12.5/5 shadow book.

SAFETY: research/PAPER only. Public read-only candles; no keys, no account,
no orders.

Usage: python3 paper_trading/ensemble_books/ensemble_book.py [--no-fetch]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PT = os.path.dirname(HERE)
ROOT = os.path.dirname(PT)
sys.path.insert(0, os.path.join(ROOT, "research", "evolution"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import lab  # noqa: E402

CANDIDATES = os.path.join(HERE, "candidates.json")
CAPITAL = 1_000_000.0
CAP = 1_000_000.0                 # config.MAX_EXPOSURE_KRW
DAILY_LOSS_LIMIT = 50_000.0       # config.DAILY_LOSS_LIMIT_KRW (flagged per day)


LATEST = os.path.join(ROOT, "research", "evolution", "results", "latest.json")
MAX_EVOLVED = 3                   # at most this many auto-promoted evolved books


def promote(path=CANDIDATES, latest=LATEST, now=None):
    """Token-free promotion: every evolved candidate that passed the
    pre-registered survival rule (evolve.SURVIVE) in the latest run becomes a
    NEW frozen shadow book launched now (never replaces or edits an existing
    book). Returns the names added."""
    if not os.path.exists(latest):
        return []
    with open(latest) as f:
        res = json.load(f)
    data = {"books": []}
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
    have = {b.get("key") for b in data["books"]}
    n_evo = sum(1 for b in data["books"] if b.get("kind") == "evolved")
    now = now or datetime.now(timezone.utc)
    launch = now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00")
    added = []
    for c in res.get("candidates", []):
        if not c.get("survives") or c["key"] in have or n_evo >= MAX_EVOLVED:
            continue
        name = f"evo_{res['generated_utc'][:10].replace('-', '')}_c{c['rank']}"
        ho = c["holdout"]["d5"]
        data["books"].append({
            "name": name, "kind": "evolved", "key": c["key"], "desc": c["desc"],
            "genome": c["genome"], "launch_utc": launch, "official": False,
            "evidence": f"run {res['generated_utc']}: holdout d5 CAGR {ho['cagr']:+.1%}, "
                        f"MDD {ho['mdd']:.1%}, Sharpe {ho['sharpe']:.2f}; DSR {c['dsr']:.2f}"})
        have.add(c["key"])
        n_evo += 1
        added.append(name)
    if added:
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
    return added


def load_books(path=CANDIDATES):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)["books"]


def _last_day(log_path):
    last = None
    if os.path.exists(log_path):
        with open(log_path) as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["day"]
    return last


def run_book(mk, L, b, out_dir):
    """Recompute book `b` from its launch; append new closed days. Returns a
    status dict for COMPARE.md."""
    os.makedirs(out_dir, exist_ok=True)
    h0 = mk.hour_of(b["launch_utc"])
    st = {"name": b["name"], "desc": b["desc"], "launch_utc": b["launch_utc"]}
    if mk.n <= h0:
        st.update(status="waiting for first closed hour after launch", equity_d0=CAPITAL,
                  equity_d5=CAPITAL, weights=[0.0] * lab.A, trades_d0=0, days=0)
        return st
    ev = L.events(b["genome"])
    band = b["genome"].get("band", 0.0)
    r = {d: lab.simulate(mk, ev, h0, mk.n, delay=d, band=band, capital=CAPITAL,
                         cap=CAP, record=True) for d in (0, 5)}
    eq0 = dict((h, e) for h, e in r[0].get("eq", []))
    eq5 = dict((h, e) for h, e in r[5].get("eq", []))
    log_path = os.path.join(out_dir, "paper_log.jsonl")
    last = _last_day(log_path)
    day_marks = [m for m in mk.day_marks if h0 < m <= mk.n]
    prev_h, new = h0, 0
    with open(log_path, "a") as f:
        for m in day_marks:
            day = (mk.time_of(m - 24)).strftime("%Y-%m-%d") if m - 24 >= h0 else \
                mk.time_of(h0).strftime("%Y-%m-%d")
            e_prev0 = eq0.get(prev_h, CAPITAL)
            e0, e5 = eq0.get(m), eq5.get(m)
            if e0 is None:
                prev_h = m
                continue
            if last is None or day > last:
                trades = [t for t in r[0].get("log", []) if prev_h <= t["hour"] < m]
                rec = {"book": b["name"], "official": False, "day": day,
                       "logged_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "equity_d0_krw": round(e0, 0), "equity_d5_krw": round(e5 or 0, 0),
                       "ret_d0_pct": round((e0 / CAPITAL - 1) * 100, 3),
                       "ret_d5_pct": round(((e5 or CAPITAL) / CAPITAL - 1) * 100, 3),
                       "day_pnl_d0_krw": round(e0 - e_prev0, 0),
                       "daily_loss_limit_hit": (e_prev0 - e0) > DAILY_LOSS_LIMIT,
                       "trades_d0": [{"asset": t["asset"], "side": t["side"],
                                      "price": t["price"], "krw": round(t["notional"], 0)}
                                     for t in trades]}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                new += 1
            prev_h = m
    st.update(status="running", equity_d0=r[0]["final_equity"], equity_d5=r[5]["final_equity"],
              weights=r[0]["final_w"], trades_d0=r[0]["trades"], trades_d5=r[5]["trades"],
              days=len(day_marks), new_records=new,
              asof=mk.time_of(mk.n).strftime("%Y-%m-%dT%H:%MZ"))
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as f:
        f.write(_summary(st, b, [dict(t, time=mk.time_of(t["hour"]).strftime("%Y-%m-%d %H:%M"))
                                 for t in r[0].get("log", [])]))
    return st


def _fmt_w(w):
    held = [f"{lab.UNIVERSE[a].split('-')[1]} {x:.0%}" for a, x in enumerate(w) if x > 0.001]
    return ", ".join(held) if held else "FLAT (cash)"


def _summary(st, b, log):
    L = [f"# SHADOW ensemble book `{st['name']}` (official=false)", "",
         "공식 원장이 아님. 진화 탐색(research/evolution)에서 걸러진 후보를 동결해 forward로 굴리는 그림자 장부.",
         f"- launched: {st['launch_utc']} UTC, as of {st.get('asof', '-')}",
         f"- strategy: `{st['desc']}`",
         f"- equity d0 (next-hour fill): {st['equity_d0']:,.0f} KRW ({(st['equity_d0'] / CAPITAL - 1):+.2%})",
         f"- equity d5 (5h blind window): {st['equity_d5']:,.0f} KRW ({(st['equity_d5'] / CAPITAL - 1):+.2%})",
         f"- position now: {_fmt_w(st['weights'])}",
         f"- trades (d0): {st['trades_d0']}",
         f"- selection evidence: {b.get('evidence', '-')}", "", "## Trades (d0)", "",
         "| time (UTC) | asset | side | price | KRW |", "|---|---|---|---|---|"]
    for t in log[-50:]:
        L.append(f"| {t['time']} | {t['asset']} | {t['side']} | {t['price']:,.0f} | {t['notional']:,.0f} |")
    return "\n".join(L) + "\n"


def _official_like(path):
    """Last equity of a daily-candle paper ledger (official / 12.5-5 shadow)."""
    last = None
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)
    return last


def write_compare(statuses):
    off = _official_like(os.path.join(PT, "paper_log.jsonl"))
    sh = _official_like(os.path.join(PT, "shadow_exit_book", "paper_log.jsonl"))
    L = ["# All paper books side by side", "",
         f"Generated {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ} by ensemble_book.py. "
         "Only the first row is the OFFICIAL book; everything else is official=false.", "",
         "| book | official | equity KRW | return | position | as of |", "|---|---|---|---|---|---|"]
    for name, rec, flag in (("official long_flat dd 20%/10%", off, "**true**"),
                            ("shadow exit dd 12.5%/5%", sh, "false")):
        if rec:
            L.append(f"| {name} | {flag} | {rec['equity_krw']:,.0f} | {rec['cum_return_pct']:+.2f}% | "
                     f"{rec['position_after']} | candle {rec['candle_t'][:10]} |")
    for s in statuses:
        L.append(f"| {s['name']} (d0 / d5) | false | {s['equity_d0']:,.0f} / {s['equity_d5']:,.0f} | "
                 f"{(s['equity_d0'] / CAPITAL - 1) * 100:+.2f}% / {(s['equity_d5'] / CAPITAL - 1) * 100:+.2f}% | "
                 f"{_fmt_w(s['weights'])} | {s.get('asof', s['status'])} |")
    L += ["", "Ensemble books start at their own launch time (not 2026-09-24), so compare "
          "returns over the same dates only from the ensemble launch onward.", ""]
    for s in statuses:
        L.append(f"- `{s['name']}`: {s['desc']}")
    with open(os.path.join(HERE, "COMPARE.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    for name in promote():
        print(f"promoted evolved survivor -> new shadow book {name}")
    books = load_books()
    if not books:
        print("no ensemble shadow books configured (candidates.json empty)")
        return
    if not a.no_fetch:
        sys.path.insert(0, os.path.join(ROOT, "research", "evolution"))
        import data_1h
        from upbit_client import UpbitClient
        client = UpbitClient("", "")          # PUBLIC read-only; no keys, no orders
        for m in lab.UNIVERSE:
            try:
                data_1h.update(m, client)
            except Exception as e:  # a failed refresh must not stop the books
                print(f"WARN 1h refresh {m}: {e}")
    mk = lab.Market()
    L = lab.Lab(mk)
    statuses = []
    for b in books:
        try:
            statuses.append(run_book(mk, L, b, os.path.join(HERE, b["name"])))
        except Exception as e:
            print(f"book {b['name']} FAILED: {e!r}")
    lines = write_compare(statuses)
    for s in statuses:
        print(f"{s['name']}: d0 {s['equity_d0']:,.0f} / d5 {s['equity_d5']:,.0f} KRW  "
              f"pos {_fmt_w(s['weights'])}  (+{s.get('new_records', 0)} day records)")
    return lines


if __name__ == "__main__":
    main()
