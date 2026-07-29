---
title: Perspective D · 아키텍처·사업모델 리뷰 (원본 아카이브)
type: review-archive
status: reference
created: 2026-07-29
reviewer_persona: "12년 경력 SaaS·정보 서비스 아키텍트 겸 사업개발 컨설턴트 · Notion·Linear·Superhuman 초기 결정 관찰"
scope: 현 아키텍처의 Stage 확장 대응력 · 데이터 격리 · Revenue-Tree 훅 · 배포·운영 성숙도
word_limit: 600
---

# Perspective D · 아키텍처·사업모델 리뷰 (원본)

## 1. 핵심 판단

현 아키텍처는 **"1인 소유자 + 관리 콘솔" 패턴**에 완전 최적화되어 있다. 강점: FastAPI 라우트 조직·SQLAlchemy 모델 분리·SOPS 배포·`require_sniper_token` 이중 스위치(토큰 + LIVE_ENABLED)까지 개인 도구로는 상위 5% 성숙도. 그러나 Stage 3(하이브리드) 진입 순간 3가지가 리라이트를 강제한다: **(a)** 인증이 "공유 비밀 하나 = 관리자"라 다중 사용자 개념 자체가 없음(models.py의 `user_id: String(50)`은 존재하나 `"default"` 고정 사용 · 라우트에서 참조 0건 확인). **(b)** SQLite 단일 파일 + FastAPI 스케줄러 프로세스 내 co-located · 외부 무료 사용자 트래픽 유입 시 write lock으로 스케줄러가 밀린다. **(c)** localStorage 토큰 저장(sniper/watchlist/powderkeg 3개 페이지 확인) · XSS 1건이면 실주문 토큰 유출. Notion·Linear 초기 조언과 동일: **user_id를 지금 안 넣으면 Stage 3에서 데이터 재구성 6~8주**. 지금 하면 3일.

## 2. Stage 1 최적화 · 7개 권고

1. **[Stage 3 재작업 회피 A] `user_id` 컬럼을 지금 전 discovery/판정 테이블에 추가** — `CrazyPick`·`MoonshotPick`·`Watchlist`·`PowderKegList`·`SuperSignal`·`SniperSignal`·`MemeAlertHistory` 7개에 nullable `user_id: str = "owner"` 기본값. 지금은 값 하나만 쓰지만 컬럼·인덱스·복합 unique(`ix_watchlist_date_ticker` → `date+ticker+user_id`)를 미리 잡아둔다. 안 하면 나중에 라이브 데이터에 backfill + 인덱스 재빌드 · 다운타임 필수.
2. **[Stage 3 재작업 회피 B] 라우트 prefix 이원화** — `/api/v1/` 아래 지금 뒤섞인 것을 `/api/v1/admin/*`(require_sniper_token 필수) vs `/api/v1/read/*`(GET 공개)로 분리. 파일은 그대로 두고 `main.py`의 include_router prefix만 재편. 지금 3시간, Stage 3에서 유료·무료 분기 넣을 때 라우트 renaming으로 CDN·검색엔진·백링크·문서 전체 무효화 방지.
3. **localStorage 토큰 → 쿠키 이관 준비** — sniper/watchlist/powderkeg의 `localStorage.getItem(TOKEN_KEY)` 3곳 발견. 지금 단일 사용자라 위험 낮지만, 코드에서 토큰을 직접 읽는 위치가 3+ 페이지에 분산되면 Stage 2 이관 시 페이지 수만큼 QA 필요. `lib/auth.ts` 하나로 통일해 `getToken()`/`setToken()` 함수만 노출.
4. **Alembic 활성화** — `backend/scripts/migrations/`에 파일 1개(P2)만 존재 · `venv`에는 alembic 설치. 지금 스키마 변경을 `Base.metadata.create_all()`로 하고 있어 컬럼 추가 시 수동 SQL이 서버에서 필요(deploy-optimus8 skill이 그것). 권고 1의 `user_id` 추가 자체가 첫 정식 Alembic 마이그레이션 트리거가 되어야 함.
5. **SQLite → Postgres 전환 스위치를 지금 코드에 반영** — `services/db.py`의 URL 하드코딩(추정) 여부와 무관하게 `DATABASE_URL` env로 통일. FastAPI 스케줄러 + 판정 배치 + 웹 read가 동일 SQLite 파일에서 read/write 경합. Postgres로 전환 자체는 Stage 2까지 미뤄도 되지만 **connection string 추상화는 지금**.
6. **감사 로그 표준화** — `audit_trades`·`order_audit`·`Log`·`sniper_api_access`(주석에만 존재, 실체 없음) 4개가 혼재. `sniper_api_access` 테이블을 실제로 만들고 auth.py의 `logger.info` 대신 DB write로 승격. Stage 3~4 유료 사용자 감사 요구 대응.
7. **CORS `allow_origins=config.cors_origins()` 검증** — `main.py` line 168, `allow_credentials=True`. 쿠키 인증 이관 시 origin이 wildcard면 즉시 실패. 지금 명시 origin만 있는지 SOPS env 확인 필요.

