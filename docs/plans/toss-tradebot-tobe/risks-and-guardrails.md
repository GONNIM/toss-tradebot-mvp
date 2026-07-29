---
title: 크로스컷 리스크 12 · 방어선
type: risk-register
status: active
created: 2026-07-29
updated: 2026-07-29
source: 4관점 병렬 리뷰 (A×3 + B×3 + C×3 + D×3)
---

# 크로스컷 리스크 12 · 방어선

## 0. 리스크 매트릭스

| # | 관점 | 리스크 | Severity | 방어선 | KPI/Trigger |
|---|---|---|---|---|---|
| A1 | 퀀트 | Selection bias 자기 과신 → 실전 배팅 확대 → 큰 손실 | 🔴 High | Judgment Journal outcome 강제 · cherry-pick 금지 | 판정 baseline 승률 baseline과 5%p 이상 괴리 시 경고 |
| A2 | 퀀트 | "내 도구 나에게 맞다" 실증 부재 → Stage 4 규제·환불·평판 | 🔴 High | 판정 정확도 baseline 공개 · Judgment vs 실 매매 상관 tracking | Stage 4 진입 전 최소 6개월 baseline 필수 |
| A3 | 퀀트 | 18개 UI 부하 → 판단 피로 → 앵커링 | 🟡 Med | L1 5개+L2 4개 축약 · L3 히든 | 페이지 방문 로그 상 상위 5개 비중 80% 유지 |
| B1 | UX | 라우트 이전 301 없음 → 크론·Telegram 링크 사망 | 🟡 Med | `next.config.mjs` redirects · 이관 배포 전 QA | 알림 클릭율 유지 (Sentry 404 알림) |
| B2 | UX | `/lab` 무덤화 → dead code 축적 | 🟢 Low | "마지막 검토일 · 6개월 방치 자동 삭제" 룰 | 자동 삭제 크론 · 월간 리뷰 |
| B3 | UX | 관리자/외부 분리 지연 → 무인증 실 종목 노출 | 🔴 High | Stage 2 진입 전 `/admin` 이관 필수 | Stage 2 진입 게이트 |
| C1 | 자산화 | Sprint T2 편중 vs optimus8 배치 0 → Q1 미달 시 폐기 1순위 | 🔴 High | Cal.com 컨설팅 슬롯 즉시 배치 · Revenue-Tree v2.3 반영 | Q1 종료 시 유료 예약 1건 이상 |
| C2 | 자산화 | v2.0 정체성 변경으로 v1.x 판정 무효화 | 🟡 Med | `hypothesis_id` 컬럼 즉시 추가 · 판정별 버전 각인 | Stage 2 인용 시 hypothesis_id 필터 |
| C3 | 자산화 | 자매 봇(upbit) GON-LLM-Wiki 병렬 배치 → 크로스 오염 | 🟢 Low | 분리 정책 문서 신설 · Wiki 폴더 명명 규칙 · 상품 헤더 명시 | 리포트·컨설팅 문서 자동 헤더 검증 |
| D1 | 아키텍처 | XSS 1건 → 실주문 토큰 탈취 → 자금 손실 | 🔴 Critical | httpOnly 쿠키 이관 · CSP 강화 · SNIPER_LIVE_ENABLED false 유지 | Stage 1 완결 전 이관 필수 |
| D2 | 아키텍처 | SQLite write lock → 스케줄러 정체 → 배치 밀림 | 🟡 Med | DATABASE_URL 추상화 · Postgres 전환 트리거 (외부 read 1건) | 스케줄러 지연 5분 이상 시 알림 |
| D3 | 아키텍처 | Alembic 없이 drift 누적 → Stage 3 진입 2주 재구축 | 🟡 Med | Alembic 즉시 활성화 · 첫 마이그레이션 = user_id 추가 | 스키마 drift 검증 pre-deploy |

## 1. Critical 리스크 상세

### D1 · XSS → 실주문 토큰 탈취 (🔴 Critical)

**시나리오**: `sniper/watchlist/powderkeg` 3개 페이지가 localStorage에 SNIPER_API_TOKEN 저장. XSS 삽입 코드 1건이면 즉시 유출. 유출 후 SNIPER_LIVE_ENABLED=true 상태면 실주문 가능.

**현 방어선**:
- SNIPER_LIVE_ENABLED 이중 스위치 (환경변수 · 관리자 UI)
- SNIPER_LIVE_ENABLED 기본 false
- 관리자 인증 확인

**추가 방어선 필요**:
- localStorage → httpOnly 쿠키 이관 (Stage 1 완결 전)
- CSP (Content Security Policy) 강화 · `next.config.mjs` 헤더
- Playwright XSS 시나리오 회귀 테스트

**Trigger**: Stage 1 완결 전 이관 강제. Stage 2 진입 게이트.

## 2. High 리스크 상세

### A1 · Selection Bias 자기 과신 (🔴 High)

**증거**: 리뷰 A 근거 · `CrazyPick.perf_1w/perf_1m` DB에는 있는데 UI 노출 0. Moonshot·Meme·VIP·Activist·Super-Signals는 사후 outcome 필드 자체 없음. **매일 10건 Pick 던지고 결과는 안 본다** → cherry-pick 100% 노출.

