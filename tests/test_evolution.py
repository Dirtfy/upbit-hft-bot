#!/usr/bin/env python3
"""Cycle 31: strategy-evolution lab + ensemble shadow books.

Guards: no sleeve looks ahead (signals up to hour h are identical whether or not
later data exists); the search Market physically excludes the holdout; the
simulator charges fee+slippage on every fill, respects the delay and never
exceeds 100% gross exposure; an ensemble's weights sum <= 1; the deflated
Sharpe falls as trials grow; GA operators stay on the grids; the ensemble shadow
book is idempotent, labelled official=false, caps exposure at 1M KRW and never
writes the official or 12.5/5 shadow ledgers. Synthetic candles, no network.

Plain asserts (no pytest): run with `python3 tests/test_evolution.py`.
"""
import json
import math
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "evolution"))
sys.path.insert(0, os.path.join(ROOT, "paper_trading", "ensemble_books"))
import lab              # noqa: E402
import ensemble_book as eb  # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


REAL = [os.path.join(ROOT, "paper_trading", p) for p in (
    "paper_log.jsonl", "JOURNAL.md", "SUMMARY.md",
    "shadow_exit_book/paper_log.jsonl", "shadow_exit_book/JOURNAL.md")]
before = [open(p, "rb").read() if os.path.exists(p) else None for p in REAL]


def synth(tmp, days=700, seed=7):
    """Random-walk hourly candles for every UNIVERSE market (SOL listed late)."""
    rng = random.Random(seed)
    t0 = datetime(2019, 1, 1)
    for k, m in enumerate(lab.UNIVERSE):
        p = 1000.0 * (k + 1)
        start = 24 * 200 if m == "KRW-SOL" else 0
        with open(os.path.join(tmp, f"{m}.csv"), "w") as f:
            f.write("time_utc,open,high,low,close,volume\n")
            for i in range(days * 24):
                o = p
                p = max(1.0, p * math.exp(rng.gauss(0.0001, 0.01)))
                if i < start:
                    continue
                hi, lo = max(o, p) * 1.002, min(o, p) * 0.998
                f.write(f"{(t0 + timedelta(hours=i)).isoformat()},{o},{hi},{lo},{p},1\n")
    return t0


