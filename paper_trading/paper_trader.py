#!/usr/bin/env python3
"""Official paper-trading logger (owner mission, 2026-09-25).

Runs the published DEFENSIVE bear-market strategy forward on LIVE, CLOSED Upbit
daily candles and keeps an auditable, human-readable paper-trading record that is
COMMITTED to the repo.

SAFETY — RESEARCH / PAPER ONLY. Read-only public endpoints only (candles); NO API
keys, NO account access, NO live orders anywhere in this file. Paper book =
1,000,000 KRW; the 1M exposure cap and all risk limits are respected.

Per newly CLOSED daily candle it:
  1. classifies the market regime (bull/bear) and the strategy target (LONG/FLAT),
     using EXACTLY the shared strategy core (src/regime.py + src/bear_strategy.py),
  2. updates a paper account (cash / BTC), marking equity to market,
  3. appends one machine record to paper_trading/paper_log.jsonl and one
     human-readable entry to paper_trading/JOURNAL.md (signal, virtual position,
     entry/exit rationale, per-cycle P/L and cumulative P/L),
  4. appends the day's OHLC bar to paper_trading/market_data_daily.csv — a small,
     committed, growing dataset for later backtesting of the paper period.

Idempotent: it resumes from the last logged candle (last line of the JSONL), so
re-running only appends candles newer than the last one. Safe on any cadence
(intended: once per day). On the FIRST run it anchors the paper period at the most
recent closed candle (no history backfill — this is a forward paper record).

Usage:  python3 paper_trading/paper_trader.py [--mode long_flat]
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import config                                   # noqa: E402
import bear_strategy as bs                      # noqa: E402
from regime import compute_regimes, sma, drawdown_from_high  # noqa: E402
import live_engine as le                        # noqa: E402  (reuse fetch + staleness)
from upbit_client import UpbitClient            # noqa: E402

JSONL_PATH = os.path.join(HERE, "paper_log.jsonl")
JOURNAL_PATH = os.path.join(HERE, "JOURNAL.md")
SUMMARY_PATH = os.path.join(HERE, "SUMMARY.md")
DATA_PATH = os.path.join(HERE, "market_data_daily.csv")
START_CAPITAL = config.BASE_TRADABLE_CAPITAL_KRW      # 1,000,000 KRW paper book


def _last_record():
    """Resume state from the last JSONL line, or None on a fresh start."""
    if not os.path.exists(JSONL_PATH):
        return None
    last = None
    with open(JSONL_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    return json.loads(last) if last else None


def _fmt(n):
    return f"{n:,.0f}"


def _regime_reason(close, sl, dd, p, regime):
    """Human-readable 'why this regime' for the journal."""
    bits = []
    if sl is not None:
        rel = close / sl - 1.0
        side = "아래" if close < sl else "위"
        bits.append(f"종가가 200일선({_fmt(sl)}) {abs(rel):.1%} {side}")
    bits.append(f"1년 고점대비 낙폭 {dd:.1%}(진입기준 {p['dd_enter']:.0%})")
    trigger = ""
    if regime == "bear":
        if sl is not None and close < sl:
            trigger = "종가<200일선"
        if dd >= p["dd_enter"]:
            trigger = (trigger + " 및 " if trigger else "") + "낙폭≥20%"
        trigger = trigger or "약세 지속(히스테리시스)"
    elif regime == "bull":
        trigger = "종가>200일선 그리고 낙폭 회복(≤10%)"
    return "; ".join(bits), trigger


def process(mode):
    p = dict(config.BEAR)
    client = UpbitClient("", "")                    # public, keyless
    bars = le.fetch_closed_daily(client, count=600)  # oldest->newest, CLOSED only
    if len(bars) < bs._warmup(p) + 1:
        print("not enough history for regime warmup; aborting")
        return 0
    closes = [b["close"] for b in bars]
    regimes = compute_regimes(bars, p)
    tgts = bs.targets(bars, p, mode)

    prev = _last_record()
    if prev is None:
        # fresh start: anchor at the most recent closed candle only (no backfill)
        start = len(bars) - 1
        cash, btc, entry = START_CAPITAL, 0.0, None
        realized_cum, cycle_no, equity_prev = 0.0, 0, START_CAPITAL
    else:
        # the account state carries a mode-specific position; refuse to continue
        # an existing record under a different mode (would corrupt the ledger).
        if prev.get("mode") != mode:
            print(f"REFUSING: existing record is mode={prev.get('mode')!r} but "
                  f"--mode {mode!r} was requested. Keep one mode per record "
                  f"(start a new record dir to switch).")
            return 0
        last_t = prev["candle_t"]
        start = next((i for i, b in enumerate(bars) if b["t"] > last_t), len(bars))
        cash, btc = prev["cash_krw"], prev["btc_qty"]
        entry = prev["entry_price"]
        realized_cum = prev["realized_cum_krw"]
        cycle_no = prev["cycle"]
        equity_prev = prev["equity_krw"]
        first_run = False

    if start >= len(bars):
        print(f"no new closed candle since {prev['candle_t']}; nothing to do (idempotent)")
        return 0

    fee = config.UPBIT_FEE
    appended = 0
    for i in range(start, len(bars)):
        b = bars[i]
        close = closes[i]
        regime = regimes[i]
        target = tgts[i]
        position = 1 if btc > 0 else 0
        sl = sma(closes, i, p["sma_long"])
        dd = drawdown_from_high(closes, i, p["dd_window"])
        cycle_no += 1

        action, fill_price, trade_pnl, notional = "HOLD", None, 0.0, 0.0
        if target == 1 and position == 0:
            # ENTER LONG — deploy up to the 1M cap; fill at this candle's close
            notional = min(cash, config.MAX_EXPOSURE_KRW)
            qty = notional * (1 - fee) / close
            cash -= notional
            btc += qty
            entry = close
            action, fill_price = "BUY", close
        elif target == 0 and position == 1:
            # EXIT to cash — sell all, fill at this candle's close
            proceeds = btc * close * (1 - fee)
            trade_pnl = proceeds - (btc * (entry or close))
            cash += proceeds
            realized_cum += trade_pnl
            action, fill_price = "SELL", close
            btc, entry = 0.0, None

        equity = cash + btc * close
        cycle_pnl = equity - equity_prev
        cum_pnl = equity - START_CAPITAL
        pos_after = "LONG" if btc > 0 else "FLAT"

        reason, trigger = _regime_reason(close, sl, dd, p, regime)
        if action == "BUY":
            act_reason = (f"장세가 상승(bull)으로 전환({trigger}) → 신규 진입: "
                          f"{_fmt(notional)} KRW를 종가 {_fmt(close)}에 가상 매수")
        elif action == "SELL":
            act_reason = (f"장세가 하락(bear)으로 전환({trigger}) → 청산: "
                          f"종가 {_fmt(close)}에 전량 가상 매도 "
                          f"(실현손익 {trade_pnl:+,.0f} KRW)")
        elif pos_after == "LONG":
            act_reason = "상승장 지속 → BTC 보유 유지(HOLD)"
        else:
            act_reason = "하락장 → 현금 보유 유지(HOLD), 진입 안 함(방어)"

        rec = {
            "cycle": cycle_no,
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "candle_t": b["t"],
            "mode": mode,
            "close": close,
            "sma_long": round(sl, 2) if sl is not None else None,
            "drawdown_from_high": round(dd, 4),
            "regime": regime,
            "target": "LONG" if target else "FLAT",
            "action": action,
            "position_after": pos_after,
            "fill_price": fill_price,
            "cash_krw": round(cash, 2),
            "btc_qty": btc,
            "entry_price": entry,
            "equity_krw": round(equity, 2),
            "cycle_pnl_krw": round(cycle_pnl, 2),
            "cum_pnl_krw": round(cum_pnl, 2),
            "cum_return_pct": round(100.0 * cum_pnl / START_CAPITAL, 4),
            "realized_cum_krw": round(realized_cum, 2),
            "reason": f"regime={regime} ({reason}); {act_reason}",
        }
        _append_jsonl(rec)
        _append_journal(rec)
        _append_market_data(b)
        equity_prev = equity
        appended += 1

    print(f"appended {appended} cycle(s); latest {bars[-1]['t']} "
          f"equity {_fmt(equity_prev)} KRW "
          f"({rec['cum_return_pct']:+.2f}% cumulative) -> {JSONL_PATH}")
    write_summary()
    age_h = le.candle_age_hours(bars[-1]["t"])
    if age_h > config.MAX_CANDLE_STALENESS_HOURS:
        print(f"NOTE: latest candle is {age_h:.1f}h old (> "
              f"{config.MAX_CANDLE_STALENESS_HOURS:.0f}h) — feed may be lagging.")
    return appended


def write_summary():
    """Regenerate SUMMARY.md — an at-a-glance rollup derived from the JSONL
    ledger (deterministic; safe to call anytime)."""
    if not os.path.exists(JSONL_PATH):
        return
    recs = [json.loads(l) for l in open(JSONL_PATH) if l.strip()]
    if not recs:
        return
    first, last = recs[0], recs[-1]
    n = len(recs)
    buys = sum(1 for r in recs if r.get("action") == "BUY")
    sells = sum(1 for r in recs if r.get("action") == "SELL")
    days_long = sum(1 for r in recs if r.get("position_after") == "LONG")
    # max drawdown of the paper equity curve
    eqs = [r["equity_krw"] for r in recs if "equity_krw" in r]
    peak, maxdd = -1e18, 0.0
    for eq in eqs:
        peak = max(peak, eq)
        if peak > 0:
            maxdd = max(maxdd, (peak - eq) / peak)
    eq_peak, eq_trough = (max(eqs), min(eqs)) if eqs else (0.0, 0.0)
    with open(SUMMARY_PATH, "w") as f:
        f.write(
            "# 모의투자 요약 (SUMMARY) — 자동 생성\n\n"
            f"*`paper_log.jsonl`에서 재생성. 최종 갱신 봉: {last['candle_t']} · "
            f"전략 모드 `{last['mode']}`. 가상 자본 시작 "
            f"{_fmt(START_CAPITAL)} KRW.*\n\n"
            "| 항목 | 값 |\n|---|---|\n"
            f"| 기간 | {first['candle_t'][:10]} → {last['candle_t'][:10]} "
            f"({n} 사이클) |\n"
            f"| 현재 포지션 | **{last['position_after']}** |\n"
            f"| 현재 평가액 | **{_fmt(last['equity_krw'])} KRW** |\n"
            f"| 누적 손익 | **{last['cum_pnl_krw']:+,.0f} KRW "
            f"({last['cum_return_pct']:+.2f}%)** |\n"
            f"| 실현 손익(누적) | {last['realized_cum_krw']:+,.0f} KRW |\n"
            f"| 평가액 고점 / 저점 | {_fmt(eq_peak)} / {_fmt(eq_trough)} KRW |\n"
            f"| 모의 최대낙폭(MDD) | {maxdd:.2%} |\n"
            f"| 매수 / 매도 / 보유중LONG | {buys} / {sells} / {days_long}일 |\n"
            f"| 최근 장세·행동 | {last['regime']} · {last['action']} |\n\n"
            "자세한 사이클별 근거·손익은 `JOURNAL.md`, 원장은 `paper_log.jsonl` 참조.\n"
        )


def _append_jsonl(rec):
    with open(JSONL_PATH, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _append_journal(rec):
    new = not os.path.exists(JOURNAL_PATH)
    with open(JOURNAL_PATH, "a") as f:
        if new:
            f.write(_journal_header())
        d = rec["candle_t"][:10]
        f.write(
            f"\n### 사이클 {rec['cycle']} — {d} (봉 {rec['candle_t']})\n\n"
            f"- **장세/신호**: {rec['regime']} · 목표 포지션 **{rec['target']}** "
            f"(전략 모드 `{rec['mode']}`)\n"
            f"- **행동**: **{rec['action']}** → 사이클 종료 시 포지션 **{rec['position_after']}**"
            f"{' · 체결가 ' + _fmt(rec['fill_price']) + ' KRW' if rec['fill_price'] else ''}\n"
            f"- **근거**: {rec['reason']}\n"
            f"- **손익**: 이번 사이클 {rec['cycle_pnl_krw']:+,.0f} KRW · "
            f"누적 {rec['cum_pnl_krw']:+,.0f} KRW "
            f"(**{rec['cum_return_pct']:+.2f}%**) · 평가액 {_fmt(rec['equity_krw'])} KRW\n"
        )


def _append_market_data(b):
    new = not os.path.exists(DATA_PATH)
    with open(DATA_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc", "open", "high", "low", "close"])
        w.writerow([b["t"], b["open"], b["high"], b["low"], b["close"]])


def _journal_header():
    return (
        "# 모의투자(Paper Trading) 저널 — 업비트 하락장 방어 전략\n\n"
        "*오너 미션(2026-09-25)에 따른 공식 모의투자 기록. 실거래·API 키·계좌 "
        "미사용, 공개 시세(read-only)만 사용. 가상 자본 1,000,000 KRW.*\n\n"
        "- **전략**: 상승장=BTC 보유, 하락장=원화 현금 (방어). 신호원은 백테스트와 "
        "동일한 코어(`src/regime.py`+`src/bear_strategy.py`).\n"
        "- **체결 가정**: 판단 시점=마감된 일봉, 체결가=해당 봉 종가, 수수료 "
        "0.05%/편도, 한 번에 한 포지션, 노출 1,000,000 KRW 상한.\n"
        "- 기계 판독용 원장은 `paper_log.jsonl`, 축적 시세는 "
        "`market_data_daily.csv` 참조.\n"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(bs.MODES), default="long_flat",
                    help="strategy target (default: long_flat — the live-engine default)")
    args = ap.parse_args()
    process(args.mode)


if __name__ == "__main__":
    main()
