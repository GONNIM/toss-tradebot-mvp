# 알림 설정 페이지 · 기획 (1022-09)

**상태:** 기획 승인 (2026-10-23 사용자 · "9번: A 가 · B 18시 · C 가") · 구현 계획 전
**목적:** 텔레그램 알림을 사용자가 화면에서 직접 켜고·끄고·줄인다. 발송 실패가 로그에만 묻히지 않게 화면에 보인다.
**근거:** `README.md` (10/22 범위·유용성 권고) · Fable 질의 `2026-10-23-alert-settings-plan-1.md`·`-2.md` (scratchpad · 판정 진행)

## 사용자 결정 (2026-10-23)
| # | 결정 | 내용 |
|---|---|---|
| A | 배포 직후 기본값 | 지금처럼 전부 켜짐 · 행마다 권고값 표시 + "권고값 한 번에 적용" 단추 (10/22 "기본값 = 권고값" 을 대체) |
| B | 하루 요약 시각 | 18:00 KST (17:05 Sector 뒤) |
| C | 끌 수 없는 묶음 | Kill Switch · 실주문(execution) · 잡 실패 warning — 단 잡 실패는 "하루 요약" 모드는 고를 수 있음 |

## 구조
- **거름 지점 한 곳:** `backend/services/notifier.py` `TelegramNotifier.send`. 앱 안의 발송은 모두 여기를 거친다 (api · cron · biotech 셸 `backend/scripts/biotech_notify.py`). 설정 확인은 프로필 필터(notifier.py:103) **앞**에 둔다 → WATCH 큐에는 설정을 통과한 알림만 들어가므로 WATCH flush(`backend/api/main.py:212-214`) 는 `gate=False` 로 재확인하지 않는다.
- **meme 통합:** `backend/discovery/meme_watch/alert.py:19,202` 는 지금 `backend/services/telegram_notifier.py` `send_message`(Markdown) 로 직접 보낸다 → `TelegramNotifier` 로 옮긴다. 본문은 HTML 로 바꾸고 escape · 메시지 내용은 같게 · 문구 테스트. `backend/tests/conftest.py:49` 의 meme 발송 가드도 새 경로로 고친다.
- **묶음 표시:** `send_info/warning/critical` 호출 29곳 · 16파일 + `.send(` 1곳(api/main.py:214) 에 `category=` 인자. 없으면 제목 글자 추정(`_infer_source`) · 그래도 모르면 항상 발송.
- **force 의 뜻:** 프로필·중복 억제 우회로만 남긴다. 설정 거름을 건너뛰는 것은 별도 `gate=False` (하루 요약 잡·WATCH flush 전용). "끌 수 없음" 은 force 가 아니라 묶음(결정 C)으로 정한다. 화약고 urgent(`backend/powderkeg/triggers.py:111`)·biotech 은 끌 수 있는 묶음.
- **배포 알림(GitHub Actions deploy-watch)** 은 DB 를 못 읽으므로 대상 밖 · 화면에 "설정 대상 아님" 표시.

## 데이터
- `notification_setting` — 묶음별: 켜기 · 모드(즉시/하루 요약) · 재발송 간격(분) · 최소 등급 · 수정 시각. 행이 없으면 기본(켜짐·즉시·간격 0).
- `notification_log` — 발송 시도마다: 묶음 · 제목 · 결과(성공/실패/설정으로 건너뜀/요약 대기) · 오류 요지(마스킹·200자) · 시각. 30일 보관.
- `notification_digest_queue` — 요약 모드 알림을 18:00 까지 쌓아 둠.
- **재발송 키:** 묶음 + 식별자(종목 등 · 호출 측이 넘김 · 없으면 제목). meme 은 자체 DB 쿨다운·재발동 판정(`alert.py:165-188`)이 있으므로 간격 0(기존 로직 유지).

## 안전 원칙
1. 설정을 읽지 못하면 보낸다 (켜짐이 기본).
2. 기록 쓰기 실패가 발송을 막지 않는다.
3. 설정은 프로세스마다 60초 캐시 → 재시작 없이 1분 안에 반영 (api · cron · biotech 셸).
4. SQLite 동시 쓰기 잠금을 견딘다 (짧은 트랜잭션 · 실패 시 로그만 버림). biotech 스크립트에 DB 의존이 새로 생기므로 로컬 테스트에 포함.

## API
- `GET /api/v1/notifications/settings` · `PUT /api/v1/notifications/settings/{category}` · `POST /api/v1/notifications/settings/apply-recommended` · `GET /api/v1/notifications/log?category=&limit=`
- 인증: `require_sniper_token` (쿠키 세션 우선 · X-API-Token 대체 · `backend/api/auth.py:149`)

## 화면 `/admin/notifications`
- ⚙️ 아래 (1단 메뉴 아님). 묶음 카드 11개 안에 설정 행 21개 + 배포 표시 1행 (권고값을 행 단위로 표현). 행: 켜기 토글 · 모드 · 재발송 간격 · 권고값 · 마지막 성공 · 최근 실패. 끌 수 없는 묶음은 토글 대신 "끌 수 없음".
- "권고값 한 번에 적용" 단추 (확인 후 실행).
- gonnim /dominance 패턴: 토글 즉시 반영 · 실패 시 되돌림 · 저장 피드백 문장 · 알림 띠.

## 하루 요약 잡
- cron 프로세스 18:00 KST · 묶음별 1건 (건수 + 제목 목록) · 보낸 뒤 큐 비움 · 실패하면 다음 날까지 보관.

## 11묶음과 권고값 (README 2026-10-22 유용성 권고)
| 묶음 | 권고 |
|---|---|
| ① Serenity 작업 | 성공 끄기 · 실패만 |
| ② 화약고 DO NOT TOUCH | 즉시 (리스트 구분은 후속 · 보유 구분은 정보 없음 · 10/22 권고 "리스트·보유만 즉시") |
| ③ 화약고 후보 | A1·A5 유지 · A2·A3 끄기 |
| ④ 티켓 승인 · 12개월 재평가 | 재평가 유지 · 승인 끄기 |
| ⑤ VIP | 7일 간격 |
| ⑥ Activist | STRONG 이상만 |
| ⑦ Sector · Crazy · Moonshot | 유지 |
| ⑧ meme | ERUPTING 즉시 · BLAZING 하루 요약 · 간격은 기존 로직 |
| ⑨ SNIPER · Kill Switch | 유지 (Kill Switch·실주문 끌 수 없음) |
| ⑩ biotech | 유지 |
| ⑪ 배포 알림 | 설정 대상 아님 |
| + 잡 실패 warning | 끌 수 없음 · 하루 요약 선택 가능 |

## 단계와 배포
- P1 표 3개 · 거름 · 기록 · API · 테스트 → P2 31곳 category · meme 통합 → P3 화면 → P4 18:00 요약 잡
- CLAUDE.md 멀티 Phase 규칙: 모두 로컬 완성 후 단일 배포 · 버전 backend·frontend 둘 다
- 알림 경로 변경이므로 PR 은 Fable "병합 승인됨 · PR #번호" 뒤 병합 (PENDING WP92)

## 범위 밖
- 알림 문구 HTML escape 일괄 점검은 P2 에서 category 를 붙이며 같이 본다 (전면 개편은 아님)
- `asyncio.to_thread` + `wait_for` 조합이 스레드를 끊지 못하는 공통 과제 (1023-01 뒤 남은 것) — 별도
- 분류기(화약고 A1) LLM 대체 경고는 로그만 (1022-15 결정 범위 축소 · 이 화면 기록에서 보임)
