#!/usr/bin/env python3
"""Non-HFT strategy research (mission part 2).

Thesis: a swing/position strategy that holds for hours-to-days makes few trades,
so Upbit's 0.10% round-trip fee is negligible against multi-percent moves — the
opposite of scalping, where fee > edge. We resample the 1-minute KRW-BTC data
to 4h and 1D bars and test long-only trend/breakout strategies with realistic
fees, reporting per-trade edge vs. the 0.10% round-trip cost.

CAVEAT: the dataset is only ~83 days and net up-trending (+7.8% buy&hold), which
flatters trend-following. Treat results as directional hypotheses to pursue in
future cycles on a longer history, not proof.
"""
import csv
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import config  # noqa

FEE = config.UPBIT_FEE
ROUND_TRIP_BPS = FEE * 2 * 1e4


def load_1m(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append((r["time_utc"], float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"])))
    return rows


def resample(rows, minutes):
    """Aggregate consecutive 1m bars into `minutes`-sized OHLC buckets."""
    out = []
    for i in range(0, len(rows) - minutes + 1, minutes):
        chunk = rows[i:i + minutes]
        t = chunk[0][0]
        o = chunk[0][1]
        h = max(c[2] for c in chunk)
        lo = min(c[3] for c in chunk)
        cl = chunk[-1][4]
        out.append({"t": t, "open": o, "high": h, "low": lo, "close": cl})
    return out


def sma(vals, n, i):
    if i + 1 < n:
        return None
    return sum(vals[i + 1 - n:i + 1]) / n


def bt_long_only(bars, want_long, capital=1_000_000.0):
    """Generic long-only backtest. want_long(i, closes, highs, lows) -> bool
    decides desired state using data up to and INCLUDING bar i; we act at bar
    i+1's open (no lookahead)."""
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    cash, coin, in_pos = capital, 0.0, False
    trades, entry = 0, 0.0
    pnls = []
    for i in range(len(bars) - 1):
        desired = want_long(i, closes, highs, lows)
        nxt = bars[i + 1]["open"]
        if desired and not in_pos:
            coin = (cash * (1 - FEE)) / nxt
            entry = nxt
            cash = 0.0
            in_pos = True
            trades += 1
        elif not desired and in_pos:
            cash = coin * nxt * (1 - FEE)
            coin = 0.0
            in_pos = False
            pnls.append((nxt - entry) / entry)
    equity = cash + coin * closes[-1]
    ret = (equity - capital) / capital
    bh = (closes[-1] - closes[0]) / closes[0]
    wins = [p for p in pnls if p > 0]
    return {
        "ret_pct": ret * 100, "bh_pct": bh * 100, "trades": trades,
        "closed": len(pnls),
        "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
        "avg_trade_pct": (sum(pnls) / len(pnls) * 100) if pnls else 0.0,
    }


def sma_cross(fast, slow):
    def f(i, closes, highs, lows):
        sf, ss = sma(closes, fast, i), sma(closes, slow, i)
        return sf is not None and ss is not None and sf > ss
    return f


def donchian(n_in, n_out):
    def f(i, closes, highs, lows):
        if i < max(n_in, n_out):
            return False
        # long if close breaks above prior n_in-bar high; stay long until it
        # falls below prior n_out-bar low (state approximated by close vs bands)
        up = closes[i] >= max(highs[i - n_in:i])
        dn = closes[i] <= min(lows[i - n_out:i])
        # crude state: long when most recent breakout was up
        return up or (not dn and closes[i] > sma(closes, n_out, i or 1))
    return f


def show(title, r):
    edge = r["avg_trade_pct"]
    verdict = "EDGE>fee" if edge * 100 > ROUND_TRIP_BPS else "edge<fee"
    print(f"{title:<26} ret={r['ret_pct']:+7.2f}%  bh={r['bh_pct']:+6.2f}%  "
          f"trades={r['trades']:>3}  win={r['win_rate']*100:>4.0f}%  "
          f"avgTrade={edge:+.2f}% ({verdict})")


def main():
    rows = load_1m("../data/krw_btc_1m_long.csv")
    print(f"loaded {len(rows)} 1m bars; Upbit round-trip fee = "
          f"{ROUND_TRIP_BPS:.0f} bps\n")
    for tf, mins in [("4h", 240), ("1D", 1440)]:
        bars = resample(rows, mins)
        bh = (bars[-1]["close"] - bars[0]["close"]) / bars[0]["close"] * 100
        print(f"--- {tf} bars: {len(bars)} bars, buy&hold {bh:+.2f}% ---")
        if tf == "4h":
            configs = [("SMA cross 10/50", sma_cross(10, 50)),
                       ("SMA cross 20/100", sma_cross(20, 100)),
                       ("SMA cross 5/20", sma_cross(5, 20)),
                       ("Donchian 20/10", donchian(20, 10)),
                       ("Donchian 40/20", donchian(40, 20))]
        else:
            configs = [("SMA cross 5/20", sma_cross(5, 20)),
                       ("SMA cross 10/30", sma_cross(10, 30)),
                       ("Donchian 10/5", donchian(10, 5)),
                       ("Donchian 20/10", donchian(20, 10))]
        for name, fn in configs:
            show(name, bt_long_only(bars, fn))
        print()


if __name__ == "__main__":
    main()
