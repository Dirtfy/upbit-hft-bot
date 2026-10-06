# SHADOW ensemble book `ctrl_evo_cand3_failed_oos` (official=false)

공식 원장이 아님. 진화 탐색(research/evolution)에서 걸러진 후보를 동결해 forward로 굴리는 그림자 장부.
- launched: 2026-10-04T04:00:00 UTC, as of 2026-10-06T12:00Z
- strategy: `tsmom[tf=4h,days=90]xbull 0.25/side 0.0 + donchian[tf=4h,n_in=10,n_out=20,atr_k=2]xbull 0.5/side 0.75 + meanrev[tf=1d,rsi_n=3,lo=10,hi=70,trend=1]xbull 0.25/side 0.75 + rotation[days=14,top_k=3,every=1]xbull 0.5/side 0.0 | gate=none vt=0.6 band=0.0 switch=1`
- equity d0 (next-hour fill): 1,019,028 KRW (+1.90%)
- equity d5 (5h blind window): 1,017,361 KRW (+1.74%)
- position now: BTC 16%, SOL 11%, ADA 11%
- trades (d0): 8
- replay check: OK (recompute == logged history)
- selection evidence: CONTROL, NOT a survivor: best evolved ensemble of run 2026-10-04T03:36:32Z (IS Sharpe 2.16) FAILED the holdout (d5 CAGR -6.2%). Tracked forward to measure overfitting, not as a recommendation.

## Trades (d0)

| time (UTC) | asset | side | price | KRW |
|---|---|---|---|---|
| 2026-10-04 04:00 | KRW-BTC | BUY | 115,328,000 | 166,700 |
| 2026-10-04 04:00 | KRW-SOL | BUY | 164,100 | 111,100 |
| 2026-10-04 04:00 | KRW-DOGE | BUY | 126 | 111,100 |
| 2026-10-04 04:00 | KRW-ADA | BUY | 331 | 111,100 |
| 2026-10-06 00:00 | KRW-BTC | SELL | 115,998,000 | 968 |
| 2026-10-06 00:00 | KRW-SOL | BUY | 163,300 | 542 |
| 2026-10-06 00:00 | KRW-DOGE | SELL | 130 | 114,627 |
| 2026-10-06 00:00 | KRW-ADA | SELL | 366 | 11,748 |
