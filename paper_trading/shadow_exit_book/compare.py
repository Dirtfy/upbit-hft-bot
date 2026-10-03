#!/usr/bin/env python3
"""Official vs SHADOW (dd 12.5%/5%) side-by-side → COMPARE.md.

Read-only on both ledgers; deterministic; safe to run anytime. Joined by candle.
Rows where the two books' regime, target or action differ are divergences. A close
price mismatch on the same candle means the books did not see identical data,
and is flagged loudly.
Usage:  python3 paper_trading/shadow_exit_book/compare.py   (prints the headline)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PT = os.path.dirname(HERE)
OFFICIAL = os.path.join(PT, "paper_log.jsonl")
SHADOW = os.path.join(HERE, "paper_log.jsonl")
OUT = os.path.join(HERE, "COMPARE.md")


def _load(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def _maxdd(recs):
    peak, mdd = 0.0, 0.0
    for r in recs:
        peak = max(peak, r["equity_krw"])
        mdd = max(mdd, 1 - r["equity_krw"] / peak) if peak else mdd
    return mdd


def stats(recs):
    if not recs:
        return None
    last = recs[-1]
    return {"candle": last["candle_t"][:10], "equity": last["equity_krw"],
            "ret": last["cum_return_pct"], "pos": last["position_after"],
            "regime": last["regime"], "realized": last["realized_cum_krw"],
            "trades": sum(r["action"] != "HOLD" for r in recs), "mdd": _maxdd(recs),
            "days_long": sum(r["position_after"] == "LONG" for r in recs)}


def joined(off=None, sh=None):
    off = _load(OFFICIAL) if off is None else off
    sh = _load(SHADOW) if sh is None else sh
    s = {r["candle_t"]: r for r in sh}
    rows = []
    for o in off:
        x = s.get(o["candle_t"])
        if x is None:
            continue
        rows.append({"t": o["candle_t"][:10], "o": o, "s": x,
                     "diverged": any(o[k] != x[k] for k in ("regime", "target", "action")),
                     "data_mismatch": o["close"] != x["close"]})
    return off, sh, rows


def headline(off=None, sh=None):
    off, sh, rows = joined(off, sh)
    a, b = stats(off), stats(sh)
    if not a or not b:
        return "shadow book: no records yet"
    div = [r for r in rows if r["diverged"]]
    mm = sum(r["data_mismatch"] for r in rows)
    return (f"official(20/10) {a['pos']} {a['equity']:,.0f} KRW {a['ret']:+.2f}% | "
            f"shadow(12.5/5) {b['pos']} {b['equity']:,.0f} KRW {b['ret']:+.2f}% | "
            f"candle {b['candle']} | divergences {len(div)}"
            + (f" (last {div[-1]['t']})" if div else "")
            + (f" | DATA MISMATCH {mm}" if mm else ""))


def write(off=None, sh=None, out=None):
    out = out or OUT
    off, sh, rows = joined(off, sh)
    a, b = stats(off), stats(sh)
    if not a or not b:
        return None
    div = [r for r in rows if r["diverged"]]
    mm = [r["t"] for r in rows if r["data_mismatch"]]
    L = ["# 공식 vs SHADOW 비교 — 자동 생성 (`compare.py`)\n",
         "*SHADOW = 후보 청산속도 dd_enter 12.5% / dd_exit 5% (오너 option B, 2026-10-04). "
         "공식 = 현행 20% / 10%. 데이터·수수료·체결·사이징·1M KRW 상한 동일. "
         "SHADOW는 공식 원장이 아니며 공식 기록에 영향 없음.*\n",
         f"헤드라인: `{headline(off, sh)}`\n",
         "| 항목 | 공식 (20%/10%) | SHADOW (12.5%/5%) |", "|---|---|---|"]
    for label, key, fmt in (("최종 봉", "candle", "{}"), ("포지션", "pos", "**{}**"),
                            ("장세", "regime", "{}"), ("평가액 KRW", "equity", "**{:,.0f}**"),
                            ("누적 수익률", "ret", "**{:+.2f}%**"),
                            ("실현손익 KRW", "realized", "{:+,.0f}"),
                            ("매매 횟수", "trades", "{}"), ("LONG 보유일", "days_long", "{}"),
                            ("최대낙폭", "mdd", "{:.2%}")):
        L.append(f"| {label} | {fmt.format(a[key])} | {fmt.format(b[key])} |")
    L.append(f"\n동일 데이터 확인: 공통 봉 {len(rows)}개 중 종가 불일치 "
             + (f"**{len(mm)}개 ⚠ {', '.join(mm)}**" if mm else "0개 ✓"))
    L.append(f"\n## 분기(divergence) — {len(div)}건\n")
    if div:
        L += ["| 봉 | 종가 | 공식 장세·행동→포지션 | SHADOW 장세·행동→포지션 | 평가액 차 (S−O) |",
              "|---|---|---|---|---|"]
        for r in div:
            o, s = r["o"], r["s"]
            L.append(f"| {r['t']} | {o['close']:,.0f} | {o['regime']}·{o['action']}→{o['position_after']}"
                     f" | {s['regime']}·{s['action']}→{s['position_after']}"
                     f" | {s['equity_krw'] - o['equity_krw']:+,.0f} |")
    else:
        L.append("아직 없음 — 두 설정 모두 같은 신호를 냈다.")
    L += ["\n## 봉별 비교\n",
          "| 봉 | 종가 | 1y고점대비 낙폭 | 공식 행동/포지션/평가액 | SHADOW 행동/포지션/평가액 | 분기 |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        o, s = r["o"], r["s"]
        L.append(f"| {r['t']} | {o['close']:,.0f} | {o['drawdown_from_high']:.1%} "
                 f"| {o['action']}/{o['position_after']}/{o['equity_krw']:,.0f} "
                 f"| {s['action']}/{s['position_after']}/{s['equity_krw']:,.0f} "
                 f"| {'◆' if r['diverged'] else ''} |")
    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")
    return out


if __name__ == "__main__":
    print(headline())
    write()
