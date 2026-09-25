# Research Loop — Journal

One bounded cycle per turn: hypothesis → backtest → measure → learn → stop.
Persisted state: this log + `best_config.json`. Eval harness:
`backtest/backtest_maker.py` (maker fills, 0.05%/side fee) on the ~83-day
1-minute KRW-BTC dataset; primary metric = **out-of-sample net return %**
(OOS = bars before 2026-08-23), secondary = profit factor.

Starting point (from prior turns): long-only 1-min mean-reversion scalping has
**no net edge after fees** — baseline OOS = −4.00%, PF 0.47, and 0/864 grid
configs were profitable. The loop now searches for a modification that crosses
into positive OOS return.

---

## Cycle 1 — Trend filter (only buy dips in uptrends)

- **Hypothesis:** entering only when price > a long SMA removes the big losers
  from dip-buying into downtrends, improving OOS return and PF.
- **Test:** baseline vs. trend SMA windows {240, 480, 720, 1440} on OOS
  (`backtest/cycle_run.py`).
- **Result (OOS, 68.8d):**
  | variant | trades | win% | PF | ret% | maxDD% |
  |---|---|---|---|---|---|
  | baseline (no filter) | 193 | 48.2 | 0.47 | −4.00 | 4.14 |
  | SMA 240 (4h) | 0 | – | – | 0.00 | 0.00 |
  | SMA 480 (8h) | 24 | 50.0 | 0.61 | −0.30 | 0.58 |
  | **SMA 720 (12h)** | 34 | 52.9 | **0.70** | **−0.35** | 0.64 |
  | SMA 1440 (24h) | 49 | 49.0 | 0.54 | −0.72 | 0.91 |
  (buy&hold +4.89%)
- **Learning:** hypothesis **partially confirmed**. The trend filter sharply
  improves quality — PF 0.47→0.70, max drawdown 4.14%→0.64%, avg loss shrinks —
  moving the system from −4.0% to roughly break-even. But it is **still net-
  negative** and well below buy&hold. The filter fixes the *loss* side; the
  remaining gap is the *edge-per-trade vs. fee* problem. SMA 240 gave 0 trades
  (a 4h SMA is too tight to coexist with a z≤−3 dip).
- **Action:** adopt `trend_window=720` into best_config (best PF + win rate;
  return tied with 480). Live default (config.STRAT) unchanged — still not
  profitable.
- **Next hypothesis (cycle 2):** attack the edge/exit side on top of the trend
  filter — e.g. let winners run (higher/trailing take-profit, exit_z below mean)
  so avg win exceeds avg loss, OR require a stronger entry (deeper z / volume
  confirmation). Also worth a train/test split to confirm the trend filter
  generalizes and isn't OOS-window-specific.

---

## Cycle 2 — Let winners run + train/test split (on top of trend_window=720)

- **Hypothesis:** on top of the trend filter, letting winners run (higher
  `exit_z` / take-profit) makes avg win > avg loss and pushes OOS return
  positive.
- **(A) Trend-filter generalization (train/test split, full 83d):**
  | config | TRAIN ret/PF/n | TEST ret/PF/n |
  |---|---|---|
  | no filter | −3.14% / 0.47 / 150 | −0.75% / 0.72 / 86 |
  | trend 720 | −0.10% / 0.82 / 23 | −0.19% / 0.72 / 18 |
  → the trend filter improves **both** halves and raises PF. It **generalizes**
  (not OOS-window-specific). Keep it.
- **(B) Let winners run (OOS, trend_window=720):** REJECTED. Raising `exit_z`
  0→1.5 dropped win rate 52.9%→41.2% and return −0.35%→−0.47/−0.53%; avg win
  rose (451→579) but not enough to offset the lost winners. Take-profit changes
  were **inert** (the maker TP limit almost never fills; exits are dominated by
  mean_revert/timeout). The 1-min reversion move is too small to reliably
  overshoot the mean.
- **Learning:** mean-reversion scalping has hit a **break-even ceiling** — even
  the best variant (trend720, exit_z=0, **−0.35% OOS**) can't beat fees or
  buy&hold. No net-positive config exists in this family. Best config
  **unchanged** from cycle 1.
- **Conclusion:** stop tuning the scalping family; pivot frequency down (below).

## Side-track — Non-HFT strategy scan (mission part 2)

Thesis: hold hours-to-days so the 0.10% fee is negligible vs. multi-percent
moves. Resampled the 1m data to 4h/1D (`backtest/nonhft_research.py`), long-only,
realistic fees. **Per-trade edge now clears the fee by ~10×:**

| Strategy (4h bars) | Return | Buy&Hold | Trades | avg/trade | vs fee |
|---|---|---|---|---|---|
| SMA cross 5/20 | +12.61% | +8.65% | 13 | +1.18% | EDGE≫fee |
| SMA cross 10/50 | +5.97% | +8.65% | 8 | +1.47% | EDGE≫fee |
| Donchian 40/20 | +4.86% | +8.65% | 26 | +0.36% | EDGE>fee |
| Donchian 10/5 (1D) | +5.90% | +9.76% | 12 | +0.98% | EDGE>fee |

**Finding:** the fee problem that kills scalping **disappears** at swing
frequency — per-trade edge (1–1.5%) ≫ 0.10% fee, and several variants
beat/match buy&hold. **Caveat:** only ~83 days, net-uptrending, tiny trade
counts (2–26) → directionally promising, NOT proven (trend-following flatters in
an uptrend). Needs multi-year data incl. bear/chop + out-of-sample.

**Most promising to pursue as future cycles (ranked):**
1. 4h **trend-following SMA cross** (e.g. 5/20, 10/50) — best edge, reasonable
   trade count, fee-insensitive.
2. **Donchian breakout** (4h/1D) — more trades, positive edge, classic/robust.
3. First required step: **fetch multi-year Upbit daily+4h candles** (the daily
   endpoint goes back years, cheap) to validate across regimes before trusting.

---

## Cycle 3 — Swing trend-following on multi-year data (train/test validated)

- **Setup:** fetched multi-regime Upbit candles (`backtest/fetch_candles.py`):
  DAILY 2017-09..2026-09 (3273 bars, incl. 2018 & 2022 bears) and 4H
  2023-01..2026-09 (8000 bars). Long-only, 0.05%/side fee, act next-bar open.
  Optimized params on TRAIN by **Calmar (CAGR/maxDD)**, validated on TEST
  (`backtest/swing_backtest.py`).
- **Results (best-on-train, then evaluated OOS on test):**
  | market | strategy | TRAIN CAGR/Calmar | TEST CAGR/Calmar | TEST win% | avg/trade | B&H test CAGR |
  |---|---|---|---|---|---|---|
  | DAILY | **Donchian in20/out20** | +98.7% / 1.88 | **+42.6% / 1.93** | 54% | +8.5% | +24.4% |
  | DAILY | SMA cross 3/30 | +95.8% / 1.91 | +38.0% / 1.67 | 35% | +4.3% | +24.4% |
  | 4H | Donchian in55/out20 | +71.6% / 5.86 | +11.4% / 0.78 | 56% | +0.85% | **−31.8%** |
  | 4H | SMA cross 10/30 | +99.8% / 5.81 | −3.4% / −0.12 | 37% | +0.08% | −31.8% |
- **Learnings:**
  1. **Daily Donchian 20/20 is the new best** — OOS CAGR +42.6%, Calmar 1.93,
     beats buy&hold, and generalizes train→test. Per-trade edge (4–24%) dwarfs
     the 0.10% fee, so the fee problem that killed scalping is gone.
  2. Trend-following's real value is **downtrend protection**: on the 4h TEST
     window buy&hold lost 31.8% while Donchian 55/20 made +11.4%.
  3. **4h SMA cross overfits** (great TRAIN, negative TEST) — rejected. Daily
     timeframe and Donchian breakout are the robust choices.
