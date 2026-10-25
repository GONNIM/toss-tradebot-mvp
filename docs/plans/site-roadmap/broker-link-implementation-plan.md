# 「토스증권에서 열기」 · 「내 계좌」 · 실주문 안전 상황판 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목 옆 한 번 눌러 토스증권 웹 주문 화면으로 가고, 실주문 안전 상태와 내 증권 계좌 가는 길을 한 곳에서 본다 (주문은 사용자가 증권사 화면에서 직접).

**Architecture:** PR 1 = /sniper 안전 상황판 + /lab/execution 퇴역 (공개 /sniper/status 에 주문 대상 한 칸 추가). PR 2a = 서버 표 `toss_stock_code` · 하루 1회 배치 (공식 토스 Open API `GET /api/v1/stocks`) · 공개 읽기 API `/broker-links` · 관리자 수정 API. PR 2b = 화면 부품 `BrokerLink` · /biotech·/powderkeg 1차 자리 · /account.

**Tech Stack:** FastAPI · SQLAlchemy async (SQLite · `Base.metadata.create_all` 로 새 표 생성) · APScheduler (Asia/Seoul) · Next.js 14 · react-query v5.

**Spec:** `docs/plans/site-roadmap/broker-link.md` (사용자 승인 2026-10-25) · 이 계획 사용자 승인 2026-10-25 (「1025-06 계획 승인 · 직접 진행」)

## Global Constraints
- 사이트는 주문을 넣지 않는다 (정체성 원칙 1). 링크·알림 주변에 「지금·매수·매도·추천」 류 단어 금지.
- 링크 글자 「토스증권에서 열기 ↗」 · 새 탭 · `rel="noopener noreferrer"`.
- 국내 주소 `https://www.tossinvest.com/stocks/A{6자리}/order` · 토스 계좌 `https://www.tossinvest.com/account` · 검색 대체 `https://www.tossinvest.com/`.
- 미국: `verified=true` 인 코드만 `/stocks/{toss_code}/order`. 그 밖에는 검색 대체 + 티커 복사.
- 토스 API 는 서버 배치에서만 (토큰 1개 규칙 · 로컬 호출 금지). 공개 API 는 표만 읽는다.
- 수정·검증 API 는 `require_sniper_token`.
- 버전: PR 1 backend 0.3.3 · frontend 0.3.2 / PR 2a backend 0.3.4 / PR 2b frontend 0.3.3.
- 배포: PR 1 → 2a → 2b 순서로 각각 병합 (사용자 「2a·2b 먼저」) · PR 마다 Fable 「병합 승인됨」 · 피할 시각 05:55–06:45 · 09:00–09:15 · 16:40–17:15 · 18:00 앞뒤.

## Review Focus
1. 틀린 미국 코드로 다른 종목이 열림 → verified=false 는 주문 링크를 내지 않는다 (Task 7 테스트).
2. 공개 `/broker-links` 에 큰 symbols · 이상한 문자 → 422, 외부 호출 0 (Task 7 테스트).
3. 배치가 사람이 고친 값 (source=manual) 을 덮어씀 → 덮지 않는다 (Task 6 테스트).
4. 서버 토큰이 `token-revoked` 로 끊김 → 캐시를 지우고 다음 호출에서 재발급 (Task 5 테스트).
5. 로그인 전 /sniper Kill Switch 가 「대기」로 보임 → 「관리자 로그인이 필요합니다」 (Task 2 검사).
6. 국내 영문 섞인 코드 (예 0101N0) → 같은 `A{코드}` 규칙 · 6자리 영숫자만 허용 (Task 4 테스트 · 실제 열림은 배포 뒤 1건 확인).

---

## PR 1 · 1025-01 (브랜치 `feat/sniper-safety`)

### Task 1: 서버 — 주문 대상 칸 · Kill Switch 링크 /sniper
**Files:** Modify `backend/api/routes/sniper.py:58-90` · `backend/execution/kill_switch.py:64` · `backend/services/notification_settings.py:65` · `backend/api/main.py` (0.3.3) · Test `backend/tests/test_alerts_p0.py:216` · `backend/tests/test_execution_wording.py:47` · new `backend/tests/test_sniper_safety.py`
**Produces:** `/api/v1/sniper/status` 응답에 `"order_target": "paper" | "toss"` (env `EXECUTION_BROKER` · 기본 paper · 그 밖 값은 paper · signal_router.py:315-330 과 같은 규칙). order_target 은 어댑터 종류 표시이고, 주문이 실제로 나가는지는 결론 한 줄 (live_enabled 등) 이 담당한다.
- [ ] 실패 테스트: `test_status_order_target_default_paper` (env 없음 → "paper") · `test_status_order_target_toss` (env "TOSS" → "toss") · 기존 두 테스트의 `/lab/execution` 단언을 `/sniper` 로 바꿈.
- [ ] 실행 → FAIL 확인 → 구현 → `cd backend && venv/bin/python -m pytest -q tests/test_sniper_safety.py tests/test_alerts_p0.py tests/test_execution_wording.py` PASS → 커밋.

