#!/usr/bin/env python3
"""Walk-forward EVOLUTION of strategy ensembles (Cycle 31) — token-free.

RESEARCH / PAPER ONLY. Runs as a standalone process (see run_evolution.sh,
spawned from the 4h daemon); a leader turn only READS its outputs.

Why a genetic algorithm (and not deep RL)
-----------------------------------------
The "RL-like loop" here is: propose ensembles -> score them by backtest ->
keep the best -> mutate/cross them -> repeat. A small (mu+lambda) GA over a
DISCRETE grid of sleeve parameters + mixing weights is the simplest thing that
does that. A real RL agent (policy over hourly actions) would need far more
data than ~7 years of one market to not overfit, can't be trained without
numpy on this host, and is much harder to audit. Discrete grids also make the
number of distinct configurations tried COUNTABLE, which the deflated Sharpe
ratio needs.

Overfitting controls
--------------------
1. HOLDOUT (HOLDOUT_START..now) is physically absent during every search: the
   search Market is loaded with end=HOLDOUT_START. It is evaluated ONCE, after
   the final candidates are frozen.
2. WALK-FORWARD: for each test year Y in WF_TEST_YEARS, evolve on
   [TRAIN_START, Y) and score the winner on year Y only. The stitched test
   years are the walk-forward out-of-sample (WFO-OOS) record.
3. Fitness is robust, not raw: for both fills (delay 0h and the repo's 5h blind
   window) take mean - 0.5*std of the Sharpe over 3 equal train sub-periods,
   then average the two. Costs: 0.05% fee + 0.05% slippage per side.
4. Every distinct configuration evaluated is counted; the deflated Sharpe ratio
   (Bailey & Lopez de Prado 2014) is reported for the final pick.
5. The survival rule (SURVIVE) is fixed in code BEFORE the holdout is run.

Usage:
    python3 research/evolution/evolve.py                  # full run (~10-30 min)
    python3 research/evolution/evolve.py --quick          # smoke test
Outputs -> research/evolution/results/{latest.json,RESULTS.md,history.jsonl}
"""
import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab  # noqa: E402

OUT = os.path.join(HERE, "results")
TRAIN_START = "2018-01-01T00:00:00"
HOLDOUT_START = "2025-01-01T00:00:00"
WF_TEST_YEARS = [2021, 2022, 2023, 2024]
DELAYS = (0, 5)


def SURVIVE(c):
    """Fixed before the holdout is looked at. A candidate survives out-of-sample
    when its walk-forward OOS Sharpe > 0, AND on the untouched holdout it makes
    money under BOTH fills, AND its holdout max drawdown is below buy-and-hold's."""
    return (c["wfo_family_sharpe"] > 0
            and c["holdout"]["d0"]["cagr"] > 0 and c["holdout"]["d5"]["cagr"] > 0
            and c["holdout"]["d5"]["mdd"] < c["bh_holdout_mdd"])


def fitness(L, g, s, e):
    sc, res = [], {}
    for d in DELAYS:
        r = L.evaluate(g, s, e, delay=d)
        res[d] = r
        if not r.get("rets"):
            return -9.0, res
        ss = lab.sub_sharpes(r["rets"], 3)
        m = sum(ss) / 3
        sd = math.sqrt(sum((x - m) ** 2 for x in ss) / 3)
        sc.append(m - 0.5 * sd)
    f = sum(sc) / len(sc)
    if res[0]["trades"] < 6:              # a "strategy" that never trades isn't one
        f -= 1.0
    return f, res


def seeds():
    """Hand seeds = the families as documented (and the repo's own books), so
    the search starts from known points rather than only noise."""
    S = [lab.fixed_genome("hold", {}, gate="dd20_10"),
         lab.fixed_genome("hold", {}, gate="dd12.5_5"),
         lab.fixed_genome("donchian", {"tf": "1d", "n_in": 20, "n_out": 20, "atr_k": 3}),
         lab.fixed_genome("tsmom", {"tf": "1d", "days": 60}),
         lab.fixed_genome("rotation", {"days": 30, "top_k": 2, "every": 7}),
         lab.fixed_genome("volbreak", {"k": 0.5, "ma_days": 5})]
    return S


