#!/usr/bin/env python3
"""Maker-entry backtest — models LIMIT (maker) order fills realistically.

This is the "paper trading" engine for the improved strategy the owner
approved. The key difference vs. backtest.py (which assumed market/taker fills
crossing the spread) is the fill model:

  ENTRY  — on a buy signal at the close of bar t, we place a LIMIT BUY at that
           close (i.e. we join the bid instead of paying the ask). It only
           fills if a later bar actually trades down to our price
           (low <= limit). If it doesn't fill within `entry_ttl` bars we cancel
           and drop the signal — no trade. Maker fills pay NO spread and NO
           slippage (but still the 0.05% Upbit fee, which has no maker rebate).

  EXIT   — take-profit is a LIMIT SELL (maker): fills only if a bar trades up to
           it (high >= tp). Stop-loss and timeout/mean-revert are MARKET
           (taker) exits with slippage, because you must get out.

Conservative choices (no optimistic bias):
  * If a single bar's range spans BOTH the stop and the take-profit, we assume
    the STOP filled first (worst case).
  * Taker exits pay slippage; maker fills do not, but we never assume a maker
    fill unless price provably reached the limit.

Usage:
    python3 backtest_maker.py --data ../data/krw_btc_1m_long.csv
    python3 backtest_maker.py --data ../data/krw_btc_1m_long.csv --oos   # only pre-original window
"""
import argparse
import csv
import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config  # noqa: E402

FEE = config.UPBIT_FEE  # 0.05% per side


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "t": r["time_utc"],
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            })
    return rows


def run(rows, p, capital=1_000_000.0, per_trade=None, entry_ttl=3,
        taker_slip_bps=1.5, entry_offset_bps=0.0):
    """p is a dict with strategy params (window, entry_z, stop_loss_pct,
    take_profit_pct, max_hold, min_std_bps). Optional p['trend_window']: if >0,
    only enter when price is above the SMA over that many bars (buy dips in
    uptrends only). 0/absent disables the filter (original behavior)."""
    per_trade = per_trade or min(config.PER_TRADE_KRW, capital)
    slip = taker_slip_bps / 1e4
    win = p["window"]
    closes = deque(maxlen=win)
    rsum = 0.0    # rolling sum of the closes currently in the window
    rsumsq = 0.0  # rolling sum of squares (for O(1) mean/std per bar)

    trend_win = p.get("trend_window", 0)
    tcloses = deque(maxlen=trend_win) if trend_win else None
    tsum = 0.0    # rolling sum for the trend SMA

    cash = capital
    trades = []
    equity_curve = []

    # order/position state
    pending = None   # dict: limit_price, expires_at (bar index)
    pos = None       # dict: qty, entry_price, entry_notional, entry_fee, tp, sl, entered_bar

    for i, bar in enumerate(rows):
        price_now = bar["close"]

        # rolling window stats over the PRIOR `win` closes (no lookahead),
        # computed in O(1) from running sum / sum-of-squares.
        if len(closes) == win:
            mean = rsum / win
            var = rsumsq / win - mean * mean
            std = var ** 0.5 if var > 0 else 0.0
            z = (price_now - mean) / std if std > 0 else None
        else:
            std = 0.0
            z = None

        # ---- 1) try to fill a resting limit BUY -------------------------
        if pending is not None and pos is None:
            if bar["low"] <= pending["limit_price"]:
                fill = pending["limit_price"]
                notional = per_trade
                qty = notional / fill
                fee = notional * FEE
                cash -= notional + fee
                pos = {
                    "qty": qty, "entry_price": fill, "entry_notional": notional,
                    "entry_fee": fee, "entered_bar": i,
                    "tp": fill * (1 + p["take_profit_pct"]),
                    "sl": fill * (1 - p["stop_loss_pct"]),
                }
                trades.append({"i": i, "t": bar["t"], "side": "buy",
                               "price": fill, "type": "maker"})
                pending = None
            elif i >= pending["expires_at"]:
                pending = None  # cancel unfilled order

        # ---- 2) manage an open position (intrabar fills) ----------------
        # Guard: never exit on the same candle we filled the entry on — a
        # candle-driven bot only acts on subsequent closed candles.
        if pos is not None and i > pos["entered_bar"]:
            exit_price = None
            reason = None
            maker_exit = False
            hit_sl = bar["low"] <= pos["sl"]
            hit_tp = bar["high"] >= pos["tp"]
            if hit_sl:  # worst-case priority: stop first
                exit_price = pos["sl"] * (1 - slip)  # taker, slips through
                reason = "stop_loss"
            elif hit_tp:
                exit_price = pos["tp"]                # maker limit sell
                reason = "take_profit"
                maker_exit = True
            else:
                bars_held = i - pos["entered_bar"]
                if z is not None and z >= p["exit_z"]:
                    exit_price = price_now * (1 - slip); reason = "mean_revert"
                elif bars_held >= p["max_hold"]:
                    exit_price = price_now * (1 - slip); reason = "timeout"
            if exit_price is not None:
                proceeds = pos["qty"] * exit_price
                exit_fee = proceeds * FEE
                cash += proceeds - exit_fee
                pnl = (proceeds - exit_fee) - (pos["entry_notional"] + pos["entry_fee"])
                trades.append({"i": i, "t": bar["t"], "side": "sell",
                               "price": exit_price, "reason": reason,
                               "type": "maker" if maker_exit else "taker",
                               "pnl": pnl})
                pos = None

        # trend filter: SMA over the prior trend_win closes (no lookahead)
        trend_ok = True
        if tcloses is not None:
            if len(tcloses) == trend_win:
                trend_ok = price_now > (tsum / trend_win)
            else:
                trend_ok = False  # not enough history yet -> don't trade

        # ---- 3) generate a new entry signal (no lookahead) --------------
        if pos is None and pending is None and z is not None and trend_ok:
            std_bps = (std / price_now) * 1e4
            if z <= -p["entry_z"] and std_bps >= p["min_std_bps"]:
                limit_price = price_now * (1 - entry_offset_bps / 1e4)
                pending = {"limit_price": limit_price,
                           "expires_at": i + entry_ttl}

        # advance the rolling window (maintain sum/sumsq with eviction)
        if len(closes) == win:
            old = closes[0]
            rsum -= old
            rsumsq -= old * old
        closes.append(price_now)
        rsum += price_now
        rsumsq += price_now * price_now
        if tcloses is not None:
            if len(tcloses) == trend_win:
                tsum -= tcloses[0]
            tcloses.append(price_now)
            tsum += price_now
        equity_curve.append(cash + (pos["qty"] * price_now if pos else 0.0))

    final_equity = cash + (pos["qty"] * rows[-1]["close"] if pos else 0.0)
    return summarize(trades, equity_curve, capital, final_equity, rows, per_trade)