**방어선**:
- Judgment Journal에 모든 페이지 판정 병치 (self-page 편애 방지)
- 모든 Pick outcome 무조건 표시 (cherry-pick 금지)
- 판정 baseline과 실 매매 상관 tracking
- 승률 baseline과 5%p 이상 괴리 시 경고 배지

**KPI**: Stage 2 진입 전 최소 30건+ 판정 · baseline 확정.

### A2 · "내 도구 나에게 맞다" 실증 부재 (🔴 High)

**증거**: CLAUDE.md·identity.md에 "GON 본인 실 매매 vs optimus8 판정 상관계수" 측정 계획 없음. Sprint 목표 1억이 판정 정확도와 무관한 채 진행 시 Stage 4 유료 구독 진입 시 **"실제 수익 근거 무"** → 규제·환불·평판 리스크.

**방어선**:
- Judgment vs 실 매매 상관계수 자동 계산 (mood별 승률 분포)
- Stage 4 진입 전 최소 6개월 baseline 공개
- "투자 권유 아님 · 정보 제공만" 헤더 표준화 (Stage 2부터 모든 자동 생성 문서)

### B3 · 관리자/외부 분리 지연 (🔴 High)

**증거**: 현재 Powderkeg/Watchlist가 실 종목 리스트·백테스트 수치를 무인증 URL로 노출. Stage 2 외부 초대 전에 `/admin` 이관 안 하면 "개인 도구" 법적 스탠스 훼손.

**방어선**:
- Stage 2 진입 전 `/admin/*` 이관 완결
- `/api/v1/admin/*` vs `/api/v1/read/*` 라우트 이원화
- 무인증 접근 시 404 or Stage 2 랜딩

**Trigger**: Stage 2 진입 게이트 · 이관 미완결 시 진입 차단.

### C1 · T2 편중 vs optimus8 배치 0 (🔴 High)

**증거**: Revenue-Tree v2.2 T2 83% 편중이나 optimus8 T2 배치 0건. Sprint 3주차 진행 중이나 optimus8이 매출에 기여 안 함.

**방어선**:
- Cal.com "판정 조회 컨설팅" 슬롯 즉시 배치 → [[sprint-revenue-integration#1-즉시-배치·t2-컨설팅-상품-신설]]
- Revenue-Tree v2.3 갱신 (Sprint Kickoff와 병렬)
- Q1 종료 시 유료 예약 1건 이상 · Stage 2 진입 KPI

## 3. Medium 리스크

### B1 · 라우트 이전 시 링크 사망

**방어선**: `next.config.mjs`의 `redirects()`에 이관 매핑. 이관 배포 전 QA (Playwright로 기존 URL 200 확인).

### C2 · v1.x 판정 무효화

**방어선**: `hypothesis_id` 컬럼 즉시 추가 · 판정별 버전 각인. Stage 2 인용 시 hypothesis_id 필터로 소급 인용 안전.

### D2 · SQLite Write Lock

**방어선**: DATABASE_URL 추상화 (지금) → Postgres 전환 (Stage 2 이후 · 외부 read 1건 관측 시 트리거).

### D3 · Alembic Drift

**방어선**: Alembic 즉시 활성화 · 첫 마이그레이션 = user_id 추가. Pre-deploy 스키마 drift 검증 script.

## 4. Low 리스크 (그러나 감시 필수)

### A3 · 18개 UI 부하

**방어선**: L1 5개+L2 4개 재편으로 즉시 완화 → [[stage1-optimization#3-정보구조-3계층-재편-b]].

### B2 · `/lab` 무덤화

**방어선**: `/lab` 인덱스에 "마지막 검토일 · 6개월 방치 자동 삭제" 컬럼. 월간 리뷰 크론.

### C3 · 자매 봇 크로스 오염

**방어선**:
- CLAUDE.md 명시 규정 유지 ("완전 분리")
- Wiki 폴더 명명 규칙: `Toss-Tradebot-MVP/` · `Upbit-Tradebot-MVP/` 분리
- 상품 (컨설팅·리포트) 헤더 자동 검증 · optimus8 상품에 upbit 원천 자료 인용 시 flag

## 5. Stage 이행 게이트

**Stage 1 → Stage 2 게이트** (모든 High 이상 방어선 확증 필수):
- [ ] D1: httpOnly 쿠키 이관 완결
- [ ] B3: `/admin` 이관 완결
- [ ] A1: Judgment Journal 30건+ · outcome 자동 계산
- [ ] A2: baseline 3개월+ 축적
- [ ] C1: Cal.com 유료 예약 1건 이상

**Stage 2 → Stage 3 게이트**:
- [ ] A2: baseline 6개월+ 공개
- [ ] D2: Postgres 전환 완결
- [ ] Payment webhook 실제 활성

## 6. 위임 · 다음 문서

- **각 방어선 실행 상세**: [[stage1-optimization]] · [[stage2-architecture]]
- **12주 로드맵 (방어선 배치 순서)**: [[roadmap-12week]]