- **New best config (project-wide):** DAILY Donchian breakout, in=20 / out=20.
  This SUPERSEDES the scalping config as the most promising strategy.
- **Caveats:** single asset (BTC/KRW), long-only; daily test (2024-26) was net-
  bullish so part of the win is beta; trade counts on test are modest (14–27).
  Still the strongest, most regime-robust result so far.
- **Next cycle (4):** stress the daily Donchian — walk-forward across multiple
  splits / rolling windows, add a regime/volatility filter or trailing-stop
  variant, and measure a proper Sharpe + per-year breakdown (esp. bear years
  2018/2022) to confirm it isn't just long-BTC beta.

---

## Cycle 4 — Robustness stress-test of the daily Donchian (walk-forward + per-year)

Goal: confirm the Cycle-3 winner (daily Donchian breakout) is a real edge, not
long-BTC beta, beyond a single 70/30 split. (`backtest/cycle4_walkforward.py`)

- **(A) Anchored walk-forward, re-optimising (in,out) by Calmar each fold —
  4/5 folds OOS-positive:**
  | fold | test window | pick | OOS total | B&H |
  |---|---|---|---|---|
  | 1 | 2018-10..2020-05 | in10/out5 | +213% | +52% |
  | 2 | 2020-05..2021-12 | in10/out5 | +398% | +441% |
  | 3 | 2021-12..2023-07 | in10/out5 | **−2.2%** | **−35.5%** |
  | 4 | 2023-07..2025-02 | in40/out20 | +145% | +285% |
  | 5 | 2025-02..2026-09 | in40/out15 | **+0.8%** | **−27.9%** |
  Params drift (in10/out5 ×3, in40/× ×2) → the *family* is robust, the exact
  length is not; treat 20/20 as representative.

- **(B) Per-year, fixed Donchian 20/20 run continuously (strat vs B&H):**
  bear years show the edge — 2018 −31% vs −77.7%; 2022 −31.7% vs −63.6%; 2025
  +12.6% vs −9.4%; 2026 +6.5% vs −18.3%. Lags in raging bulls (2017/2023/2024).
  Full 9y: **strat +16,313% vs B&H +2,335%** (43 trades).

- **Learning / conclusion:** the daily Donchian edge is REAL and comes from
  **downside protection** — it slashes bear-market drawdowns (losing ~30% instead
  of ~65–78%), which compounds into large full-cycle outperformance and strong
  risk-adjusted return (test Calmar 1.93). It is *not* just long-BTC beta; it
  underperforms in straight-up bulls (the premium paid for the insurance).
  **This is the confirmed project-best strategy** (see best_config.json).

- **Next cycle (5):** (a) add a trailing-stop / ATR-based exit variant and a
  simple regime filter (e.g. only long above the 200-day SMA) to see if bull-
  market lag can be reduced without hurting bear protection; (b) begin porting
  the daily Donchian into a daily-cadence bot skeleton (still paper/research;
  no live funds) so it is deployable when approved.

---

## Cycle 5 — Dataset extension to full Upbit history + integrity verification + revalidation

**Goal:** extend the backtest data to a substantially longer, TRUSTWORTHY history
and re-check whether it changes the best config.

**Provenance / range / granularity:**
- Source: Upbit official candle API (`/v1/candles/days`, `/v1/candles/minutes/240`).
  Same exchange as the owner's account. Fetcher: `backtest/fetch_candles.py`.
- DAILY `krw_btc_1d.csv`: 3273 bars, 2017-09-25 .. 2026-09-10 (~9y; Upbit BTC/KRW
  inception). Already full history — unchanged.
- 4H `krw_btc_4h_full.csv`: **19,628 bars, 2017-09-26 .. 2026-09-11 (~9y)** —
  EXTENDED from the previous 3.6y (8000-bar) set. Now canonical for 4h research.

**Integrity checks (`backtest/verify_data.py`) — all passed:**
| check | DAILY | 4H full |
|---|---|---|
| schema/parse | OK (0 bad) | OK (0 bad) |
| strictly increasing (no dup / no out-of-order) | OK | OK |
| gaps / missing candles | **0** | **3 candles (0.015%)** |
| OHLC sanity (l≤o,c≤h, l≤h, >0) | OK (0 viol) | OK (0 viol) |
| volume ≥ 0 | OK | OK |
| extreme moves (flagged) | 1: 2020-03-12 −33% (real COVID crash) | 2: Dec-2017 bubble |
- 4h gaps are single 8h omissions in Dec-2017 / Aug-2018 / Dec-2023 (early
  illiquidity / brief downtime) — negligible, left as-is (no synthetic fill).
- Timezone: API `candle_date_time_utc` vs `_kst` verified consistently +9h; CSVs
  store the UTC field. Lookahead: backtests decide on bar *i* (closed) and fill at
  bar *i+1* open — unchanged discipline, no future data used.

**Revalidation on the longer data (train 2017-2024 / test 2024-2026):**
| market | best-on-train | TRAIN Calmar | TEST CAGR / Calmar | test trades |
|---|---|---|---|---|
| DAILY (unchanged) | Donchian 20/20 | 1.88 | +42.6% / 1.93 | 14 |
| **4H (extended)** | **Donchian 30/20** | 3.41 | **+47.5% / 1.93** | **64** |
| 4H (extended) | SMA 3/30 | 3.45 | +46.4% / 1.92 | 154 |

**Did the longer data change results?** YES, in a good way:
- The Cycle-3 claim "4h SMA cross OVERFITS, use daily" was an artifact of the
  short 3.6y 4h set. With full 9y history (training now includes 2018 & 2022
  bears), 4h trend-following **validates out-of-sample** (Calmar ~1.9, same as
  daily) with far MORE trades (64 test vs 14 daily) → statistically stronger.
- Best-strategy FAMILY unchanged: **Donchian breakout, long-only**. Now confirmed
  robust on BOTH daily (20/20) and 4h (30/20). 4h 30/20 promoted to co-best /
  preferred for its higher trade count.
- No change to the core thesis: swing trend-following edge ≫ fee, concentrated in
  downside protection, robust across regimes.

**Next cycle (6):** run the multi-fold walk-forward (like Cycle 4) on the full 4h
set; then start the daily/4h-cadence Donchian bot skeleton (research/paper only).

---

## Cycle 6 — Refine the daily Donchian: regime filter vs ATR trailing stop

**Goal:** reduce the bull-market lag / improve risk-adjusted return of the daily
Donchian 20/20 without hurting bear protection. Train/test 70/30 on the Cycle-5
verified daily data. (`backtest/cycle6.py`)

**Data integrity re-affirmed this cycle** (`verify_data.py`, unchanged datasets):
daily 0 gaps / 0 dup / OHLC OK; 4h 3 missing candles (0.015%) / 0 dup / OHLC OK.

**Results (CAGR% / Calmar / maxDD% / trades):**
| variant | TRAIN | TEST |
|---|---|---|
| base 20/20 | 99 / 1.88 / 53 / 28 | 43 / 1.93 / 22 / 14 |
| +regime SMA100 | 50 / 1.00 / 50 / 23 | 16 / 0.80 / 20 / 11 |
| +regime SMA200 | 60 / 1.32 / 46 / 16 | 15 / 1.05 / 14 / 8 |
| **+ATRtrail k3** | 107 / 2.20 / 49 / 28 | **41 / 2.14 / 19 / 15** |
| +ATRtrail k4 | 97 / 1.85 / 53 / 28 | 44 / 2.29 / 19 / 14 |
| +both(SMA200,k3) | 65 / 1.78 / 37 / 16 | 12 / 0.82 / 15 / 9 |

**Learnings:**
- **Regime filter REJECTED.** Gating entries on close>SMA100/200 cut TEST CAGR
  43%→15-16% and Calmar 1.93→0.80-1.05 — it blocks profitable re-entries during
  recoveries (price often still below a lagging SMA). Hurts, doesn't help.