def evolve(L, s, e, rng, pop_n, gens, trials, log=print, tag=""):
    """(mu+lambda) GA. Returns sorted [(fitness, genome, res)] of unique genomes."""
    seen = {}

    def score(g):
        k = lab.key(g)
        if k not in seen:
            f, res = fitness(L, g, s, e)
            seen[k] = (f, g, res)
            trials.add(k)
        return seen[k][0]

    pop = seeds() + [lab.random_genome(rng) for _ in range(pop_n - len(seeds()))]
    for g in pop:
        score(g)
    elite_n = max(2, pop_n // 8)
    for gen in range(gens):
        ranked = sorted(pop, key=lambda g: -score(g))
        nxt = ranked[:elite_n]
        while len(nxt) < pop_n:
            a = max(rng.sample(ranked, 3), key=score)
            b = max(rng.sample(ranked, 3), key=score)
            c = lab.crossover(a, b, rng) if rng.random() < 0.6 else a
            c = lab.mutate(c, rng)
            score(c)
            nxt.append(c)
        pop = nxt
        best = max(pop, key=score)
        log(f"  {tag} gen {gen + 1:>2}/{gens}: best fitness {score(best):+.3f} "
            f"(unique tried {len(seen)})")
    out = sorted(seen.values(), key=lambda x: -x[0])
    return out


def slim(r):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
            if k in ("cagr", "mdd", "sharpe", "trades", "turnover", "exposure", "total", "days")}


def stitched(daily_rets_list):
    eq, e = [1.0], 1.0
    for rets in daily_rets_list:
        for r in rets:
            e *= 1 + r
            eq.append(e)
    marks = list(enumerate(eq))
    return lab.metrics(marks, 0, 0.0, 0.0, 0.0)


