# 화면 재구성 기획 — 메뉴 5개 + 종목 화면 (1022-10)

**상태:** 사용자 승인 (2026-10-28 「1022-10 이대로」) · 단계마다 구현 → Fable → 승인 → 배포
**근거:** 사용자 지시 10/28 (메뉴 산재·중복 · 가이드라인 기반 최적 화면 · 흩어진 정보를 묶어 한눈에 종합 판단) · 조사·Fable 확인 `docs/plans/biotech/fable-bundles/2026-10-28-1022-10-01.md` (로컬) · 이 폴더 `README.md` (10/22 순위 2~8)

## 화면 기준
- 저장소 루트 `DESIGN.md` (coinbase 판) + CLAUDE.md 「디자인 기준」 의 이 프로젝트 값 (반경 8·14·알약 · 그림자 없음 · 본문 17px · 숫자 `tabular-nums` · 상승 빨강 · 하락 파랑 · 강조색 틸).
- 10/22 gonnim 규칙 가운데 위와 겹치지 않는 것 (내부 코드 숨김 · 상태 문구에 다음 동작 · 빈 상태 문구 · 접근성) 은 그대로 쓴다.

## 지금 문제 (10/28 조사)
| # | 문제 | 근거 |
|---|---|---|
| 1 | 메뉴 = 헤더 (로고·Lab·⚙) + L1 9 + L2 7 (+ Influencer 전용 2) · 영어+이모지 | `frontend/components/layout/AppNav.tsx:11-36` · `frontend/app/layout.tsx:33-43` |
| 2 | page.tsx 35 · 숨은 화면 10곳 넘음 | `frontend/app/**` |
| 3 | 겹침: /dashboard·/account 제목 둘 다 「내 계좌」·같은 API · 보유 종목 3벌 (/dashboard·/account·/positions) · 우량주 스크리너 3벌 (/principles/screener·/rulebook·/powderkeg 저PBR) · 원칙집 2벌 · Serenity·Hunter · Activist·VIP · Watchlist·Sniper | dashboard/page.tsx:53·69 · account/page.tsx:52·237 |
| 4 | 종목 상세는 `/influencer/serenity/[ticker]` 하나 · 한 종목 정보가 10곳 넘게 흩어짐 · `/journal?ticker=` 필터 안 됨 | positions/page.tsx:330·383 |
| 5 | 홈은 「연결 대기」 고정 칸 4개 | app/page.tsx:55-67 |
| 6 | 로그인 칸 13화면 (같은 쿠키 세션) | AdminSessionBar 11 · BiotechSessionControl 2 |

## 정보 구조
| 메뉴 | 무엇을 보나 | 묶는 지금 화면 |
|---|---|---|
| 오늘 (/) | 오늘 후보 · 보유 경보 (손절 근접·시한) · 오늘 할 판단 · 시스템 실패 (위) | 새 화면 |
| 후보 | 종류별 탭 | 단기 (Watchlist·Sniper) · 미국 (Crazy·Moonshot·밈) · 바이오 · 인플루언서 (Serenity·Hunter) · 이벤트 (Activist) · 국내 가치 (화약고·원칙 스크리너·5단계 필터·섹터) |
| 종목 (`/stock/[ticker]` · 검색) | 한 종목의 모든 신호 · 뉴스·사건 · 내 판단·보유·청산 계획 · 토스 링크 · 판단 입력 | 새 화면 · 모든 화면의 종목 이름이 여기로 |
| 내 계좌 | 보유 + 청산 계획 + 깊이 감시 + 실주문 안전 한 줄 | /dashboard + /account + /positions → /account 한 화면 · /vip 는 탭으로 둠 (10/29 사용자 「권고대로」 · 보유 중복 아님 · 알림 링크 닿는 화면) |
| 기록 | 판단·결과 · 손익비 통계 · 손절 기록 · 실행 기록 | /journal + /rulebook 통계 + /logs |
| ⚙ 설정 (헤더) | 로그인 하나 · 알림 · 운영 값 · 원칙 헌장 · 실험장 | /admin/* · /principles · /lab (쉬는 기능) |

## 단계
| 단계 | 내용 | 서버 변경 |
|---|---|---|
| 0 | 보안: 인증 없는 쓰기 API 4곳 (1028-03 · 별도 일) | 있음 (보호 추가) |
| 1 | 메뉴 묶음 4 + ⚙ (종목은 3단계) · 헤더 로그인 하나 · **주소는 옮기지 않음** (10/29 사용자 「권고대로」 · 질의 `2026-10-29-1022-10-02.md`) · 화면 내용 그대로 | 없음 |
| 2 | 내 계좌 합치기 (보유 3벌 → 1): /account = 요약 → 보유 표 하나 → 종목별 청산 계획 (`#plan`) → 실주문 안전·카카오·토스 주소 · 옛 /dashboard → /account · /positions → /account#plan (redirect 307 · 사이트 안 링크는 새 주소) (10/29 사용자 「권고대로」 · 질의 `2026-10-29-1022-10-05.md`) | 없음 |
| 3 | 종목 화면 | 읽기 전용 모음 API 1개 (WP92 승인) |
| 4 | 오늘 홈 (README 순위 2 · `docs/plans/toss-tradebot-tobe/identity.md` 개정 여부 함께) | 읽기 전용 API 1개 (WP92 승인) |
| 5 | 문구·색·글자 통일 (`docs/design-rules.md` 를 DESIGN.md 기준으로 개정) · 모바일 | 없음 |

## 지킬 것 (Fable 10/28)
- 텔레그램 알림 링크 11곳 (`backend/services/notification_settings.py:47-67` · digest :39 · `execution/kill_switch.py:64`) 은 같은 내용에 닿아야 한다 · 단계마다 검증. 1단계는 주소를 옮기지 않아 그대로 닿는다 (10/29 개정). 뒤 단계에서 화면을 합쳐 주소가 바뀌면 옛 주소 redirect 로 살린다. 탭 주소만으로 바꾸지 않는다.
- 「후보」 로 올리는 것은 운영 기능 (Crazy·Moonshot·밈) 만 · 쉬는 실험 (backtest·super-signals) 은 설정 아래 실험장에 남김 (README 순위 8 경계를 앞당김).
- 단계별 배포는 README 10/22 사용자 결정 · 단계마다 그 자체로 완결 (옛 주소 동작 · 콘솔 오류 0 · chrome-devtools 데스크톱·모바일) 을 보고에 적는다.
