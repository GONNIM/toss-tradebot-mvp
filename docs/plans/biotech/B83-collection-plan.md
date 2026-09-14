# B83 · H3 폐지 종목 수집 재편성 계획 (Tiingo 1차 · SimFin 폴백)

**작성**: 2026-09-04 · **실행**: **없음** · Fable 검수 후
**전제**: B85 재판정 (v2.1) · Tiingo 18/20 PASS · SimFin 14/20 FAIL · **합집합 20/20 = 100% (v4 표본)**
**대체**: 이전 `B83-reduced-verification-draft.md` (전 소스 FAIL 시나리오 · 폐기 대상)

## 1. 판정 근거 (오프라인 재판정)

- 판정식 v2.1 · `first_bar ≤ 창시작+7d AND last_bar ≥ event-30d`
- Tiingo v2 11/20 → v2.1 **18/20 PASS** (+7 upgraded)
- SimFin v2 9/20 → v2.1 **14/20 FAIL** (+5 upgraded)
- Alpha Vantage: **미측정** (응답 본문 미보관 · B86 재분류)
- **합집합 Tiingo ∪ SimFin: 20/20 = 100%** (교집합 12 · Tiingo only 6 · SimFin only 2)
- 집단별 v2.1 합집합: acquired 15/15 · bankrupt 3/3 · delisted 2/2

## 2. 수집 대상 (B87 수정 · 2026-09-04)

**원장 140 delisted 바이오 · 전량 대상** (Fable 승인 · 깊이 통일 재수집):
- kept 5 (깊이 통일 재수집 · Tiingo/SimFin 로 EODHD 대체)
- data_lost_overwrite 13 (재수집)
- queued_v3 74 (신규 수집)
- hold_similar 9 (후보 심볼 순차 시도)
- B60_pending 39 (Tiingo/SimFin 재시도 후 잔여만 B60_pending 유지)

**본 계획 대상**: **원장 140 전량**

## 2a. 수집 창 (B87-1-1 · 수정)

- **티커당 `2020-01-01 ~ form25_date+30d` 전 구간 수집**
- 테스트용 `event-365 ~ event` 창 사용 금지 (백테스트 D-30~D+180 창 보전 목적)
- 절단: `form25_date + 30d` 초과 바 제거 (B74 절단 규약 · 재활용 심볼 오염 차단)

## 2b. adj_close 컬럼 (B87-1-2)

- Tiingo `adjClose` 필드 저장
- SimFin: 조정가 필드 확인 후 저장 · 부재 시 raw 만 저장 + 컬럼에 명시
- **수익률 계산은 adj_close 기준**
- CSV 스키마: `ticker · date · open · high · low · close · adj_close · volume · source`

## 2c. bar_density 컬럼 (B87-1-4)

- `bar_density = 실 바 수 / 기간 거래일 추정` (기간 거래일 = 총일수 × 252/365)
- 자동 격리 없음 · **LIPO 류 (신규 상장 · 짧은 이력) 사례 식별용**
- B74 검증 (first ≤ form25-90d) 은 유지

## 3. 수집 순서

### 3-1. Tiingo 1차 (전건)
- 87 티커 × 1 call = 87 calls (Tiingo 무료 한도 1,000/day · 여유)
- 500 unique symbols/월 한도 유의 · 이번 한 번 87 소진 (여유 413)
- 창: event_date - 365 ~ event_date · v2.1 판정
- 실패 (NOT_FOUND · 부분 커버) 만 다음 단계

### 3-2. SimFin 2차 (Tiingo 실패분만)
- v4 표본 기준 Tiingo 실패 2 (AKUS/AVEO NOT_FOUND) · 원장 87 적용 시 ~5~10% 예상 = 5~10건
- SimFin 500 credits/월 한도 · 5~10건 소진 · 여유

### 3-3. 양소스 모두 실패분
- B60 표지 파싱 대상 잔류 (별건 · SEC 쿨다운 후)
- 예상: 원장 87 중 소량 (v4 표본 20/20 커버 · 원장 확장 시 일부 증가 가능)

## 4. 활성 종목 (yfinance 재수집 불요)

- yfinance 194/194 완주 (B81 무결성 확인 · 285,382 rows · avg 1,471 rows/ticker)
- **재수집 금지** · 통합기 병합 시 그대로 유지

## 5. 편향 방향 정량화 (미커버 잔여분 분석)

**표본 대비 (v4 20)**:
- 미커버 0/20 (v2.1) · 편향 방향 미측정 필요 없음 (합집합 100%)

**원장 확장 시 예상 (140)**:
- Tiingo NOT_FOUND 은 대체로 오래된 폐지 or 티커 재활용 사례
- 원장 대상 87 중 예상 미커버 = 5~10건 · 인수/파산 비율 사전 산출:
  - 원장 87 대상 (data_lost_overwrite 13 + queued_v3 74) 의 event_type 분포 별도 산출 필요
  - 미커버 인수 비율 > 파산 비율 이면 알파 판정 편향 방향 = 인수 프리미엄 저평가

## 6. 수집 소요 추정

- Tiingo 87 calls × ~1 sec/call (rate limit 관용적) = **~2~3분**
- SimFin fallback ~5~10 calls × ~1 sec = **~10초**
- 총 수집: **~3분** (실 실행 시)
- 저장: `h3_prices_{sha}_{date}_run{N}.csv` (B81 실행별 파일)
- 통합기: `biotech_h3_merge_prices.py` (중복 dedupe · 최신 우선)

## 7. 판정 규칙 (수집 시)

- 판정식 v2.1 적용 (B84)
- 통과분만 h3_prices 적재 · 실패 quarantine 직행 (`h3_prices_quarantined_raw_*.csv`)
- 원장 즉시 갱신 (`update_ledger_status()` · kept 전환)

## 8. Fable 검수 대기 사항

- [ ] 수집 대상 87건 (data_lost_overwrite 13 + queued_v3 74) 승인
- [ ] Tiingo 1차 · SimFin 2차 순서 승인
- [ ] hold_similar 9 · B60_pending 39 별건 처리 승인
- [ ] AV 재측정 승인 (본문 보관 컬럼 신설 후 · 후순위)
- [ ] 실제 실행 시점 승인 (Tiingo 500 unique/월 · 87 소진 후 잔여 413)

## 9. 관련 CSV

- `backend/data/biotech_coverage_test3_add7af7_2026-09-04.csv` (원 실측)
- `backend/data/biotech_coverage_test3_rejudge_add7af7.csv` (v2.1 재판정)
- `backend/data/h3_delisted_ledger_v2_add7af7.csv` (원장 140)
- `backend/data/h3_prices_merged_add7af7.csv` (기존 병합 · 199 tickers)
- `docs/plans/biotech/SOURCES.md` (Tiingo PASS · SimFin FAIL · AV 미측정)
- `docs/plans/biotech/README.md` §4 (B84 판정식 v2.1)