- **ATR trailing stop ADOPTED (k=3, atr_n=14).** Improves risk-adjusted return on
  BOTH halves (Calmar TRAIN 1.88→2.20, TEST 1.93→2.14) and cuts max drawdown
  (TEST 22%→19%) with CAGR essentially intact. k=4 had a better TEST but weaker
  TRAIN (1.85) — k=3 is the more consistent, robust choice.
- **Bull-market lag is STRUCTURAL** to breakout entries (you miss the first leg);
  neither the regime gate nor the exit tweak fixes it (per-year strat vs B&H is
  ~unchanged in bull years). This is an inherent property of trend-following, not
  a bug to tune away — accepted.

**Updated best config:** DAILY Donchian breakout in20/out20 **+ ATR(14) trailing
stop, k=3**. Metrics (TEST): CAGR +41%, Calmar 2.14, maxDD 19%. This is a modest
but genuine, OOS-validated risk-adjusted improvement over Cycle-4's base.

**Next cycle (7):** apply the ATR-trail refinement to the 4h Donchian 30/20 and
walk-forward it on the full 4h set; then begin the daily/4h-cadence Donchian bot
skeleton (research/paper only, no live funds).

---

## Cycle 7 — Does the ATR trailing stop generalize to 4h? (ONE hypothesis)

**Hypothesis:** the ATR(14) trailing stop k=3 that improved the DAILY Donchian
(Cycle 6) will also improve the 4h Donchian 30/20 co-best.
**Test:** full-history 4h data (integrity-verified, Cycle 5), train/test 70/30,
vs current-best base 4h 30/20. (`backtest/cycle7.py`, reuses Cycle-6 engine.)

**Results (CAGR% / Calmar / maxDD% / trades):**
| variant | TRAIN | TEST |
|---|---|---|
| base 30/20 (current best 4h) | 118 / 3.30 / 36 / 150 | 48 / **1.93** / 25 / 64 |
| +ATRtrail k3 | 123 / 3.68 / 33 / 156 | 41 / 1.53 / 27 / 70 |
| +ATRtrail k4 | 121 / 3.64 / 33 / 151 | 42 / 1.68 / 25 / 68 |
| +ATRtrail k5 | 121 / 3.64 / 33 / 150 | 49 / 1.98 / 25 / 64 |

**Outcome: HYPOTHESIS REJECTED.** Tight trails (k3/k4) *raise TRAIN but lower
TEST* Calmar (1.93→1.53/1.68) — a classic overfit signature; on noisier 4h bars
the trailing stop exits into whipsaws. Only a very loose k5 is neutral (TEST 1.98
≈ base 1.93, same maxDD/CAGR), i.e. it rarely triggers. **No OOS benefit.**

**Learning:** exit design is timeframe-dependent. The Cycle-6 ATR-trail win is
SPECIFIC to daily (low-noise) bars; it does not transfer to 4h. Keep the 4h
co-best as plain Donchian 30/20 (no trailing stop).

**Best config: UNCHANGED.** Daily Donchian 20/20 + ATR(14) trail k=3 remains
primary; 4h Donchian 30/20 (no trail) remains the validated co-best.

**Next cycle (8):** either (a) test volatility-targeted position sizing for
better risk-adjusted return within the 1M cap, or (b) start the daily-cadence
Donchian bot skeleton (research/paper only, no live funds).

---

## Cycle 7 (addendum) — 4h ATR-trail WALK-FORWARD + paper bot skeleton

Data integrity re-affirmed (verify_data.py): datasets unchanged, all checks pass
(daily 0 gaps; 4h 3 missing/0.015%; no dup/out-of-order; OHLC sane; UTC; no
lookahead).

**(1) Multi-fold walk-forward of the 4h ATR-trail** (`cycle7_walkforward.py`,
fixed Donchian 30/20, compare base vs +ATRtrail across 5 anchored folds):
| fold | test window | base Calmar | k3 | k5 |
|---|---|---|---|---|
| 1 | 2019-02..2020-08 | 3.71 | 5.41 | 4.64 |
| 2 | 2020-08..2022-02 | 13.95 | 13.35 | 13.95 |
| 3 | 2022-02..2023-08 | 1.30 | 1.86 | 1.38 |
| 4 | 2023-08..2025-03 | 8.66 | 7.99 | 8.80 |
| 5 | 2025-03..2026-09 | 0.62 | 0.22 | 0.67 |
- k3 beats base in only **2/5** folds (and hurts in folds 2,4,5); k5 in 4/5 but
  only marginally (k5 is so loose it rarely fires). CONFIRMS the Cycle-7 single-
  split result across folds: **ATR-trail is not a robust OOS improvement on 4h.**
  4h co-best stays plain Donchian 30/20.

**(2) Research/paper-only Donchian bot skeleton** (`src/donchian_bot.py`,
+ candle helpers in `src/upbit_client.py`):
- Fetches Upbit PUBLIC candles (no keys), replays Donchian(+ATR trail on daily,
  none on 4h) over closed candles to get the CURRENT target (LONG/FLAT), and in
  PAPER mode logs the order it *would* place, sized within the 1,000,000 KRW cap
  via the shared RiskManager. **No live code path exists** — it cannot place
  orders. Own risk-state file per timeframe; paper/risk state gitignored.
- Smoke test (2026-09-11): daily -> target LONG (breakout_entry), would paper-buy
  200,000 KRW; 4h -> target FLAT, no action. Runs clean.

**Best config: UNCHANGED** (daily Donchian 20/20 + ATR-trail k3; 4h 30/20 plain).
**Next cycle (8):** forward-run the paper skeleton on a daily schedule to log live
signals, and/or test volatility-targeted sizing within the 1M cap.

---

## Cycle 8 — Volatility-targeted position sizing (ONE hypothesis)

**Hypothesis:** sizing each entry inversely to recent realized volatility
(f = clip(target_vol / realized_vol, 0, 1), long-only, no leverage, held to
exit) improves the risk-adjusted return of the current best (daily Donchian
20/20 + ATR(14) trail k3) OOS vs full exposure. (`backtest/cycle8.py`, vol_N=20,
train/test 70/30 on the verified daily data.)

**Results (CAGR% / Calmar / maxDD%):**
| variant | TRAIN | TEST |
|---|---|---|
| baseline full-exposure | 107 / 2.20 / 49 | 41 / 2.14 / 19 |
| **voltarget 2%/day** | 89 / 2.61 / 34 | **40 / 2.31 / 17** |
| voltarget 3%/day | 103 / 2.63 / 39 | 41 / 2.14 / 19 |
| voltarget 4%/day | 110 / 2.61 / 42 | 41 / 2.14 / 19 |
| voltarget 5%/day | 110 / 2.49 / 44 | 41 / 2.14 / 19 |

**Outcome: PARTIALLY CONFIRMED — adopted as an optional sizing overlay.**
- A **tight 2%/day target improves OOS** risk-adjusted return: TEST Calmar
  2.14→2.31, maxDD 19%→17%, with CAGR essentially flat (41→40). It also improves
  TRAIN Calmar (2.20→2.61) and cuts TRAIN maxDD (49→34) — consistent on both
  halves.
- Looser targets (3-5%/day) rarely bind (BTC daily vol is often <3%), so they
  are INERT on test (identical to baseline) though still help TRAIN.
- Modest, single-parameter improvement (some overfit risk on the exact 2%), but
  the direction — de-risk in high-vol regimes — is principled and never worse
  than baseline at looser settings. The 1,000,000 KRW cap remains the hard
  absolute-exposure limit; vol-targeting only ever scales DOWN from full.

**Best config update:** keep DAILY Donchian 20/20 + ATR trail k3 as the core;
ADD an optional volatility-target sizing overlay (target ~2-2.5%/day, no
leverage) that improves drawdown with ~flat CAGR. 4h co-best unchanged.

**Next cycle (9):** wire the vol-target overlay into src/donchian_bot.py (paper
only), and/or forward-run the paper skeleton on a schedule to accumulate signals.

---

