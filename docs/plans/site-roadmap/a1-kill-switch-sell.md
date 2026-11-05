# A1 · Kill Switch 켜진 뒤 보유 종목 매도 허용 (1105-02)

- 승인: 2026-11-05 사용자 「1105-02 권고대로 · ㉯ 적용」 (계획 · ㉮ A 체크 칸 · ㉯ 는 별도 1105-03)
- 검수: `docs/plans/biotech/fable-bundles/2026-11-05-1105-02-01.md` (조건부 GO · 막음 1) → `-02.md` (GO · 권고 3)
- 앞 일: `a1-daily-loss-stop.md` (1025-02 · 손실 자동 정지 수리 · ㉠)

## 문제
- 하루 손실 한도로 Kill Switch 가 켜지면 두 어댑터(`paper_adapter.py` · `toss_adapter.py`)의 `submit_order` 가 주문 종류를 가리지 않고 `KillSwitchActive` 를 냈다.
- 그래서 정지 뒤에 보유 종목의 손절·추적 매도까지 막혔다. 5초마다 `kill_switch_blocks_sell` 경고만 반복되고 포지션은 남았다.
- 손실을 멈추려고 켠 장치가 손실 정리를 막는 모순이다.

## 고침 (서버 0.3.38 · 화면 0.3.33)
1. `KillSwitchState.sell_allowed: bool = True`. 상태 파일에 칸이 없으면(옛 파일) True 로 읽는다.
2. `KillSwitch.blocks(side)`: 꺼져 있으면 False. 켜져 있으면 매수는 늘 True, 매도는 `sell_allowed` 가 False 일 때만 True.
3. 두 어댑터 `submit_order` 첫 검사를 `self._ks.blocks(req.side)` 로 바꾼다. entry 방어 1(매수 차단) · signal_router 의 정지 중 전체 건너뜀은 그대로 둔다.
4. `activate(reason, actor, sell_allowed=True)`:
   - 꺼져 있으면 전처럼 발동하고 `sell_allowed` 를 기록한다.
   - 이미 켜져 있고 `sell_allowed=False` 가 오면 True→False 로 좁힌다. 상태 파일을 고치고, 사유에 「매도도 멈춤 (누가 · 언제)」 를 덧붙이고, 텔레그램을 한 번 보낸다. 처음 발동한 사람·시각은 그대로 둔다.
   - 이미 켜져 있고 True 가 오면 바꾸지 않는다. False→True 는 해제 뒤 다시 발동할 때만 된다.
5. 자동 손실 정지(`sniper.py`)는 `sell_allowed=True` 로 발동한다. 같은 5초 주기 안에서 발동 → 보유 목록 순회 → 청산이 이어진다.
6. 알림: 허용이면 제목 「새 매수 멈춤」 · 본문 「보유 종목의 손절·추적 매도는 계속됩니다」. 멈춤이면 제목 「모든 주문 멈춤」 · 본문 「매수와 매도 모두 나가지 않습니다. 보유 종목은 직접 정리해야 합니다」.
7. API: `/sniper/status` 에 `kill_switch_sell_allowed` · `/sniper/kill-switch/status` 와 발동 응답에 `sell_allowed` · 발동 입력에 `sell_allowed` (기본 True).
8. 화면 `/sniper` 실주문 안전 상황판:
   - 결론 한 줄 · 전역 상태 배지를 `sell_allowed` 로 나눈다 (「새 진입 멈춤 · 보유 종목 손절·추적 청산은 계속」 / 「모든 주문 멈춤 (보유 종목 청산도 멈춤)」). 결론 줄은 기존 금지어 검사(「매수」「매도」 를 쓰지 않음) 때문에 「진입」「청산」 으로 쓴다.
   - 수동 발동 아래 체크 칸 「보유 종목 매도도 멈춤」 (기본 꺼짐).
   - 켜진 동안 「매도도 멈춤」 버튼으로 좁힐 수 있다. 이미 멈춤이면 버튼을 숨긴다.
9. 문서 계약: `kill_switch.py` 머리말 · `order_manager.py` docstring · OMI 스펙 (`02-omi-interface-spec.md` 6번 원칙 · docstring · Kill Switch 행) · `01-track-c-roadmap.md` · `a1-daily-loss-stop.md` 의 「다음 주기로 밀린다」 (틀림 · 같은 주기에서 청산).

## 시험
- `test_kill_switch.py`: 방향별 차단 · 옛 상태 파일 호환 · 좁히기와 다시 읽기 유지 · 켜진 상태 True 재요청은 그대로 · 같은 좁히기 재요청은 알림 없음 · 해제 뒤 재발동은 다시 허용.
- `test_contract.py` (모의): 정지 중 매도 체결 · 매수 거부 · `sell_allowed=False` 매도 거부.
- `test_toss_adapter.py` (가짜 Toss): 정지 중 매도 접수 · 좁힌 뒤 매도 거부.
- `test_daily_loss_stop.py`: 끝까지 흐름 — 보유 1종목 + 손실 왕복 6회 → `manage_positions` 한 번에 자동 정지 (매도 허용) 와 보유 종목 청산 → 새 진입 거부. 옛 규칙(매도도 막음)으로 되돌리면 이 시험이 실패하는 것을 확인했다.
- `test_execution_wording.py`: 두 알림 문구와 문구 규칙.
- 화면: `sniper-safety.check.ts` (결론·배지 두 모드 · 금지어) · `tsc --noEmit`.

## 한계 (알고 두는 것)
- 앞으로 API 오류 계열 자동 발동(예: 토스 연결 실패로 켜는 정지)을 만들면 `sell_allowed=False` 가 원칙이다. 매도도 같은 오류로 실패·재시도만 반복할 수 있기 때문이다. 지금 자동 발동은 손실 정지 하나뿐이다.
- 상태는 파일 + 프로세스 메모리(`_cached`)다. 운영은 uvicorn 1 워커이고 스케줄러가 같은 프로세스라 지금은 문제없다. 다른 프로세스(로컬 두 번째 서버 · cron 데몬)에서 바꾸면 재시작 전까지 서로 보이지 않는다.
- 홈 화면(`/`) 의 「긴급 정지 작동 중」 한 줄은 이번에 나누지 않았다 (`/today` 응답 계약 변경이 필요).
- 기존 미체결 주문 취소는 원래 구현이 없다 (문서에서 그 문장을 고쳤다).

## 범위 밖
- 청산 시각 칸 `exited_at` · signal_router 정책 · 한도·시드.
- Toss 한 주문 하드 상한(10만 원)이 매도에도 걸리는 문제 → 1105-03 (사용자 ㉯ 적용 · 별도 PR · 실주문 허용 전 필수).
