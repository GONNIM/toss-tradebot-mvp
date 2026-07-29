---
title: 12주 실행 로드맵
type: execution-plan
status: active
created: 2026-07-29
updated: 2026-07-29
scope: Stage 1 완결 · Stage 2 진입 자격 확보
timeline: 2026-07-29 ~ 2026-10-21 (12주)
---

# 12주 실행 로드맵

## 0. 목표 · 게이트

**최종 목표**: Stage 1 (개인 판단 도구) 완결 · Stage 2 진입 KPI 확보

**Stage 2 진입 KPI** (전항 필수):
- [ ] Judgment Journal 판정 30건+ · rejection criteria 100%
- [ ] 판정 정확도 baseline 확정 (T+7 outcome 자동)
- [ ] Obsidian sync 3경로 자동화
- [ ] 관리자 인증 100% · 무인증 실 종목 노출 0
- [ ] 3계층 재편 완결 · L3 `/lab` 이관
- [ ] T2 Cal.com 컨설팅 슬롯 유료 예약 1건

## 1. Phase A · 아키텍처 리셋 (주 1~2 · 2026-07-29 ~ 08-11)

**목적**: 나중에 재작업 커질 아키텍처 결정을 지금 배치. 판정 도구 개선 이전에 폐기·격리·재편 완결.

### 주 1 · 폐기 + DB 격리

- [ ] `docs/plans/tradebot-tobe/` `git rm` (Phase 6 보안 5항만 [[phase6-security-salvage]]로 흡수)
- [ ] `user_id` 컬럼 7개 테이블 nullable 추가 (default "owner")
  - CrazyPick · MoonshotPick · Watchlist · PowderKegList · SuperSignal · SniperSignal · MemeAlertHistory
- [ ] 복합 unique 인덱스 재편 (`date + ticker + user_id`)
- [ ] **Alembic 활성화** · 첫 마이그레이션 = user_id 추가 (`backend/scripts/migrations/2026-07-30-user-id.py`)

**검증**:
- 로컬 sqlite3에서 신규 컬럼·인덱스 확증
- pytest 회귀 (기존 판정 API 정상)

### 주 2 · 라우트 재편

- [ ] API prefix 이원화 · `main.py` include_router 재편
  - `/api/v1/admin/*` (require_sniper_token 필수)
  - `/api/v1/read/*` (GET 공개)
- [ ] 프론트 `/admin/*` 라우트 이관 · nav 재구성
  - L1 (5개): Journal(placeholder) · Watchlist · Sniper · Positions · Dashboard · Logs
  - L2 (4개): Powderkeg · Activist · VIP · Sector
  - L3 `/lab/*` 이관: crazy · moonshot · meme-watch · super-signals · backtest · execution
- [ ] `next.config.mjs` `redirects()` 설정 (301) · 기존 URL 유지
- [ ] `main.py`에서 dead API include 제외: crazy · super_signals · moonshot · execution
- [ ] Home 재작성: "오늘의 컨트롤 타워" (실시간 배지 4개 · 장 상태 · Journal placeholder)

**검증**:
- Playwright: 기존 알림 URL `/powderkeg` → 신 URL 200
- 크론·Telegram 링크 QA

**게이트 A**: 배포 검증 3중 통과 시 Phase B 착수.

## 2. Phase B · Judgment Journal 착수 (주 3~4 · 08-12 ~ 08-25)

**목적**: 판정→결과 폐루프 완결. Stage 1 진짜 KPI (자기 판단 오류율 측정) 착수.

### 주 3 · Judgment Journal 신설

- [ ] `user_judgments` 테이블 (Alembic 두번째 마이그레이션)
- [ ] API 라우트 `/api/v1/judgments` (POST · GET · PATCH outcome · baseline)
- [ ] `/journal` 페이지 L1 최상단 · Home 배지 연동
- [ ] 판정 생성 팝업 컴포넌트 (Powderkeg lock · Watchlist 편입 · Sniper enable 시)
- [ ] `mood` 프리셋 · `market_regime` 자동 태깅 (KOSPI 20MA·VKOSPI)

**검증**:
- 판정 3건 생성 · outcome cron으로 T+7 자동 계산 확증

### 주 4 · 통계 규율 이식

- [ ] Crazy/Moonshot: DB perf_1w/perf_1m UI 노출 (모든 pick · cherry-pick 금지)
- [ ] Meme/VIP/Activist/Super-Signals: `outcome_at_horizon` 컬럼 신설 · 크론 자동 계산
- [ ] 정보 유형 배지: `[LEADING]` `[LAGGING]` `[COINCIDENT]` (각 페이지 헤더)
- [ ] 통계 유의성 표기: 표본 n · 95% CI · `|t| < 2` 결론 어려움
- [ ] Backtest sources 데이터마이닝 방지 (전체 조합 강제 + 경고 배너)

**검증**:
- 각 페이지 SSR 스냅샷: 배지·CI·n 표기 확증
- Powderkeg 판정 vs Crazy 판정을 Journal에서 병치 확인

**게이트 B**: 판정 5건+ 축적 시 Phase C 착수.

## 3. Phase C · 자산화 훅 (주 5~6 · 08-26 ~ 09-08)

**목적**: 매 판정이 GON-LLM-Wiki로 자동 sync. Stage 2 상품화 원천 확보.

### 주 5 · 판정 4요소 컬럼

