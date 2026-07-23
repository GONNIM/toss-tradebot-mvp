# P2-1 · 상폐 재무 백필 · 구현 계획서

**작성일**: 2026-07-23
**우선순위**: 🥉 우선순위 3 · P2-2 PIT 층화 백테스트의 결정적 선행 의존성
**예상 소요**: **코드 5~7h** + **백필 실행 자연 대기 반나절** (원 추정 2~3일 → KIND 실측으로 대폭 단축)
**의존/후속**: 완료 후 P2-2 as-of 재무 조회 구현 가능

## 0. 계획 변경 · v1.1 (2026-07-23)

**원 계획 v1.0의 파괴 · 재설정**:
- v1.0의 상폐 후보 추출 · `DartCorpCodeMap.stock_code IS NULL` → **실측 파괴** (66,271건 · 대부분 비상장 회사 · 상폐 아님)
- KrxMarketSnapshot 히스토리 · 2일치만 · 상폐 감지 불가
- data.krx.co.kr JSON API · 2026 로그인 봉쇄 (P4-5 기록)

**v1.1 채택 소스** · **KIND `delcompany.do`** 실측 통과
- URL: `https://kind.krx.co.kr/investwarn/delcompany.do` (POST `forward=delcompany_down`)
- 응답: EUC-KR HTML `<table>` · **6자리 종목코드 직접 제공 → 회사명 매핑 불필요**
- 5년치 전체 393건 · KOSPI+KOSDAQ 공통주 311건 · 이관성 제외 후 236건

---

## 1. 목적 · 배경

### 필요 이유
P2-2 PIT 층화 백테스트는 **이벤트 시점에 상폐 회사도 후보로 남아야 생존 편향이 해소**된다. 현재 `FinancialSnapshot`에 상폐사 재무가 없어 as-of 조회를 해도 상폐 종목이 누락 → 생존 편향 재발.

### 3rd-review-response.md §10 P2 명시
> "PIT 로 재설계하면 표본 문제도 자동 해결. **단, 상폐 재무 백필이 진짜 선행**."

### 현 준비 상태
- ✅ `FinancialSnapshot.is_delisted`, `delisted_at` 컬럼 이미 존재 (v1.30 · 커밋 6314ec0)
- ✅ `DartCorpCodeMap` 테이블 (100k+ 항목) · 상폐사 포함 · `stock_code IS NULL` 이 상폐 후보
- ✅ DART API 접근 · 상폐 회사도 corp_code 유지 · 재무 조회 가능
- ❌ 수집기 · 배치 API · 진행 저장 · 이번 P2-1 범위

---

## 2. 예상 규모 (v1.1 · KIND 실측 반영)

- 최근 5년치 KIND `delcompany.do` 전체 393건 (KOSPI 49 + KOSDAQ 262 + KONEX 82)
- **Powderkeg 대상 (KOSPI+KOSDAQ 공통주): 311건**
- 이관성 사유 (이전상장·피흡수합병·완전자회사·스팩·해산·재상장) 제외 후: **236건**
- 각 종목 최근 3년치 · 재무 236 × 3 년 × 3 report_code ≈ 2,124 콜 + 최대주주 708 콜
- **총 ~2,832 API 콜**
- DART 무료 계정 일 상한 여유 · **반나절 이내 완결 가능** (안전 sleep 300ms 유지)

---

## 3. 설계

### 3.1 상폐 후보 추출 (v1.1 · KIND delcompany.do)

**전략**: KIND `POST /investwarn/delcompany.do` · `forward=delcompany_down` · EUC-KR HTML 파싱
- 파라미터: `currentPageSize=3000` · `fromDate=<5년전>` · `toDate=<오늘>` · `tabType=1` · `marketType=` (전체)
- 응답 컬럼 6: 번호 · 회사명 · **종목코드(6자리)** · 폐지일자 · 폐지사유 · 비고
- Referer 필수 (P4-5와 동일 패턴)

**이관성 필터** (재무 백필 대상 축소):
```python
EXCLUDE_KEYWORDS = ['이전상장','피흡수합병','완전자회사','유가증권시장 상장','스팩','해산 사유']
# → 311 → 236 (부실 상폐 위주)
```

**corp_code 매핑**: 기존 `corp_codes.py:60 resolve_corp_code(ticker)` 재사용 (`DartCorpCodeMap.stock_code == ticker` · 매칭률 95~99%)

**대안 기각 (v1.0 v1.1 변경 사유)**:
- ~~`DartCorpCodeMap.stock_code IS NULL` 필터~~: 66,271건 대부분 비상장 · 상폐 신호 아님 (실측)
- KRX MDCSTAT23801: 2026 로그인 봉쇄
- pykrx/FDR: 상폐 리스트 미지원

### 3.2 상폐사 목록 collector 신규 · `backend/powderkeg/collectors/krx_delisted.py` (신규)

P4-5 `krx_admin_issue.py` 템플릿 재사용:
- `fetch_delisted_list(from_date, to_date) -> list[dict]` · KIND POST + EUC-KR 파싱
- 응답 dict: `{ticker, corp_name, delisted_date, reason, note}`
- Referer + User-Agent · retry 2회

