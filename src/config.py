"""Configuration + secret loading.

Secrets are loaded from environment variables, optionally seeded from a
gitignored `secrets.env` file. Keys are NEVER written to logs or reports:
`redact()` guards any accidental echo.
"""
import os

MARKET = "KRW-BTC"

# --- Hard risk limits (see risk.py). These are the safety envelope. ---
MAX_EXPOSURE_KRW = 1_000_000.0   # mission cap: total notional never exceeds this
# Fixed trading budget (Cycle 15). Sizing draws only from this base; any account
# balance ABOVE it is locked/protected profit that is never re-risked. Tunable.
# Tradable capital = min(BASE_TRADABLE_CAPITAL_KRW, current free balance) — see
# RiskManager.tradable_capital(). Drawdown below base -> trade the reduced balance
# (never deploy more than base, never deploy money you don't have).
BASE_TRADABLE_CAPITAL_KRW = 1_000_000.0
PER_TRADE_KRW = 200_000.0        # notional per entry (<= MAX_EXPOSURE_KRW)
DAILY_LOSS_LIMIT_KRW = 50_000.0  # kill switch trips if realized daily loss exceeds
MIN_ORDER_KRW = 5_000.0          # Upbit minimum order size
UPBIT_FEE = 0.0005               # 0.05% per side (KRW market)

# --- Execution-gap risk (Cycle 13). The agent can be blind for up to ~5h (the
# session limit); during that window it places/adjusts nothing. A naked position
# is then exposed to the full adverse move over the blind window. Empirically
# (9y BTC/KRW, backtest/cycle13_gap.py) the ~5h adverse move is ~-5.6% at the 1st
# percentile and ~-13% at the 0.1st. Two independent protections (risk.py):
#   1) a RESTING protective stop is assumed always in the market (bounds loss to
#      the stop distance even while blind) — the primary mitigation; and
#   2) if sizing WITHOUT relying on the stop, cap notional so a BLIND_WORST_MOVE
#      drop cannot breach DAILY_LOSS_LIMIT_KRW.
MAX_BLIND_HOURS = 5.0            # assume the bot can do nothing for up to this long
BLIND_WORST_MOVE = 0.13         # conservative adverse move over a blind window (13%)

# --- Strategy params (see backtest results; tune in one place) ---
# Chosen from the targeted backtest (see research/BACKTEST_REPORT.md). This is
# the most trade-dense config that stayed positive after fees (PF~1.05, 39
# trades). The edge is MARGINAL and not yet proven live -> paper mode is the
# default; do not run live until forward paper results confirm expectancy.
STRAT = dict(
    window=120,
    entry_z=3.0,
    exit_z=0.0,
    stop_loss_pct=0.012,
    take_profit_pct=0.012,
    max_hold=60,
    min_std_bps=5.0,
)

# --- Bear-market regime filter (see research/BEAR_MARKET_STRATEGY.md) ---
# A defensive trend/regime filter for KRW-BTC (Upbit is spot-only: no shorting,
# so a "bear-market strategy" here means capital preservation — hold cash through
# downtrends and only be long in confirmed up-regimes). Two independent bear
# triggers: (1) price below its long SMA (Faber 2007 200-day timing rule) and
# (2) drawdown-from-trailing-high beyond DD_ENTER (the conventional -20% bear
# definition). Hysteresis (BAND / DD_EXIT) damps whipsaw at the boundary.
BEAR = dict(
    sma_long=200,     # long-term trend filter (daily bars); Faber-style timing
    sma_mid=50,       # mid MA (reported; death-cross context)
    band=0.0,         # hysteresis band around SMA as a fraction (0 = plain cross)
    dd_window=365,    # trailing-high lookback (bars) for the drawdown breaker
    dd_enter=0.20,    # drawdown-from-high that forces the bear regime (>= 20%)
    dd_exit=0.10,     # must recover to within this of the high to allow bull again
    n_in=20,          # Donchian entry channel (active breakout overlay)
    n_out=10,         # Donchian exit channel
)

# --- LIVE trading master switch (OFF by default) -------------------------
# Live order placement is gated behind ALL of: this flag True, the CLI --live
# flag, a typed confirmation phrase, AND present API keys. Default False so no
# real order can ever fire without a deliberate go-live CONFIG change relayed by
# the owner. Flipping to live is this one flag + keys — not a code rewrite.
LIVE_TRADING_ENABLED = False

POLL_SECONDS = 2.0   # loop cadence; 1-min candles, so sub-minute polling is fine

# --- Execution (maker entries) ---
ENTRY_TTL_CANDLES = 3   # cancel an unfilled maker buy after this many candles
TAKER_SLIP_BPS = 1.5    # assumed adverse slippage on taker (stop/timeout) exits


def _load_secrets_file(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_keys():
    """Return (access_key, secret_key). Raises if missing. Never logs them."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _load_secrets_file(os.path.join(here, "secrets.env"))
    access = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
    secret = os.environ.get("UPBIT_SECRET_KEY", "").strip()
    if not access or not secret:
        raise RuntimeError(
            "Missing UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY. Set them in the "
            "environment or in a gitignored secrets.env (see "
            "secrets.env.example).")
    return access, secret


def redact(s):
    """Best-effort scrub of anything key-shaped from a string before logging."""
    for k in ("UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY"):
        v = os.environ.get(k)
        if v and v in s:
            s = s.replace(v, "***REDACTED***")
    return s
