# Paper period report (all books)

Generated 2026-10-12T00:05Z by period_report.py (read-only, deterministic).
Period: 2026-09-24 .. 2026-10-24 (planned). Latest official candle: 2026-10-11. In progress: day 18 of ~31; numbers are interim.

| book | official | days | first..last | equity KRW | return | max DD | trades | note |
|---|---|---|---|---|---|---|---|---|
| official long_flat dd 20%/10% | **true** | 18 | 2026-09-24..2026-10-11 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 18/18 days |
| shadow exit dd 12.5%/5% | false | 18 | 2026-09-24..2026-10-11 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 18/18 days |
| ctrl_evo_cand3_failed_oos (d0) | false | 8 | 2026-10-04..2026-10-11 | 985,273 | -1.47% | 3.07% | 17 | d5 equity 984,876 KRW; launched 2026-10-04 |
| ret_donchian20_atr3 (d0) | false | 8 | 2026-10-04..2026-10-11 | 981,970 | -1.80% | 3.86% | 1 | d5 equity 981,970 KRW; launched 2026-10-04 |
| BTC buy-and-hold (benchmark) | false | 18 | 2026-09-24..2026-10-11 | 977,065 | -2.29% | 3.86% | 1 | bought at first candle open, never sold |

Official vs 12.5/5 decision divergences: 0 (identical decisions so far)

Reading guide:
- The ensemble books start 2026-10-04, so their returns cover fewer days than the official book.
- One month is far too short to separate skill from luck (Cycle 11 power analysis). Use this as an operations check, not as proof of edge.
- Max DD is measured on end-of-day equity from the 1,000,000 KRW start.

## Re-entry outlook (from BTC close 113,364,000 on 2026-10-11)

Lowest BTC daily close that, held from tomorrow on, would switch a FLAT book to long (regime.py: close > SMA200 AND within dd_exit of the 365-day high).

| book | dd_exit | needed by tomorrow | needed by 2026-10-24 | rise needed by 2026-10-24 |
|---|---|---|---|---|
| official 20%/10% | 10% | 154,512,000 | 152,562,600 | +34.6% |
| shadow 12.5%/5% | 5% | 163,096,000 | 161,038,300 | +42.1% |

The 365-day high 173,833,000 (2025-10-12) leaves the window on 2026-10-12. The prices above already account for highs leaving the window.