## Cycle 8 (addendum) — Forward paper-runner + persistent per-timeframe logs

Mission part (2) (volatility-target sizing) was completed above. This addendum
delivers part (1): forward-run the paper-only Donchian bot and persist a track
record. Data integrity re-affirmed (verify_data.py, unchanged: daily 0 gaps; 4h
3 missing/0.015%; no dup/out-of-order; OHLC sane; UTC; no lookahead).

**What changed:** rewrote `src/donchian_bot.py` into an idempotent forward-runner.
- Fetches CLOSED Upbit public candles (no keys), replays the strategy
  (daily=Donchian 20/20 + ATR(14) trail k3; 4h=Donchian 30/20 no trail),
  paper book = 1,000,000 KRW, long-only all-in, fills at next-bar OPEN, 0.05%/side.
- Appends ONE row per closed candle to `logs/paper_<tf>.csv` with columns:
  time, close, position, action, fill_price, equity_krw, realized_pnl_cum_krw,
  trades, reason. Idempotent — re-running only appends candles newer than the
  last logged one (verified: 2nd run appended 0). **No live path; no keys.**
- Added `run_donchian_paper.sh` (runs both TFs). No OS cron in this env, so the
  cadence is invocation-driven (each research cycle); the script documents the
  daily / every-4h cron lines for a real deployment.

**Warm-start backfill (last 200 closed candles each):**
| timeframe | window | paper return | trades | current position |
|---|---|---|---|---|
| daily | last 200 days | **+9.1%** (equity 1,090,795 KRW) | 3 | LONG |
| 4h | last ~33 days | **+14.9%** (equity 1,148,915 KRW) | 2 | FLAT |

These are short recent windows (not the multi-year validation) — they exist to
seed the forward track; real forward evaluation accumulates as candles close.

**Best config: UNCHANGED** (daily Donchian 20/20 + ATR trail k3 + optional
vol-target ~2%/day; 4h 30/20 plain). **Next cycle (9):** keep appending the paper
track each cycle; once enough forward candles accumulate, compare realized paper
PnL vs backtest expectation; optionally wire the vol-target overlay into the
paper runner.

---

## Cycle 9 — Vol-target overlay wired into the paper bot + risk-manager gate

Research/paper only. Data integrity re-affirmed (verify_data.py, unchanged: daily
0 gaps; 4h 3 missing/0.015%; no dup/out-of-order; OHLC sane; UTC; no lookahead).

**(1) Wired the Cycle-8 vol-target overlay into `src/donchian_bot.py`:**
- Entry sizing now uses fraction f = clip(target_vol/realized_vol, 0, 1) (no
  leverage; only scales DOWN). Daily target_vol=2.5%/day, vol_n=20 (validated);
  4h left OFF (not validated there). Fraction computed at the DECISION bar and
  carried on the pending order (no lookahead).
- Gated behind PAPER mode (`--mode paper`; no live path exists). The shared
  RiskManager now governs the current BUY intent: `risk.can_open()` enforces the
  HALT kill switch + 1M exposure cap before any intended entry; paper size =
  min(f*capital, cap-allowed).
- **Proven this cycle:** vol_frac at 2.5%/day target min 0.98 in the current
  low-vol window (barely binds -> paper equity ~unchanged, matching Cycle 8);
  at a tighter 1.0% target min 0.39 / mean 0.70 (scales down as designed). Kill
  switch: with the HALT flag set, `can_open()` raises and the bot logs the BUY
  intent as BLOCKED.

**(2) Forward-run recorded** (`run_donchian_paper.sh both`, idempotent):
| tf | paper track | return | trades | position |
|---|---|---|---|---|
| daily (vol-target 2.5%) | last 200 candles | +9.1% (1,090,795 KRW) | 3 | LONG |
| 4h (full size) | last 200 candles | +14.9% (1,148,915 KRW) | 2 | FLAT |
Vol-target did not bind materially in this recent low-vol window (f≈1), so the
daily track equals full exposure here — expected. Logs persist in
logs/paper_<tf>.csv (one row per closed candle) and accumulate each cycle.

**Best config: UNCHANGED** (daily Donchian 20/20 + ATR trail k3 + vol-target
~2.5%/day; 4h 30/20 plain). **Next cycle (10):** keep appending the paper track;
once several forward candles accumulate, compare realized paper PnL vs backtest
expectation; consider a volatility regime where the 2.5% target binds to observe
the sizing effect live.

### Cycle 9 — verification re-run (same cycle, new session)

A session rotation landed the Cycle-9 mission again; the work was already on disk
from the prior session, so this turn **independently verified** it rather than
re-implementing, and extended the track. All checks reproduced:
- **Vol-target overlay** (`vol_fraction`): at target 2.5%/day, min 0.98 / mean
  1.00 (binds below full only 2/179 bars — ~inert in the current low-vol regime);
  at a tighter 1.0%/day, min 0.39 / mean 0.67 — scales DOWN as designed, never
  above 1.0. Matches the Cycle-9 claims.
- **Kill-switch gate** (`RiskManager.can_open`): HALT flag set → raises RiskHalt
  ("kill switch active"); daily realized loss ≤ −50,000 KRW → trips HALT and
  raises. Normal state allows 200,000 KRW (PER_TRADE_KRW) per entry within the
  1M cap. Confirmed the bot's BUY-intent path logs BLOCKED when the gate raises.
- **Forward-run / idempotency**: appended **1 new closed 4h candle**
  (2026-09-12T04:00, close 105,053,000, still FLAT) → 4h track now 200 rows;
  re-run appended 0. Daily unchanged (no new closed daily candle; 09-12 still
  forming) → 199 rows, still LONG, +9.1%. Integrity unchanged (public candle
  endpoints, no keys, no live path).

Two doc inconsistencies reconciled (no behaviour change): `donchian_bot.py`
header relabelled Cycle 8→9; `best_config.json` now states the OOS-validated
optimum (2%/day) and the paper-runner setting (2.5%/day, within the mission's
2–2.5% band) separately instead of a single ambiguous `0.02`.

**Best config: UNCHANGED.** Next cycle (10) as above.

---

## Cycle 10 — Dual-book paper logging (full vs vol-target) + forward-run

Research / PAPER ONLY: no live orders, account untouched/unfunded, keys unused,
1,000,000 KRW cap and all risk limits unchanged. Data integrity re-affirmed
(`verify_data.py`, unchanged: daily 3273 bars / 0 gaps; 4h 19628 bars / 3 missing
= 0.015%; 0 dup/out-of-order; OHLC sane; extreme moves = real 2020-COVID /
2017-bubble events). Provenance: Upbit official candle API (public endpoints).

**(1) `src/donchian_bot.py` now logs TWO parallel paper books on the SAME signals
so full-exposure and vol-target-sized equity can be compared as the track grows:**
- `replay()` tracks both books simultaneously — FULL = always all-in within the
  1M cap; VOLTGT = entry scaled by `vol_fraction` ∈ [0,1] (only ever DOWN, no
  leverage, 1M cap still the hard limit). They differ only in the invested
  fraction on entry; identical buy/sell timing (next-bar open, no lookahead).
- The daily vol-target was set to the **OOS-validated optimum 2%/day** (was 2.5%),
  matching the mission's "~2%/day". 4h overlay stays OFF (not validated there),
  so its two columns are identical by construction.
- New CSV schema (regenerated from the same deterministic ~200-candle warm-start;
  old 2.5%/single-column files preserved as `logs/paper_*.cycle9.bak`):
  `time_utc, close, position, action, fill_price, vol_frac, equity_full_krw,
  equity_voltgt_krw, realized_full_cum_krw, realized_voltgt_cum_krw, trades,
  reason`.

