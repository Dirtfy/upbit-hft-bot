#!/usr/bin/env python3
"""COUNTERFACTUAL shadow replay (owner-approved 2026-10-01) — NOT the official
paper ledger.

The official paper run has stayed FLAT since 2026-09-24 because the market is in
a bear regime, so its BUY -> hold -> SELL path has never run. This one-off script
drives that path end to end through the REAL engine code
(`live_engine.execute` + `RiskManager`), in DRY-RUN, against real market data:

  A  forced_regime   — the committed 4h trail (paper_trading/market_data_4h.csv),
                       one decision per closed 4h candle, with the regime
                       OVERRIDDEN to a fixed bull/bear schedule (counterfactual).
                       Real prices; fees, slippage, sizing and the risk book are
                       real.
  B  risk_stress     — same real 4h data with a SYNTHETIC price shock injected
                       plus an operator HALT and a stale-feed step, so the
                       daily-loss kill switch, HALT entry block, exit-under-HALT,
                       stale-data block and manual HALT clear all fire.
  C  historical      — no override: the genuine long_flat strategy replayed daily
                       over real history (data/krw_btc_1d.csv, gitignored backtest
                       dataset) from 2023-01-01, so real bear->bull->bear regime
                       flips drive the trades.

SAFETY — research/PAPER only: no network, no API keys, no account, no orders.
State and risk files live in a throwaway temp dir; nothing official (paper_log,
JOURNAL, SUMMARY, live_engine state/risk files) is read or written. Config limits
(1,000,000 KRW cap, per-trade size, daily loss limit) are used unchanged.

Output: paper_trading/shadow/shadow_<scenario>.jsonl + SHADOW_REPORT.md +
JOURNAL.md (counterfactual trade journal).
Usage:  python3 paper_trading/shadow/shadow_replay.py
"""
import csv
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PT = os.path.dirname(HERE)
ROOT = os.path.dirname(PT)
sys.path.insert(0, os.path.join(ROOT, "src"))
import config                      # noqa: E402
import bear_strategy as bs         # noqa: E402
import live_engine as le           # noqa: E402
from risk import RiskManager       # noqa: E402

DATA_4H = os.path.join(PT, "market_data_4h.csv")
DATA_1D = os.path.join(ROOT, "data", "krw_btc_1d.csv")
REPORT = os.path.join(HERE, "SHADOW_REPORT.md")
JOURNAL = os.path.join(HERE, "JOURNAL.md")
BAR_4H = timedelta(hours=4)
BAR_1D = timedelta(days=1)


