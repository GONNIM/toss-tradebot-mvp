# A1 · 손실 자동 정지 수리 (1025-02)

- 승인: 2026-11-05 사용자 「1025-02 권고대로」 (계획 · ㉠ 매도만 허용 · ㉡ 그대로 둠 · ㉢ 그대로 둠)
- 검수: `docs/plans/biotech/fable-bundles/2026-11-05-1025-02-01.md` (조건부 GO · 막음 2) → `-02.md` (GO · 권고 5)

## 문제
- 하루 손실이 시드의 3% (`daily_loss_limit_pct` -0.03 × `seed_cap_krw` 100만 = 3만 원) 이하이면 Kill Switch 를 켜는 5초 잡이 있다.
- 하루 손익 계산(`backend/execution/audit.py` 의 옛 `daily_realized_pnl`)이 「오늘 매도 체결액 − 수수료」 합이라 늘 0 이상이었다. 그래서 발동할 수 없었다.
- sniper · watchlist 직접 주문 경로(`entry.py` · `exit.py`)는 `order_audit` 에 기록하지 않았다. 기록은 signal_router 경로 4곳뿐이었다.

## 고침 (PR · 서버 0.3.37)
1. 직접 주문 경로 기록: `record_direct_order` 가 진입(상태 검사 앞)과 청산 주문 결과를 `order_audit` 에 남긴다. 기록 실패는 WARNING 만 남기고 주문 흐름은 계속된다. `/execution` 화면과 Toss 미체결 대조(reconciler)도 이 주문을 보게 된다.
2. 하루 손익 (`daily_pnl_detail`): 오늘 청산된 `sniper_signal` 마다 짝 감사 행(매수 entry · 매도 exit)을 찾는다. 두 행 모두 filled · partial 일 때만 계산한다. q = min(매도 수량, 매수 수량). 손익 = 매도 평균가×q − 매도 수수료×q/매도 수량 − (매수 평균가×q + 매수 수수료×q/매수 수량).
3. 계산 불가: 감사 행 없음 · 매도 거부(REJECTED · ERROR) · 미체결(ACCEPTED) 매수 · 매도 수량 > 매수 수량. 계산 불가가 있으면 WARNING 로그와 텔레그램 알림을 보낸다. 같은 청산은 하루 1회(한국 날짜 + signal id · 메모리 · 재시작하면 다시 1회). Kill Switch 판단은 계산된 건만으로 한다.
4. 하루 경계: UTC 00:00 = 한국 09:00 · 매도 감사 행 `created_at` 기준. 한국 정규장 기준이고, 밤새 보유 뒤 다음 날 청산되면 다음 날 손익이다.
5. 오류 처리: 5초 잡은 조회 오류 시 발동하지 않는다(오작동 방지) · ERROR 로그 하루 1회. 매수 전 검사(`risk_budget` · signal_router 경로)는 조회 오류 시 매수를 막는다.
6. 시험: `backend/tests/discovery/test_daily_loss_stop.py` 11건 (끝까지 흐름 6회째 발동 · 이익만 · 부분 체결 · 수수료 · 감사 행 없음 알림 1회 · 거부 청산 · 수량 초과 · 어제 제외 · risk_budget 차단 · 직접 경로 기록 · 기록 실패 무해).

## 사용자 결정 (11/05)
- ㉠ Kill Switch 발동 뒤 봇의 매도만 허용 → 별도 PR (1105-02) · 실주문 허용 전 필수. 지금은 두 어댑터가 Kill Switch 켜짐을 주문 종류와 상관없이 막아, 발동 뒤 손절 매도도 막힌다(5초마다 `kill_switch_blocks_sell` 경고). 허용 뒤에도 발동 순간의 청산은 다음 5초 주기로 밀린다.
- ㉡ 계산 불가 시 신규 진입 차단 → 그대로 둠(알림만). 실주문 허용을 켜기 전에 다시 정한다.
- ㉢ force_close 운영 False → 그대로 둠. 실주문 허용 때 다시 본다.

## 알고 두는 것 (이번에 바꾸지 않음)
- 분모가 두 곳에서 다르다: 5초 잡은 `seed_cap_krw`, 매수 전 검사는 `total_equity_krw` × 0.7.
- 직접 진입은 매수 전에 하루 손익을 보지 않는다. 보호는 5초 잡뿐이라 최대 5초 창이 있다(방어 7 은 별도 결정).
- signal_router 경로 주문은 `sniper_signal` 이 없어 하루 손익 합계에 들어가지 않는다(지금 꺼짐).
- reconciler 는 Toss 미체결 행의 `total_fee` 를 갱신하지 않는다. 실주문에서 접수(ACCEPTED)로 시작한 주문은 수수료 0 으로 남아 손익이 실제보다 좋게 계산될 수 있다.
- 운영 DB 는 11/05 기준 `sniper_signal` 0행 · `order_audit` 0행이다(11/05 PO 확인). 실데이터 검증은 없고 시험으로만 검증했다.
- 화면 「오늘 손익」 숫자 표시는 이번 범위 밖이다(`broker-link.md`).
