#!/usr/bin/env python3
"""Tests for the bear-market strategy: regime detection, target signals, the
fill engine (no-lookahead / fees), and the live-engine safety gating.

Plain asserts (no pytest): run with `python3 tests/test_bear_strategy.py`.
Research/paper only — constructs no client, places no orders, uses no keys.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config          # noqa: E402
import regime          # noqa: E402
import bear_strategy as bs  # noqa: E402
import live_engine as le    # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def bars_from_closes(closes):
    """Synthetic OHLC bars from a close series (open=prev close, hi/lo = close)."""
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append({"t": f"2020-01-{i+1:02d}T00:00:00" if i < 31 else f"2020-{(i//30)+1:02d}-{(i%30)+1:02d}T00:00:00",
                    "open": o, "high": max(o, c), "low": min(o, c), "close": c})
    return out


P = dict(sma_long=5, sma_mid=3, band=0.0, dd_window=10, dd_enter=0.20,
         dd_exit=0.10, n_in=3, n_out=2)

# ---- (1) regime primitives ----------------------------------------------
print("regime detection:")
# rising series: after warmup, price above SMA -> bull
up = [100, 101, 102, 103, 104, 106, 108, 110, 112, 114, 116, 118]
r = regime.compute_regimes(bars_from_closes(up), P)
check("first sma_long-1 bars are warmup", r[:4] == ["warmup"] * 4)
check("sustained uptrend -> ends bull", r[-1] == "bull")

# crash from a peak: drawdown breaker forces bear even if near SMA
crash = [100, 110, 120, 130, 140, 150, 150, 150, 150, 120, 100, 90]
rc = regime.compute_regimes(bars_from_closes(crash), P)
check("drawdown >20% off high forces bear", rc[-1] == "bear")
dd = regime.drawdown_from_high([100, 150, 120], 2, 10)
check("drawdown_from_high computes 20% off 150", abs(dd - (1 - 120 / 150)) < 1e-9)

# hysteresis: once bear, need recovery ABOVE sma to flip back (not just touch)
check("sma helper returns None before warmup", regime.sma([1, 2, 3], 1, 5) is None)
check("sma helper averages window", regime.sma([2, 4, 6], 2, 3) == 4)

# ---- (2) target signals --------------------------------------------------
print("target signals:")
lf = bs.targets(bars_from_closes(up), P, "long_flat")
check("long_flat target is 1 exactly when regime bull",
      all((t == 1) == (rr == "bull") for t, rr in zip(lf, r)))
check("warmup bars are flat (0) in long_flat", all(lf[i] == 0 for i in range(4)))

# breakout with no regime enters on a new high; regime variant can veto
bo = bs.targets(bars_from_closes(up), P, "breakout")
bor = bs.targets(bars_from_closes(up), P, "breakout_regime")
check("breakout goes long in a clean uptrend", bo[-1] == 1)
check("breakout_regime never long while regime is bear",
      all(not (bor[i] == 1 and r[i] == "bear") for i in range(len(bor))))
check("unknown mode rejected",
      _raises(lambda: bs.targets(bars_from_closes(up), P, "nope")))

# ---- (3) fill engine: no lookahead + fees --------------------------------
print("fill engine:")
# desired long from bar 0 -> fill happens at bar 1 OPEN, not bar 0
b = bars_from_closes([100, 110, 121])
eq, held, tr = bs.run_book(b, [1, 1, 1], 1_000_000)
check("entry fills at NEXT bar open (no same-bar fill)", held[0] == 0 and held[1] == 1)
# bought at bar1 open=100 (=prev close), fee 0.05%; equity at bar1 close=110
expected_coin = 1_000_000 * (1 - config.UPBIT_FEE) / 100
check("equity marks position at close with fee applied",
      abs(eq[1] - expected_coin * 110) < 1.0)
# a flat->long->flat round trip records one trade with the right return.
# open[i] = close[i-1], so closes [100,120,120] give entry open=100 (bar1),
# exit open=120 (bar2) -> +20% gross.
b2 = bars_from_closes([100, 120, 120])
eq2, held2, tr2 = bs.run_book(b2, [1, 0, 0], 1_000_000)
check("one round trip recorded", len(tr2) == 1)
check("trade return ~ +20% before fees", abs(tr2[0]["ret"] - 0.2) < 1e-9)
# buy-and-hold never goes to cash
bh = bs.buy_and_hold(b, 1_000_000)
check("buy_and_hold tracks price from first open", bh[-1] > bh[0])

# last-bar decision cannot be executed (no next bar) -> no lookahead leak
eq3, held3, _ = bs.run_book(b, [0, 0, 1], 1_000_000)
check("a target on the final bar never fills (needs a next open)", held3[-1] == 0)

# ---- (4) live-engine safety gating ---------------------------------------
print("live-engine gating:")
check("master switch defaults OFF", config.LIVE_TRADING_ENABLED is False)


class _Args:
    live = True
    yes = True
    mode = "long_flat"


ok, reasons = le.live_gates_ok(_Args())
check("live gates NOT ok with master switch off", ok is False)
check("reason names the master switch",
      any("LIVE_TRADING_ENABLED" in x for x in reasons))
check("reason names missing keys", any("keys" in x for x in reasons))


class _ArgsNoLive(_Args):
    live = False


ok2, reasons2 = le.live_gates_ok(_ArgsNoLive())
check("without --live, gates report the flag missing",
      any("--live" in x for x in reasons2))

# ---- summary -------------------------------------------------------------
failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
