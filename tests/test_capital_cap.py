#!/usr/bin/env python3
"""Cycle 15 — tests for the fixed tradable-capital cap that protects profit.

Plain asserts (no pytest dependency): run with `python3 tests/test_capital_cap.py`.
Covers (1) the sizing primitive (RiskManager), including profit accumulation and
drawdown, and (2) the paper-book replay actually protecting profit (capped vs an
uncapped counterfactual). Research/paper only — no orders, no keys.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config            # noqa: E402
import risk              # noqa: E402
import donchian_bot as d  # noqa: E402

BASE = config.BASE_TRADABLE_CAPITAL_KRW
checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def rm():
    return risk.RiskManager(os.path.join(tempfile.mkdtemp(), "r.json"))


# ---- (1) sizing primitive ------------------------------------------------
print("tradable_capital / protected_profit:")
r = rm()
check("no balance tracked -> full base", r.tradable_capital() == BASE)
check("profit: balance 1.1x base -> tradable capped at base",
      r.tradable_capital(BASE + 100_000) == BASE)
check("profit: 100k above base is protected",
      r.protected_profit(BASE + 100_000) == 100_000)
check("at base -> no protected profit", r.protected_profit(BASE) == 0)
check("drawdown: balance below base -> tradable = balance",
      r.tradable_capital(BASE - 400_000) == BASE - 400_000)
check("drawdown: nothing protected below base",
      r.protected_profit(BASE - 400_000) == 0)

print("can_open sizes against capped tradable capital (not raw balance):")
_pt = config.PER_TRADE_KRW
config.PER_TRADE_KRW = 5_000_000.0        # lift per-trade so the BASE cap binds
try:
    r = rm()
    check("huge balance (5x base) still capped at base",
          r.can_open(free_balance=5 * BASE) == BASE)
    r = rm()
    check("drawdown balance 0.6x base -> sized to 0.6x base",
          abs(r.can_open(free_balance=0.6 * BASE) - 0.6 * BASE) < 1e-6)
    r = rm()
    check("no balance arg -> base (backward compatible)",
          r.can_open() == BASE)
    # gap cap also respects tradable capital
    r = rm()
    gc = r.gap_capped_notional(stop_distance_frac=0.5, free_balance=5 * BASE)
    check("gap_capped_notional <= tradable base", gc <= BASE)
finally:
    config.PER_TRADE_KRW = _pt

# ---- (2) replay protects profit -----------------------------------------
print("paper-book replay protects profit above base (capped vs uncapped):")
# tiny-window Donchian so a few synthetic bars trigger enter/win/exit/re-enter
p = {"unit": 240, "n_in": 2, "n_out": 2, "atr_k": 0.0, "atr_bars": 2,
     "target_vol": None, "vol_n": 2}


def bar(t, o, h, l, c):
    return {"t": f"2026-09-12T{t:02d}:00:00", "open": o, "high": h,
            "low": l, "close": c}


bars = [
    bar(0, 100, 100, 100, 100), bar(1, 100, 100, 100, 100),
    bar(2, 100, 100, 100, 100),                 # anchor (flat, books = BASE)
    bar(3, 100, 100, 100, 100),                 # BUY ~100 (breakout of 2-bar high)
    bar(4, 300, 300, 300, 300),                 # winner runs
    bar(5, 320, 320, 320, 320),
    bar(6, 310, 310, 250, 260),                 # SELL ~300 (channel exit) -> big win
    bar(7, 305, 330, 305, 325),                 # RE-ENTER ~320 (only BASE deployed)
    bar(8, 30, 30, 30, 30),                     # CRASH while long
    bar(9, 30, 30, 30, 30),
]
rows = d.replay(bars, p, "resting", anchor_idx=2)
final_capped = float(rows[-1]["equity_full_krw"])

_B = d.BASE
d.BASE = 1e15                                    # uncapped counterfactual
try:
    rows_u = d.replay(bars, p, "resting", anchor_idx=2)
    final_uncapped = float(rows_u[-1]["equity_full_krw"])
finally:
    d.BASE = _B

n_buys = sum(1 for r in rows if r["action"] == "BUY")
print(f"    buys={n_buys}  final_capped={final_capped:,.0f}  "
      f"final_uncapped={final_uncapped:,.0f}")
check("scenario re-enters after a win (>=2 buys)", n_buys >= 2)
check("capped book keeps protected profit through the crash (final > 1.5x base)",
      final_capped > 1.5 * BASE)
check("uncapped book re-risks profit and is far smaller after the crash",
      final_uncapped < 0.5 * BASE)
check("cap made a large difference (capped >> uncapped)",
      final_capped > 3 * final_uncapped)

# ---- summary -------------------------------------------------------------
failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
