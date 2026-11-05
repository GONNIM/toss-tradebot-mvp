# A1 · 실주문 전 남은 15건 (1105-04 · 05 · 06)

- 승인: 2026-11-05 사용자 「1·2·3 모두 진행 · 먼저 쉽게 보고 후 승인」 → 2026-11-06 「㉠~㉧ 권고대로 · 15건 진행」
- 검수: `docs/plans/biotech/fable-bundles/2026-11-05-1105-04-01.md` (계획 · 조건부 GO · 막음 3 · 권고 7 · 모두 반영)
- 앞 일: `a1-daily-loss-stop.md` (1025-02) · `a1-kill-switch-sell.md` (1105-02) · `a1-toss-sell-cap.md` (1105-03)
- 판: 서버 0.3.40 · 화면 0.3.34 · 한 PR · 커밋 3개 (묶음마다) · 한 번 배포

## 고친 전제
주문 체결 확인 작업(`reconcile_pending_orders` · 30초)은 `EXECUTION_ENABLED`(신호 연결 자동 주문)와 `EXECUTION_BROKER=toss` 가 **둘 다** 켜져야 등록되었다. 스나이퍼·관심 종목만 실주문으로 켜면 돌지 않아, 직접 주문의 감사 행이 「접수」로 남았다. 그러면 하루 손익(-3% 자동 정지)이 계산되지 않고, 1105-03 「봇이 산 수량」 도 체결 수량 대신 주문 수량을 썼다. → ㉦.

## 1105-04 · 실주문 전 결정 (사용자 결정 ㉠~㉤ · ㉦)
| # | 결정 | 고침 |
|---|---|---|
| ㉠ | 오늘 손익을 계산 못 한 청산이 있으면 새 매수 멈춤 | `audit.pre_entry_loss_block` · 직접 진입 방어 7 · 신호 연결 매수 전 검사 둘 다. 체결 확인 중(매수·매도가 pending·accepted·partial 이고 체결 0)인 청산은 `DailyPnl.pending` 으로 나눠 세지 않음 · 진입마다 다시 셈 · 하루 경계 UTC 00:00 (한국 09:00). 알림 제목 「하루 손익 계산 불가 · 오늘 새 매수 멈춤」. |
| ㉡ | 15:00 강제 청산은 실주문 켤 때 함께 켬 | 코드 변경 없음 · `docs/operations/go-live-checklist.md` 2번 (매도 허용 `sell_allowed` True 여야 나감 · Fable 권고 7). |
| ㉢ | 10/26 정지는 실주문 직전 사용자가 해제 | 코드 변경 없음 · 점검표 6번. |
| ㉣ | 신호 연결 매도 = min(계좌 보유, 신호 연결이 산 순수량) | `audit.router_net_qty`: 출처 vip · super_signal · meme_stock · activist · sector_leaders 행만 · 같은 broker_kind 만 · 매수는 체결 수량 · 매도는 열린 주문이면 주문 수량을 뺌. 0 이면 주문 없이 건너뜀 (Fable 막음 2). |
| ㉤ | 손실 한도 기준을 시드로 통일 | 매수 전 검사 분모 `total_equity_krw` → 스나이퍼 `seed_cap_krw`. 직접 진입에도 같은 검사(한도 × 0.7 = -2.1%)를 붙여 문턱을 「매수 전 -2.1% · 자동 정지 -3%」 둘로 정리 (Fable 권고 1: 미리 멈춤은 자동 정지 전에 새 손실을 막는 여유). |
| ㉦ | 실계좌면 체결 확인 작업 늘 등록 | `main.py`: `EXECUTION_BROKER=toss` 면 등록. 열린 Toss 주문이 없으면 Toss 조회 0회. 점검표 5번에 시작 기록 줄 확인. |

## 1105-05 · 작은 고칠 점
6. `sniper_signal.exited_at` (alembic `b7e2a9c41d05` · nullable · idempotent) · 청산 때 채움.
7. `daily_pnl_detail` 은 `exited_at` 이 오늘 이후이거나 비어 있는(옛) 행만 읽음. 날짜 판정은 매도 감사 행 기준 그대로.
8. `execute_entry(source=)` · 관심 종목 `watchlist` · 화면 수동 `manual` · 스나이퍼 `sniper` (기본).
9. reconciler 가 `total_fee` 를 채움: 응답에 수수료 칸(fee · commission · totalFee · totalCommission · commissionAmount · fills[].fee)이 있으면 그 값, 없으면 수수료율 × 체결액(국내 0.015% · 해외 0.25% · 모의 어댑터와 같은 율). `raw_response.reconciles[].fee_source` = `toss_response` / `rate_estimate` (Fable 권고 4). 수수료 칸이 실제로 있는지는 공식 문서에 없어 추정 · 첫 실주문 응답으로 확인 (점검표 8번). `GET /api/v1/commissions` 는 응답 모양을 확인하지 못해 쓰지 않음.
10. 좁히기 알림 「바뀐 시각」 줄은 넣지 않음 (이유 줄에 「매도도 멈춤 (누가 · 언제)」 가 이미 있음 · Fable 권고 2).
11. `/today` 안전 칸에 `kill_switch_sell_allowed` · 홈 「긴급 정지 작동 중 (새 진입만 멈춤)」 / 「(모든 주문 멈춤)」 (`homeKillLabel`).
12. 정리: `assembly.py` dict 검사를 `.get` 앞으로 · cron 시험 이름 · 등록 안 된 `routes/execution.py` 발동에 `sell_allowed`.
- 배포 [3/7] alembic: 3번까지 10초 간격 재시도 · 실패하면 배포 중단 (Fable 권고 3). 예전 `| tail -10 || {…}` 은 tail 의 성공으로 alembic 실패를 놓쳤다.