**(2) Forward-run (both TFs, idempotent — re-run appended 0):**
| tf | span | full exposure | vol-target (2%) | trades | pos |
|---|---|---|---|---|---|
| daily | 2026-02-25 .. 09-11 (0.54y) | **+9.1%** (1,090,795) | **+8.8%** (1,088,235) | 3 | LONG |
| 4h    | 2026-08-10 .. 09-12 (0.09y) | **+14.9%** (1,148,915) | +14.9% (overlay off) | 2 | FLAT |
At the 2% target the daily overlay binds on a few bars in this calm uptrend, so
vol-target slightly trails full (+8.8% vs +9.1%) — expected: de-risking costs a
little upside in low-vol regimes and pays off by cutting drawdown in high-vol
ones. The two columns will diverge more meaningfully if/when a high-vol regime
arrives.

**(3) Backtest-expectation comparison — set up but NOT yet meaningful.** The
daily track is a 0.54y warm-start window with only **3 trades**; a naive
extrapolation of the backtest TEST CAGR (41%) over 0.54y is ~+20% vs realized
full +9.1%, but at n=3 the sampling variance dwarfs that gap, and the edge is
regime-dependent (lags in bulls, protects in bears). **Conclusion: too few
forward trades to compare yet.** The dual-book columns now in place are the
instrument for this comparison; revisit once several genuinely-forward trades
accumulate.

**Best config: UNCHANGED** (daily Donchian 20/20 + ATR trail k3 + vol-target
2%/day; 4h 30/20 plain). **Next cycle (11):** keep appending both books each
cycle; once enough forward trades close, compare realized paper PnL (both books)
vs backtest expectation and note divergence; watch for a high-vol window where
full vs vol-target separate.

### Cycle 10 (addendum, 2026-09-12T10:57Z) — forward-run + per-trade comparison

Re-invoked the forward-runner on cadence. No candle closed since the prior run
(~19 min earlier; daily 09-12 still forming, 4h 08:00 bar not yet closed), so both
TFs idempotently appended **0 rows** — correct steady-state. Integrity/provenance
re-affirmed (`verify_data.py` unchanged: daily 0 gaps, 4h 3 missing/0.015%, no
dup/out-of-order, OHLC sane; Upbit official API, public endpoints, no keys).

**Began the realized-vs-backtest comparison (per-trade, net of 0.05%/side).**
Round-trips extracted from the paper CSVs:
| tf | closed trades | win rate | avg trade | detail |
|---|---|---|---|---|
| daily | 2 (+1 OPEN) | 50% | **−0.45%** | +3.87%, −4.76%; the +9.1% equity is driven by the OPEN LONG (+10.3% unrealized since 2026-08-20), not the closed pair |
| 4h | 2 | 50% | **+7.78%** | +19.05%, −3.49% |

Backtest expectation (best_config 70/30 split): win rate ~54%, avg trade ~8.5%.
The 4h paper avg (+7.78%) sits right at expectation; the daily closed avg
(−0.45%) is far below — but with only **2 closed trades per TF** the sampling
error is enormous (a single trade flips win rate by 50pts), so neither is a real
signal. **No divergence can be asserted yet**; the most recent move is consistent
with the known profile (big OPEN trend-follow winner + one small whipsaw loss).
Verdict unchanged: accumulate more genuinely-forward trades before concluding.

---

## Cycle 11 — Power analysis: how many forward trades define "enough"?

Research/paper only; no orders, no keys, 1M cap and risk limits unchanged.
Forward-run re-invoked (2026-09-12T10:59Z, ~2 min after the prior run): no candle
closed, both TFs idempotently appended **0 rows** (re-run also 0). The track is a
warm-start seeded 2026-09-12, so **genuinely-forward trades so far ≈ 0** — which
is exactly why the mission's "compare once enough accumulate" could not yet fire.
So this cycle answers the precondition quantitatively: **what is "enough"?**

`backtest/cycle11_power.py` replays the EXACT paper-bot strategy
(`src/donchian_bot.replay`, same params/fees/fill timing) over the full verified
9y history, extracts per-trade net returns, and sizes the forward sample needed
for a 95% CI on the mean trade to exclude 0 (i.e. to distinguish the edge from
noise):

| tf | trades (9y) | mean/trade | std | win rate | freq | N* (95% CI > 0) | forward time |
|---|---|---|---|---|---|---|---|
| daily | 43 | **+19.5%** | 50.4% | 51% | 4.8/yr | **26 trades** | **~5.4 yr** |
| 4h | 214 | **+3.4%** | 12.0% | 46% | 23.9/yr | **49 trades** | **~2.1 yr** |

**Key takeaways:**
- The edge per trade is large but extremely noisy (daily std 50% on a +19.5%
  mean); validating it purely from forward data needs 26 daily trades ≈ **5.4
  years**, or 49 4h trades ≈ **2.1 years**.
- **The 4h book is the far faster route to statistical confirmation** (~2y vs
  ~5y) despite its smaller per-trade edge, because it trades ~5× more often. If
  forward validation within a practical horizon matters, prioritise 4h.
- This reframes the forward track's purpose: over realistic horizons it is a
  live-execution / no-blowup sanity check and a regime monitor, NOT a
  from-scratch edge proof — the 9y OOS walk-forward remains the primary evidence.
- (Note the +19.5% full-history daily mean vs the +8.5% 70/30-TEST avg: the full
  series includes the 2017/2020-21 mega-winners; both are "backtest expectation"
  over different windows — the CI logic is unaffected.)

**Best config: UNCHANGED.** Provenance/integrity re-affirmed (`verify_data.py`
unchanged; Upbit official public API). **Next cycle (12):** keep appending both
books; begin counting FORWARD trades past the 2026-09-12 anchor; report 4h
progress toward N*=49 as the leading validation metric.

### Cycle 11 (addendum, 2026-09-12T15:31Z) — forward-run, 1 new 4h candle

~4.5h after the prior run the 4h 08:00 bar closed and was appended (idempotent):
2026-09-12T08:00, close 105,230,000, still FLAT — 4h track now **200 rows**.
Daily unchanged (09-12 still forming) = 199 rows, LONG. Re-run appended 0 (idempotent).
**Forward trades past the 2026-09-12 anchor: still 0** (no BUY/SELL this candle),
so the realized-vs-backtest comparison is unchanged and remains premature — no
divergence to assert. Progress toward the Cycle-11 validation target: 4h 0/49,
daily 0/26. Integrity/provenance re-affirmed (`verify_data.py` unchanged; Upbit
official public API, no keys). Best config UNCHANGED.

### Cycle 12 (2026-09-12T15:34Z) — forward-run; escalating cadence blocker

Mission steps executed: (1) integrity/provenance re-affirmed (`verify_data.py`
unchanged: daily 3273/0 gaps, 4h 19628/3 missing=0.015%, no dup/out-of-order,
OHLC sane; Upbit official public API, no keys); (2) forward-runner re-invoked —
~2 min after the prior run, no candle closed, both TFs idempotently appended 0
(re-run also 0); (3) lead metric **4h forward trades = 0/49** past the 2026-09-12
anchor (only 1 candle past anchor; daily 0/26). Best config UNCHANGED.

**Structural blocker raised to owner (report.txt = needs_input):** this is the
5th near-identical cycle within hours. The lead metric can only advance as real
candles close (daily 1/day, 4h 6/day) and there is no OS cron in this workspace,
so cycles fired minutes apart produce nothing. Requested a decision: run
`run_donchian_paper.sh` on a scheduler on the bot's host, OR space these missions
to ~daily, OR authorize me to self-schedule wake-ups at 4h-candle cadence.
No work is lost meanwhile; the runner stays idempotent.

---

## Cycle 13 — EXECUTION-GAP robustness (agent-outage + market gaps)

Research/paper only; no orders, no keys, 1M cap and risk limits unchanged. Data
integrity/provenance re-affirmed (`verify_data.py`, unchanged: daily 3273/0 gaps;
4h 19628/3 missing=0.015%; no dup/out-of-order; OHLC sane; Upbit official public
candle API). Full analysis: `backtest/cycle13_gap.py` (self-contained, 9y).

