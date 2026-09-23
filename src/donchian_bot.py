#!/usr/bin/env python3
"""Donchian swing bot — RESEARCH / PAPER-ONLY forward-runner (Cycle 13).

Cycle 9: Cycle-8 volatility-target sizing overlay wired into the entry (fraction
in [0,1], no leverage, only scales DOWN); BUY intent gated by the shared
RiskManager (HALT kill switch + 1M cap). --mode paper only; no live order path.

Cycle 13 (EXECUTION-GAP robustness): default execution is now `--exec resting` —
exchange-side stop orders (entry buy-stop at prior high, exit sell-stop at
channel-low / ATR-trail) that fill intrabar WITHOUT the agent, so the paper book
survives outages of up to config.MAX_BLIND_HOURS (~5h). Entry sizing is gap-capped
(RiskManager.gap_capped_notional) so a plausible blind-window drop cannot breach
the daily loss limit. Legacy next-open fills remain available via `--exec market`
(gap-exposed). See backtest/cycle13_gap.py for the delay-sweep / mitigation study.

Runs the research-best strategy forward on CLOSED Upbit candles and accumulates a
persistent paper track record per timeframe. It NEVER places live orders (there
is no live code path) and never uses API keys — public candle endpoints only.

Strategy per timeframe (see research/best_config.json):
  * daily : Donchian 20/20 breakout + ATR(14) trailing stop k=3   (Cycles 3-6)
  * 4h    : Donchian 30/20 breakout, no trailing stop             (Cycle 7)

Paper book = MAX_EXPOSURE_KRW (1,000,000 KRW) — i.e. the most the strategy could
deploy live under the cap. Long-only, all-in on signal; fills at the next bar's
OPEN (no lookahead), fee 0.05%/side. Each closed candle appends one row to
logs/paper_<tf>.csv. The runner is IDEMPOTENT: re-running only appends candles
newer than the last logged one, so it is safe to invoke on any cadence (intended:
once per day for daily, every 4h for 4h).

Usage:
  python3 donchian_bot.py --tf daily            # append any new closed daily candles
  python3 donchian_bot.py --tf 4h
  python3 donchian_bot.py --tf daily --backfill 200   # warm-start last N candles
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statistics import pstdev  # noqa: E402
import config  # noqa: E402
from upbit_client import UpbitClient, UpbitError  # noqa: E402
from risk import RiskManager, RiskHalt  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
FEE = config.UPBIT_FEE
SLIP = config.TAKER_SLIP_BPS / 1e4          # resting-stop adverse slippage (Cycle 13)
CAPITAL = config.MAX_EXPOSURE_KRW
# Cycle 15: fixed trading budget. Each entry deploys at most BASE; profit that
# lifts the book above BASE stays as protected cash and is never re-risked.
BASE = config.BASE_TRADABLE_CAPITAL_KRW
# Cycle 14: the forward paper equity is anchored to a FIXED calendar start so the
# persisted curve is stable across runs. Earlier the equity was recomputed over a
# sliding ~250-candle window, so when an old trade slid out the logged equity
# stepped (observed 2026-09-19: a 4h row jumped +11.0% -> -0.4% with no trade).
# Bars before the anchor are used ONLY for indicator warmup; equity starts at
# CAPITAL, FLAT, at the anchor. Keep the anchor recent enough to stay inside the
# fetch window (daily: months of headroom; 4h: ~5 weeks at count=250).
FORWARD_ANCHOR = "2026-09-12T00:00:00"

# target_vol/vol_n = the Cycle-8 volatility-target sizing overlay (daily-vol
# target, no leverage, only ever scales DOWN from full exposure). Validated on
# daily; left OFF for 4h (not validated there).
PARAMS = {
    "daily": {"unit": "days", "n_in": 20, "n_out": 20, "atr_k": 3.0,
              "atr_bars": 14, "target_vol": 0.02, "vol_n": 20},
    "4h":    {"unit": 240,    "n_in": 30, "n_out": 20, "atr_k": 0.0,
              "atr_bars": 14, "target_vol": None, "vol_n": 20},
}
# Two parallel paper books are logged on the SAME signals so they can be compared
# as the track grows: FULL = always all-in within the 1M cap; VOLTGT = entry
# scaled by vol_fraction in [0,1] (only ever DOWN). For 4h the overlay is off so
# the two columns are identical by construction.
COLS = ["time_utc", "close", "position", "action", "fill_price", "vol_frac",
        "equity_full_krw", "equity_voltgt_krw",
        "realized_full_cum_krw", "realized_voltgt_cum_krw", "trades", "reason"]


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {config.redact(str(msg))}"
    print(line, flush=True)
    with open(os.path.join(LOG_DIR, "donchian_bot.log"), "a") as f:
        f.write(line + "\n")


def fetch_closed(client, p, count=250):
    if p["unit"] == "days":
        raw = client.candles_days(config.MARKET, count=count)
    else:
        raw = client.candles_minutes(config.MARKET, unit=p["unit"], count=count)
    raw = list(reversed(raw))                         # oldest -> newest
    bars = [{"t": c["candle_date_time_utc"], "open": float(c["opening_price"]),
             "high": float(c["high_price"]), "low": float(c["low_price"]),
             "close": float(c["trade_price"])} for c in raw]
    return bars[:-1]                                  # drop forming candle


def atr(bars, n, i):
    if i < n:
        return None
    s = 0.0
    for j in range(i - n + 1, i + 1):
        h, l, pc = bars[j]["high"], bars[j]["low"], bars[j - 1]["close"]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / n


def vol_fraction(bars, i, p):
    """Cycle-8 vol-target fraction in [0,1] at bar i (no leverage). Returns 1.0
    when the overlay is disabled (target_vol None) or history is insufficient."""
    tv, n = p.get("target_vol"), p.get("vol_n", 20)
    if not tv or i < n:
        return 1.0
    rets = [bars[j]["close"] / bars[j - 1]["close"] - 1 for j in range(i - n + 1, i + 1)]
    rv = pstdev(rets)
    return 1.0 if rv <= 0 else max(0.0, min(1.0, tv / rv))


def rest_levels(bars, i, p, hi_since=None):
    """Cycle-13 gap-robust RESTING order levels placed from CLOSED data through
    bar i-1 (valid for bar i, agent may be offline):
      entry buy-stop  = prior n_in-bar high
      exit  sell-stop = max(prior n_out-bar low, ATR-trail below running high)
    Returns (entry_level, exit_level)."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    entry_lvl = max(highs[i - p["n_in"]:i]) if i >= p["n_in"] else None
    exit_lvl = min(lows[i - p["n_out"]:i]) if i >= p["n_out"] else None
    if exit_lvl is not None and p["atr_k"] and hi_since:
        a = atr(bars, p["atr_bars"], i - 1)
        if a is not None:
            exit_lvl = max(exit_lvl, hi_since - p["atr_k"] * a)
    return entry_lvl, exit_lvl


