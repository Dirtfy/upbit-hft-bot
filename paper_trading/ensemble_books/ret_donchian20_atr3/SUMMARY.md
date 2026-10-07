# SHADOW ensemble book `ret_donchian20_atr3` (official=false)

공식 원장이 아님. 진화 탐색(research/evolution)에서 걸러진 후보를 동결해 forward로 굴리는 그림자 장부.
- launched: 2026-10-04T04:00:00 UTC, as of 2026-10-07T12:00Z
- strategy: `donchian[tf=1d,n_in=20,n_out=20,atr_k=3] | gate=none vt=0 band=0.0 switch=0`
- equity d0 (next-hour fill): 984,017 KRW (-1.60%)
- equity d5 (5h blind window): 984,017 KRW (-1.60%)
- position now: BTC 100%
- trades (d0): 1
- replay check: OK (recompute == logged history)
- selection evidence: Cycle 3-6 return strategy (not evolved). Only book passing the pre-registered survival rule on the 2025-01..2026-10 holdout: d0 CAGR +2.5%, d5 +4.3%, MDD 17.8%, Sharpe 0.32; B&H d5 -10.2%

## Trades (d0)

| time (UTC) | asset | side | price | KRW |
|---|---|---|---|---|
| 2026-10-04 04:00 | KRW-BTC | BUY | 115,328,000 | 1,000,000 |
