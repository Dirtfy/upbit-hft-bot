# Paper period report (all books)

Generated 2026-10-13T12:26Z by period_report.py (read-only, deterministic).
Period: 2026-09-24 .. 2026-10-24 (planned). Latest official candle: 2026-10-12. In progress: day 19 of ~31; numbers are interim.

| book | official | days | first..last | equity KRW | return | max DD | trades | note |
|---|---|---|---|---|---|---|---|---|
| official long_flat dd 20%/10% | **true** | 19 | 2026-09-24..2026-10-12 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 19/19 days |
| shadow exit dd 12.5%/5% | false | 19 | 2026-09-24..2026-10-12 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 19/19 days |
| ctrl_evo_cand3_failed_oos (d0) | false | 9 | 2026-10-04..2026-10-12 | 981,621 | -1.84% | 3.31% | 17 | d5 equity 981,237 KRW; launched 2026-10-04 |
| ret_donchian20_atr3 (d0) | false | 9 | 2026-10-04..2026-10-12 | 960,284 | -3.97% | 5.14% | 1 | d5 equity 960,284 KRW; launched 2026-10-04 |
| BTC buy-and-hold (benchmark) | false | 19 | 2026-09-24..2026-10-12 | 955,509 | -4.45% | 5.14% | 1 | bought at first candle open, never sold |

Official vs 12.5/5 decision divergences: 0 (identical decisions so far)

Reading guide:
- The ensemble books start 2026-10-04, so their returns cover fewer days than the official book.
- One month is far too short to separate skill from luck (Cycle 11 power analysis). Use this as an operations check, not as proof of edge.
- Max DD is measured on end-of-day equity from the 1,000,000 KRW start.

## Re-entry outlook (from BTC close 110,863,000 on 2026-10-12)

Lowest BTC daily close that, held from tomorrow on, would switch a FLAT book to long (regime.py: close > SMA200 AND within dd_exit of the 365-day high).

| book | dd_exit | needed by tomorrow | needed by 2026-10-24 | rise needed by 2026-10-24 |
|---|---|---|---|---|
| official 20%/10% | 10% | 153,063,000 | 152,562,600 | +37.6% |
| shadow 12.5%/5% | 5% | 161,566,500 | 161,038,300 | +45.3% |

The 365-day high 171,680,000 (2025-10-13) leaves the window on 2026-10-13. The prices above already account for highs leaving the window.