## 1105-06 · 백업 후속
13. `services/backup_watch.py` · API 스케줄러 매일 09:10 KST: `.backup/LATEST` 가 없음 · 가리키는 폴더 없음 · 성공 표식 `.ok` 없음 · 36시간보다 오래됨이면 텔레그램 「시스템 경고」 (Fable 권고 5).
14. 압축 방식(㉥): 그대로 둠 (gzip). 보관 7개(`BACKUP_KEEP`) × 약 360MB ≈ 2.5GB · 디스크 44% (11/05) (Fable 권고 6).
15. crontab 봇 구역 (㉧): `deploy/merge_cron_lines.sh` 가 `# >>> toss-tradebot … # <<< toss-tradebot <<<` 구역을 `deploy/biotech_cron_lines.txt` 로 통째 바꿈. 구역 밖에 같은 줄이 있으면 처음 한 번 구역으로 옮김. 안전장치: 봇 줄 없음 · 결과 빔 · 구역 표시 어긋남 · 구역 밖 줄이 옮긴 줄보다 더 줄어듦 → exit 3 · 배포는 crontab 을 바꾸지 않고 경고만 냄. 바꾸기 전 사본 `var/crontab.before` (되돌리기: `crontab var/crontab.before`) (Fable 막음 3).

## 시험
- `test_daily_loss_stop.py`: -2.1% 에서 진입 거부 · 계산 불가 청산이면 진입 거부 · 체결 확인 중 청산은 막지 않음 (pending) · 신호 연결 매수 전 검사 분모 시드 · 관심 종목 매수 뒤 VIP 매도 건너뜀 · 순수량까지만 매도 (열린 매도·실계좌 행 반영) · 청산 시각 · 진입 출처 · 수수료 출처.
- `test_backup_watch.py` 6 · `test_biotech_wp96_cron.py` 8 (옛 줄 옮김 · 구역 통째 바꿈 · 빈 봇 줄 중단 · 구역 표시 어긋남 중단 · 배포 단계 사본) · `test_watchlist_assembly_gov.py` dict 아님 · `test_today.py` 칸.
- 시험 격리: `tests/execution/conftest.py` 의 `db_ready` 가 `sniper_signal` 을 비움 (매수 전 검사가 다른 시험 파일의 청산 기록을 읽지 않게).
- 마이그레이션: 빈 칸 → upgrade · 두 번째 upgrade 변화 없음 · downgrade · upgrade (로컬 sqlite).
- 새 1105-04 시험 7개는 옛 코드에서 실패하는 것을 확인했다. 전체 pytest 1870 통과 · 6 건너뜀.

## 한계 (알고 두는 것)
- 매도 주문이 Toss 에서 「거부」 상태로 돌아오면 그 신호는 청산된 것으로 닫히고(예전과 같음) 그날 손익은 계산 불가가 되어 새 매수가 멈춘다. 보유는 남으니 화면에서 직접 정리해야 한다.
- 처음 구역으로 옮길 때 구역 밖에 남은 「예전에 바뀐 옛 봇 줄」(지금 줄 파일과 글자가 다른 줄)은 자동으로 알아볼 수 없어 그대로 남는다. 운영 crontab 8줄(11/06 01:30 조회)은 사용자 줄 4(주석 1 포함)와 지금 줄 파일과 같은 봇 줄 4다. 그 사본에 새 스크립트를 돌리면 구역 표시 2줄만 더해지고(봇 줄 4개가 이미 맨 끝) 두 번째 실행은 같은 결과였다.
- 수수료율 짐작은 실제와 다를 수 있다 (점검표 8번).
- 하루 손익은 sniper_signal 이 있는 직접 경로만 센다. 신호 연결 경로 주문의 손익은 들어가지 않는다 (1025-02 그대로).
