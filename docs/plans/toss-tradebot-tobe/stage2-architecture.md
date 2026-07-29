---
title: Stage 1→2 이행 아키텍처
type: architecture-spec
status: active
created: 2026-07-29
updated: 2026-07-29
implements: 리뷰 B (URL·인증) · C (자산화 훅) · D (데이터 격리·관측성)
principle: "지금 결정 안 하면 Stage 3에서 6~8주 재작업 강제 (리뷰 D)"
---

# Stage 1 → 2 이행 아키텍처 (지금 결정 · 나중 재작업 회피)

## 0. 핵심 원칙

리뷰 D 인용: **"Notion·Linear 초기 조언과 동일. user_id를 지금 안 넣으면 Stage 3에서 데이터 재구성 6~8주. 지금 하면 3일."**

본 문서는 Stage 1 진행과 동시에 배치해야 할 아키텍처 결정을 명시. Stage 3~4 이행 시 재작업을 최소화.

## 1. 데이터 격리 (D · 최우선 · 지금 3일 · Stage 3에서 6~8주)

### 1.1 `user_id` 컬럼 7개 테이블 nullable 추가

```
CrazyPick · MoonshotPick · Watchlist · PowderKegList
SuperSignal · SniperSignal · MemeAlertHistory
```

- `user_id: str = "owner"` 기본값
- 신설 [[stage1-optimization#1-1-db-스키마·user_judgments-테이블|UserJudgment]]는 처음부터 포함
- **복합 unique 인덱스 재편**: 예 `ix_watchlist_date_ticker` → `date + ticker + user_id`

### 1.2 Alembic 활성화

- 현재 `Base.metadata.create_all()` 방식 · **스키마 drift 검증 없음** · Stage 3 진입 직전 "정합성 재구축 2주" 리스크 (리뷰 D)
- venv에는 alembic 이미 설치 확인
- `user_id` 추가 자체를 첫 정식 Alembic 마이그레이션 트리거로

### 1.3 DATABASE_URL env 추상화

- SQLite → Postgres 전환 자체는 Stage 2 이후 · **connection string 추상화는 지금**
- `services/db.py`의 URL 하드코딩 여부 확인 후 env로 통일
- FastAPI 스케줄러 + 판정 배치 + 웹 read가 동일 SQLite 파일 = write lock 위험 (리뷰 D)

## 2. URL 이원화 (B+D)

### 2.1 API 라우트 prefix 재편

- `/api/v1/admin/*` — `require_sniper_token` 필수 (관리·편집·실행)
- `/api/v1/read/*` — GET 공개 (Stage 2+ 무인증 read API)
- 파일은 그대로 · `main.py`의 `include_router` prefix만 재편

### 2.2 프론트 라우트 재편

```
/admin/*    — 관리 콘솔 (settings · logs · execution · sniper 등)
/insights/* — 외부 뷰 (Stage 2+ · Weekly Report · 판정 이력 공개 페이지)
/           — Home (오늘의 컨트롤 타워 · Stage 1 판정 도구)
/lab/*      — 실험장 (nav 히든 · L3)
```

### 2.3 301 Redirect 필수 (리뷰 B 지적)

- 크론·Telegram 알림·docs 링크에서 `/powderkeg` 등 절대 경로 사용 중
- 라우트 이전 시 301 없으면 알림 링크 사망
- `next.config.mjs`의 `redirects()` 설정 필수

## 3. 인증 이관 (B+D)

### 3.1 localStorage → httpOnly 쿠키

**현 위치 3곳** (리뷰 D 확증):
- `sniper/page.tsx` L27
- `watchlist/page.tsx` L18
- `powderkeg/page.tsx` 관련

XSS 1건이면 실주문 토큰 유출 (D 리스크 1위).

### 3.2 `lib/auth.ts` 통일

- `getToken()` / `setToken()` / `clearToken()` 하나로 노출
- 페이지별 산발 참조 → 단일 진입점

### 3.3 Role 3단계

```
admin      — GON 본인 · 전 기능
subscriber — Stage 3~4 유료 · read + 심화 API
anon       — Stage 3+ 무료 · public read 일부
```

### 3.4 CORS `allow_origins` 검증

- `main.py` `allow_credentials=True` · 쿠키 인증 이관 시 **origin이 wildcard면 즉시 실패**
- SOPS env 명시 origin만 있는지 확인

## 4. 자산화 훅 (C · Stage 2 상품화 원천)

### 4.1 판정 4요소 컬럼 추가

`powderkeg_list` (및 향후 판정 테이블):
- `hypothesis_id: str` — 어떤 가설 버전으로 판정 (v2.0-powderkeg-6cond 등)
- `market_context: str` — VKOSPI·KOSPI 20MA 위/아래 등 자동 태깅
- `retrospect_url: str` — 승격 후 이벤트·매수·결과 링크

**백필 불요** — 신 판정부터 축적.

### 4.2 `conditions_json`에 margin 값 저장 의무화

- 현재 `{"1":true, ...}` boolean만 · `first-passed-result.md`에는 margin 있으나 DB에 없음
- 강등·복귀 추이 = **콘텐츠 소재**

### 4.3 `powderkeg_tier_history` 신설

- run 단위 스냅샷 대신 **종목별 시계열** view/table
- 경인전자 강등 (v2 정체성 부적합)처럼 tier 이동 자체가 인용 가능한 이벤트

### 4.4 `reject_reasons` 카테고리화

```
parsing_error       — 데이터 파싱 오류 (예: 서희건설 v1.0→v1.1 취소)
threshold_miss      — 규모·수치 임계 미달
hypothesis_revision — 가설 변경으로 강등
```

월 1회 집계 · Weekly Report 소재.

### 4.5 Obsidian sync 3경로 자동화

**Wiki 목적지**: `/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/`

```
Runs/{run_id}.md      — run 종료 훅 · 신규 승격·강등 diff
Weekly/{YYYY-Www}.md  — 매주 일 08:00 · 주간 종합
Tickers/{ticker}.md   — 승격 종목 첫 시 생성 · 이후 append
```

**패턴 복제**: `GON-LLM-Wiki/Goals/2026-1억-Sprint/gonnim-landing/scripts/sync-kickoff.ts` 기존 자동화 참조.

### 4.6 판정 근거 인용 가능 URL

- `optimus8.cafe24.com/insights/decision/{run_id}/{ticker}` permalink 신설
- 뉴스레터·리포트·컨설팅에서 직접 링크 가능

## 5. 관측성·확장 준비 (D)

### 5.1 Sentry + PostHog 무료 티어

- 배포 SHA `NEXT_PUBLIC_BUILD_SHA` 이미 노출됨
- Sentry로 라우트별 error rate · Stage 3 유료 SLA 근거
- PostHog로 페이지 방문·판정 저널 사용 패턴 tracking

### 5.2 감사 로그 `sniper_api_access` 실체화

- 현재 주석에만 존재 · 실 테이블 없음
- `auth.py`의 `logger.info` → DB write로 승격
- Stage 3~4 유료 사용자 감사 요구 대응

### 5.3 결제 훅 스텁 (Stage 3~4 대비)

```python
@router.post("/api/v1/webhooks/payment")
def payment_webhook(payload: dict):
    # Stage 3 이후 활성 · 지금은 200 반환 스텁
    return {"ok": True}
```

Stage 3 진입 시 `Account.subscription_id` 컬럼만 추가하면 활성.

### 5.4 백업·롤백

- SQLite 백업 스크립트 확증 (upbit-tradebot-mvp의 `scripts/backup.sh` 패턴 참조)
- Stage 3~4 유료 데이터 손실 방어선

## 6. 실행 순서

[[roadmap-12week]] 주 1~2 (아키텍처 리셋) + 주 7~8 (인증 이관) 참조.

**Dependency Graph**:
```
1.1 user_id + Alembic
       │
       ├─→ 2. URL 이원화 (라우트 이관 시 user_id 필요)
       │
       └─→ 4. 자산화 훅 (user_id·hypothesis_id 동시 필요)
              │
              └─→ 4.5 Obsidian sync (자산화 훅 완결 후)

3. 인증 이관 (독립 · 주 7~8)
5. 관측성 (독립 · 주 7~8)
```

## 7. 위임 · 다음 문서

- **Stage 1 재편·통계 규율 이식**: [[stage1-optimization]]
- **Sprint 매출 연동 (자산화 훅 활용처)**: [[sprint-revenue-integration]]
- **리스크 · 방어선**: [[risks-and-guardrails]]