### Task 2: 화면 — 안전 상황판 (/sniper 맨 위)
**Files:** Create `frontend/lib/sniper-safety.ts` · `frontend/lib/sniper-safety.check.ts` · `frontend/components/sniper/SafetyPanel.tsx` · Modify `frontend/app/sniper/page.tsx` (「📊 전역 상태」 자리) · `frontend/lib/api.ts` (SniperStatus 에 order_target)
**Produces:** `safetyConclusion(s: {live_enabled: boolean; sniper_enabled: boolean; watchlist_enabled: boolean; kill_switch_active: boolean}): {tone: "stop" | "off" | "on"; text: string}`
- 문구 (고정): kill 발동 → stop 「Kill Switch 발동 중 — 자동 주문이 멈춰 있습니다」 · live 꺼짐 → off 「실주문 허용 꺼짐 — 실계좌 주문이 나가지 않습니다」 · 두 경로 모두 꺼짐 → off 「자동 진입 두 경로가 모두 꺼져 있습니다」 · 그 밖 → on 「자동 진입이 켜져 있습니다 (주문 대상: 모의|실계좌)」.
- 카드: 결론 한 줄 · 주문 대상 · 하루 손실 한도 (`/sniper/params` 의 `daily_loss_limit_pct` (-0.03) × 100 → 「-3.0%」) + 「오늘 손익은 계산 수리 뒤 표시 (1025-02)」 · Kill Switch 상태·사유·누가·언제 + 발동(사유 입력)·해제 버튼 (기존 `api.execution.killSwitch` 를 `api.sniper.killSwitch` 로 이름만 옮김) · 상태 조회 `retry: (n, e) => ![401,404].includes(e.status) && n < 2` · 401 이면 「관리자 로그인이 필요합니다」.
- [ ] `sniper-safety.check.ts` (tsx · 기존 `biotech-display.check.ts` 방식) 에 네 경우 문구 단언 · kill 이 다른 값보다 앞선다는 단언 → 실행 FAIL → 구현 → `npx tsx frontend/lib/sniper-safety.check.ts` PASS → `npx tsc --noEmit` 0 → 커밋.

### Task 3: 화면 — /lab/execution 퇴역
**Files:** Delete `frontend/app/lab/execution/` · Modify `frontend/next.config.mjs:53-54` (`/execution`·`/execution/:path*`·`/lab/execution`·`/lab/execution/:path*` → `/sniper`) · `frontend/lib/api.ts:753-805` (`execution` 묶음에서 killSwitch 만 `sniper` 로 옮기고 나머지 삭제 · 다른 호출처 0 확인 `grep -rn "api.execution" frontend/app frontend/components`) · `frontend/app/lab/page.tsx:63-68` (항목 → 「Sniper 안전 상황판으로 통합 (10/25)」 · href /sniper) · `frontend/package.json` 0.3.2
- [ ] grep 0 확인 → 수정 → `npx tsc --noEmit` 0 · `npm run build` 는 dev 서버가 꺼진 상태에서만 (켜져 있으면 tsc + dev 로그 + curl 로 대신 · PROFILE 42행) → 로컬 렌더 (API 전용 모드 · 텔레그램 끔): /sniper 비로그인·로그인 두 상태 · `/lab/execution` → `/sniper` 이동 · 콘솔 오류 0 → 커밋 → PR 1.

---

## PR 2a · 1025-06 서버 (브랜치 `feat/broker-codes`)

