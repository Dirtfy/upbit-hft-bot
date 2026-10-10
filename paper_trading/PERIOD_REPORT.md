# Paper period report (all books)

Generated 2026-10-10T00:05Z by period_report.py (read-only, deterministic).
Period: 2026-09-24 .. 2026-10-24 (planned). Latest official candle: 2026-10-09. In progress: day 16 of ~31; numbers are interim.

| book | official | days | first..last | equity KRW | return | max DD | trades | note |
|---|---|---|---|---|---|---|---|---|
| official long_flat dd 20%/10% | **true** | 16 | 2026-09-24..2026-10-09 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 16/16 days |
| shadow exit dd 12.5%/5% | false | 16 | 2026-09-24..2026-10-09 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 16/16 days |
| ctrl_evo_cand3_failed_oos (d0) | false | 6 | 2026-10-04..2026-10-09 | 984,743 | -1.53% | 3.07% | 17 | d5 equity 984,347 KRW; launched 2026-10-04 |
| ret_donchian20_atr3 (d0) | false | 6 | 2026-10-04..2026-10-09 | 978,823 | -2.12% | 3.86% | 1 | d5 equity 978,823 KRW; launched 2026-10-04 |
| BTC buy-and-hold (benchmark) | false | 16 | 2026-09-24..2026-10-09 | 973,936 | -2.61% | 3.86% | 1 | bought at first candle open, never sold |

Official vs 12.5/5 decision divergences: 0 (identical decisions so far)

Reading guide:
- The ensemble books start 2026-10-04, so their returns cover fewer days than the official book.
- One month is far too short to separate skill from luck (Cycle 11 power analysis). Use this as an operations check, not as proof of edge.
- Max DD is measured on end-of-day equity from the 1,000,000 KRW start.

## Re-entry outlook (from BTC close 113,001,000 on 2026-10-09)

Lowest BTC daily close that, held from tomorrow on, would switch a FLAT book to long (regime.py: close > SMA200 AND within dd_exit of the 365-day high).

| book | dd_exit | needed by tomorrow | needed by 2026-10-24 | rise needed by 2026-10-24 |
|---|---|---|---|---|
| official 20%/10% | 10% | 156,449,700 | 152,562,600 | +35.0% |
| shadow 12.5%/5% | 5% | 165,141,350 | 161,038,300 | +42.5% |

The 365-day high 173,833,000 (2025-10-12) leaves the window on 2026-10-12. The prices above already account for highs leaving the window.

