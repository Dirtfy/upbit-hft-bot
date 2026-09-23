#!/usr/bin/env python3
"""Cycle 13 — EXECUTION-GAP robustness (research/analysis only; no orders).

Models stretches where the bot cannot act (agent offline up to ~5h; missed
candle-close / halts) and tests mitigations, over the full verified 9y history
for daily and 4h. Strategy matches the paper bot / best_config:
  daily : Donchian 20/20 + ATR(14) trailing stop k=3
  4h    : Donchian 30/20 (no trail)

Execution models
  * market(delay_bars, stale_bars):  signal decided at bar i's close; baseline
    fills at bar i+1 open. An outage of D hours that straddles that open forces
    the fill to the FIRST open after the outage clears -> delay_bars =
    ceil(D / bar_hours) extra bars (worst case: outage always covers the open).
    stale_bars: if an ENTRY would fill more than this many bars late, CANCEL it
    (don't chase a decayed edge); protective EXITS are never cancelled.
  * resting: exchange-side stop orders at levels known from CLOSED bars — entry
    buy-stop at the prior n_in-bar high, exit sell-stop at max(prior n_out-bar
    low, ATR-trail). These trigger intrabar WITHOUT the agent, so they are
    outage-immune (the only agent-dependent piece is ratcheting the ATR trail
    tighter, which merely pauses during a blind window; the stop stays in place).
    Fills at the level, with taker slippage, or at the open on a gap-through.

Fees: 0.05%/side (maker-ish next-open baseline). Resting stops add TAKER_SLIP.
"""
import csv
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config  # noqa: E402

FEE = config.UPBIT_FEE
SLIP = config.TAKER_SLIP_BPS / 1e4          # resting-stop adverse slippage
DATA = {"daily": (os.path.join(HERE, "..", "data", "krw_btc_1d.csv"), 24.0,
                  {"n_in": 20, "n_out": 20, "atr_k": 3.0, "atr_bars": 14}),
        "4h":    (os.path.join(HERE, "..", "data", "krw_btc_4h_full.csv"), 4.0,
                  {"n_in": 30, "n_out": 20, "atr_k": 0.0, "atr_bars": 14})}
CAP = config.MAX_EXPOSURE_KRW


def load(path):
    b = []
    with open(path) as f:
        for r in csv.DictReader(f):
            b.append({"t": r["time_utc"], "open": float(r["open"]),
                      "high": float(r["high"]), "low": float(r["low"]),
                      "close": float(r["close"])})
    return b


def atr(bars, n, i):
    if i < n:
        return None
    s = 0.0
    for j in range(i - n + 1, i + 1):
        h, l, pc = bars[j]["high"], bars[j]["low"], bars[j - 1]["close"]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / n