def baselines():
    return {
        "buy_and_hold": lab.fixed_genome("hold", {}),
        "official_dd20_10": lab.fixed_genome("hold", {}, gate="dd20_10"),
        "shadow_dd12.5_5": lab.fixed_genome("hold", {}, gate="dd12.5_5"),
        "donchian20_20_atr3": lab.fixed_genome("donchian", {"tf": "1d", "n_in": 20,
                                                             "n_out": 20, "atr_k": 3}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", type=int, default=40)
    ap.add_argument("--gens", type=int, default=20)
    ap.add_argument("--seed", type=int, default=None,
                    help="default: 31 + number of previous runs (each weekly run explores anew)")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick:
        a.pop, a.gens = 10, 2
    os.makedirs(OUT, exist_ok=True)
    # Every earlier run also selected on the same data and LOOKED at the same
    # holdout, so trials are counted cumulatively across runs (DSR) and the
    # number of holdout looks is reported.
    prev = []
    hist_path = os.path.join(OUT, "history.jsonl")
    if os.path.exists(hist_path):
        prev = [json.loads(x) for x in open(hist_path) if x.strip()]
    if a.seed is None:
        a.seed = 31 + len(prev)
    prior_trials = sum(h.get("n_trials", 0) for h in prev)
    t_start = time.time()
    rng = random.Random(a.seed)
    trials = set()
    logf = open(os.path.join(OUT, "run.log"), "w")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    # ---------------- search universe: holdout physically absent
    mk_s = lab.Market(end=HOLDOUT_START)
    L_s = lab.Lab(mk_s)
    log(f"search data: {mk_s.t0:%F} .. {mk_s.time_of(mk_s.n):%F} (holdout from {HOLDOUT_START[:10]} NOT loaded)")
    t0 = mk_s.hour_of(TRAIN_START)

    # ---------------- walk-forward
    wf = []
    for y in WF_TEST_YEARS:
        ts, te = mk_s.hour_of(f"{y}-01-01T00:00:00"), mk_s.hour_of(f"{y + 1}-01-01T00:00:00")
        log(f"WFO fold: train {TRAIN_START[:10]}..{y}-01-01, test {y}")
        ranked = evolve(L_s, t0, ts, rng, a.pop, a.gens, trials, log, tag=f"[{y}]")
        f, g, res = ranked[0]
        test = {d: L_s.evaluate(g, ts, te, delay=d) for d in DELAYS}
        base = {n: L_s.evaluate(bg, ts, te, delay=5) for n, bg in baselines().items()}
        wf.append({"year": y, "fitness": f, "genome": g, "desc": lab.describe(g),
                   "is": {f"d{d}": slim(res[d]) for d in DELAYS},
                   "oos": {f"d{d}": slim(test[d]) for d in DELAYS},
                   "oos_rets": {d: test[d]["rets"] for d in DELAYS},
                   "baselines_oos_d5": {n: slim(r) for n, r in base.items()},
                   "baselines_oos_rets": {n: r["rets"] for n, r in base.items()}})
        log(f"  -> {y} OOS d0 {test[0]['cagr']:+.1%} / d5 {test[5]['cagr']:+.1%}  "
            f"(official d5 {base['official_dd20_10']['cagr']:+.1%}, B&H {base['buy_and_hold']['cagr']:+.1%})")
    wfo = {f"d{d}": slim(stitched([f["oos_rets"][d] for f in wf])) for d in DELAYS}
    wfo_base = {n: slim(stitched([f["baselines_oos_rets"][n] for f in wf])) for n in baselines()}

    # ---------------- final search on all pre-holdout data
    hs = mk_s.n
    log(f"FINAL search: train {TRAIN_START[:10]}..{HOLDOUT_START[:10]}")
    ranked = evolve(L_s, t0, hs, rng, a.pop, a.gens, trials, log, tag="[final]")
    sharpes = [r[2][0]["sharpe"] for r in ranked if r[2].get(0) and "sharpe" in r[2][0]]
    msr = sum(sharpes) / len(sharpes)
    sr_var = sum((x - msr) ** 2 for x in sharpes) / max(1, len(sharpes) - 1)
    # top-3 DISTINCT candidates (different active sleeve sets where possible)
    picks, sigs = [], set()
    for f, g, res in ranked:
        sig = tuple(i for i, w in enumerate(g["w_bull"]) if w) + (g["gate"],)
        if sig in sigs:
            continue
        sigs.add(sig)
        picks.append((f, g, res))
        if len(picks) == 3:
            break

    # ---------------- holdout: evaluated ONCE, after picks are frozen
    mk_f = lab.Market()
    L_f = lab.Lab(mk_f)
    h0, h1 = mk_f.hour_of(HOLDOUT_START), mk_f.n
    i0, i1 = mk_f.hour_of(TRAIN_START), mk_f.hour_of(HOLDOUT_START)
    bres = {}
    for n, bg in baselines().items():
        bres[n] = {"is": {f"d{d}": slim(L_f.evaluate(bg, i0, i1, delay=d)) for d in DELAYS},
                   "holdout": {f"d{d}": slim(L_f.evaluate(bg, h0, h1, delay=d)) for d in DELAYS},
                   "wfo": wfo_base[n]}
    bh_mdd = bres["buy_and_hold"]["holdout"]["d5"]["mdd"]
    cands = []
    for rank, (f, g, res) in enumerate(picks, 1):
        ho = {d: L_f.evaluate(g, h0, h1, delay=d) for d in DELAYS}
        dsr = lab.deflated_sharpe(res[0]["sharpe"], res[0]["rets"], len(trials) + prior_trials, sr_var)
        c = {"rank": rank, "fitness": round(f, 4), "genome": g, "key": lab.key(g),
             "desc": lab.describe(g),
             "is": {f"d{d}": slim(res[d]) for d in DELAYS},
             "holdout": {f"d{d}": slim(ho[d]) for d in DELAYS},
             "dsr": round(dsr, 4), "bh_holdout_mdd": bh_mdd,
             "wfo_family_sharpe": wfo["d5"]["sharpe"]}
        c["survives"] = SURVIVE(c)
        c["beats_official_holdout_d5"] = ho[5]["sharpe"] > bres["official_dd20_10"]["holdout"]["d5"]["sharpe"]
        cands.append(c)
        log(f"  cand {rank}: holdout d0 {ho[0]['cagr']:+.1%} d5 {ho[5]['cagr']:+.1%} "
            f"mdd {ho[5]['mdd']:.1%}  DSR {dsr:.2f}  survives={c['survives']}  {c['desc']}")

    res = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_end_utc": f"{mk_f.time_of(mk_f.n):%Y-%m-%dT%H:%MZ}",
        "config": {"pop": a.pop, "gens": a.gens, "seed": a.seed, "train_start": TRAIN_START,
                   "holdout_start": HOLDOUT_START, "wf_test_years": WF_TEST_YEARS,
                   "delays_h": list(DELAYS), "cost_per_side": lab.COST,
                   "universe": lab.UNIVERSE},
        "n_trials": len(trials), "cumulative_trials": len(trials) + prior_trials,
        "holdout_looks": len(prev) + 1, "is_sharpe_var": round(sr_var, 4),
        "wfo": {"folds": [{k: v for k, v in f.items() if k not in ("oos_rets", "baselines_oos_rets", "genome")}
                          for f in wf], "stitched": wfo},
        "baselines": bres, "candidates": cands,
        "runtime_s": round(time.time() - t_start, 1),
    }
    with open(os.path.join(OUT, "latest.json"), "w") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(OUT, "history.jsonl"), "a") as f:
        f.write(json.dumps({"generated_utc": res["generated_utc"], "n_trials": res["n_trials"],
                            "wfo_d5": wfo["d5"], "candidates": [
                                {k: c[k] for k in ("rank", "key", "holdout", "dsr", "survives")}
                                for c in cands]}) + "\n")
    with open(os.path.join(OUT, "RESULTS.md"), "w") as f:
        f.write(render(res))
    log(f"done in {res['runtime_s']}s, {len(trials)} distinct configurations tried")


