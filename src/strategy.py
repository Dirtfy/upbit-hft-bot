"""Trading strategy — shared by the backtester and the live bot.

Candidate strategy: **long-only Bollinger / z-score mean-reversion scalping**
on short (1-minute) candles.

Why this shape:
  * Upbit KRW spot has no retail margin/shorting, so the strategy MUST be
    long-only. Classic market-making both-sides quoting is not available; the
    tradable edge on a highly liquid pair like BTC/KRW at the 1-minute scale is
    short-horizon mean reversion after sharp deviations from a local mean.
  * REST latency (~50-200 ms) and Upbit rate limits (~8-30 req/s) rule out
    true tick/micro-HFT. This is *high-frequency scalping*: many small trades
    on 1-minute bars, each with a tight take-profit and a hard stop.

The core is a pure function of a rolling price window so the exact same logic
runs in the backtest and live. It emits a target signal; position/risk sizing
and order execution live outside this module.
"""
from collections import deque
from dataclasses import dataclass, field
from statistics import fmean, pstdev


@dataclass
class Params:
    window: int = 20          # rolling window (candles) for mean/std
    entry_z: float = 2.0      # enter long when z-score <= -entry_z
    exit_z: float = 0.0       # exit when z-score >= exit_z (revert to mean)
    stop_loss_pct: float = 0.004   # hard stop, fraction of entry price (0.4%)
    take_profit_pct: float = 0.006 # take profit, fraction of entry price (0.6%)
    max_hold: int = 30        # force-exit after N candles (avoid bag-holding)
    min_std_bps: float = 5.0  # ignore signals when vol is tiny (bps of price)


@dataclass
class Signal:
    action: str               # "buy", "sell", or "hold"
    reason: str = ""
    z: float = 0.0


@dataclass
class StrategyState:
    """Rolling state; feed it one closed candle at a time via update()."""
    params: Params = field(default_factory=Params)
    closes: deque = field(default_factory=lambda: deque())
    in_position: bool = False
    entry_price: float = 0.0
    bars_held: int = 0

    def __post_init__(self):
        self.closes = deque(maxlen=self.params.window)

    def _zscore(self, price):
        if len(self.closes) < self.params.window:
            return None, None, None
        mean = fmean(self.closes)
        std = pstdev(self.closes)
        if std <= 0:
            return None, mean, std
        return (price - mean) / std, mean, std

    def update(self, close):
        """Return a Signal given a newly *closed* candle's close price.

        The decision uses the window *before* this close is appended (no
        lookahead): stats are computed on prior candles, the signal applies to
        acting at the next open.
        """
        p = self.params
        z, mean, std = self._zscore(close)
        sig = Signal("hold", z=z or 0.0)

        if self.in_position:
            self.bars_held += 1
            change = (close - self.entry_price) / self.entry_price
            if change <= -p.stop_loss_pct:
                sig = Signal("sell", "stop_loss", z or 0.0)
            elif change >= p.take_profit_pct:
                sig = Signal("sell", "take_profit", z or 0.0)
            elif z is not None and z >= p.exit_z:
                sig = Signal("sell", "mean_revert", z)
            elif self.bars_held >= p.max_hold:
                sig = Signal("sell", "timeout", z or 0.0)
        else:
            if z is not None and std is not None:
                std_bps = (std / close) * 1e4
                if z <= -p.entry_z and std_bps >= p.min_std_bps:
                    sig = Signal("buy", "oversold", z)

        self.closes.append(close)
        return sig

    def mark_entered(self, price):
        self.in_position = True
        self.entry_price = price
        self.bars_held = 0

    def mark_exited(self):
        self.in_position = False
        self.entry_price = 0.0
        self.bars_held = 0
