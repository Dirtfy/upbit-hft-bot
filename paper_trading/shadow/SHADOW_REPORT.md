# 그림자 리플레이(SHADOW REPLAY) — 반사실(COUNTERFACTUAL) 결과

> **⚠ 공식 모의투자 원장이 아님.** 공식 원장(`paper_log.jsonl`/`JOURNAL.md`/`SUMMARY.md`, 1,000,000 KRW, FLAT)은 이 리플레이로 전혀 변경되지 않는다. 여기 숫자는 '장세가 바뀌었다면' 가정의 엔진 경로 검증용이다.

*생성: `paper_trading/shadow/shadow_replay.py` · 2026-10-02 10:35 UTC · 실제 엔진 코드(`live_engine.execute` + `RiskManager`) DRY-RUN, 네트워크/키/주문 없음. 한도 그대로: 노출 1,000,000 · 1회 200,000 · 일손실 50,000 KRW · 수수료 0.05%/편도 · 슬리피지 1.5bp/편도.*

| 시나리오 | 구간 | 결정 수 | 매수/매도 | 승 | 실현손익(수수료·슬리피지 후) | 수수료 | 슬리피지 | 최종 평가액 | 발동한 리스크 경로 |
|---|---|---|---|---|---|---|---|---|---|
| A 장세 강제(실제 4h 시세) | 2026-08-27→2026-10-02 | 216 | 12/12 | 3 | +11,668 KRW | 2,406 | 722 | 1,011,668 | — |
| B 리스크 스트레스(합성 충격 포함) | 2026-09-27→2026-09-30 | 13 | 5/5 | 1 | -61,510 KRW | 969 | 291 | 938,490 | exit_allowed_under_halt×1, halt_blocked_entry×2, kill_switch_tripped×1, stale_blocked_entry×1 |
| C 실제 장세(일봉 2023~) | 2023-01-01→2026-09-27 | 1366 | 10/10 | 3 | +224,827 KRW | 2,113 | 634 | 1,224,827 | — |

- 최대 1회 진입 금액: forced_regime 200,000, risk_stress 200,000, historical 200,000 KRW (한도 200,000); 최대 미결제 노출: forced_regime 200,000, risk_stress 200,000, historical 200,000 KRW (상한 1,000,000).
- 시나리오별 결정 단위 원장: `shadow_<scenario>.jsonl` (모든 레코드 `counterfactual: true`).
