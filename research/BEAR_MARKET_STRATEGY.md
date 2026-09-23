# Bear-market strategy for KRW-BTC — design, evidence, and citations

*Project: upbit-hft-bot. Research/PAPER only. Live trading is off by default and
gated (see "Live/dry-run gating"). This note is the design record the owner asked
for (mission items 1 & 1-1).*

---

## 1. Scope decisions (the owner said "research it yourself")

**Asset — KRW-BTC (Upbit spot).** It is Upbit's most liquid pair, it is what the
rest of this project already trades and has integrity-verified history for
(2017-09 → 2026-09, ~9 years, `data/krw_btc_1d.csv`), and that window contains
**two full bear markets** (2018 and 2021-22) plus several sharp corrections — the
regimes a bear strategy must be judged on.

**"Bear market" — two independent, standard definitions, OR'd together:**

1. **Trend:** price closes **below its 200-day SMA**. This is the classic
   long-moving-average timing rule (Faber 2007 uses the 10-*month* SMA ≈ 200
   trading days). It is slow but robust and defines the primary trend.
2. **Drawdown:** price is **≥ 20% below its trailing 1-year high**. "A decline of
   at least 20% from the peak" is the conventional market definition of a bear
   market; it reacts faster than the SMA to a crash and acts as a circuit breaker.

A bar is **bear** if *either* trigger fires, **bull** otherwise. Hysteresis (once
bear, require price back *above* the SMA **and** drawdown recovered to ≤10% before
returning to bull) damps whipsaw at the boundary. Code: `src/regime.py`.

**Why a *defensive* strategy (not shorting).** Upbit KRW markets are **spot-only**
— no retail margin/futures, so BTC cannot be shorted here. The achievable and
literature-backed edge in a downtrend is therefore **capital preservation**: be
long only in confirmed up-regimes and sit in **KRW cash** through bear regimes,
side-stepping the deep drawdowns that buy-and-hold suffers. This is time-series
momentum / trend-following applied as a regime filter. (If the owner later wants
to *profit* from downtrends, that requires a venue with shorting — e.g. a
regulated BTC futures/perp account — and is out of scope for Upbit spot; noted as
a follow-up.)

---

## 2. The strategy (three variants, all long-only / flat)

Implemented in `src/bear_strategy.py`; targets computed from data through bar *i*,
filled at bar *i+1*'s **open** (no lookahead); Upbit fee 0.05%/side.

| variant | rule | role |
|---|---|---|
| `long_flat` | long when regime = bull, else flat (cash) | the pure regime filter (Faber-style timing) |
| `breakout` | Donchian 20/10 breakout, **no** regime filter | active baseline to measure the filter against |
| `breakout_regime` | Donchian breakout, but only **enter** in bull regime and force-**exit** the moment regime turns bear | the bear-defended active strategy |

The regime is the **single source of truth** shared by the backtest and the live
engine, so what is validated historically is exactly what would trade.

---

## 3. Backtest evidence (9y daily KRW-BTC, to 2026-09-23)

Run: `python3 backtest/bear_backtest.py` (full output: metrics, trade log, ASCII
equity chart, bear-window breakdown). Headline (1,000,000 KRW, full-book
compounding, apples-to-apples with buy-and-hold):

| strategy | totRet% | CAGR% | **maxDD%** | Sharpe | inMkt% | trades | win% |
|---|--:|--:|--:|--:|--:|--:|--:|
| buy_and_hold | 2595 | 44.2 | **86.8** | 0.91 | 100 | 0 | – |
| long_flat | 517 | 22.4 | **46.7** | 0.86 | 31 | 15 | 47 |
| breakout | 7012 | 60.6 | 56.5 | 1.42 | 40 | 61 | 59 |
| **breakout_regime** | 867 | 28.7 | **27.7** | **1.16** | 19 | 26 | 58 |

**Performance *inside* the two historical bear markets** (return over the window):

| window | buy_and_hold | long_flat | breakout | breakout_regime |
|---|--:|--:|--:|--:|
| 2018 (Jan–Dec) | **−77.7%** | **0.0%** | −45.8% | **0.0%** |
| 2021-22 (Nov'21–Dec'22) | **−73.5%** | −22.0% | −29.4% | **−7.3%** |

**Reading it honestly.**
- The filter's job is **drawdown reduction, not return maximisation**. It works:
  max drawdown falls from **86.8% (buy-and-hold) to 27.7%** (`breakout_regime`),
  and the catastrophic 2018 bear (−78%) becomes **flat** (the filter was in cash
  the whole year), while 2021-22 (−73%) becomes −7% to −22%.