### Task 4: 표와 주소 규칙
**Files:** Modify `backend/services/models.py` (끝에 `TossStockCode`) · Create `backend/services/broker_links.py` · Test `backend/tests/test_broker_links.py`
**Produces:**
- `TossStockCode` (`__tablename__="toss_stock_code"`): `symbol` str(16) PK · `toss_code` str(20) nullable · `list_date` str(10) nullable · `source` str(8) ("api"|"manual") · `verified` bool default False · `updated_at`.
- `toss_code_from_list_date(list_date: str | None) -> str | None` → `"2026-01-02"` → `"US20260102001"` · None/형식 오류 → None.
- `is_kr_code(sym: str) -> bool` (6자리 영숫자 · 숫자 1개 이상).
- `broker_link(symbol: str, row: TossStockCode | None) -> dict` → `{"symbol", "kind": "order"|"search", "url", "verified": bool}`. KR → order `…/stocks/A{sym}/order` (verified True). US + row.verified + toss_code → order. 그 밖 → search `https://www.tossinvest.com/`.
- [ ] 테스트: `test_code_from_list_date` (`"1981-05-27"` → `"US19810527001"` · None · `"1981/05/27"` → None) · `test_kr_link` (005930 · 0101N0) · `test_us_unverified_is_search` · `test_us_verified_is_order` · `test_lowercase_and_junk` (`"aapl"` → 대문자 처리 · `"A;B"` → ValueError) → FAIL → 구현 → PASS → 커밋.

### Task 5: 토스 종목 조회 · token-revoked
**Files:** Modify `backend/execution/brokers/toss_client.py` (267-283행 근처 · 189행) · Test `backend/tests/test_toss_client_stocks.py`
**Produces:** `TossClient.stocks(symbols: list[str]) -> list[dict]` (`GET /api/v1/stocks` · `symbols` 콤마 · 최대 200 · `use_account_header=False` · 응답 `result` 목록 그대로).
- 189행 조건에 `"token-revoked"` 추가 (캐시 삭제 + BrokerCommunicationError).
- [ ] 테스트 (httpx MockTransport · 실제 호출 없음): `test_stocks_no_account_header` · `test_stocks_over_200_raises` · `test_token_revoked_clears_cache` → FAIL → 구현 → PASS → 커밋.

### Task 6: 하루 1회 배치
**Files:** Modify `backend/services/broker_links.py` · `backend/scheduler/cron.py:798-830` (`refresh_toss_stock_codes` · `CronTrigger(hour=7, minute=40)` · id `toss_stock_codes_daily`) · Test `backend/tests/test_broker_links.py`
**Produces:** `async refresh_toss_stock_codes(client=None, symbols: list[str] | None = None) -> dict` (`{"asked", "found", "missing", "skipped_manual"}`).
- 대상: symbols 를 주지 않으면 최신 레이더 CSV 티커 (`backend/api/routes/biotech.py:311` `_latest_radar_csv` 를 `backend/services/biotech_files.py` 로 옮겨 두 곳이 같이 씀) 중 KR 이 아닌 것.
- 표 생성은 api 프로세스 `init_db` (backend/api/main.py:86 · create_all) 가 한다 · cron 프로세스는 만들지 않는다 · 배포가 두 서비스를 같이 재시작하므로 첫 07:40 전에 표가 있다. 테스트는 빈 DB 에서 init_db 뒤 실행.
- 소문 카드·종목 상세의 티커가 레이더 CSV 밖이면 표에 없으므로 검색 대체로 보인다 (안전 · 의도).
- `_latest_radar_csv` · `_search_dirs` · `_latest` · `DATA_DIR_RUNTIME` 이동은 글자 그대로 (패턴 `radar_v1_3_????????.csv` · 순서 RUNTIME > docs > backend/data) · biotech 테스트 묶음 통과.
- source=manual 은 건드리지 않음 · source=api 행 (찾은 것·못 찾은 것 모두) 은 updated_at 기준 7일 뒤에만 재조회 · 못 찾은 종목은 toss_code None 으로 저장 · 결과 로그 한 줄 `[broker-links] asked=… found=… missing=… manual=…` · WEN 이 대상에 있으면 list_date 를 로그에 함께 (대조 ①).
- [ ] 테스트 (가짜 client): `test_refresh_creates_rows` · `test_refresh_keeps_manual` · `test_refresh_missing_saved_null` · `test_refresh_batches_200` → FAIL → 구현 → PASS → 커밋.

