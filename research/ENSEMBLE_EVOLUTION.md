# Return-seeking strategies, ensembles and walk-forward evolution (Cycle 31)

Owner missions of 2026-10-04: (1) look for strategies that aim for **return**, not only
bear-market defense; (2) "mix several strategies and evolve them with backtests,
RL-style". RESEARCH / PAPER ONLY: public read-only candles, no keys, no account, no
orders. The official 20%/10% book and the 12.5%/5% shadow book are untouched.

## 1. What the repo already had

Besides the dd 20%/10% regime filter (`long_flat`, defensive) and the early HFT
scalping (lost money after fees), the repo **already had return-seeking strategies**:

| strategy | where | status before this cycle |
|---|---|---|
| Daily Donchian 20/20 breakout + ATR(14) trailing stop k=3 | `src/donchian_bot.py`, Cycles 3-6 | best OOS result of Cycles 3-6 (test CAGR +41%, Calmar 2.14) and paper-run in Cycles 8-14, then superseded by the owner's bear-market feature (Cycle 18) |
| 4h Donchian 30/20 | same, Cycle 7 | co-best on 4h |
| Volatility-target sizing overlay (2%/day) | Cycle 8 | optional overlay |
| SMA cross 3/30 (daily), 10/30 (4h) | `backtest/swing_backtest.py` | 4h version rejected (overfit) |
| `breakout` / `breakout_regime` modes | `src/bear_strategy.py` | available, not the official mode |

None of these were in a running paper book when this cycle started.

## 2. Literature (verified citations)