**Problem.** Signals fire on closed candles and the legacy paper runner assumed a
fill at the next-bar OPEN. If the agent is blind for up to ~5h (session limit) or
a candle-close is missed, that fill slips to the first open AFTER the outage —
a delayed/gapped fill several bars late. Quantified as a worst case (every fill
slips by the outage) over the full 9y history:

| tf | baseline CAGR / Calmar / maxDD | 5h outage (worst case) | degradation |
|---|---|---|---|
| daily | 80.7% / 1.66 / 48.5% | +1 bar: 75.1% / 1.52 / 49.4% | −5.6pp CAGR |
| 4h | 94.5% / 2.65 / 35.7% | +2 bar: **75.5% / 1.55 / 48.6%** | **−19pp CAGR, Calmar 2.65→1.55** |

Daily is lightly exposed (one open/day → a 5h gap = at most one bar late); 4h is
materially exposed (a 5h gap straddles a whole 4h bar → 2-bar slip). Wider stress:
4h at 12h = −33pp, 48h = −56pp. Monte-Carlo EXPECTED degradation (random 5h
outages): 4h loses only −1.7pp at ~1/week but −10.6pp at ~1/day; daily −3.4pp /
−30.8pp respectively — i.e. degradation scales with outage frequency.

**Mitigations tested (out-of-sample, 9y):**
- **(a) Resting exchange-side stop orders** — entry buy-stop at the prior n_in-bar
  high, exit sell-stop at channel-low / ATR-trail; fill intrabar WITHOUT the agent
  (taker slip 1.5bps). **Outage-immune by construction.** 4h: CAGR 94.5→**96.0%**,
  Calmar 2.65→2.62 (≈baseline AND gap-proof — clear win). daily: CAGR 80.7→60.2%,
  maxDD 48.5→44.3% (gives back some CAGR because the ATR trail is close-based by
  design and intrabar stops whipsaw more; still gap-proof and lower drawdown).
- **(c) Staleness guard** (cancel entries filling >1 bar late) — under a
  *persistent* worst-case outage this degenerates to **0 trades** (turns the
  strategy off), so it is NOT a standalone fix; only sensible as a filter for
  occasional delays, paired with resting orders.
- **(b) Catch-up / reconciliation on restart** — already inherent: the runner
  recomputes the full intended state from all closed candles each invocation and
  converges idempotently (re-run appends 0), so a missed window self-heals on the
  next run without chasing.
- **(d) Blind-window sizing** — see risk manager below.

**Recommendation adopted: resting stop orders as the DEFAULT execution.** Wired
into `src/donchian_bot.py` (`--exec resting`, now default; `--exec market` keeps
the legacy gap-exposed path). The forward paper track was regenerated in resting
mode (old market track preserved as `logs/paper_*.cycle12market.bak`). For daily
the recommended LIVE shape is a hybrid — resting entry + an always-in protective
channel/initial-ATR stop that bounds blind-window loss, with the tighter ATR trail
managed by the agent when online (it simply pauses ratcheting during an outage;
the resting stop still caps loss).