tmp = tempfile.mkdtemp()
try:
    t0 = synth(tmp)
    mk = lab.Market(tmp)
    check("hourly grid + daily/4h resample aligned", len(mk.d["c"]) == 700 and len(mk.h4["c"]) == 4200)
    check("unlisted asset is None before listing", mk.close[3][0] is None and mk.close[3][-1] is not None)

    # ---- no lookahead: truncate the data, signals before the cut must match
    cut = (t0 + timedelta(days=500)).isoformat()
    mk_cut = lab.Market(tmp, end=cut)
    hc = mk_cut.n
    rng = random.Random(1)
    ok = True
    for name, (fn, space) in lab.SLEEVES.items():
        for _ in range(4):
            p = {k: rng.choice(v) for k, v in space.items()}
            full = [e for e in fn(mk, **p) if e[0] <= hc - 1]
            part = [e for e in fn(mk_cut, **p) if e[0] <= hc - 1]
            if full != part:
                ok = False
                print("    lookahead in", name, p)
    check("no sleeve uses data after the signal hour (truncation test)", ok)
    check("search Market physically excludes later data", mk_cut.n < mk.n
          and mk_cut.time_of(mk_cut.n) <= datetime.fromisoformat(cut).replace(tzinfo=mk.t0.tzinfo))

    # ---- simulator: cost and delay
    ev = [(100, lab.LONG_BTC), (200, lab.ZERO)]
    r0 = lab.simulate(mk, ev, 0, 300, delay=0, cost=0.001, record=True)
    gross = mk.c[199] / mk.c[99]
    check("round trip pays fee+slippage on both sides",
          abs(r0["final_equity"] - gross * (1 - 0.001) / (1 + 0.001) * 1) < 2e-3 * gross
          and len(r0["log"]) == 2)
    r5 = lab.simulate(mk, ev, 0, 300, delay=5, cost=0.0, record=True)
    check("delay=5 fills 5 hours later", [t["hour"] for t in r5["log"]] == [105, 205])
    rz = lab.simulate(mk, ev, 0, 300, delay=0, cost=0.0)
    check("zero cost round trip == price ratio", abs(rz["final_equity"] - gross) < 1e-9)

    # ---- ensembles stay long-only, unlevered
    L = lab.Lab(mk)
    rng = random.Random(3)
    worst = 0.0
    for _ in range(25):
        g = lab.random_genome(rng)
        for _, w in L.events(g):
            worst = max(worst, sum(w))
            assert min(w) >= 0
    check("ensemble gross weight <= 1 and >= 0", worst <= 1.0 + 1e-9)
    g = lab.random_genome(rng)
    for _ in range(50):
        g = lab.mutate(lab.crossover(g, lab.random_genome(rng), rng), rng)
    on_grid = all(g["p"][n][k] in v for n, (_, sp) in lab.SLEEVES.items() for k, v in sp.items()) \
        and all(g[k] in v for k, v in lab.META_SPACE.items()) \
        and all(w in lab.WEIGHT_GRID for w in g["w_bull"] + g["w_side"])
    check("GA operators stay on the discrete grids (countable trials)", on_grid)
    r = L.evaluate(lab.fixed_genome("hold", {}, gate="dd20_10"), 0, mk.n)
    check("gated hold is flat during regime warmup", r["trades"] <= 1 or r["exposure"] < 1)

    # ---- deflated Sharpe: more trials -> lower probability
    rets = [random.Random(5).gauss(0.001, 0.02) for _ in range(1500)]
    d10 = lab.deflated_sharpe(1.0, rets, 10, 0.25)
    d5000 = lab.deflated_sharpe(1.0, rets, 5000, 0.25)
    check("DSR decreases with the number of trials", 0 <= d5000 < d10 <= 1)

    # ---- ensemble shadow book: idempotent, official=false, capped, isolated
    out = os.path.join(tmp, "book")
    launch = (t0 + timedelta(days=650, hours=7)).isoformat()
    b = {"name": "t_book", "desc": "test", "launch_utc": launch,
         "genome": lab.fixed_genome("tsmom", {"tf": "1d", "days": 10})}
    st = eb.run_book(mk, L, b, out)
    recs = [json.loads(x) for x in open(os.path.join(out, "paper_log.jsonl"))]
    check("book writes one record per closed day after launch", len(recs) == 50)
    check("every record official=false and labelled", all(r["official"] is False and r["book"] == "t_book"
                                                          for r in recs))
    eb.run_book(mk, L, b, out)
    recs2 = [json.loads(x) for x in open(os.path.join(out, "paper_log.jsonl"))]
    check("rerun is idempotent (no duplicate days)", len(recs2) == len(recs))
    # a fill exactly at a day boundary must not move that day's (already logged) mark
    evb = [(240, lab.LONG_BTC), (480, lab.ZERO)]
    short = lab.simulate(mk, evb, 0, 480, cost=0.001)["final_equity"]
    longer = dict(lab.simulate(mk, evb, 0, 600, cost=0.001, record=True)["eq"])[480]
    check("day mark excludes fills at the mark hour (append-only safe)", abs(short - longer) < 1e-9)
    st2 = eb.run_book(mk, L, b, out)
    check("replay of logged history is consistent", st2["consistent"] and st2["drift_krw"] == 0)
    lp = os.path.join(out, "paper_log.jsonl")
    lines = open(lp).read().splitlines()
    r0_ = json.loads(lines[3]); r0_["equity_d0_krw"] += 5000
    lines[3] = json.dumps(r0_)
    open(lp, "w").write("\n".join(lines) + "\n")
    st3 = eb.run_book(mk, L, b, out)
    check("tampered/revised history is flagged as drift", not st3["consistent"] and st3["drift_krw"] == 5000)
    big = max((t["krw"] for r in recs for t in r["trades_d0"] if t["side"] == "BUY"), default=0)
    check("no BUY deploys more than the 1,000,000 KRW cap", 0 < big <= 1_000_000 + 1)
    check("book starts with 1,000,000 KRW", abs(recs[0]["equity_d0_krw"] - 1_000_000) < 60_000)

    # ---- token-free promotion: only pre-registered survivors, max 3, idempotent
    def cand(rank, survives):
        g = lab.fixed_genome("tsmom", {"tf": "1d", "days": 10 * rank})
        return {"rank": rank, "survives": survives, "key": lab.key(g), "desc": "x", "genome": g,
                "dsr": 0.5, "holdout": {"d5": {"cagr": 0.1, "mdd": 0.1, "sharpe": 1.0}}}
    latest = os.path.join(tmp, "latest.json")
    cpath = os.path.join(tmp, "candidates.json")
    json.dump({"generated_utc": "2026-10-04T00:00:00Z",
               "candidates": [cand(1, True), cand(2, False), cand(3, True)]}, open(latest, "w"))
    added = eb.promote(cpath, latest)
    check("promotion adds survivors only", added == ["evo_20261004_c1", "evo_20261004_c3"])
    check("promotion is idempotent", eb.promote(cpath, latest) == [])
    json.dump({"generated_utc": "2026-10-11T00:00:00Z",
               "candidates": [cand(4, True), cand(5, True)]}, open(latest, "w"))
    check("at most 3 evolved books", len(eb.promote(cpath, latest)) == 1)
    check("promoted books are official=false",
          all(b["official"] is False for b in json.load(open(cpath))["books"]))
finally:
    shutil.rmtree(tmp)

check("real official + 12.5/5 shadow ledgers byte-identical",
      before == [open(p, "rb").read() if os.path.exists(p) else None for p in REAL])

# ---- the weekly GA defers on a busy host and never spawns (no real run here)
import subprocess  # noqa: E402
sh = os.path.join(ROOT, "research", "evolution", "run_evolution.sh")
latest_real = os.path.join(ROOT, "research", "evolution", "results", "latest.json")
st_before = os.stat(latest_real).st_mtime if os.path.exists(latest_real) else None
env = dict(os.environ, EVOLVE_EVERY_DAYS="0", EVOLVE_MIN_MEM_MB="99999999")
out = subprocess.run(["bash", sh, "maybe"], env=env, capture_output=True, text=True).stdout
check("due run defers when memory is short", "deferred" in out and "spawned" not in out)
env = dict(os.environ, EVOLVE_EVERY_DAYS="0", EVOLVE_MIN_MEM_MB="0", EVOLVE_MAX_LOAD="-1")
out = subprocess.run(["bash", sh, "run"], env=env, capture_output=True, text=True).stdout
check("run defers when load is high (no GA started)", "deferred" in out and "START" in out
      and "END" not in out)
check("deferral leaves the GA results untouched",
      st_before == (os.stat(latest_real).st_mtime if os.path.exists(latest_real) else None))

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