**신규 모델** · `PowderKegDelistedIssue`
- id, ticker, corp_name, delisted_date, reason, note, snapshot_date, refreshed_at
- append-only (매 크롤링마다 새 row)

### 3.3 상폐사 재무 수집기 · `backend/powderkeg/collectors/dart_financials.py` (확장)

신규 함수: `collect_delisted_financials(tickers, years, sleep_ms=300) -> dict`
- 각 ticker → `resolve_corp_code(ticker)`로 corp_code 확보 → 기존 재무 조회 재사용
- 저장 시 `is_delisted=True`, `delisted_at=최근 재무의 reference_date` 자동 세팅
- 재시도 · 실패 tolerance · errors[] 축적 · 부분 성공 허용
- rate control · sleep_ms 기본 300ms

### 3.4 배치 트리거 API 2종

**A. 상폐사 목록 갱신** · `POST /powderkeg/collectors/krx-delisted-refresh` (인증)
- 파라미터: `from_date`, `to_date` (기본 최근 5년)
- 응답: `{snapshot_date, total, kospi, kosdaq, konex, excluded_transitional, target_candidates}`

**B. 상폐사 재무 백필** · `POST /powderkeg/collectors/dart-financials-delisted-batch` (인증)
- 파라미터: `years` (기본 [2023, 2024, 2025]) · `limit` (기본 50) · `offset` (기본 0) · `dry_run` (기본 False)
- 응답: `{total_candidates, processed, matched, errors, next_offset, elapsed_sec}`

### 3.5 진행 저장 (재개 지원)

**신규 모델 · `PowderKegDelistedBackfillProgress`**
- id · run_id (YYYYMMDD-HHMMSSK)
- last_offset · total_candidates · inserted · errors
- status (running/paused/done/error)
- updated_at

### 3.5 테스트 · `backend/tests/test_powderkeg_delisted_backfill.py` (신규)

- `collect_delisted_batch` 단위 (mock DART 응답)
- is_delisted=True 저장 검증
- Progress row upsert
- API 트리거 응답 스키마

### 3.6 migrate-schema · 신규 progress 테이블 idempotent CREATE

기존 패턴대로 `direct_creates` 리스트에 추가.

---

## 4. 배포·백필 실행 절차

1. **로컬 완료** (코드 6h)
2. **커밋 · push → GHA 자동 배포 v1.40**
3. **migrate-schema 트리거** (신규 progress 테이블 생성)
4. **1차 배치 트리거** — dry_run=True 로 상폐 후보 수 실측
5. **본 배치 시작** — offset=0 · limit=100 · sleep=300ms (배치당 ~30분)
6. **자연 대기 2~3일** — 매일 오전에 next_offset 진행 · 진행률 API 로 모니터링
7. **완료 후** — Full FinancialSnapshot 개수·is_delisted 카운트 실측 · P2-2 as-of 구현 진입 준비

---

## 5. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| DART API 일 콜 상한 초과 | 배치 크기 100 + sleep 300ms · 실 부하 ~200콜/분 |
| 상폐 corp_code에 재무 미제공 | 실패 tolerance · errors 카운트 · 부분 성공 허용 |
| 신규 테이블 마이그레이션 실패 | migrate-schema idempotent 재사용 |
| 백필 중 서버 재시작 | Progress 테이블 cursor 저장 · 재개 API |
| 상폐 후보가 예상보다 많음/적음 | dry_run 으로 사전 실측 · 계획 조정 여지 |
| 재무 필드 누락 (구식 종목) | 기존 dart_financials 관대한 파싱 그대로 · null 허용 |

---

## 6. 완결 정의 (Done Criteria)

- [ ] 상폐 후보 추출 SQL 실측 (dry_run) · 후보 수 확증
- [ ] `collect_delisted_batch` 함수 · pytest 통과
- [ ] `POST /collectors/dart-financials-delisted-batch` API 실 응답 스키마 OK
- [ ] `PowderKegDelistedBackfillProgress` 모델 + migrate-schema idempotent
- [ ] 신규 pytest 통과 · 회귀 없음
- [ ] 단일 배포 v1.40 · SSR SHA + 신규 API 실측 통과
- [ ] 1차 dry_run 완료 · 후보 수 리포트
- [ ] 백필 실행 시작 (offset=0 · limit=100)
- [ ] 최종 완료 시 · FinancialSnapshot is_delisted=True 카운트 실측 (~2,700 목표)
- [ ] `next-session.md` 완료 표시 · 본 계획서 개정 이력 갱신

---

## 7. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-23 | v1.0 | 신규 · 사용자 승인 (A 옵션) 후 저장 |
| 2026-07-23 | v1.1 | dry probe 실측으로 v1.0 파괴 · KIND `delcompany.do` 채택 · 236 종목 · 반나절 백필 (기존 2~3일 대폭 단축) |
| 2026-07-23 | v1.2 | 로컬 구현 완료 · collector(393건 실측) + 재무 확장(collect_delisted_financials) + API 3종 + pytest 6/6 + 회귀 없음 · 배포 대기 |
