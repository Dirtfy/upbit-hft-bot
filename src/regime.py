"""Bear-market regime detection for KRW-BTC (daily bars).

The regime is the single source of truth shared by the backtest
(backtest/bear_backtest.py) and the live/dry-run engine (src/live_engine.py),
so what is tested historically is exactly what trades.

A bar is classified "bear" when EITHER trend or drawdown says so:
  1. TREND  : close < SMA(sma_long)             (Faber 2007 long-SMA timing rule)
  2. DRAWDOWN: close is >= dd_enter below its trailing dd_window high
              (the conventional ">=20% off the peak" bear-market definition)
Otherwise "bull". Hysteresis avoids flip-flopping at the boundary: once bear,
we require close > SMA*(1+band) AND drawdown back within dd_exit to return to
bull; once bull, either trigger flips us to bear. Bars before SMA warmup are
"warmup" (treated as not-long by callers).

Rationale and citations: research/BEAR_MARKET_STRATEGY.md.
"""


def sma(vals, i, n):
    """Simple moving average of vals[i-n+1 .. i], or None if insufficient history."""
    if n <= 0 or i + 1 < n:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def drawdown_from_high(closes, i, window):
    """Fractional drawdown of close[i] below the trailing `window`-bar high (0..1)."""
    lo = max(0, i - window + 1)
    peak = max(closes[lo:i + 1])
    if peak <= 0:
        return 0.0
    return max(0.0, 1.0 - closes[i] / peak)


def compute_regimes(bars, p):
    """Return a list[str] ("warmup"|"bull"|"bear"), one per bar, computed with
    data through that bar only (no lookahead). `p` is a BEAR-style param dict."""
    closes = [b["close"] for b in bars]
    band = p.get("band", 0.0)
    out = []
    state = "bear"                       # start defensive: long only once confirmed
    for i in range(len(bars)):
        sl = sma(closes, i, p["sma_long"])
        if sl is None:
            out.append("warmup")
            continue
        dd = drawdown_from_high(closes, i, p["dd_window"])
        if state == "bull":
            if closes[i] < sl * (1 - band) or dd >= p["dd_enter"]:
                state = "bear"
        else:  # bear -> require trend AND drawdown recovery to re-enter
            if closes[i] > sl * (1 + band) and dd <= p["dd_exit"]:
                state = "bull"
        out.append(state)
    return out


def current_regime(bars, p):
    """Regime of the most recent (closed) bar — what the live engine acts on."""
    r = compute_regimes(bars, p)
    return r[-1] if r else "warmup"