**Risk manager now treats the 5h blind window as a first-class input.** New
`config.MAX_BLIND_HOURS=5`, `config.BLIND_WORST_MOVE=0.13` (≈0.1st-percentile 9y
5h adverse move; empirical: median −0.5%, 1%ile −5.6%, 0.1%ile −13.4%, min −33%
on 4h data — daily bars can't resolve sub-24h so that row is an upper bound).
`RiskManager.gap_capped_notional(stop_distance_frac)` caps entry notional so a
blind-window drop cannot breach DAILY_LOSS_LIMIT: with a resting stop the bound is
the stop distance; naked it is BLIND_WORST_MOVE (→ ≤ ~384k KRW naked). At the
existing 200k/trade limit a 13% blind move = 26k < 50k limit, so 200k sizing is
already gap-safe; the cap binds only for larger/naked positions (e.g. the 1M
full-exposure paper book would lose 130k naked → live sizing must be gap-capped).

**Forward track (resting mode, last ~200 candles):** daily +11.2% (FLAT, 3 trades)
— the prior LONG exited on the ATR/channel stop as price fell from ~110M to ~103M;
4h +15.6% (FLAT, 2 trades). Current resting orders: daily BUY-STOP @ 112,445,000
(protective stop ~9.3% below); 4h BUY-STOP @ 108,242,000 (~5.8% below). Both
gap-capped, PAPER only, no live orders.

**Best config: strategy UNCHANGED; execution model UPGRADED to resting stops for
gap-robustness.** best_config.json updated (last_cycle=13). **Next cycle (14):**
keep the resting forward track accruing toward the 4h N*=49 validation target;
watch resting vs market divergence and any real outage in the log.

---

## Cycle 14 (daily cycle, 2026-09-19) — Fixed-anchor forward-equity curve

Standing daily turn. Research/paper only; no orders, no keys, 1M cap and risk
limits unchanged. Data integrity re-affirmed (verify_data.py unchanged: daily
3273/0 gaps; 4h 19628/3 missing=0.015%; OHLC sane; Upbit official public API).

**Picked the highest-value open item: the sliding-window equity artifact** flagged
in Cycle 13. It stopped being cosmetic today — appending new candles made the 4h
persisted equity jump **+11.0% -> -0.4% within the same CSV with no trade**, purely
because an old winning trade slid out of the recomputed ~250-candle window. The
logged track was self-contradictory.

**Fix (src/donchian_bot.py):** the forward equity is now pinned to a FIXED calendar
anchor `FORWARD_ANCHOR = 2026-09-12` (the forward-start already used for the N*
validation count). `replay(..., anchor_idx)` uses pre-anchor bars ONLY for indicator
warmup and starts the books at CAPITAL, FLAT, at the anchor, so equity(T) is a pure
function of bars from the anchor and is identical on every run regardless of how far
back the fetch reaches. `main()` locates the anchor in the fetched window (warns and
falls back if it ever slides out; safe for months on daily, ~5 weeks on 4h at
count=250).

**Verified stable:** replaying the full window vs a window trimmed 10 bars at the
front and 5 at the back gives **0 equity mismatches** on overlapping timestamps
(previously they differed). Track regenerated from the anchor (old sliding-window
files kept as logs/paper_*.cycle13slide.bak); idempotent (re-run appends 0).

**Honest forward track since the 2026-09-12 anchor (this supersedes the earlier
backfill-window numbers, which were NOT genuinely forward):**
| tf | rows | trades since anchor | equity | note |
|---|---|---|---|---|
| daily | 7 (09-12..09-18) | 0 | **1,000,000 (+0.0%)** | flat at anchor; no breakout yet; resting BUY-STOP @ 112,000,000 pending |
| 4h | 45 (09-12..09-19) | 1 (open) | **1,034,614 (+3.5%)** | LONG; resting SELL-STOP @ 103,000,000 (~7.3% below) |

So genuinely-forward progress toward the Cycle-11 validation targets is daily 0/26,
4h 0-closed/49 — the counter now rests on a clean, stable curve. Best config
strategy/execution UNCHANGED. **Next:** keep the anchored track accruing; when the
anchor approaches the 4h fetch-window edge (~5 weeks), deepen the fetch (paginate)
so the anchor never drifts.

---

## Cycle 15 — Fixed tradable-capital cap that protects accumulated profit

Feature (owner request). Research/PAPER only; no orders, no keys, live path
untouched. Goal: the bot deploys only a fixed budget (default 1,000,000 KRW) no
matter how the balance grows; profit above the base is set aside and never
re-risked (no compounding of profit).

**Config parameter:** `config.BASE_TRADABLE_CAPITAL_KRW` (default 1,000,000 KRW),
tunable, not hardcoded. Distinct from `MAX_EXPOSURE_KRW` (the hard notional
ceiling); sizing now draws from the capped tradable capital.

**Definition & drawdown choice (documented):**
`tradable_capital(free_balance) = min(BASE_TRADABLE_CAPITAL_KRW, free_balance)`;
`protected_profit = max(0, free_balance - base)`. Drawdown: if losses pull free
balance below the base, tradable capital = the (reduced) free balance — we never
deploy MORE than the base, and never deploy money we don't have. Consequence
(stated plainly): profit is "set aside" as balance-above-base and is never
re-risked as long as the account stays at/above the base; there is no separate
lockbox that would survive the account falling below the base (at which point the
strategy has lost its entire starting budget and profit-protection is moot).

**Wired in:**
- `RiskManager.tradable_capital()` / `.protected_profit()`; `can_open(free_balance
  =None)` and `gap_capped_notional(..., free_balance=None)` now size against
  `min(MAX_EXPOSURE_KRW, tradable_capital)`. `free_balance=None` returns the base
  (backward-compatible; paper runner enforces the cap in its own book).
- Paper runner `donchian_bot.py`: each entry deploys `min(BASE, cash)` for both
  the full and vol-target books; profit that lifts the book above BASE stays as
  protected idle cash and is never redeployed.

**Tests (`tests/test_capital_cap.py`, plain asserts, 14/14 pass):**
- profit accumulation: balance 1.1x base -> tradable stays at base, 100k protected;
- drawdown: balance 0.6x base -> tradable = 0.6x base, nothing protected;
- `can_open` caps at base even with a 5x-base balance (per-trade lifted so the cap
  binds), sizes down in drawdown, base-default when no balance passed;
- replay integration: after a winning trade the re-entry deploys only the base and
  a subsequent crash leaves the protected profit intact — capped book ends
  2,089,730 KRW vs an uncapped counterfactual 280,520 KRW.

Safety posture UNCHANGED: still research/paper, no live orders, no keys touched.
Forward track unaffected so far (the single open 4h position was entered with
exactly the base; protection engages on the next entry after a profitable exit).
best_config.json updated (last_cycle=15).

---

## Cycle 16 — Data-gathering routed through the live Upbit public API

Owner directive: gather market data from the live Upbit API, not any static/
simulated source. Research/PAPER only; public read-only endpoints; no orders, no
keys.

**Audit finding:** there was never any simulated/synthetic PRICE data. The forward
paper runner already fetched live Upbit public candles via `UpbitClient`
(candles_days / candles_minutes), and the backtest datasets were real Upbit data
fetched via `fetch_candles.py` — but they were STATIC snapshots (stale to
2026-09-10). ("simulated" in the codebase refers only to simulated ORDER FILLS in
paper mode and the Cycle-13 outage Monte-Carlo — not data.)

**Changes:**
- `UpbitClient.candles_history()` — paginated public candle history (>200 rows,
  walks the `to` cursor, dedups) on the shared client, so there is ONE canonical
  live-Upbit data path for both research datasets and the paper runner. Public
  read-only; no keys.
- `backtest/refresh_data.py` — canonical data-gathering entrypoint: pulls daily +
  4h fresh from `api.upbit.com` via the client and runs `verify_data.py`.
- Refreshed the datasets from the live API to now: daily 3273->3283 rows (to
  2026-09-20), 4h 19628->19683 rows (to 2026-09-20T04:00). Integrity unchanged:
  0 dup/out-of-order, daily 0 gaps, 4h 3 known missing (0.015%), OHLC sane,
  extreme moves = real 2020-COVID / 2017 events. Pre-refresh files kept as
  data/*.pre_refresh.bak.

**Safety confirmed (no live-trading path enabled):** the paper runner has NO
order/private calls (grep: no buy_/sell_/accounts/private=True/load_keys); the
client is constructed with empty keys ("", "") in both the runner and the refresh
script; no API keys are hardcoded anywhere; account untouched/unfunded. Paper
runner verified working on the live feed; test suite 14/14. best_config.json
updated (last_cycle=16).

---

## Cycle 17 (2026-09-23 daily) — Fixed the canonical data path's silent integrity-check failure + advanced forward track

Research/PAPER only; public read-only endpoints; no live orders, no keys,
account untouched/unfunded, 1,000,000 KRW cap and all risk limits intact.

**Bug found & fixed (real, in the Cycle-16 canonical data path).**
`backtest/verify_data.py` hardcoded relative paths (`../data/krw_btc_1d.csv`)
in its `__main__`, so it only resolved when cwd was `backtest/`.
`refresh_data.py` (the Cycle-16 "one canonical data-gathering entrypoint")
invokes verify as a subprocess *without* setting cwd, so when refresh is run
from the repo root the integrity check silently `FileNotFoundError`-ed and the
data was accepted UNVERIFIED. This defeats the whole point of the canonical
path ("data must be trustworthy before use").
- Fix: `verify_data.py` now resolves the data dir relative to the script file
  (`DATA = <script>/../data`), not the caller's cwd. Works identically run
  standalone from `backtest/` or as the refresh subprocess from repo root.
- Verified: `python3 backtest/refresh_data.py` from the repo root now runs the
  full integrity check end-to-end.

**Data refreshed from the live Upbit public API (to now):**
- daily 3286 rows -> 2026-09-23T00:00, 4h 19701 rows -> 2026-09-23T04:00.
- Integrity CLEAN: daily 0 dup / 0 out-of-order / 0 gaps; 4h 0 dup/ooo,
  3 known historical gaps (0.015%, the same 2017/2018/2023 8h gaps); OHLC sane;
  extreme moves = the known 2020-03-12 COVID crash (-33.1%) and 2017 events.

**Forward paper track advanced to today (was stale at 2026-09-20):**
- daily: 11 rows, LONG since 2026-09-19 breakout, paper equity +3.2%
  (full = vol-target = 1,031,918 KRW); resting sell-stop @ 108,640,286
  (~6.1% below last close).
- 4h: 67 rows, LONG, paper equity +8.4% (1,084,367 KRW); resting sell-stop @
  109,268,000 (~6.2% below).
- Both books still single-position, no new trades closed since the anchor, so
  the forward-validation power picture is unchanged (daily needs ~26 trades /
  ~5yr; the track is accumulating as expected, slowly).

**Safety confirmed:** paper runner + refresh script have no order/private calls
(grep clean), both construct `UpbitClient("", "")` (no keys). Test suite
14/14 pass. best_config.json bumped to last_cycle=17.

---

## Cycle 18 (2026-09-23) — OWNER FEATURE: bear-market strategy + backtest + live engine

Owner mission (via secretary), 3 deliverables. Research/PAPER only; live is OFF by
default and gated; no keys touched; account untouched/unfunded; 1M cap + all risk
limits intact.

**(1) Bear-market strategy + research note** — `research/BEAR_MARKET_STRATEGY.md`.
Chose KRW-BTC (Upbit spot, 9y verified history w/ 2018 + 2021-22 bears). Bear
defined by EITHER close < SMA200 (Faber-style trend) OR drawdown >=20% off the
trailing-year high (conventional bear def), with hysteresis. Upbit is spot-only
(no shorting) so the strategy is DEFENSIVE: long only in bull regimes, KRW cash in
bear regimes. 5 cited references (Faber 2007; Detzel/Liu/Strauss/Zhou/Zhu 2021 —
MA rules cut BTC drawdowns; Liu & Tsyvinski 2021 — crypto TS-momentum; Moskowitz
et al. 2012; Hurst et al. 2017), each verified for title/author/link.

**(2) Runnable backtest** — `backtest/bear_backtest.py` (`python3 backtest/
bear_backtest.py`). Prints metrics, trade log, ASCII equity chart, and a
bear-window breakdown; stdlib only; fills at next-open (no lookahead), 0.05%/side.
Result (9y daily, to 2026-09-23): maxDD buy-and-hold 86.8% -> breakout_regime
27.7%; the 2018 bear (-77.7% B&H) becomes 0.0% (in cash), 2021-22 (-73.5%) becomes
-7.3%. Filter trades return for drawdown protection, as intended. Current live
regime = BEAR (BTC ~30% off high) -> strategy is flat now.

**(3) Live engine, dry-run by default** — `src/live_engine.py` + `src/regime.py` +
`src/bear_strategy.py` (strategy is the SINGLE SOURCE OF TRUTH shared by backtest
and live). One idempotent decision/invocation (daily cadence). Live order
placement gated behind ALL of: config.LIVE_TRADING_ENABLED (master switch, default
False) + --live + typed "TRADE LIVE" + present keys; miss any -> stays dry-run
(logs the exact order it WOULD place, no keys, no private calls). Going live = flag
+ keys, not a rewrite. Sizing/limits via the shared RiskManager. The master switch
now also gates the legacy bot.py --live. Added config.BEAR params + config.
LIVE_TRADING_ENABLED.

**Safety verified:** both order calls (buy_market/sell_market) sit strictly inside
`if live:` branches; dry-run constructs UpbitClient("", "") (no keys); tested
--live-with-gates-failing correctly stays dry-run. Tests: new
tests/test_bear_strategy.py 22/22 (regime, targets, no-lookahead fill engine,
gating) + existing tests/test_capital_cap.py 14/14 (no regression). README +
OPERATIONS.md updated. best_config.json bumped to last_cycle=18.

---

## Cycle 19 (2026-09-23) — OWNER: published to GitHub + structure diagram + Korean report

Owner mission (via secretary). Research/PAPER only; live OFF and gated; no keys
committed; account untouched. Owner decision recorded: bear strategy stays
DEFENSIVE only (loss-avoidance; no shorting/derivatives scope).

**(1) GitHub publish** — created public repo **https://github.com/Dirtfy/upbit-hft-bot**
(Dirtfy is a user account, not an org) via the A_Company git credential helper;
pushed `main` (45 files). Korean repo description + README (code comments left in
English per owner). SAFETY: hardened .gitignore to exclude AI-company scaffolding
(CLAUDE.md, handoff/mission/prompt/report, leader.log, .claude/) and all runtime
state (data/, logs/, *.HALT, *risk*.json, secrets.env); verified staged + remote
trees are free of secrets/scaffolding (grep clean). secrets.env.example ships
placeholders only.

**(2) Structure diagram** — `docs/architecture.dot` -> `docs/architecture.png`
(committed). Shows data layer, the shared strategy core (config/regime/
bear_strategy) as SINGLE SOURCE OF TRUTH feeding BOTH backtest and live engine,
the RiskManager envelope, and the 4-gate DRY-RUN vs LIVE flow. Rendered via
render_diagram.sh; installed NanumGothic into ~/.fonts so Korean labels render
(no CJK font was present). PNG for owner email: docs/architecture.png.

**(3) Korean strategy report** — `docs/strategy_report_ko.md` (committed): what it
does (상승장 BTC 보유 / 하락장 현금), bear detection (200일 MA / 1년 고점대비
-20% + 되돌림 버퍼), headline backtest (MDD 86.8% -> 27.7%; 2018 -77.7% -> 0.0%),
and the safety gating.

No code/strategy logic changed this cycle; docs + packaging only. Tests remain
22/22 + 14/14. best_config.json -> last_cycle=19.

---

## Cycle 20 (2026-09-24 daily) — Data-staleness guard on the live engine

Daily standing cycle. Research/PAPER only; live OFF and gated; no keys; account
untouched/unfunded; 1M cap + all risk limits intact.

**Gap found & closed.** The live engine (`src/live_engine.py`) decided off
whatever the public API returned, with **no freshness check**. If the Upbit feed
lags/outages, or the engine sits idle for days, it would still open a *new*
position on stale market data — precisely when a defensive strategy should NOT be
adding risk. Added a data-staleness guard:
- `config.MAX_CANDLE_STALENESS_HOURS = 48.0` (a daily candle closes 24h after its
  open; a healthy daily run sees a <24h-old close, so 48h allows one skipped day
  of slack before flagging).
- `live_engine.candle_age_hours()` — pure helper: hours since the last CLOSED
  daily candle (open + 24h). Naive/UTC-stamped timestamps handled.
- In `decide_and_execute`: when stale, log a WARNING and **refuse NEW entries**
  (BUY), while **protective exits (SELL) and HOLD stay allowed** — reducing risk
  is always safe even on an old candle. Asymmetric by design (never open fresh
  risk blind; always able to get out).

**Verified.** Unit tests added to `tests/test_bear_strategy.py` (now **28/28**):
fresh ~6h candle under limit, ~102h candle over limit, one-skipped-day (~30h)
within slack, naive-UTC handling. End-to-end (monkeypatched, no network): stale +
LONG-target + FLAT ⇒ BUY refused (no state write); stale + FLAT-target + LONG ⇒
protective SELL still flattens. Live DRY-RUN on fresh data (last_closed
2026-09-23) shows no false trigger: regime=bear ⇒ FLAT ⇒ HOLD. capital-cap tests
14/14 unchanged.

**Forward track advanced** (idempotent paper runner, new candles captured):
daily 12 rows, +3.4% (1 open LONG); 4h 73 rows, +7.5% (1 open LONG). Data
refreshed live to 2026-09-24 (daily 3287 rows, 4h 19707 rows); integrity OK
(only the long-known 2 pre-2018 extreme moves + 1 historical 4h gap flagged).

**Also noted (prior turns, doc-only):** the Korean report gained an expected
annual-return section (defensive CAGR +28.7% vs buy-and-hold +44.2% over the same
9y, plus scenario-discounted forward estimate 8–15% base) and the architecture
diagram was reworked into a functional/runtime view; both pushed to the repo.

best_config.json -> last_cycle=20.

---

## Cycle 21 (2026-09-25) — OWNER: official ~1-month paper-trading period + data-storage audit

Owner mission (via secretary): formally run a ~1-month paper-trading period with a
COMMITTED, human-readable record, and answer where market data is being stored /
how it accumulates. Research/PAPER only; read-only public endpoints; no keys, no
account, no live orders; 1M paper book + all risk limits intact.

**(1) Committed paper-trading pipeline** — new `paper_trading/` (NOT gitignored):
`paper_trader.py` runs the published defensive bear strategy forward on LIVE
closed daily candles, marks a 1M paper account to market, and appends per cycle:
`paper_log.jsonl` (machine ledger), `JOURNAL.md` (human-readable: regime/signal,
virtual position, entry/exit rationale, per-cycle + cumulative P/L), and
`market_data_daily.csv` (the day's OHLC — a small committed dataset for later
backtesting of the paper window). Reuses the shared regime/strategy core (so the
logged logic == the backtested logic) and the Cycle-20 staleness guard. Idempotent
(resumes from the last logged candle; first run anchors at the latest closed
candle, no backfill). Verified: BUY/SELL/HOLD transitions + P&L on a synthetic
bull→crash replay (entered the ramp, exited +122k before the crash, capital
protected); idempotent re-run appends 0. First real cycle: 2026-09-24, regime=bear
(drawdown −35.3% off the 1y high dominates even though price sits ~11% above
SMA200) → FLAT → defensive cash hold; equity 1,000,000 KRW (+0.00%).

**(2) Data-storage audit (answer to the owner).** YES, we already store latest
market data via `backtest/refresh_data.py` (live Upbit public API, read-only):
`data/krw_btc_1d.csv` (daily OHLCV, 3288 rows → 2026-09-25) and
`data/krw_btc_4h_full.csv` (4h OHLCV, ~19.7k rows), plus older 1m history. Fields:
time_utc + OHLC + volume. LIMITATION: `data/` is gitignored (not in the public
repo) and only refreshes when a cycle runs (~1/day). The daily bear strategy is
fully served by once-a-day cadence (1 closed daily candle/day); finer-grained
continuous accumulation (4h/1m/orderbook) would need a separate scheduler — see
report.txt for the plan/options. The new committed `market_data_daily.csv` gives
an auditable in-repo daily trail going forward.

best_config.json -> last_cycle=21.