- [ ] `hypothesis_id` · `market_context` · `retrospect_url` 3컬럼 추가 (Alembic)
- [ ] `powderkeg_list.conditions_json`에 margin 값 저장 의무화
- [ ] `powderkeg_tier_history` view/table 신설 (종목별 시계열)
- [ ] `reject_reasons` 카테고리화 · 월 1회 집계 API

### 주 6 · Obsidian Sync 3경로

**대상**: `/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/`

- [ ] run 종료 훅 → `Runs/{run_id}.md` 자동 생성
- [ ] 매주 일 08:00 크론 → `Weekly/{YYYY-Www}.md`
- [ ] 승격 종목 첫 시 → `Tickers/{ticker}.md` (이후 append)
- [ ] 판정 근거 permalink: `optimus8.cafe24.com/insights/decision/{run_id}/{ticker}`
- [ ] 패턴 참조: `GON-LLM-Wiki/Goals/2026-1억-Sprint/gonnim-landing/scripts/sync-kickoff.ts`

**검증**:
- 로컬 판정 1건 → Wiki 3경로 자동 생성 확증
- Weekly 크론 dry-run 1회

**게이트 C**: sync 3경로 자동화 확증 시 Phase D 착수.

## 4. Phase D · 인증·관측성 (주 7~8 · 09-09 ~ 09-22)

**목적**: XSS 방어선 완결 · Stage 3 SLA 근거 축적 시작.

### 주 7 · 인증 이관

- [ ] localStorage → httpOnly 쿠키 (sniper·watchlist·powderkeg 3곳)
- [ ] `lib/auth.ts` 통일 (getToken·setToken·clearToken)
- [ ] Role 3단계 (admin·subscriber·anon) · middleware
- [ ] CORS `allow_origins` 명시 origin 검증
- [ ] `sniper_api_access` 감사 테이블 실체화 · `auth.py` DB write 승격

### 주 8 · 관측성

- [ ] Sentry 무료 티어 · 라우트별 error rate
- [ ] PostHog 무료 티어 · 페이지 방문·판정 저널 사용 tracking
- [ ] `DATABASE_URL` env 추상화 (Postgres 전환 대비)
- [ ] `/api/v1/webhooks/payment` 스텁 (200 반환)
- [ ] 백업 스크립트 · upbit-tradebot-mvp `backup.sh` 패턴 참조

**게이트 D**: XSS 회귀 테스트 통과 · Sentry 첫 error 관측 시 Phase E 착수.

## 5. Phase E · 판정 축적·baseline (주 9~10 · 09-23 ~ 10-06)

**목적**: Stage 2 진입 자격 KPI 최종 검증.

### 주 9~10 · 사용 정착

- [ ] 매일 아침 Watchlist·Journal 확인
- [ ] Powderkeg 승격 시 판정 생성 (필수)
- [ ] 마감후 Journal 리뷰 · outcome 재확인
- [ ] 주 1회 Weekly Insights 초안 검토 (오탈자·문맥)

**KPI 검증**:
- Judgment Journal 30건+ (누적)
- 판정 baseline: 승률·평균 수익률·mood별 분포 확정
- Obsidian sync 3경로 정상 (Runs·Weekly·Tickers 파일 각 10건+)
- 무인증 실 종목 노출 0 (Sentry 확증)

## 6. Phase F · Stage 2 진입 준비 (주 11~12 · 10-07 ~ 10-20)

**목적**: Sprint T2 매출 첫 실현.

### 주 11 · T2 컨설팅 오픈

- [ ] Cal.com 슬롯 "optimus8 판정 조회 (30분)" 등록
- [ ] `gonnim.dev/consulting` 상품 카드 추가
- [ ] 예약 폼: 관심 종목 3개 수집
- [ ] 세션 전 자동 판정 이력 pull (permalink 활용)
- [ ] 세션 후 요약 문서 자동 생성 (Obsidian `Consulting/{date}-{client}.md`)
- [ ] 결제: 계좌 이체 (Stage 3에서 Stripe/Toss)

### 주 12 · Weekly Report 자동 초안·Sprint Radar 연동

- [ ] Weekly Insights 자동 초안 (매주 일 08:00)
- [ ] Sprint Radar 판정 이력 흡수 훅 (`/api/v1/read/judgments` public API)
- [ ] Revenue-Tree v2.3 갱신 (optimus8 T2 배치 반영)
- [ ] Stage 2 진입 KPI 최종 판정 · Stage 2 착수 여부 결정

**최종 게이트**: 위 KPI 6항 전항 통과 시 Stage 2 착수 · 통과 실패 시 원인 분석 · 2~4주 추가.

## 7. 배포 규칙

- 각 Phase 완료 후 **단일 배포** (Phase별 부분 배포 금지 · [[../../../CLAUDE|CLAUDE.md]] 원칙)
- 서버 배포는 GitHub Actions 자동 (push=배포)
- 배포 검증 3중 (SSR SHA · 서버 .env · 러닝 프로세스 env)
- Alembic 마이그레이션은 코드 배포 전 서버에서 먼저 실행

## 8. 리스크 · 방어선 참조

각 Phase의 방어선은 [[risks-and-guardrails]] 참조.

## 9. 위임 · 다음 문서

- **각 단계 세부 스펙**: [[stage1-optimization]] · [[stage2-architecture]]
- **Sprint 매출 연동**: [[sprint-revenue-integration]]
- **폐기된 tradebot-tobe에서 살린 것**: [[phase6-security-salvage]]