def metrics(eq, pnls, closes, bars, bar_hours):
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    yrs = len(bars) * bar_hours / (365.25 * 24)
    cagr = ((eq[-1] / eq[0]) ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1
    wins = [p for p in pnls if p > 0]
    return {"cagr_pct": cagr * 100, "maxdd_pct": mdd * 100,
            "calmar": (cagr / mdd) if mdd > 0 else 0.0,
            "closed": len(pnls),
            "win_rate": (len(wins) / len(pnls) * 100) if pnls else 0.0,
            "avg_trade_pct": (sum(pnls) / len(pnls) * 100) if pnls else 0.0,
            "final_mult": eq[-1] / eq[0]}


def signals(bars, p):
    """Precompute per-bar (breakout_level, exit_level, want_entry, want_exit)
    using ONLY closed data up to bar i (no lookahead). Returns decision arrays."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    warm = max(p["n_in"], p["n_out"], p["atr_bars"] if p["atr_k"] else 0)
    return highs, lows, warm


def run_market(bars, p, delay_bars=0, stale_bars=None):
    """Market fills at bar (i+1+delay_bars) open. Entries cancelled if late beyond
    stale_bars; exits always execute (delayed)."""
    highs, lows, warm = signals(bars, p)
    cash, coin, in_pos, entry, hi_since = CAP, 0.0, False, 0.0, 0.0
    pnls, eq = [], []
    pending = None                         # (side, decide_i)
    n = len(bars)
    for i, b in enumerate(bars):
        # execute any pending order whose scheduled fill bar == i
        if pending:
            side, di, fill_bar = pending
            if i == fill_bar:
                px = b["open"]
                if side == "buy" and not in_pos:
                    coin = cash * (1 - FEE) / px; cash = 0.0
                    in_pos, entry, hi_since = True, px, b["close"]
                elif side == "sell" and in_pos:
                    cash = coin * px * (1 - FEE); pnls.append((px - entry) / entry)
                    coin = 0.0; in_pos = False
                pending = None
        if in_pos:
            hi_since = max(hi_since, b["close"])
        # decide on this closed bar
        if i >= warm and pending is None:
            breakout = b["high"] >= max(highs[i - p["n_in"]:i])
            breakdown = b["low"] <= min(lows[i - p["n_out"]:i])
            trail = False
            if in_pos and p["atr_k"]:
                a = atr(bars, p["atr_bars"], i)
                trail = a is not None and b["close"] <= hi_since - p["atr_k"] * a
            fill_bar = i + 1 + delay_bars
            if not in_pos and breakout and fill_bar < n:
                if stale_bars is None or delay_bars <= stale_bars:
                    pending = ("buy", i, fill_bar)     # else: cancel (skip entry)
            elif in_pos and (breakdown or trail) and fill_bar < n:
                pending = ("sell", i, fill_bar)        # exits never cancelled
        eq.append(cash + coin * b["close"])
    return metrics(eq, pnls, [x["close"] for x in bars], bars, DATA_HRS)


def run_resting(bars, p):
    """Exchange-side stop orders; fills at levels intrabar (outage-immune)."""
    highs, lows, warm = signals(bars, p)
    cash, coin, in_pos, entry, hi_since = CAP, 0.0, False, 0.0, 0.0
    pnls, eq = [], []
    for i, b in enumerate(bars):
        if i > warm:
            if not in_pos:
                lvl = max(highs[i - p["n_in"]:i])          # buy-stop at prior high
                if b["high"] >= lvl:
                    px = max(b["open"], lvl) * (1 + SLIP)   # gap-through -> open
                    coin = cash * (1 - FEE) / px; cash = 0.0
                    in_pos, entry, hi_since = True, px, b["close"]
            else:
                hi_since = max(hi_since, b["close"])
                ch = min(lows[i - p["n_out"]:i])           # channel-low stop
                lvl = ch
                if p["atr_k"]:
                    a = atr(bars, p["atr_bars"], i)
                    if a is not None:
                        lvl = max(ch, hi_since - p["atr_k"] * a)  # trail (higher)
                if b["low"] <= lvl:
                    px = min(b["open"], lvl) * (1 - SLIP)   # gap-through -> open
                    cash = coin * px * (1 - FEE); pnls.append((px - entry) / entry)
                    coin = 0.0; in_pos = False
        if in_pos:
            hi_since = max(hi_since, b["close"])
        eq.append(cash + coin * b["close"])
    return metrics(eq, pnls, [x["close"] for x in bars], bars, DATA_HRS)


def run_market_mc(bars, p, outage_h, per_year, bar_hours, seeds=40):
    """Monte-Carlo EXPECTED degradation: random outages of `outage_h` at
    `per_year` rate; a signal's fill slips only if its open instant lies in an
    outage. Returns mean CAGR/maxDD over seeds."""
    n = len(bars)
    span_yrs = n * bar_hours / (365.25 * 24)
    n_out = int(per_year * span_yrs)
    dbar = math.ceil(outage_h / bar_hours)
    cagrs, mdds = [], []
    for s in range(seeds):
        rng = random.Random(1000 + s)
        blind = set()
        for _ in range(n_out):
            start = rng.randint(0, n - 1)
            for k in range(start, min(n, start + dbar + 1)):
                blind.add(k)                    # bar-open instants that are blind
        highs, lows, warm = signals(bars, p)
        cash, coin, in_pos, entry, hi_since = CAP, 0.0, False, 0.0, 0.0
        pnls, eq, pending = [], [], None
        for i, b in enumerate(bars):
            if pending:
                side, fb = pending
                if i == fb:
                    px = b["open"]
                    if side == "buy" and not in_pos:
                        coin = cash * (1 - FEE) / px; cash = 0.0
                        in_pos, entry, hi_since = True, px, b["close"]
                    elif side == "sell" and in_pos:
                        cash = coin * px * (1 - FEE); pnls.append((px - entry) / entry)
                        coin = 0.0; in_pos = False
                    pending = None
            if in_pos:
                hi_since = max(hi_since, b["close"])
            if i >= warm and pending is None:
                breakout = b["high"] >= max(highs[i - p["n_in"]:i])
                breakdown = b["low"] <= min(lows[i - p["n_out"]:i])
                trail = False
                if in_pos and p["atr_k"]:
                    a = atr(bars, p["atr_bars"], i)
                    trail = a is not None and b["close"] <= hi_since - p["atr_k"] * a
                want = ("buy" if (not in_pos and breakout) else
                        "sell" if (in_pos and (breakdown or trail)) else None)
                if want:
                    fb = i + 1
                    while fb < n and fb in blind:   # slip past blind opens
                        fb += 1
                    if fb < n:
                        pending = (want, fb)
            eq.append(cash + coin * b["close"])
        m = metrics(eq, pnls, [x["close"] for x in bars], bars, bar_hours)
        cagrs.append(m["cagr_pct"]); mdds.append(m["maxdd_pct"])
    return sum(cagrs) / len(cagrs), sum(mdds) / len(mdds)


def adverse_5h(bars, bar_hours):
    """Empirical distribution of the worst adverse (down) move over a ~5h window."""
    w = max(1, round(5.0 / bar_hours))
    moves = []
    for i in range(len(bars) - w):
        p0 = bars[i]["close"]
        lo = min(bars[j]["low"] for j in range(i + 1, i + 1 + w))
        moves.append((lo - p0) / p0)
    moves.sort()
    q = lambda f: moves[int(f * (len(moves) - 1))]
    return {"p50": q(0.50) * 100, "p01": q(0.01) * 100,
            "p001": q(0.001) * 100, "min": moves[0] * 100, "w_bars": w}


DATA_HRS = 24.0

if __name__ == "__main__":
    for tf, (path, hrs, p) in DATA.items():
        DATA_HRS = hrs
        bars = load(path)
        print(f"\n########## {tf}  ({bars[0]['t'][:10]}..{bars[-1]['t'][:10]}, "
              f"{len(bars)} bars, {hrs}h) ##########")
        base = run_market(bars, p, 0)
        print(f"[baseline market next-open]  CAGR {base['cagr_pct']:7.1f}%  "
              f"Calmar {base['calmar']:.2f}  maxDD {base['maxdd_pct']:.1f}%  "
              f"trades {base['closed']}  avg {base['avg_trade_pct']:+.2f}%  "
              f"x{base['final_mult']:.1f}")
        print("  -- WORST-CASE delayed-execution sweep (every fill slips D hours) --")
        for D in (1, 4, 5, 8, 12, 24, 48):
            db = math.ceil(D / hrs)
            m = run_market(bars, p, db)
            dd = (m['cagr_pct'] - base['cagr_pct'])
            print(f"    D={D:>2}h (+{db} bar): CAGR {m['cagr_pct']:7.1f}% "
                  f"({dd:+6.1f}pp)  Calmar {m['calmar']:.2f}  maxDD {m['maxdd_pct']:.1f}%"
                  f"  avg {m['avg_trade_pct']:+.2f}%")
        # staleness guard at 5h outage: cancel entries later than 1 bar
        st = run_market(bars, p, math.ceil(5 / hrs), stale_bars=1)
        print(f"  -- MITIGATION (c) staleness guard @D=5h, cancel entry >1 bar late: "
              f"CAGR {st['cagr_pct']:.1f}%  Calmar {st['calmar']:.2f}  "
              f"maxDD {st['maxdd_pct']:.1f}%  trades {st['closed']}")
        rest = run_resting(bars, p)
        print(f"  -- MITIGATION (a) RESTING stop orders (outage-immune, taker slip "
              f"{config.TAKER_SLIP_BPS}bps): CAGR {rest['cagr_pct']:.1f}%  "
              f"Calmar {rest['calmar']:.2f}  maxDD {rest['maxdd_pct']:.1f}%  "
              f"trades {rest['closed']}  avg {rest['avg_trade_pct']:+.2f}%")
        # verify resting is D-independent (loop D by re-running resting; identical)
        print("  -- Monte-Carlo EXPECTED degradation, random 5h outages (market path) --")
        for rate in (52, 365):
            c, d = run_market_mc(bars, p, 5.0, rate, hrs)
            print(f"    ~{rate}/yr 5h outages: mean CAGR {c:7.1f}% "
                  f"({c-base['cagr_pct']:+.1f}pp)  mean maxDD {d:.1f}%")
        adv = adverse_5h(bars, hrs)
        print(f"  -- worst adverse move over ~5h ({adv['w_bars']} bar): "
              f"median {adv['p50']:.2f}%  1%ile {adv['p01']:.1f}%  "
              f"0.1%ile {adv['p001']:.1f}%  min {adv['min']:.1f}%")
