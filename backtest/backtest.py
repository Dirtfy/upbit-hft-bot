#!/usr/bin/env python3
"""Backtest the long-only mean-reversion scalping strategy on Upbit candles.

Design choices that keep the result honest:
  * No lookahead: the signal for bar t is computed from closes up to and
    including bar t, and the fill happens at bar t+1's OPEN.
  * Fees: Upbit KRW market fee is 0.05% per side -> 0.10% round trip, charged
    on notional at each fill.
  * Slippage: configurable bps applied against us on both entry and exit to
    approximate crossing the spread / market-order impact.
  * Exposure cap: never risk more than --capital KRW of notional at once.

Usage:
    python3 backtest.py --data ../data/krw_btc_1m.csv            # single run
    python3 backtest.py --data ../data/krw_btc_1m.csv --grid     # param search
"""
import argparse
import csv
import itertools
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from strategy import Params, StrategyState  # noqa: E402

FEE_PER_SIDE = 0.0005   # 0.05% Upbit KRW market fee


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "t": r["time_utc"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    return rows


def run(rows, params, capital=1_000_000.0, slippage_bps=2.0, fee=FEE_PER_SIDE):
    st = StrategyState(params=params)
    slip = slippage_bps / 1e4
    cash = capital
    coin = 0.0
    entry_notional = 0.0
    trades = []
    equity_curve = []
    pending = None  # signal to execute at next open

    for i, bar in enumerate(rows):
        # 1) execute any pending order at THIS bar's open
        if pending == "buy" and coin == 0.0:
            price = bar["open"] * (1 + slip)
            notional = min(cash, capital)
            qty = notional / price
            fee_paid = notional * fee
            cash -= notional + fee_paid
            coin = qty
            entry_notional = notional
            st.mark_entered(price)
            trades.append({"i": i, "side": "buy", "price": price,
                           "qty": qty, "fee": fee_paid, "t": bar["t"]})
        elif pending == "sell" and coin > 0.0:
            price = bar["open"] * (1 - slip)
            proceeds = coin * price
            fee_paid = proceeds * fee
            cash += proceeds - fee_paid
            pnl = (proceeds - fee_paid) - entry_notional - trades[-1]["fee"]
            trades.append({"i": i, "side": "sell", "price": price,
                           "qty": coin, "fee": fee_paid, "t": bar["t"],
                           "pnl": pnl})
            coin = 0.0
            entry_notional = 0.0
            st.mark_exited()
        pending = None

        # 2) compute signal on this closed bar
        sig = st.update(bar["close"])
        if sig.action == "buy" and coin == 0.0:
            pending = "buy"
        elif sig.action == "sell" and coin > 0.0:
            pending = "sell"

        equity = cash + coin * bar["close"]
        equity_curve.append(equity)

    # liquidate at final close for reporting
    final_equity = cash + coin * rows[-1]["close"]
    return summarize(trades, equity_curve, capital, final_equity, rows)


def summarize(trades, equity_curve, capital, final_equity, rows):
    sells = [t for t in trades if t["side"] == "sell"]
    pnls = [t["pnl"] for t in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    # max drawdown on equity curve
    peak = -1e18
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    ret = (final_equity - capital) / capital
    bh_ret = (rows[-1]["close"] - rows[0]["close"]) / rows[0]["close"]
    return {
        "trades": len(sells),
        "win_rate": (len(wins) / len(sells)) if sells else 0.0,
        "total_pnl_krw": final_equity - capital,
        "return_pct": ret * 100,
        "buyhold_pct": bh_ret * 100,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "max_dd_pct": max_dd * 100,
        "final_equity": final_equity,
    }


def fmt(res):
    return (f"trades={res['trades']:>4}  win={res['win_rate']*100:5.1f}%  "
            f"ret={res['return_pct']:+6.2f}%  bh={res['buyhold_pct']:+6.2f}%  "
            f"PF={res['profit_factor']:.2f}  maxDD={res['max_dd_pct']:.2f}%  "
            f"pnl={res['total_pnl_krw']:+,.0f} KRW")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="../data/krw_btc_1m.csv")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--slippage_bps", type=float, default=2.0)
    ap.add_argument("--grid", action="store_true")
    args = ap.parse_args()
    rows = load(args.data)
    print(f"loaded {len(rows)} candles: {rows[0]['t']} -> {rows[-1]['t']}")
    print(f"capital={args.capital:,.0f} KRW  slippage={args.slippage_bps}bps  "
          f"fee={FEE_PER_SIDE*100}%/side\n")

    if not args.grid:
        res = run(rows, Params(), args.capital, args.slippage_bps)
        print("default params:", Params())
        print(fmt(res))
        return

    best = None
    combos = list(itertools.product(
        [15, 20, 30, 45, 60],        # window
        [1.5, 2.0, 2.5, 3.0],        # entry_z
        [0.003, 0.004, 0.006],       # stop_loss
        [0.004, 0.006, 0.010],       # take_profit
        [20, 40],                    # max_hold
    ))
    print(f"grid search: {len(combos)} combos\n")
    results = []
    for w, ez, sl, tp, mh in combos:
        p = Params(window=w, entry_z=ez, stop_loss_pct=sl,
                   take_profit_pct=tp, max_hold=mh)
        r = run(rows, p, args.capital, args.slippage_bps)
        results.append((p, r))
    # rank by total pnl but require a minimum trade count for significance
    ranked = sorted(
        [(p, r) for p, r in results if r["trades"] >= 20],
        key=lambda x: x[1]["total_pnl_krw"], reverse=True)
    print("TOP 10 (>=20 trades), ranked by PnL:")
    for p, r in ranked[:10]:
        print(f"  W={p.window:>2} eZ={p.entry_z} SL={p.stop_loss_pct} "
              f"TP={p.take_profit_pct} MH={p.max_hold} | {fmt(r)}")
    print("\nWORST 5:")
    for p, r in ranked[-5:]:
        print(f"  W={p.window:>2} eZ={p.entry_z} SL={p.stop_loss_pct} "
              f"TP={p.take_profit_pct} MH={p.max_hold} | {fmt(r)}")


if __name__ == "__main__":
    main()
