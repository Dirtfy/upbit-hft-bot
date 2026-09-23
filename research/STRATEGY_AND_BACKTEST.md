# BTC/KRW HFT Bot — Strategy Research & Backtest Report

Project: upbit-hft-bot · Data source: Upbit official API · Date: 2026-09-07
(Updated 2026-09-10 with the maker-entry upgrade + large-sample / walk-forward
paper-trading results — see §10, which supersedes the earlier optimism.)

> **UPDATE HEADLINE (2026-09-10):** With the approved maker-order upgrade and a
> **much larger, statistically meaningful sample (83 days / 193–236 trades)**,
> the strategy **loses money** (≈ **−4.0%**, naive annualized ≈ **−17% to −21%/yr**)
> and **0 of 864 parameter sets were profitable even in-sample**. The mean-
> reversion edge does **not** survive Upbit's fees. Recommendation: **do not
> pursue live trading with this strategy.** Full detail in §10.


---

## 1. Executive summary (read this first)

**The honest bottom line: naive high-frequency scalping of BTC/KRW on Upbit has
negative expected value after fees, and the best strategy we could construct is
only marginally break-even — it does *not* justify committing live capital
yet.**

- Upbit charges **0.05% per side (0.10% round-trip)** on the KRW market, and —
  unlike Binance — offers **no maker rebate** (maker fee == taker fee). This is
  the dominant cost and it is unavoidable.
- Our mean-reversion signal genuinely predicts short-term reversals (at zero
  cost it returns **+5.5%** over the test window with a **70% win rate**,
  beating buy-and-hold). But the **per-trade gross edge (~7.5 bps) is smaller
  than the round-trip cost (~10 bps + slippage)**, so realistic net results
  hover around break-even.
- The best net configuration returns **+0.4% to +0.6% over ~14 days** on only
  17–39 trades — statistically fragile — while simply **holding BTC returned
  +2.7%** over the same period with far less operational risk.

**Recommendation:** ship the bot in **paper-trading mode**, run it forward on
live data for several weeks, and only consider a *minimal* live test (well under
the 1,000,000 KRW cap) if forward paper results confirm a positive expectancy
over 100+ trades. See §7. (Note: the provided account currently holds 0 KRW, so
live trading is not possible until it is funded — which we do **not** recommend
until the above bar is met.)

---

## 2. Why "HFT" here means high-frequency *scalping*, not micro-HFT

True HFT (sub-millisecond, co-located, order-book microstructure) is not
achievable for a retail Upbit account:

| Constraint | Reality on Upbit REST |
|---|---|
| Latency | ~50–200 ms round-trip from a normal host; no co-location |
| Rate limits | ~8–30 requests/sec depending on endpoint group |
| Order types | Spot only; **no margin, no shorting** on the retail KRW market |
| Fees | 0.05%/side flat, **no maker rebate** |

So the tradable niche is **long-only, short-horizon (1-minute) mean-reversion
scalping**: enter when price deviates sharply below its local mean, exit on
reversion / take-profit / stop / timeout. Many small trades, tight risk — high
*frequency* relative to swing trading, but bounded by REST realities.

## 3. Strategies considered

| Strategy | Verdict for Upbit BTC/KRW |
|---|---|
| Market making (quote both sides, earn spread) | ✗ Needs maker rebate or captured spread > 0.10%; Upbit spread on BTC is typically 1 tick (~1–2 bps) << round-trip fee. Not viable. |
| Momentum / breakout scalping | ✗ 1-min breakouts on BTC/KRW mean-revert as often as they continue; fees dominate. |
| Statistical arbitrage (KRW "kimchi premium" vs. offshore) | Promising but out of scope: needs a second venue + FX + transfer logistics; higher capital. Flagged for future work. |
| **Bollinger / z-score mean-reversion (long-only)** | **✓ chosen** — the only signal with a demonstrable gross edge on the data. |

## 4. The candidate strategy (implemented)

Rolling window of `window` 1-minute closes → mean & std → z-score of the latest
close. Long-only.

- **Entry:** z ≤ −`entry_z` (sharp dip below local mean) **and** volatility
  above a floor (`min_std_bps`, to skip dead tape).
- **Exit (whichever first):** revert to mean (z ≥ `exit_z`), **take-profit**
  (`take_profit_pct`), **stop-loss** (`stop_loss_pct`), or **timeout**
  (`max_hold` bars, to avoid bag-holding).

