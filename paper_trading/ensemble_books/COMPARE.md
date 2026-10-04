# All paper books side by side

Generated 2026-10-04T03:40Z by ensemble_book.py. Only the first row is the OFFICIAL book; everything else is official=false.

| book | official | equity KRW | return | position | as of |
|---|---|---|---|---|---|
| official long_flat dd 20%/10% | **true** | 1,000,000 | +0.00% | FLAT | candle 2026-10-03 |
| shadow exit dd 12.5%/5% | false | 1,000,000 | +0.00% | FLAT | candle 2026-10-03 |
| ret_donchian20_atr3 (d0 / d5) | false | 1,000,000 / 1,000,000 | +0.00% / +0.00% | FLAT (cash) | waiting for first closed hour after launch |
| ctrl_evo_cand3_failed_oos (d0 / d5) | false | 1,000,000 / 1,000,000 | +0.00% / +0.00% | FLAT (cash) | waiting for first closed hour after launch |

Ensemble books start at their own launch time (not 2026-09-24), so compare returns over the same dates only from the ensemble launch onward.

- `ret_donchian20_atr3`: donchian[tf=1d,n_in=20,n_out=20,atr_k=3] | gate=none vt=0 band=0.0 switch=0
- `ctrl_evo_cand3_failed_oos`: tsmom[tf=4h,days=90]xbull 0.25/side 0.0 + donchian[tf=4h,n_in=10,n_out=20,atr_k=2]xbull 0.5/side 0.75 + meanrev[tf=1d,rsi_n=3,lo=10,hi=70,trend=1]xbull 0.25/side 0.75 + rotation[days=14,top_k=3,every=1]xbull 0.5/side 0.0 | gate=none vt=0.6 band=0.0 switch=1