def summarize(trades, equity_curve, capital, final_equity, rows, per_trade):
    sells = [t for t in trades if t["side"] == "sell"]
    pnls = [t["pnl"] for t in sells]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gross_win = sum(wins); gross_loss = -sum(losses)
    peak = -1e18; max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e); max_dd = max(max_dd, (peak - e) / peak if peak > 0 else 0)
    days = len(rows) / (60 * 24)
    ret = (final_equity - capital) / capital
    bh = (rows[-1]["close"] - rows[0]["close"]) / rows[0]["close"]
    reasons = {}
    for t in sells:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return {
        "days": days, "trades": len(sells),
        "win_rate": (len(wins) / len(sells)) if sells else 0.0,
        "total_pnl_krw": final_equity - capital,
        "return_pct": ret * 100, "buyhold_pct": bh * 100,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "max_dd_pct": max_dd * 100, "final_equity": final_equity,
        "per_trade": per_trade, "reasons": reasons,
        "avg_pnl_per_trade": (sum(pnls) / len(pnls)) if pnls else 0.0,
    }


def report(res, title=""):
    r = res
    print(f"--- {title} ---")
    print(f"period: {r['days']:.1f} days   per_trade={r['per_trade']:,.0f} KRW "
          f"(capital=1,000,000)")
    print(f"trades={r['trades']}  win={r['win_rate']*100:.1f}%  "
          f"PF={r['profit_factor']:.2f}  maxDD={r['max_dd_pct']:.2f}%")
    print(f"cumulative PnL = {r['total_pnl_krw']:+,.0f} KRW  "
          f"({r['return_pct']:+.2f}% on capital)   buy&hold={r['buyhold_pct']:+.2f}%")
    print(f"avg PnL/trade = {r['avg_pnl_per_trade']:+,.1f} KRW   "
          f"avg win={r['avg_win']:+,.0f}  avg loss={r['avg_loss']:+,.0f}")
    print(f"exit reasons: {r['reasons']}")
    # naive annualization
    if r["days"] > 0:
        ann = ((1 + r["return_pct"] / 100) ** (365.0 / r["days"]) - 1) * 100
        lin = r["return_pct"] * (365.0 / r["days"])
        print(f"ANNUALIZED (naive): compounded={ann:+.1f}%/yr   linear={lin:+.1f}%/yr")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="../data/krw_btc_1m_long.csv")
    ap.add_argument("--oos", action="store_true",
                    help="restrict to bars BEFORE the original 14-day window "
                         "(true out-of-sample)")
    ap.add_argument("--entry_ttl", type=int, default=3)
    ap.add_argument("--offset_bps", type=float, default=0.0)
    args = ap.parse_args()
    rows = load(args.data)
    if args.oos:
        rows = [r for r in rows if r["t"] < "2026-08-23T17:59:00"]
    print(f"loaded {len(rows)} candles: {rows[0]['t']} -> {rows[-1]['t']}")
    print(f"fee={FEE*100}%/side (maker=taker on Upbit), maker entries, "
          f"entry_ttl={args.entry_ttl} bars, offset={args.offset_bps}bps\n")
    res = run(rows, config.STRAT, entry_ttl=args.entry_ttl,
              entry_offset_bps=args.offset_bps)
    report(res, f"MAKER strategy, params={config.STRAT}")


if __name__ == "__main__":
    main()