Code: `src/strategy.py` (pure function of the price window; identical logic runs
in backtest and live).

## 5. Backtest methodology (kept deliberately honest)

- **Data:** 20,000 Upbit 1-minute KRW-BTC candles, 2026-08-23 → 2026-09-06
  (~14 days), pulled from the official API (`backtest/fetch_data.py`).
- **No lookahead:** the signal for bar *t* is computed from closes up to *t*;
  the fill is simulated at bar *t+1*'s open.
- **Costs:** 0.05%/side fee on notional at each fill + configurable slippage.
- **Exposure:** capped at 1,000,000 KRW notional, matching the live limit.
- **Baseline:** buy-and-hold over the same window (+2.70%).

Engine: `backtest/backtest.py`. Reproduce with:
```
cd backtest && python3 fetch_data.py && python3 backtest.py --data ../data/krw_btc_1m.csv --grid
```

## 6. Results

**6a. Default naive params (window=20, z=2.0) — the trap most bots fall into:**

```
trades=269  win=27.5%  ret=-31.76%  bh=+2.70%  PF=0.12  maxDD=31.92%
```
Overtrading + fees = catastrophic. This is the expected fate of "just scalp the
dips" bots.

**6b. Fee-sensitivity diagnostic (best config) — isolates signal vs. cost:**

```
fee=0.000%/side slip=0bp  -> ret=+5.52%  win=69.9%  PF=1.97   (signal has a real edge)
fee=0.000%/side slip=2bp  -> ret=+2.65%  win=65.8%  PF=1.40
fee=0.050%/side slip=0bp  -> ret=-1.78%  win=61.6%  PF=0.78   (fees flip it negative)
fee=0.050%/side slip=2bp  -> ret=-4.57%  win=47.9%  PF=0.51
fee=0.050%/side slip=5bp  -> ret=-8.54%  win=32.9%  PF=0.27
```
Conclusion: **the edge is real but ~the same size as trading costs.** Whether it
nets positive depends entirely on execution quality (getting near-maker fills,
minimizing slippage).

**6c. Best realistic configs (fee=0.05%/side, slip=1 bp ≈ patient maker fills):**

```
W=90  eZ=4.0 SL=0.008 TP=0.012 MH=60 | trades=17  win=64.7%  ret=+0.55%  PF=1.34  maxDD=1.24%
W=120 eZ=3.0 SL=0.012 TP=0.012 MH=60 | trades=39  win=59.0%  ret=+0.36%  PF=1.05  maxDD=2.73%   <-- chosen default
```
Positive, low drawdown — but small and fragile. 17 trades is far too few to
trust a PF; the 39-trade config is more credible but its PF ~1.05 is barely
above noise. **Both underperform buy-and-hold (+2.70%) over this window.**

We deliberately chose the more trade-dense (W=120) config as the shipping
default: more trades = more forward-testing signal, and its behaviour is less
likely to be a curve-fit artifact.

## 7. What would have to be true before going live

1. **Forward paper test:** run `src/bot.py` (paper mode) for ≥ 3–4 weeks and
   accumulate ≥ 100 trades. Require net-positive PnL *after* modelled fees and a
   profit factor comfortably > 1.1.
2. **Execution upgrade:** replace market-order entries with **limit (maker)
   entries** to avoid paying the spread — the diagnostic shows this is the
   difference between negative and positive. (The client already supports
   `buy_limit`/`sell_limit`; wiring maker entries into the loop with fill polling
   is the top follow-up task.)
3. **Then** a minimal live test — e.g. 50,000–100,000 KRW per trade, far under
   the 1,000,000 KRW cap — with the kill switch armed, before any scaling.

## 8. Limitations & risks (stated plainly)

- Only ~14 days of data; one market regime. Not enough to certify an edge.
- Backtest fills are modelled, not real; live slippage on market orders can be
  worse than 1 bp, which the diagnostic shows would erase the edge.
- Grid search over one window risks curve-fitting; treat §6c as *hypotheses to
  forward-test*, not proven parameters.
- Crypto is volatile and can gap through stops; the stop-loss limits but does
  not eliminate loss on a fast move.

## 10. Maker upgrade + large-sample paper trading (2026-09-10) — the verdict

