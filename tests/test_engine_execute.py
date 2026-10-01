#!/usr/bin/env python3
"""Tests for the engine's BUY -> SELL execution path (`live_engine.execute`) and
the counterfactual shadow replay that drives it (Cycle 27).

Regression cover for the bugs the shadow replay found:
  * live SELL booked record_close(0, 0): open notional never released and the
    daily-loss kill switch could never fire on live losses;
  * dry-run never touched the risk book, so cap / kill switch were untested;
  * dry-run SELL PnL ignored fees (and there was no slippage);
  * a HALT flag blocked protective exits as well as entries.

No network, no keys: the "live" case uses an in-memory fake exchange client.
Plain asserts (no pytest): run with `python3 tests/test_engine_execute.py`.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "paper_trading", "shadow"))
import config                      # noqa: E402
import live_engine as le           # noqa: E402
from risk import RiskManager       # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


T0 = datetime(2026, 9, 27, tzinfo=timezone.utc)
FEE = config.UPBIT_FEE


def bar(px, t=T0):
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%S"), "open": px, "high": px,
            "low": px, "close": px}


def book():
    d = tempfile.mkdtemp()
    clock = {"now": T0 + timedelta(days=1, minutes=5)}
    risk = RiskManager(os.path.join(d, "risk.json"), clock=lambda: clock["now"])
    return risk, os.path.join(d, "state.json"), clock


def run(target, b, risk, state, clock, **kw):
    return le.execute(target, b, risk=risk, state_path=state, now=clock["now"],
                      log=lambda m: None, **kw)


# ---- fee/slippage-correct round trip PnL ----
check("round_trip_pnl: flat price loses exactly both fees",
      abs(le.round_trip_pnl(200_000, 200_000 * (1 - FEE) / 100.0, 100.0)
          - (200_000 * (1 - FEE) ** 2 - 200_000)) < 1e-6)

# ---- dry-run BUY -> SELL books into the risk manager ----
risk, state, clock = book()
b1 = run(1, bar(100_000_000.0), risk, state, clock, slip_bps=0)
check("dry-run BUY sized at PER_TRADE and recorded as open notional",
      b1["action"] == "BUY" and b1["notional"] == config.PER_TRADE_KRW
      and risk.s["open_notional"] == config.PER_TRADE_KRW)
s1 = run(0, bar(110_000_000.0), risk, state, clock, slip_bps=0)
exp = b1["qty"] * 110_000_000.0 * (1 - FEE) - b1["notional"]
check("dry-run SELL PnL is net of both fees",
      s1["action"] == "SELL" and abs(s1["pnl"] - exp) < 1e-6)
check("dry-run SELL releases open notional and books realized PnL",
      risk.s["open_notional"] == 0 and abs(risk.s["realized_pnl_today"] - exp) < 1e-6
      and risk.s["trades_today"] == 1)

# ---- slippage moves both fills against us ----
risk, state, clock = book()
b = run(1, bar(100.0e6), risk, state, clock, slip_bps=10)
s = run(0, bar(100.0e6), risk, state, clock, slip_bps=10)
check("slippage: buy above close, sell below close, both counted",
      b["fill"] > 100.0e6 > s["fill"] and b["slippage"] > 0 and s["slippage"] > 0)

# ---- kill switch trips from dry-run losses; HALT blocks entry, not exit ----
risk, state, clock = book()
for _ in range(2):
    run(1, bar(100.0e6), risk, state, clock, slip_bps=0)
    last = run(0, bar(85.0e6), risk, state, clock, slip_bps=0)   # ~-30k each
check("two -15% round trips in one day trip the kill switch",
      risk.is_halted() and last["risk_path"] == "kill_switch_tripped"
      and risk.s["realized_pnl_today"] <= -config.DAILY_LOSS_LIMIT_KRW)
e = run(1, bar(100.0e6), risk, state, clock, slip_bps=0)
check("HALT blocks a new entry", e["action"] == "HOLD"
      and e["risk_path"] == "halt_blocked_entry")
check("clearing HALT the same day re-trips it (loss still over the limit)",
      (risk.clear_halt(), run(1, bar(100.0e6), risk, state, clock, slip_bps=0))[1]
      ["risk_path"].startswith("veto") and risk.is_halted())
risk.clear_halt()
clock["now"] += timedelta(days=1)                 # next UTC day: loss window resets
run(1, bar(100.0e6, T0 + timedelta(days=1)), risk, state, clock, slip_bps=0)
risk.trip_halt("operator")
x = run(0, bar(100.0e6, T0 + timedelta(days=1)), risk, state, clock, slip_bps=0)
check("HALT still allows the protective exit", x["action"] == "SELL"
      and x["risk_path"] == "exit_allowed_under_halt")

# ---- stale data blocks entry, allows exit ----
risk, state, clock = book()
clock["now"] = T0 + timedelta(days=4)          # candle closed 72h ago
e = run(1, bar(100.0e6), risk, state, clock)
check("stale feed blocks a new entry", e["risk_path"] == "stale_blocked_entry")
clock["now"] = T0 + timedelta(days=1, minutes=5)
run(1, bar(100.0e6), risk, state, clock)
clock["now"] = T0 + timedelta(days=4)
x = run(0, bar(100.0e6), risk, state, clock)
check("stale feed still allows an exit", x["action"] == "SELL"
      and x["risk_path"] == "exit_allowed_on_stale_data")


# ---- LIVE path with a fake exchange: SELL now books real PnL ----
class FakeClient:
    def __init__(self, px):
        self.px, self.krw, self.btc, self.orders = px, 1_000_000.0, 0.0, []

    def balance(self, cur):
        return (self.krw if cur == "KRW" else self.btc), 0.0

    def ticker(self, market):
        return {"trade_price": self.px}

    def buy_market(self, market, krw):
        self.orders.append(("BUY", krw))
        self.btc += krw * (1 - FEE) / self.px
        self.krw -= krw
        return {"uuid": "fake-buy"}

    def sell_market(self, market, qty):
        self.orders.append(("SELL", qty))
        self.krw += qty * self.px * (1 - FEE)
        self.btc -= qty
        return {"uuid": "fake-sell"}


risk, state, clock = book()
fc = FakeClient(100.0e6)
run(1, bar(100.0e6), risk, state, clock, live=True, client=fc, slip_bps=0)
fc.px = 85.0e6
x = run(0, bar(85.0e6), risk, state, clock, live=True, client=fc, slip_bps=0)
check("live SELL releases open notional (was stuck at 200k)",
      risk.s["open_notional"] == 0 and [o[0] for o in fc.orders] == ["BUY", "SELL"])
check("live SELL books the realized loss (was booked as 0)",
      x["pnl"] < -29_000 and abs(risk.s["realized_pnl_today"] - x["pnl"]) < 1e-6)
fc.px = 100.0e6
run(1, bar(100.0e6), risk, state, clock, live=True, client=fc, slip_bps=0)
fc.px = 85.0e6
run(0, bar(85.0e6), risk, state, clock, live=True, client=fc, slip_bps=0)
check("live losses can now trip the daily kill switch", risk.is_halted())

# ---- shadow replay: isolated, labelled, exercises every risk path ----
import shadow_replay as sr          # noqa: E402

out = tempfile.mkdtemp()
sr.HERE = out                       # write the replay ledger to a temp dir
official = [os.path.join(ROOT, "paper_trading", f)
            for f in ("paper_log.jsonl", "JOURNAL.md", "SUMMARY.md")]
before = [open(p, "rb").read() for p in official]
evs = sr.scenario_stress(sr.load_bars(sr.DATA_4H))
paths = {e["risk_path"] for e in evs}
check("stress replay fires kill switch, HALT block, exit-under-HALT, stale block",
      {"kill_switch_tripped", "halt_blocked_entry", "exit_allowed_under_halt",
       "stale_blocked_entry"} <= paths)
check("every shadow record is labelled counterfactual",
      all(json.loads(l)["counterfactual"] is True
          for l in open(os.path.join(out, "shadow_risk_stress.jsonl"))))
check("shadow replay leaves the official ledger byte-identical",
      before == [open(p, "rb").read() for p in official])
fr = sr.scenario_forced(sr.load_bars(sr.DATA_4H))
check("forced-regime replay completes round trips within the caps",
      sum(e["action"] == "SELL" for e in fr) >= 1
      and max(e["open_notional"] for e in fr) <= config.MAX_EXPOSURE_KRW
      and max(e.get("notional", 0) for e in fr) <= config.PER_TRADE_KRW)

failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