def _row(name, m):
    return (f"| {name} | {m['cagr']:+.1%} | {m['mdd']:.1%} | {m['sharpe']:.2f} | "
            f"{m.get('trades', 0)} | {m.get('turnover', 0):.1f} |")


def render(r):
    L = [f"# Strategy evolution — results ({r['generated_utc']})", "",
         "RESEARCH / PAPER ONLY. Generated by `research/evolution/evolve.py` (token-free).",
         f"Data to {r['data_end_utc']}. Cost {r['config']['cost_per_side']:.2%}/side "
         f"(fee + slippage). Fills: d0 = next-bar open, d5 = 5h blind window.",
         f"Train from {r['config']['train_start'][:10]}; holdout {r['config']['holdout_start'][:10]}"
         f"..now was NOT loaded during any search.",
         f"**Distinct configurations tried: {r['n_trials']}** this run (pop {r['config']['pop']} x "
         f"gens {r['config']['gens']} x {len(r['config']['wf_test_years']) + 1} searches, seed "
         f"{r['config']['seed']}); **{r['cumulative_trials']} across all runs**, holdout looked at "
         f"{r['holdout_looks']} time(s).", "",
         "## Walk-forward (each year scored by a model evolved only on earlier data)", "",
         "| test year | winner OOS d0 CAGR | d5 CAGR | d5 MDD | d5 Sharpe | official d5 CAGR | B&H CAGR | winner |",
         "|---|---|---|---|---|---|---|---|"]
    for f in r["wfo"]["folds"]:
        o0, o5 = f["oos"]["d0"], f["oos"]["d5"]
        b = f["baselines_oos_d5"]
        L.append(f"| {f['year']} | {o0['cagr']:+.1%} | {o5['cagr']:+.1%} | {o5['mdd']:.1%} | "
                 f"{o5['sharpe']:.2f} | {b['official_dd20_10']['cagr']:+.1%} | "
                 f"{b['buy_and_hold']['cagr']:+.1%} | {f['desc']} |")
    L += ["", "Stitched walk-forward OOS (all test years):", "",
          "| book | CAGR | MDD | Sharpe | trades | turnover/yr |", "|---|---|---|---|---|---|",
          _row("evolved (d0)", r["wfo"]["stitched"]["d0"]),
          _row("evolved (d5)", r["wfo"]["stitched"]["d5"])]
    for n, b in r["baselines"].items():
        L.append(_row(f"{n} (d5)", b["wfo"]))
    L += ["", "## Final candidates: in-sample vs untouched holdout", "",
          "| book | IS CAGR d5 | IS MDD | IS Sharpe | HOLDOUT CAGR d0 | HOLDOUT CAGR d5 | HO MDD d5 | HO Sharpe d5 | HO trades | DSR | survives |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, b in r["baselines"].items():
        i5, h0, h5 = b["is"]["d5"], b["holdout"]["d0"], b["holdout"]["d5"]
        L.append(f"| {n} | {i5['cagr']:+.1%} | {i5['mdd']:.1%} | {i5['sharpe']:.2f} | {h0['cagr']:+.1%} | "
                 f"{h5['cagr']:+.1%} | {h5['mdd']:.1%} | {h5['sharpe']:.2f} | {h5['trades']} | – | baseline |")
    for c in r["candidates"]:
        i5, h0, h5 = c["is"]["d5"], c["holdout"]["d0"], c["holdout"]["d5"]
        L.append(f"| cand {c['rank']} | {i5['cagr']:+.1%} | {i5['mdd']:.1%} | {i5['sharpe']:.2f} | "
                 f"{h0['cagr']:+.1%} | {h5['cagr']:+.1%} | {h5['mdd']:.1%} | {h5['sharpe']:.2f} | "
                 f"{h5['trades']} | {c['dsr']:.2f} | {'YES' if c['survives'] else 'no'} |")
    L += [""] + [f"- cand {c['rank']}: `{c['desc']}`" for c in r["candidates"]]
    L += ["", "DSR = deflated Sharpe ratio (probability the in-sample Sharpe is real after "
          f"{r['cumulative_trials']} trials; >0.95 is the usual bar). DSR only corrects for "
          "multiple testing; it cannot see a regime change, which is why the holdout decides.",
          "Survival rule (fixed before the holdout ran): WFO-OOS Sharpe > 0, holdout CAGR > 0 "
          "at d0 and d5, holdout MDD (d5) below buy-and-hold's.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