def replay(bars, p, exec_mode="resting", anchor_idx=0):
    """Deterministic replay -> one row-dict per bar; equity marked at each close.
    Bars before anchor_idx are used only for indicator warmup (no trading, no
    rows); the books start at CAPITAL, FLAT, at anchor_idx so the equity curve is
    stable regardless of how far back the fetch window reaches (Cycle 14).

    exec_mode:
      * "market"  — signal on bar i, fill at bar i+1 OPEN (legacy; needs the agent
        online at the open, so it is EXPOSED to execution gaps).
      * "resting" — Cycle-13 gap-robust default: exchange-side stop orders fill
        intrabar at levels known from closed bars (entry buy-stop at prior high,
        exit sell-stop at channel-low / ATR-trail). These trigger WITHOUT the
        agent, so the paper book is outage-immune (see backtest/cycle13_gap.py).

    Two parallel books run on the SAME signals so full-exposure and vol-target-
    sized equity stay comparable: _f = FULL (all-in), _v = VOLTGT (entry scaled by
    vol_fraction, never above full)."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    cash_f, coin_f, real_f = CAPITAL, 0.0, 0.0      # full-exposure book
    cash_v, coin_v, real_v = CAPITAL, 0.0, 0.0      # vol-target book
    in_pos, entry_f, entry_v, hi_since = False, 0.0, 0.0, 0.0
    trades = 0
    pending = None                                    # market-mode next-open order
    warm = max(p["n_in"], p["n_out"], p["atr_bars"] if p["atr_k"] else 0)
    rows = []
    for i, b in enumerate(bars):
        if i < anchor_idx:                 # warmup only: no trading, no rows logged
            continue
        action, fill, frac_used, reason = "HOLD", "", "", ""
        if exec_mode == "market":
            # execute pending order at THIS bar's open
            if pending and pending[0] == "buy" and not in_pos:
                fill = b["open"]; frac = pending[1]
                invest_f = min(BASE, cash_f)                 # cap: protect profit
                coin_f = invest_f * (1 - FEE) / fill; cash_f -= invest_f
                invest_v = frac * min(BASE, cash_v)
                coin_v = invest_v * (1 - FEE) / fill; cash_v -= invest_v
                in_pos, entry_f, entry_v, hi_since = True, fill, fill, b["close"]
                trades += 1; action = "BUY"; frac_used = frac
            elif pending and pending[0] == "sell" and in_pos:
                fill = b["open"]
                proc_f = coin_f * fill * (1 - FEE); real_f += proc_f - coin_f * entry_f
                cash_f += proc_f; coin_f = 0.0
                proc_v = coin_v * fill * (1 - FEE); real_v += proc_v - coin_v * entry_v
                cash_v += proc_v; coin_v = 0.0
                in_pos = False; action = "SELL"
            pending = None
        else:  # resting: orders placed from bar i-1's close trigger intrabar now
            if i > warm and not in_pos:
                lvl = max(highs[i - p["n_in"]:i])                 # buy-stop
                if b["high"] >= lvl:
                    fill = max(b["open"], lvl) * (1 + SLIP)       # gap-through->open
                    frac = vol_fraction(bars, i - 1, p)
                    invest_f = min(BASE, cash_f)             # cap: protect profit
                    coin_f = invest_f * (1 - FEE) / fill; cash_f -= invest_f
                    invest_v = frac * min(BASE, cash_v)
                    coin_v = invest_v * (1 - FEE) / fill; cash_v -= invest_v
                    in_pos, entry_f, entry_v, hi_since = True, fill, fill, b["close"]
                    trades += 1; action = "BUY"; frac_used = frac; reason = "breakout"
            elif i > warm and in_pos:
                ch = min(lows[i - p["n_out"]:i])
                lvl = ch
                if p["atr_k"]:
                    a = atr(bars, p["atr_bars"], i)
                    if a is not None:
                        lvl = max(ch, hi_since - p["atr_k"] * a)
                if b["low"] <= lvl:
                    fill = min(b["open"], lvl) * (1 - SLIP)
                    proc_f = coin_f * fill * (1 - FEE); real_f += proc_f - coin_f * entry_f
                    cash_f += proc_f; coin_f = 0.0
                    proc_v = coin_v * fill * (1 - FEE); real_v += proc_v - coin_v * entry_v
                    cash_v += proc_v; coin_v = 0.0
                    in_pos = False; action = "SELL"
                    reason = "trail" if lvl > ch else "channel"
        # update trailing high (marks running high for the ATR trail)
        if in_pos:
            hi_since = max(hi_since, b["close"])
        if exec_mode == "market" and i >= warm:
            breakout = b["high"] >= max(highs[i - p["n_in"]:i])
            breakdown = b["low"] <= min(lows[i - p["n_out"]:i])
            trail = False
            if in_pos and p["atr_k"]:
                a = atr(bars, p["atr_bars"], i)
                trail = a is not None and b["close"] <= hi_since - p["atr_k"] * a
            if not in_pos and breakout:
                pending, reason = ("buy", vol_fraction(bars, i, p)), "breakout"
            elif in_pos and (breakdown or trail):
                pending, reason = ("sell", 0.0), ("trail" if trail else "channel")
        eq_f = cash_f + coin_f * b["close"]
        eq_v = cash_v + coin_v * b["close"]
        rows.append({"time_utc": b["t"], "close": f"{b['close']:.0f}",
                     "position": "LONG" if in_pos else "FLAT",
                     "action": action, "fill_price": (f"{fill:.0f}" if fill else ""),
                     "vol_frac": (f"{frac_used:.3f}" if frac_used != "" else ""),
                     "equity_full_krw": f"{eq_f:.0f}",
                     "equity_voltgt_krw": f"{eq_v:.0f}",
                     "realized_full_cum_krw": f"{real_f:.0f}",
                     "realized_voltgt_cum_krw": f"{real_v:.0f}",
                     "trades": trades, "reason": reason})
    return rows


def last_logged_time(path):
    if not os.path.exists(path):
        return None
    last = None
    with open(path) as f:
        for r in csv.DictReader(f):
            last = r["time_utc"]
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", choices=["daily", "4h"], default="daily")
    ap.add_argument("--mode", choices=["paper"], default="paper",
                    help="only 'paper' is supported — there is no live path")
    ap.add_argument("--backfill", type=int, default=0,
                    help="seed the last N closed candles (warm start)")
    ap.add_argument("--exec", choices=["resting", "market"], default="resting",
                    help="resting = Cycle-13 gap-robust exchange-side stops "
                         "(default); market = legacy next-open fills (gap-exposed)")
    args = ap.parse_args()
    p = PARAMS[args.tf]
    csv_path = os.path.join(LOG_DIR, f"paper_{args.tf}.csv")
    client = UpbitClient("", "")                      # public only; no keys
    # Shared risk manager still governs the (paper) decision: kill switch (HALT
    # flag) + exposure cap are enforced before any intended entry.
    risk = RiskManager(os.path.join(HERE, f"donchian_risk_{args.tf}.json"))

    try:
        bars = fetch_closed(client, p, count=250)
    except UpbitError as e:
        log(f"fetch error: {e}")
        return
    # Cycle 14: pin the equity start to a fixed calendar anchor (warmup before it).
    warm = max(p["n_in"], p["n_out"], p["atr_bars"] if p["atr_k"] else 0)
    a_idx = next((k for k, b in enumerate(bars) if b["t"] >= FORWARD_ANCHOR), None)
    if a_idx is None or a_idx < warm:
        # anchor slid out of the fetch window (or too little warmup) -> fall back
        # to a warmup-clamped start and warn; curve start drifts until fetch deepens
        if a_idx is None:
            log(f"[{args.tf}] WARN anchor {FORWARD_ANCHOR} older than fetch window; "
                f"equity start will drift — deepen fetch count")
        anchor_idx = max(warm, a_idx or 0)
    else:
        anchor_idx = a_idx
    rows = replay(bars, p, args.exec, anchor_idx)      # fixed-anchor forward track

    last_t = last_logged_time(csv_path)
    if args.backfill and last_t is None:
        rows_to_write = rows[-args.backfill:]
        write_header = True
    else:
        rows_to_write = [r for r in rows if last_t is None or r["time_utc"] > last_t]
        write_header = not os.path.exists(csv_path)

    if not os.path.exists(csv_path) and not rows_to_write and args.backfill:
        rows_to_write = rows[-args.backfill:]; write_header = True

    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if write_header:
            w.writeheader()
        for r in rows_to_write:
            w.writerow(r)

    final = rows[-1]
    eq_f = float(final["equity_full_krw"]); ret_f = (eq_f - CAPITAL) / CAPITAL * 100
    eq_v = float(final["equity_voltgt_krw"]); ret_v = (eq_v - CAPITAL) / CAPITAL * 100
    log(f"[{args.tf}] appended {len(rows_to_write)} rows (total track "
        f"{sum(1 for _ in open(csv_path))-1}). latest {final['time_utc']} "
        f"close={final['close']} pos={final['position']} trades={final['trades']} "
        f"paper_equity full={eq_f:,.0f} ({ret_f:+.1f}%) "
        f"vol-target={eq_v:,.0f} ({ret_v:+.1f}%) -> {csv_path}")
    pos, n, last_close = final["position"], len(bars), float(final["close"])
    if args.exec == "resting":
        # ---- current RESTING orders (Cycle-13): what would sit on the exchange
        # for the NEXT bar and execute even if the agent is offline up to
        # MAX_BLIND_HOURS. Entry size gap-capped by the shared risk manager. ---
        hi = last_close
        if pos == "LONG":                              # running high since entry
            for r in reversed(rows):
                hi = max(hi, float(r["close"]))
                if r["action"] == "BUY":
                    break
        entry_lvl, exit_lvl = rest_levels(bars, n, p, hi if pos == "LONG" else None)
        if pos == "FLAT" and entry_lvl:
            channel = min(bars[j]["low"] for j in range(n - p["n_out"], n))
            stop_frac = max(1e-6, (entry_lvl - channel) / entry_lvl)
            f = vol_fraction(bars, n - 1, p)
            try:
                allowed = risk.gap_capped_notional(stop_distance_frac=stop_frac)
            except RiskHalt as e:
                log(f"[{args.tf}] resting BUY-STOP @ {entry_lvl:,.0f} but BLOCKED "
                    f"by risk manager: {e} [no live order]")
            else:
                notional = min(f * CAPITAL, allowed)
                log(f"[{args.tf}] RESTING BUY-STOP @ {entry_lvl:,.0f} "
                    f"(protective SELL-STOP would sit ~{stop_frac*100:.1f}% below); "
                    f"vol_frac={f:.2f} -> gap-capped size ~{notional:,.0f} KRW "
                    f"[outage-immune, no live order]")
        elif pos == "LONG" and exit_lvl:
            dist = (last_close - exit_lvl) / last_close * 100
            log(f"[{args.tf}] RESTING SELL-STOP @ {exit_lvl:,.0f} "
                f"(~{dist:.1f}% below last close; bounds blind-window loss) "
                f"[outage-immune, no live order]")
        else:
            log(f"[{args.tf}] resting orders warming up (need history) "
                f"[paper only, no live orders]")
    else:
        # legacy market-mode intent (gap-exposed; needs agent online at the open)
        pend = final["reason"]
        if pend == "breakout" and pos == "FLAT":
            f = vol_fraction(bars, n - 1, p)
            try:
                allowed = risk.can_open()
            except RiskHalt as e:
                log(f"[{args.tf}] intent=BUY next bar but BLOCKED: {e}")
            else:
                notional = min(f * CAPITAL, allowed)
                log(f"[{args.tf}] intent=BUY next bar: vol_frac={f:.2f} -> paper "
                    f"size ~{notional:,.0f} KRW (cap-allowed {allowed:,.0f})")
        elif pend in ("channel", "trail") and pos == "LONG":
            log(f"[{args.tf}] intent=SELL/exit next bar ({pend}) [no live order]")
        else:
            log(f"[{args.tf}] intent=none (paper only, no live orders)")


if __name__ == "__main__":
    main()
