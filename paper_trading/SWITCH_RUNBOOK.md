# Runbook: switching the official exit rule 20%/10% → 12.5%/5%

Prepared in Cycle 40 (2026-10-13) for the ~10/24 decision. **Do nothing here
without the owner's explicit approval.** Paper only; no live trading is implied.

## What changes
1. `src/config.py` `BEAR`: `dd_enter=0.125`, `dd_exit=0.05`. Nothing else in the
   strategy changes. Keep the decision on the **daily close** (Cycle 39: a 4h-checked
   breaker whipsaws).
2. The guards that pin the old rule (they exist to stop an *unapproved* switch).
   Update their expected value in the same commit:
   - `tests/test_exit_sweep.py`
   - `tests/test_exit_cross_coin.py`
   - `tests/test_exit_4h_stress.py`
   - `tests/test_shadow_exit_book.py` ("official records carry their breaker params")

## What does NOT change
- **The official ledger stays continuous.** It is not reset. Since Cycle 40 every
  official record carries `params`, so the record after the switch shows the new
  rule and every record before it shows 20/10. Records without `params` are 20/10.
- **Labels follow the ledger automatically.** This covers the COMPARE.md headline,
  the ensemble COMPARE table and PERIOD_REPORT, so no label edits are needed.
- **Daemons need no restart.** Each tick runs a fresh process, so the next 00:05 UTC
  paper tick uses the new config.

## Timing and immediate effect
- Commit the switch at any time between ticks. The 00:05 UTC tick that follows is
  the first decision under 12.5/5.
- Both rules read **bear** today, and both books are FLAT. The switch causes no
  trade. The book would go long only once BTC holds above SMA200 and within 5% of
  its 365-day high (Cycle 36 outlook).

## The shadow book after a switch (owner choice)
After a switch the shadow (12.5/5) duplicates the official book. Options:
- **retire it.** Stop calling `shadow_book.py` from the paper daemon tick and keep
  its files as the record of the trial period.
- **flip it to the old rule.** Set `OVERRIDE` to 20/10, with a new `BOOK` name and a
  fresh directory. The old rule then keeps running as a control.

## Evidence summary (see research/RESEARCH_LOG.md)
- maxDD cut is robust. It holds in the BTC backtest (46.7% → 28.5%), over 13/13
  start dates, in walk-forward, on 5/5 other coins (Cycle 37) and at 6/6 fill
  hours (Cycle 39).
- The return edge holds on BTC at every fill hour but on only 1/5 other coins,
  so do not count on it.
- The forward paper period cannot discriminate between the rules: 0 divergences,
  and both books are FLAT (Cycle 36).
