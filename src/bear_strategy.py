"""Bear-market defense strategy — shared logic for backtest AND live engine.

Upbit KRW markets are spot-only (no shorting/margin for retail), so the way to
"trade the bear" is capital preservation: be long BTC only in a confirmed
up-regime and sit in KRW cash through downtrends, side-stepping the deep
bear-market drawdowns that buy-and-hold suffers. See
research/BEAR_MARKET_STRATEGY.md for the design and citations.

Three long/flat variants (all long-only, all-in / flat):
  * "long_flat"        — long when regime is bull, flat otherwise (the pure
                         regime filter; Faber-style timing).
  * "breakout"         — Donchian(n_in/n_out) breakout, NO regime filter
                         (an active baseline to measure the filter against).
  * "breakout_regime"  — Donchian breakout, but only ENTER when the regime is
                         bull and force-EXIT the moment it turns bear (the
                         bear-defended active strategy).

Targets are computed from data through bar i only; fills happen at bar i+1's
OPEN (no lookahead). This module is import-only (no side effects) so both the
runnable backtest and the live/dry-run engine derive the target position from
exactly the same code — what you backtest is what trades.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from regime import compute_regimes  # noqa: E402

FEE = config.UPBIT_FEE

MODES = ("long_flat", "breakout", "breakout_regime")


def _warmup(p):
    return max(p["sma_long"], p["dd_window"], p["n_in"], p["n_out"])


def targets(bars, p, mode):
    """Return list[int] desired position (0 flat / 1 long) per bar, no lookahead.

    For breakout variants the signal is stateful (Donchian channel): enter when
    the bar's high breaks the prior n_in-bar high; exit when its low breaks the
    prior n_out-bar low. The regime overlay gates entries and forces exits."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
    regimes = compute_regimes(bars, p)
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    des, state = [], 0
    n_in, n_out = p["n_in"], p["n_out"]
    for i in range(len(bars)):
        if mode == "long_flat":
            des.append(1 if regimes[i] == "bull" else 0)
            continue
        if i < max(n_in, n_out):
            des.append(0)
            continue
        up = max(highs[i - n_in:i])          # prior channel (excludes bar i)
        dn = min(lows[i - n_out:i])
        bull = regimes[i] == "bull"
        if state == 0:
            if bars[i]["high"] >= up and (mode == "breakout" or bull):
                state = 1
        else:
            breakdown = bars[i]["low"] <= dn
            regime_exit = (mode == "breakout_regime" and regimes[i] == "bear")
            if breakdown or regime_exit:
                state = 0
        des.append(state)
    return des


def run_book(bars, desired, capital, fee=FEE):
    """Fill `desired` positions at each next bar's OPEN, compounding the full book
    (all-in / flat). Returns (equity[], pos[], trades[]). Equity is marked at each
    bar's close; pos[i] is the position held THROUGH bar i."""
    cash, coin, pos = capital, 0.0, 0
    entry_px = entry_t = None
    equity, held, trades = [], [], []
    pending = None
    for i, b in enumerate(bars):
        # execute the decision made on bar i-1 at THIS bar's open
        if pending is not None and pending != pos:
            fill = b["open"]
            if pending == 1:                 # buy: deploy all cash
                coin = cash * (1 - fee) / fill
                cash = 0.0
                entry_px, entry_t = fill, b["t"]
                pos = 1
            else:                            # sell: liquidate to cash
                proceeds = coin * fill * (1 - fee)
                ret = fill / entry_px - 1
                trades.append({"entry_t": entry_t, "exit_t": b["t"],
                               "entry": entry_px, "exit": fill, "ret": ret,
                               "pnl_frac": proceeds / (coin * entry_px) - 1})
                cash, coin, pos = proceeds, 0.0, 0
        pending = None
        equity.append(cash + coin * b["close"])
        held.append(pos)
        # decide for the next bar
        if i < len(desired) and desired[i] != pos:
            pending = desired[i]
    return equity, held, trades


def buy_and_hold(bars, capital, fee=FEE):
    """Benchmark: buy at the first bar's open, hold to the end."""
    fill = bars[0]["open"]
    coin = capital * (1 - fee) / fill
    return [coin * b["close"] for b in bars]


def replay(bars, p, mode, capital):
    """Convenience: targets -> run_book. Returns (equity, held, trades)."""
    return run_book(bars, targets(bars, p, mode), capital)