- **Time-series momentum / trend following.** Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, JFE 104(2) — [doi:10.1016/j.jfineco.2011.11.003](https://doi.org/10.1016/j.jfineco.2011.11.003). Hurst, Ooi & Pedersen (2017), *A Century of Evidence on Trend-Following Investing*, JPM 44(1) — [doi:10.3905/jpm.2017.44.1.015](https://doi.org/10.3905/jpm.2017.44.1.015). Faber (2007), *A Quantitative Approach to Tactical Asset Allocation*, J. Wealth Mgmt 9(4) — [doi:10.3905/jwm.2007.674809](https://doi.org/10.3905/jwm.2007.674809).
- **Crypto momentum.** Liu & Tsyvinski (2021), *Risks and Returns of Cryptocurrency*, RFS 34(6) — [doi:10.1093/rfs/hhaa113](https://doi.org/10.1093/rfs/hhaa113) (strong TS momentum in BTC/ETH/XRP). Liu, Tsyvinski & Wu (2022), *Common Risk Factors in Cryptocurrency*, JF 77(2) — [doi:10.1111/jofi.13119](https://doi.org/10.1111/jofi.13119) (cross-sectional momentum factor).
- **Technical rules in crypto.** Corbet, Eraslan, Lucey & Sensoy (2019), FRL 31 — [doi:10.1016/j.frl.2019.04.027](https://doi.org/10.1016/j.frl.2019.04.027). Grobys, Ahmed & Sapkota (2020), FRL 32 — [doi:10.1016/j.frl.2019.101396](https://doi.org/10.1016/j.frl.2019.101396) (MA rule works on alts, weaker on BTC). Detzel, Liu, Strauss, Zhou & Zhu (2021), Financial Management 50(1) — [doi:10.1111/fima.12310](https://doi.org/10.1111/fima.12310).
- **Volatility breakout.** Williams (1999), *Long-Term Secrets to Short-Term Trading*, Wiley (practitioner origin; not peer-reviewed). Gerritsen, Bouri, Ramezanifar & Roubaud (2020), FRL 34 — [doi:10.1016/j.frl.2019.08.011](https://doi.org/10.1016/j.frl.2019.08.011) (trading-range breakout beat buy-and-hold on daily BTC net of costs).
- **Mean reversion.** Connors & Alvarez (2008), *Short Term Trading Strategies That Work* (RSI(2); practitioner). Bollinger (2001), *Bollinger on Bollinger Bands*. Zaremba et al. (2021), *Up or Down? Short-term Reversal, Momentum, and Liquidity Effects in Cryptocurrency Markets* (reversal concentrated in illiquid coins; liquid coins like BTC show momentum; venue not re-verified).
- **Volatility targeting.** Moreira & Muir (2017), *Volatility-Managed Portfolios*, JF 72(4) — [doi:10.1111/jofi.12513](https://doi.org/10.1111/jofi.12513). Harvey et al. (2018), *The Impact of Volatility Targeting*, JPM 45(1) — [doi:10.3905/jpm.2018.45.1.014](https://doi.org/10.3905/jpm.2018.45.1.014).
- **Pairs / relative value.** Gatev, Goetzmann & Rouwenhorst (2006), RFS 19(3) — [doi:10.1093/rfs/hhj020](https://doi.org/10.1093/rfs/hhj020). Tadi & Witzany (2025), *Copula-Based Trading of Cointegrated Cryptocurrency Pairs*, Financial Innovation 11 — [doi:10.1186/s40854-024-00702-7](https://doi.org/10.1186/s40854-024-00702-7).
- **Backtest overfitting.** Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, JPM 40(5) — [doi:10.3905/jpm.2014.40.5.094](https://doi.org/10.3905/jpm.2014.40.5.094). Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*, J. Comp. Finance 20(4) — [doi:10.21314/JCF.2016.322](https://doi.org/10.21314/JCF.2016.322). Harvey & Liu (2015), *Backtesting*, JPM 42(1) — [doi:10.3905/jpm.2015.42.1.013](https://doi.org/10.3905/jpm.2015.42.1.013).
- **Evolutionary search.** Allen & Karjalainen (1999), *Using genetic algorithms to find technical trading rules*, JFE 51(2) — [doi:10.1016/S0304-405X(98)00052-X](https://doi.org/10.1016/S0304-405X(98)00052-X): GA-found rules did **not** beat buy-and-hold after costs out of sample. Our result below repeats this.

Two caveats from the literature: much of the published crypto evidence is in-sample-heavy and pre-2022; and short-horizon mean reversion is weak in liquid coins such as BTC.

## 3. Design (`research/evolution/`)

- **Data.** Public 1h candles for KRW-BTC, ETH, XRP, SOL, DOGE, ADA (`data_1h.py`, incremental, gitignored `data/1h/`). Daily (00:00 UTC) and 4h bars are resampled from the same hourly grid, so all timeframes share one clock.
- **Sleeves (strategy families)**, long-only spot, with a discrete parameter grid for each:
  - `hold`: always long BTC. With a gate, this is exactly the official `long_flat`.
  - `tsmom`: TS momentum on 1d/4h/1h.
  - `donchian`: breakout + ATR trail, 1d/4h.
  - `volbreak`: Larry Williams k-breakout, triggered **intraday from 1h bars** and exited at the next 00:00 UTC.
  - `meanrev`: RSI(n) with an optional 200d trend filter, 1d/4h/1h.
  - `rotation`: dual-momentum top-k over the 6 coins.
  - `pairs`: ETH/BTC z-score long-only switch.
- **Ensemble (genome).** Weights in {0, .25, .5, .75, 1} per sleeve, normalised so gross exposure is ≤ 1. Overlays:
  - optional **regime switching**, with separate weights for "BTC > SMA200" and "otherwise";
  - optional **bear gate**, the repo's dd 20/10 or 12.5/5 filter via `src/regime.py`;
  - **vol targeting** on 20d BTC realised vol;
  - a **rebalance band** to cut turnover.
- **Simulator.** A signal from a bar closing at hour t fills at the open of hour t+delay.
  - Two fills are always reported: **d0** = next-bar open, and **d5** = the repo's 5h blind window (`config.MAX_BLIND_HOURS`).
  - Cost is **0.05% fee + 0.05% slippage per side**.
  - Equity is marked daily. Sharpe uses daily returns × √365.
- **Search: a (μ+λ) genetic algorithm.** Pop 40, 20 generations, elitism, tournament selection, uniform crossover, and grid-neighbour mutation, seeded with the textbook configurations.
  - **Why a GA and not a bandit or a real RL agent:** it is the simplest loop that does "propose → backtest → keep the best → vary". A deep RL policy would need far more data than about 7 years of one market, cannot be trained without numpy on the host, and is hard to audit.
  - A discrete grid also keeps the trial count countable, which the deflated Sharpe ratio needs.
  - Bandit allocation was not used. It needs a stream of independent rewards, and here the sub-strategies are strongly correlated, since nearly all of them are long BTC.
- **Overfitting controls:**
  1. **Holdout 2025-01-01 → now is physically absent** during every search: the search `Market` is loaded with `end=HOLDOUT_START`, and a test asserts this.
  2. **Walk-forward:** evolve on 2018 → Y and score year Y, for Y in 2021–2024. The stitched result is the WFO-OOS record.
  3. **Robust fitness:** for both d0 and d5, take mean − 0.5·std of the Sharpe over 3 train sub-periods, then average the two.
  4. **Every distinct configuration is counted**, and the **deflated Sharpe ratio** is reported.
  5. **The survival rule was written in code before the holdout ran:** WFO-OOS Sharpe > 0, holdout CAGR > 0 at both d0 and d5, and holdout MDD < buy-and-hold's.
- **Token-free.**
  - `run_evolution.sh maybe` is called from the 4h daemon tick, which the host cron keeps alive. It spawns a detached run when the last one is more than 7 days old.
  - Each run uses a new seed and counts trials cumulatively across runs.
  - Results go to `research/evolution/results/{RESULTS.md,latest.json,history.jsonl}`.

## 4. Results (run 2026-10-04, data to 2026-10-04 03:00Z; 3,463 distinct configs, +97 in a smoke test)

Holdout = 2025-01-01 .. 2026-10-04 (about 21 months, a down market for BTC).

| book | IS CAGR (d5) | IS MDD | IS Sharpe | HOLDOUT CAGR d0 | HOLDOUT CAGR d5 | HO MDD | HO Sharpe | HO trades |
|---|---|---|---|---|---|---|---|---|
| buy & hold BTC | +32.6% | 86.9% | 0.77 | −10.2% | −10.2% | 50.0% | −0.09 | 1 |
| official dd 20/10 | +28.0% | 50.0% | 0.96 | −4.2% | −3.8% | 23.9% | −0.14 | 4 |
| shadow dd 12.5/5 | +40.3% | 31.2% | 1.41 | −2.9% | −3.6% | 23.7% | −0.15 | 4 |
| Donchian 20/20 + ATR3 (Cycle 6, not evolved) | +53.1% | 66.5% | 1.22 | **+2.5%** | **+4.3%** | **17.8%** | **0.32** | 19 |
| evolved cand 1 | +95.0% | 26.3% | 2.18 | −7.8% | −11.5% | 28.2% | −0.52 | 894 |
| evolved cand 2 | +92.0% | 28.1% | 2.20 | −4.7% | −9.1% | 26.9% | −0.38 | 510 |
| evolved cand 3 | +69.7% | 23.2% | 2.16 | −2.5% | −6.2% | 21.9% | −0.28 | 688 |
| 1/N textbook ensemble (no search) | +52.2% | 65.0% | 1.30 | −2.4% | −2.7% | 23.9% | −0.05 | 655 |

Walk-forward OOS (2021–2024, stitched, d5):

| book | CAGR | MDD | Sharpe |
|---|---|---|---|
| evolved winners | +15.6% | 46.2% | 0.67 |
| buy and hold | +44.4% | 74.2% | 0.95 |
| official dd 20/10 | +15.3% | 50.0% | 0.60 |
| 12.5/5 | +36.5% | 31.2% | 1.26 |
| Donchian 20/20 + ATR3 | +46.0% | 42.5% | 1.19 |

The 12.5/5 and Donchian parameters were themselves chosen earlier on data that overlaps these years, so their WFO numbers are flattering.

**Verdict.**
- **The evolved ensembles do not beat the simple baselines after costs.**
  - In-sample they look excellent (Sharpe about 2.2, MDD about 25%).
  - Walk-forward they are mediocre (Sharpe 0.67), and on the untouched holdout all three lose money. None meets the survival rule.
  - Deflated Sharpe showed ≈1.00 even so. It corrects for the number of trials, but not for a regime change or for correlated trials. That is why the holdout, not DSR, is the decision gate.
- The only book that made money on the holdout under both fills is the repo's old **Donchian 20/20 + ATR3** (not evolved).
- Intraday sleeves die on costs: 1h RSI mean reversion turned over about 400×/yr and returned −16% to −41% CAGR on the holdout.
- Of the sleeves, the ETH/BTC pairs switch suffered most: ETH kept underperforming BTC.
- A textbook coin rotation (30d, top-2, weekly) was positive on the holdout on its own (d5 +8.0% CAGR, MDD 36%). But its in-sample MDD was 82%, and I saw that number while building the lab, so it is a peeked result, not a clean OOS one. It was not launched.

## 5. Shadow books launched (`paper_trading/ensemble_books/`, official=false)

| book | why | evidence |
|---|---|---|
| `ret_donchian20_atr3` | return-seeking; the only configuration that passed the pre-registered survival rule on the holdout | holdout d5 +4.3% CAGR, MDD 17.8%, vs buy-and-hold −10.2% |
| `ctrl_evo_cand3_failed_oos` | **control, not a recommendation**: the best evolved ensemble, tracked forward to measure overfitting | IS Sharpe 2.16 → holdout −6.2% |

- Both books launched 2026-10-04 04:00 UTC with 1,000,000 KRW, capped at 1,000,000 KRW, using the same costs and the d0/d5 fills.
- `ensemble_book.py` runs in the 4h daemon tick. It recomputes each book deterministically from launch and appends one record per closed UTC day.
- Any future evolved candidate that passes `SURVIVE` is **auto-promoted** into a new frozen book (at most 3), with no leader turn needed.
- The side-by-side table of all books is `paper_trading/ensemble_books/COMPARE.md`.

Reproduce: `python3 research/evolution/data_1h.py && python3 research/evolution/evolve.py`
(about 4 min). Tests: `python3 tests/test_evolution.py`.
