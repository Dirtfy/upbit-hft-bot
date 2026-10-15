# Paper period report (all books)

Generated 2026-10-15T12:27Z by period_report.py (read-only, deterministic).
Period: 2026-09-24 .. 2026-10-24 (planned). Latest official candle: 2026-10-14. In progress: day 21 of ~31; numbers are interim.

| book | official | days | first..last | equity KRW | return | max DD | trades | note |
|---|---|---|---|---|---|---|---|---|
| official long_flat dd 20%/10% | **true** | 21 | 2026-09-24..2026-10-14 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 21/21 days |
| shadow exit dd 12.5%/5% | false | 21 | 2026-09-24..2026-10-14 | 1,000,000 | +0.00% | 0.00% | 0 | FLAT on 21/21 days |
| ctrl_evo_cand3_failed_oos (d0) | false | 11 | 2026-10-04..2026-10-14 | 980,855 | -1.91% | 3.38% | 17 | d5 equity 980,473 KRW; launched 2026-10-04 |
| ret_donchian20_atr3 (d0) | false | 11 | 2026-10-04..2026-10-14 | 959,323 | -4.07% | 5.24% | 2 | d5 equity 977,496 KRW; launched 2026-10-04 |
| BTC buy-and-hold (benchmark) | false | 21 | 2026-09-24..2026-10-14 | 950,984 | -4.90% | 5.59% | 1 | bought at first candle open, never sold |

Official vs 12.5/5 decision divergences: 0 (identical decisions so far)

Reading guide:
- The ensemble books start 2026-10-04, so their returns cover fewer days than the official book.
- One month is far too short to separate skill from luck (Cycle 11 power analysis). Use this as an operations check, not as proof of edge.
- Max DD is measured on end-of-day equity from the 1,000,000 KRW start.


## Operational integrity (period to date)

| check | result | note |
|---|---|---|
| official daily ledger | 21 candles, 0 duplicates, 0 gaps | 4 late (>2h): 2026-09-24, 2026-09-25, 2026-09-26, 2026-10-03 |
| shadow 12.5/5 daily ledger | 21 candles, 0 duplicates, 0 gaps | 1 late (>2h): 2026-10-03 |
| same data in both books | 0 close mismatches | |
| 4h candle trail | 129 candles in period, 0 gaps | |
| daemon outages (self-healed) | 10 real (last 2026-10-04), 6 logged false positives excluded; downtime upper bound ~32.4 h | no missed decision: ledgers above have no gaps |

Late records before the daemons existed (Cycles 22-24) were run by hand; the shadow book's launch backfill is excluded. A late record still uses the closed candle of its day, so decisions are unaffected.
## Re-entry outlook (from BTC close 110,338,000 on 2026-10-14)

Lowest BTC daily close that, held from tomorrow on, would switch a FLAT book to long (regime.py: close > SMA200 AND within dd_exit of the 365-day high).

| book | dd_exit | needed by tomorrow | needed by 2026-10-24 | rise needed by 2026-10-24 |
|---|---|---|---|---|
| official 20%/10% | 10% | 152,562,600 | 152,562,600 | +38.3% |
| shadow 12.5%/5% | 5% | 161,038,300 | 161,038,300 | +45.9% |

The 365-day high 169,514,000 (2025-10-26) leaves the window on 2026-10-26. The prices above already account for highs leaving the window.