### Task 7: API
**Files:** Create `backend/api/routes/broker_links.py` · Modify `backend/api/main.py` (include `/api/v1/broker-links` · 0.3.4) · Test `backend/tests/test_broker_links_api.py`
**Produces:**
- `GET /api/v1/broker-links?symbols=AAPL,005930` (공개 · 최대 50 · 각 1~12자 `[A-Za-z0-9.\-]` · 표만 읽음) → `{"links": [broker_link(...)]}`.
- `GET /api/v1/broker-links/codes` (토큰) → 미국 행 목록 (verified 거짓 먼저).
- `PUT /api/v1/broker-links/{symbol}` (토큰) body `{"toss_url": str | None, "verified": bool}` → `US\d{11}` 를 주소에서 뽑아 source=manual · 없으면 422.
- [ ] 테스트: `test_get_public_reads_table_only` (토스 client 를 부르면 실패하는 가짜로 패치) · `test_get_too_many_422` · `test_get_bad_chars_422` · `test_put_requires_token` · `test_put_parses_url` (`https://www.tossinvest.com/stocks/US19810527001/order` → `US19810527001`) · `test_unverified_us_is_search` → FAIL → 구현 → 전체 `venv/bin/python -m pytest -q` (기존 실패 6건 외 0) → 커밋 → PR 2a.

---

## PR 2b · 1025-06 화면 (브랜치 `feat/broker-link-ui`)

### Task 8: 부품
**Files:** Create `frontend/lib/broker-link.ts` · `frontend/lib/broker-link.check.ts` · `frontend/components/BrokerLink.tsx` · Modify `frontend/lib/api.ts` (`brokerLinks.get(symbols: string[])` · `codes()` · `put(symbol, body)`)
**Produces:** `useBrokerLinks(symbols: string[])` (react-query · 한 화면 한 번 묶음 요청 · staleTime 1시간) · `<BrokerLink symbol links />` → kind order 면 「토스증권에서 열기 ↗」 새 탭 · search 면 「토스증권 검색에서 찾기 ↗」 + 누를 때 티커 클립보드 복사 (실패해도 이동).
- [ ] check: `krOrderUrl("005930")` · 글자 두 가지에 금지어 (지금·매수·매도·추천) 없음 단언 → FAIL → 구현 → PASS → tsc 0 → 커밋.

### Task 9: 1차 자리
**Files:** Modify `frontend/app/biotech/page.tsx` (레이더 표 티커 칸 112행 · 소문 카드 머리 159행 근처 · 종목 상세) · `frontend/app/powderkeg/page.tsx` (Tier 1 표 행 · KR 은 API 없이 `krOrderUrl`)
- [ ] 수정 → tsc 0 · build (dev 서버 꺼진 상태에서만) → 로컬 렌더 두 화면 (로그인 뒤) · 링크 주소가 규칙대로인지 3건 확인 → 커밋.

### Task 10: /account
**Files:** Create `frontend/app/account/page.tsx` · Modify `frontend/components/layout/AppNav.tsx` (「💼 Positions」 옆 「내 계좌」) · `frontend/package.json` 0.3.3
- 내용: 토스증권 (계좌 바로 가기 새 탭 · 이 사이트의 토스 실계좌 보유 요약 = 기존 `/api/v1/dashboard/toss-account` 재사용 · 로그인) · 카카오페이증권 안내 한 줄 「휴대폰 카카오페이 앱 → 증권에서 ISA·ETF 를 확인하세요」 (QR 은 앱 주소 확인 뒤 · 이번 범위 아님) · 안전 한 줄 (`safetyConclusion` · 「자세히: /sniper」) · 미국 코드 확인 표 (codes · 토스 주소 붙여 넣기 · 「확인함」 → verified).
- [ ] 수정 → tsc 0 · build (dev 서버 꺼진 상태에서만) → 로컬 렌더 비로그인·로그인 → 커밋 → PR 2b.

## 배포 뒤 확인 (각 PR)
- PR 1: 운영 /sniper 결론 한 줄 「실주문 허용 꺼짐…」 · `/lab/execution` → `/sniper` · 1022-06 발동→해제 1회 (사용자).
- PR 2a: 다음 07:40 배치 로그 1줄 (사용자에게 /admin 또는 서버 로그 요청) · WEN list_date 대조 ① → 결과 (US19810527001 의 일자 일치·불일치) 를 PR 2b 병합 승인 요청에 한 줄로 적는다. 불일치면 `toss_code_from_list_date` 수정은 별도 PR 이고, 그 전까지 verified 는 수동만.
- PR 2b: 맥북에서 바이오 미국 5종목을 토스 주소와 대조 (대조 ②) → /account 에서 확인함 · 화약고 국내 1종목 열림.