The owner approved two follow-ups: (1) upgrade entries from market to **limit
(maker) orders + fill polling**, and (2) run **paper trading** to a
statistically meaningful sample and report cumulative P/L + an annualized
estimate. Both are done. Because a turn can't span 3–4 weeks of wall-clock
time, "paper trading" was run as a **forward simulation over a large
out-of-sample historical window** (a stronger test than 3–4 calendar weeks: it
yields 193+ trades immediately). The identical maker-fill logic also now runs in
the live bot, so live-forward paper mode behaves the same.

**Maker fill model** (`backtest/backtest_maker.py`, deliberately conservative):
- Entry = resting LIMIT buy at the signal bar's close (join the bid, pay no
  spread). Fills **only if a later bar trades down to it**; cancelled after 3
  candles if unfilled. Maker fills pay no slippage — but still Upbit's 0.05%
  fee (no maker rebate).
- Take-profit = maker LIMIT sell (fills only if price trades up to it).
- Stop-loss / mean-revert / timeout = taker MARKET exits with 1.5 bps slippage.
- If a bar spans both stop and target, the **stop** is assumed to fill first.

**Data:** 120,000 Upbit 1-minute KRW-BTC candles, **2026-06-15 → 2026-09-07
(~83 days)** — ~69 days of which are out-of-sample vs. the original window.

**10a. Cumulative paper P/L (shipping default params, per_trade 200k of 1M):**

| Sample | Days | Trades | Win% | PF | Cumulative P/L | Return | Buy&Hold |
|---|---|---|---|---|---|---|---|
| Full 83d | 83.3 | 236 | 50.4% | 0.55 | **−38,906 KRW** | −3.89% | +7.81% |
| Out-of-sample 69d | 68.8 | 193 | 48.2% | 0.47 | **−40,015 KRW** | −4.00% | +4.89% |

The tell: **take-profit fired only once**; positions exit via timeout/mean-
revert, and the **average loss (−760 KRW) is ~2× the average win (+390 KRW)**.
Winning slightly more than half the time but losing twice as much per loss = a
losing system after fees.

**10b. Estimated annualized earning rate (as requested, heavily caveated):**

Naively extrapolating the out-of-sample −4.00% over 68.8 days:
- compounded: **≈ −19.5%/yr**  ·  linear: **≈ −21.2%/yr**
- (full-sample basis gives ≈ −16% to −17%/yr)

**Caveat — do not treat this as a forecast.** It is a naive extrapolation from a
single ~83-day window in one market regime; realized results would vary widely
and could be worse (live slippage, partial fills, downtime). The one robust
conclusion is the **sign: negative.** There is no positive annualized rate to
project here.

**10c. Walk-forward validation — why we're confident it's not just bad tuning:**

Optimised over an **864-config grid** on the first 60% of the data (TRAIN) and
evaluated on the untouched last 40% (TEST):
- **0 of 864 configurations were profitable even on TRAIN** (best profit factor
  0.77 — still a loss). Consequently 0 were profitable on TEST.
- A real edge would leave a clear cluster of TRAIN-profitable configs that stay
  positive on TEST. We found none. The marginal +0.5% from the original 14-day
  grid (§6c) was small-sample noise.

**10d. Conclusion & recommendation:** the 1-minute long-only mean-reversion
scalping strategy has a genuine *gross* signal but **no net edge after Upbit's
0.10% round-trip fee**, confirmed on a large out-of-sample set and by walk-
forward. **Recommend against committing any live capital to this strategy.**
The maker-entry code and paper harness remain in place and reusable; the honest
next move is a *different* source of edge (e.g. cross-exchange "kimchi premium"
stat-arb), not further tuning of this one.

## 11. Files

- `backtest/fetch_data.py` — historical data downloader (Upbit API)
- `backtest/backtest.py` — original market-fill backtest + grid search
- `backtest/diagnose.py` — fee/slippage sensitivity diagnostic
- `backtest/grid2.py` — targeted parameter search
- `backtest/backtest_maker.py` — **maker-fill paper-trading engine** (§10)
- `backtest/walkforward_maker.py` — **train/test walk-forward validation** (§10)
- `src/strategy.py`, `src/bot.py` — the strategy + live bot (maker entries)
- `data/krw_btc_1m.csv`, `data/krw_btc_1m_long.csv` — datasets (gitignored)