def load_bars(path, since=None):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            t = r["time_utc"]
            if since and t < since:
                continue
            bars.append({"t": t, "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def _dt(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


class Shadow:
    """One isolated dry-run book: temp state + temp risk file + replay clock."""

    def __init__(self, name):
        self.name = name
        self.dir = tempfile.mkdtemp(prefix=f"shadow_{name}_")
        self.state = os.path.join(self.dir, "state.json")
        self.now = datetime(1970, 1, 1, tzinfo=timezone.utc)   # set per step
        self.risk = RiskManager(os.path.join(self.dir, "risk.json"),
                                clock=lambda: self.now)
        self.cash = config.BASE_TRADABLE_CAPITAL_KRW
        self.btc = 0.0
        self.events = []

    def step(self, bar, target, now, note=None):
        self.now = now
        msgs = []
        ev = le.execute(target, bar, risk=self.risk, state_path=self.state,
                        free_krw=self.cash, now=now, log=msgs.append)
        if ev["action"] == "BUY":
            self.cash -= ev["notional"]
            self.btc += ev["qty"]
        elif ev["action"] == "SELL":
            self.cash += ev["notional"] + ev["pnl"]
            self.btc -= ev["qty"]
        rec = {"scenario": self.name, "counterfactual": True, "candle_t": bar["t"],
               "decided_at": now.isoformat(), "close": bar["close"],
               "target": "LONG" if target else "FLAT", **ev,
               "cash": round(self.cash, 2), "btc": round(self.btc, 8),
               "equity": round(self.cash + self.btc * bar["close"], 2),
               "risk_today": round(self.risk.s["realized_pnl_today"], 2),
               "open_notional": round(self.risk.s["open_notional"], 2),
               "halted": self.risk.is_halted(), "note": note, "log": msgs}
        for k in ("fill", "qty", "notional", "fee", "slippage", "pnl"):
            if k in rec:
                rec[k] = round(rec[k], 8 if k == "qty" else 2)
        self.events.append(rec)
        return rec

    def close(self):
        with open(os.path.join(HERE, f"shadow_{self.name}.jsonl"), "w") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        shutil.rmtree(self.dir, ignore_errors=True)
        return self.events


# ---------------------------------------------------------------- scenarios ---

def scenario_forced(bars):
    """Regime override: 12 bars (2 days) bull, then 6 bars (1 day) bear, repeat."""
    sh = Shadow("forced_regime")
    for i, b in enumerate(bars):
        target = 1 if (i % 18) < 12 else 0
        sh.step(b, target, _dt(b["t"]) + BAR_4H + timedelta(minutes=1),
                note="override=" + ("bull" if target else "bear"))
    return sh.close()


def scenario_stress(bars):
    """Scripted risk walk on real 4h bars; synthetic shocks are labelled."""
    sh = Shadow("risk_stress")
    seq = bars[-30:]

    def bar(k, shock=None):
        b = dict(seq[k])
        if shock:
            b = dict(b, close=b["close"] * (1 + shock), low=min(b["low"], b["close"] * (1 + shock)))
        return b

    def at(k, extra=timedelta(0)):
        return _dt(seq[k]["t"]) + BAR_4H + timedelta(minutes=1) + extra

    # 1) normal round trip on real prices
    sh.step(bar(0), 1, at(0), "enter")
    sh.step(bar(1), 0, at(1), "exit (real price)")
    # 2) two losing round trips inside one UTC day -> daily-loss kill switch
    #    (DAILY_LOSS_LIMIT 50,000 KRW on 200,000 KRW trades needs ~-25% total).
    #    The risk day follows the DECISION time (candle open + 4h), so start on a
    #    00:00 candle: its four decisions land 04:01..16:01 of one UTC day.
    k0 = next(k for k in range(2, 30) if seq[k]["t"][11:13] == "00")
    k1, k2, k3 = k0 + 1, k0 + 2, k0 + 3
    sh.step(bar(k0), 1, at(k0), "enter")
    sh.step(bar(k1, -0.15), 0, at(k1), "exit into SYNTHETIC -15% shock")
    sh.step(bar(k2), 1, at(k2), "re-enter same day (loss still under limit)")
    sh.step(bar(k3, -0.15), 0, at(k3), "exit into SYNTHETIC -15% shock -> kill switch")
    nxt = k3 + 1
    # 3) HALT blocks a new entry, also after UTC day rollover (flag persists)
    sh.step(bar(nxt), 1, at(nxt), "bull signal while HALTed")
    sh.step(bar(nxt + 6), 1, at(nxt + 6, timedelta(days=1)), "next day, still HALTed")
    # 4) operator clears HALT -> trading resumes; operator re-HALTs while LONG
    sh.risk.clear_halt()
    sh.step(bar(nxt + 7), 1, at(nxt + 7, timedelta(days=1)), "after operator HALT clear")
    sh.risk.trip_halt("operator HALT (shadow test)")
    sh.step(bar(nxt + 8), 0, at(nxt + 8, timedelta(days=1)), "bear while HALTed -> exit must still go through")
    sh.risk.clear_halt()
    # 5) normal round trip after the HALT is cleared; sizing stays at PER_TRADE
    sh.step(bar(nxt + 9), 1, at(nxt + 9, timedelta(days=1)), "fresh entry")
    sh.step(bar(nxt + 10), 0, at(nxt + 10, timedelta(days=1)), "exit")
    # 6) stale feed: decide 60h after the candle closed -> entry refused
    sh.step(bar(nxt + 11), 1, at(nxt + 11, timedelta(days=1, hours=60)), "stale feed (60h old)")
    return sh.close()


def scenario_historical(bars, since="2023-01-01"):
    """Genuine long_flat targets (no override) over real daily history."""
    p = dict(config.BEAR)
    tg = bs.targets(bars, p, "long_flat")
    start = next(i for i, b in enumerate(bars) if b["t"] >= since)
    sh = Shadow("historical")
    for i in range(start, len(bars)):
        sh.step(bars[i], tg[i], _dt(bars[i]["t"]) + BAR_1D + timedelta(minutes=5),
                note="real regime")
    return sh.close()


# ---------------------------------------------------------------- report -----

def summarize(evs):
    buys = [e for e in evs if e["action"] == "BUY"]
    sells = [e for e in evs if e["action"] == "SELL"]
    pnl = sum(e["pnl"] for e in sells)
    fees = sum(e["fee"] for e in buys + sells)
    slip = sum(e["slippage"] for e in buys + sells)
    wins = sum(1 for e in sells if e["pnl"] > 0)
    paths = {}
    for e in evs:
        if e["risk_path"]:
            key = e["risk_path"].split(":")[0] if e["risk_path"].startswith("veto") else e["risk_path"]
            paths[key] = paths.get(key, 0) + 1
    last = evs[-1]
    return {"steps": len(evs), "from": evs[0]["candle_t"], "to": last["candle_t"],
            "buys": len(buys), "sells": len(sells), "wins": wins, "pnl": pnl,
            "fees": fees, "slip": slip, "equity": last["equity"],
            "open": last["btc"] > 0, "max_notional": max((e["notional"] for e in buys), default=0),
            "max_open": max(e["open_notional"] for e in evs), "paths": paths}


def write_report(results):
    L = ["# 그림자 리플레이(SHADOW REPLAY) — 반사실(COUNTERFACTUAL) 결과",
         "",
         "> **⚠ 공식 모의투자 원장이 아님.** 공식 원장(`paper_log.jsonl`/`JOURNAL.md`/"
         "`SUMMARY.md`, 1,000,000 KRW, FLAT)은 이 리플레이로 전혀 변경되지 않는다. "
         "여기 숫자는 '장세가 바뀌었다면' 가정의 엔진 경로 검증용이다.",
         "",
         f"*생성: `paper_trading/shadow/shadow_replay.py` · "
         f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · "
         f"실제 엔진 코드(`live_engine.execute` + `RiskManager`) DRY-RUN, 네트워크/키/주문 없음. "
         f"한도 그대로: 노출 {config.MAX_EXPOSURE_KRW:,.0f} · 1회 {config.PER_TRADE_KRW:,.0f} · "
         f"일손실 {config.DAILY_LOSS_LIMIT_KRW:,.0f} KRW · 수수료 {config.UPBIT_FEE:.2%}/편도 · "
         f"슬리피지 {config.TAKER_SLIP_BPS}bp/편도.*",
         "",
         "| 시나리오 | 구간 | 결정 수 | 매수/매도 | 승 | 실현손익(수수료·슬리피지 후) | 수수료 | 슬리피지 | 최종 평가액 | 발동한 리스크 경로 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    desc = {"forced_regime": "A 장세 강제(실제 4h 시세)",
            "risk_stress": "B 리스크 스트레스(합성 충격 포함)",
            "historical": "C 실제 장세(일봉 2023~)"}
    for name, s in results.items():
        paths = ", ".join(f"{k}×{v}" for k, v in sorted(s["paths"].items())) or "—"
        L.append(f"| {desc[name]} | {s['from'][:10]}→{s['to'][:10]} | {s['steps']} | "
                 f"{s['buys']}/{s['sells']} | {s['wins']} | {s['pnl']:+,.0f} KRW | "
                 f"{s['fees']:,.0f} | {s['slip']:,.0f} | {s['equity']:,.0f}"
                 f"{' (보유중)' if s['open'] else ''} | {paths} |")
    L += ["",
          "- 최대 1회 진입 금액: " + ", ".join(
              f"{n} {s['max_notional']:,.0f}" for n, s in results.items())
          + f" KRW (한도 {config.PER_TRADE_KRW:,.0f}); 최대 미결제 노출: " + ", ".join(
              f"{n} {s['max_open']:,.0f}" for n, s in results.items())
          + f" KRW (상한 {config.MAX_EXPOSURE_KRW:,.0f}).",
          "- 시나리오별 결정 단위 원장: `shadow_<scenario>.jsonl` (모든 레코드 `counterfactual: true`).",
          ""]
    with open(REPORT, "w") as f:
        f.write("\n".join(L))


def write_journal(all_events):
    L = ["# 반사실(COUNTERFACTUAL) 그림자 저널 — 공식 모의투자 아님",
         "",
         "> **⚠ COUNTERFACTUAL.** 아래 체결은 모두 가정(장세 강제·합성 충격·과거 재생)이며 "
         "공식 원장(`../paper_log.jsonl`, `../JOURNAL.md`)과 무관하다. "
         "가격·수수료·슬리피지·리스크 장부는 실제 엔진 코드로 계산했다.",
         ""]
    for name, evs in all_events.items():
        L += [f"## {name}", "",
              "| 결정 시각(UTC) | 봉 | 목표 | 행동 | 체결가 | 금액 | 손익 | 일손실 누계 | HALT | 리스크 경로 | 비고 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in evs:
            if e["action"] == "HOLD" and not e["risk_path"]:
                continue
            pnl = f"{e['pnl']:+,.0f}" if "pnl" in e else "—"
            L.append(f"| {e['decided_at'][:16]} | {e['candle_t'][:16]} | {e['target']} | "
                     f"{e['action']} | {e.get('fill', 0):,.0f} | {e.get('notional', 0):,.0f} | "
                     f"{pnl} | {e['risk_today']:+,.0f} | {'Y' if e['halted'] else ''} | "
                     f"{e['risk_path'] or ''} | {e['note'] or ''} |")
        L.append("")
    with open(JOURNAL, "w") as f:
        f.write("\n".join(L))


def main():
    events = {"forced_regime": scenario_forced(load_bars(DATA_4H)),
              "risk_stress": scenario_stress(load_bars(DATA_4H))}
    if os.path.exists(DATA_1D):
        events["historical"] = scenario_historical(load_bars(DATA_1D))
    else:
        print(f"skip historical: {DATA_1D} missing (run backtest/refresh_data.py)")
    results = {n: summarize(e) for n, e in events.items()}
    write_report(results)
    write_journal(events)
    for n, s in results.items():
        print(f"{n:14s} steps={s['steps']:4d} buys={s['buys']:3d} sells={s['sells']:3d} "
              f"pnl={s['pnl']:+12,.0f} fees={s['fees']:9,.0f} slip={s['slip']:8,.0f} "
              f"equity={s['equity']:12,.0f} paths={s['paths']}")
    print(f"report -> {REPORT}")


if __name__ == "__main__":
    main()