- You pay for that protection in raw return: `long_flat` compounds far less than
  buy-and-hold because it is only in the market ~31% of the time and the SMA
  re-entry is late. `breakout_regime` recovers most of the risk-adjusted quality
  (Sharpe 1.16, best maxDD) — it is the recommended bear-defended configuration.
- `breakout` (no filter) has the highest raw CAGR but a 56% drawdown — it is the
  "what the filter is protecting you from" baseline, not a bear strategy.
- Caveats: single asset, single history (survivorship/regime-luck), fills at next
  open with a flat fee and no slippage/partial-fill modelling, and only 15–26
  round trips for the filtered variants → wide confidence intervals. Treat the
  drawdown *reduction* as the robust finding, not the exact CAGR.

**Current live signal (2026-09-23):** regime = **bear** (BTC ~30% below its
trailing-year high), so all variants are **FLAT / cash** right now — the strategy
is doing exactly what it should in the present drawdown.

---

## 4. References (title, author, link)

1. **Faber, Mebane T. (2007).** *A Quantitative Approach to Tactical Asset
   Allocation.* The Journal of Wealth Management, Spring 2007 (updated 2013).
   SSRN 962461 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461 .
   The canonical long-SMA timing rule (buy when price > 10-month/200-day SMA,
   else cash): "equity-like returns with bond-like volatility and drawdowns."
   Basis for our trend trigger.

2. **Detzel, A., Liu, H., Strauss, J., Zhou, G., & Zhu, Y. (2021).** *Learning and
   Predictability via Technical Analysis: Evidence from Bitcoin and Stocks with
   Hard-to-Value Fundamentals.* Financial Management 50(1), 107–137.
   DOI 10.1111/fima.12310 — https://onlinelibrary.wiley.com/doi/abs/10.1111/fima.12310
   (SSRN 3115846). Directly on point: 5–100-day moving-average rules predict
   Bitcoin returns in- and out-of-sample and **"significantly reduce the severity
   of drawdowns relative to a buy-and-hold position in Bitcoin."** This is the
   core empirical justification for an MA regime filter on BTC.

3. **Liu, Y., & Tsyvinski, A. (2021).** *Risks and Returns of Cryptocurrency.*
   The Review of Financial Studies 34(6), 2689–2727.
   DOI 10.1093/rfs/hhaa113 — https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024
   (NBER w24877). Establishes a **strong time-series momentum effect** specific to
   crypto — i.e. trend persists, which is what a trend/regime filter harvests.

4. **Moskowitz, T., Ooi, Y. H., & Pedersen, L. H. (2012).** *Time Series
   Momentum.* Journal of Financial Economics 104(2), 228–250.
   https://www.sciencedirect.com/science/article/abs/pii/S0304405X11002613 .
   Time-series momentum across 58 instruments/asset classes; a trend signal that
   is long winners/short losers earns positive returns and does especially well
   in market panics — the theoretical backbone of trend-as-defense.

5. **Hurst, B., Ooi, Y. H., & Pedersen, L. H. (2017).** *A Century of Evidence on
   Trend-Following Investing.* The Journal of Portfolio Management 44(1).
   https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing .
   Trend-following delivers positive returns over 137 years and, importantly,
   tends to be **long volatility / crisis-robust** — the property we want in a
   bear regime.

*How the design maps to the evidence:* trigger #1 (200-day SMA) = Faber (1) +
Detzel et al. (2) applied to BTC; the persistence that makes timing work = Liu &
Tsyvinski (3) and Moskowitz et al. (4); the "protects in crises" property we rely
on for bear defense = Moskowitz et al. (4) and Hurst et al. (5). Trigger #2 (−20%
drawdown) is the conventional bear-market definition used as a faster circuit
breaker.

---

## 5. How to run / how the live gating works

- **Backtest:** `python3 backtest/bear_backtest.py` (see `--mode`, `--capital`,
  `--no-chart`, `--data`). Reproducible; refresh data first with
  `python3 backtest/refresh_data.py`.
- **Live/dry-run engine:** `python3 src/live_engine.py` — **DRY-RUN by default**
  (computes and logs the exact order it *would* place; no keys, no private calls).
  Live is gated behind **all** of: `config.LIVE_TRADING_ENABLED = True` (master
  switch, default **False**), the `--live` flag, a typed confirmation phrase, and
  present API keys. Missing any → it stays dry-run. Flipping to live is a **config
  change (flag + keys), not a code change**. Sizing/kill-switch/1M-cap are enforced
  by the shared `RiskManager`. Full operator instructions: `OPERATIONS.md`.