## 3. Stage 2 이행 준비 · 4개 결정

1. **판정 이력 API를 read-only public + JSON schema 확정** — `/api/v1/read/watchlist/{date}`·`/read/powderkeg/{run_id}` 형태. Sprint Radar가 이 판정 이력을 사업 아이템 스코어링 근거로 흡수할 접점 확정(사용자 요청 3번). 지금 스키마 잠그면 T2(단발 리포트) 자동 생성 시 재작업 0.
2. **Stripe/Toss Payments webhook endpoint 스텁** — `/api/v1/webhooks/payment` POST 라우트만 지금 생성(200 반환). Stage 3 진입 시 `subscription_id` 컬럼을 `Account`에 추가하면 됨. T1 반복 매출 훅.
3. **Postgres 이관 결정 마감일 설정** — Stage 2 발동 조건(외부 사용자 1명이라도 read API 히트) 관측되는 순간 Postgres. SQLite 백업(`backup.sh` 미확인)이 Stage 3 데이터 손실 방어선 부족.
4. **관측성 · Sentry + PostHog 무료 티어** — 배포 SHA는 이미 `NEXT_PUBLIC_BUILD_SHA` 노출됨. Sentry로 라우트별 error rate만 붙여도 Stage 3 유료 SLA 근거 확보.

## 4. 폐기·비판

- **`docs/plans/tradebot-tobe/tradebot-tobe-prompt.md` 전량 폐기 확정**. Phase 6 "보안 하드닝 5항"만 살릴 것: (1) 실주문 rate limit(FastAPI slowapi), (2) 감사 로그 DB화(권고 6과 동일), (3) 토큰 로테이션 절차, (4) SOPS age key backup, (5) `/health` 외 인증 없는 라우트 인벤토리 작성. Phase 0 backtest 인프라는 이미 `backend/backtest/engine.py`·powderkeg 백테스트로 실현됨 · 재수집 불필요.
- **`accounts`·`orders`·`AuditTrade` 3개 테이블(models.py 396~476)의 "Phase K 후 활성" 주석 삭제**. 실체는 있으나 라우트 참조 0건 확인. 현 정체성("급등주 사전 예측")과 무관 · Stage 3에서 유료 실주문 붙일 때 다시 설계할 것이므로 지금 dead code로 남기지 말고 `models_legacy.py`로 격리 또는 삭제.
- **`live_tape_ranking`·`SniperSignal` — 사용자 메모리 `strategic_pivot_pre_market`에 따라 Sprint 1 real-time tape 폐기됨**. 테이블은 남았으나 스케줄러 활성 여부 재점검. 폐기면 삭제, 유지면 주석 갱신.
- **frontend `/execution`·`/super-signals`·`/crazy`·`/moonshot` 4개 페이지 — layout.tsx에서 이미 nav 제거**되었으나 라우트·API 라우트 모두 살아있음. dead code · Stage 3 감사 시 부담. `execution.py`·`super_signals.py`·`crazy.py`·`moonshot.py` 라우트를 `main.py`에서 include 제외.

## 5. 리스크 3개

1. **XSS 1건 = 실주문 토큰 탈취** — localStorage + SNIPER_LIVE_ENABLED=true 조합 시 즉시 자금 손실. 현 단계에도 Playwright 등으로 실사 필요.
2. **SQLite write lock으로 스케줄러 정체** — powderkeg·watchlist·meme·sniper 잡이 동일 프로세스 · 동일 파일. 판정 배치가 read API 하나 붙자마자 뒤로 밀리는 사고 발생 가능. 로컬에서 재현 안 됨.
3. **Alembic 없이 스키마 변경 누적** — models.py에 1200라인, 실 DB와 drift 검증 없음. Stage 3 진입 직전 "정합성 재구축 스프린트"에 2주 소요될 위험.
