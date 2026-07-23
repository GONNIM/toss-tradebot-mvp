# P2-2 · PIT 층화 백테스트 재설계 · 구현 계획서

**작성일**: 2026-07-23
**우선순위**: 🥉 우선순위 3 · P2-1 완료 후 후속
**예상 소요**: 5~7h
**의존/후속**: P2-1 상폐 재무 백필 완결됨 (v1.40 · 322 rows · 136 tickers) → 이제 착수 가능

---

## 1. 문제 (실 코드 실측)

`backtest.py:106-127` 의 `run_stratified_backtest(stratum="powderkeg_passed")` 는 **오늘 최신 run의 passed 종목만** `ticker_filter`로 사용:
- 이벤트가 2024-05-15 발생 · 그 종목이 지금 상폐 → 필터에서 제외 (**생존 편향**)
- 이벤트 당시엔 화약고 아니었지만 지금 화약고 → 포함 (**look-ahead bias**)

두 편향이 CAR·검증 게이트 결과를 왜곡함. P2-2 목표는 **각 이벤트 시점에 화약고였던 종목만 표본에 포함**.

---

## 2. PIT 소스별 실측 가능 여부

| 조건 | 원천 | as-of 조회 |
|---|---|---|
| 2 net_cash · 5 audit · 7 op_profit · 8 fscore · 6 cash_reality | `FinancialSnapshot` (P2-1 상폐 포함) | ✅ 완결 |
| 3 owner_pct | `MajorShareholder.reference_date` | ✅ 완결 |
| 4 not_big_biz | `BigBusinessGroup` (연 단위 seed) | ⚠️ 연 오차 |
| 1 pbr · 9 adv60 | `KrxMarketSnapshot` (2일치만) | ❌ PIT 불가 |
| 10 no_bad_history | `PowderKegKrxIssue` (오늘 1일치) | ❌ PIT 불가 |

## 3. 설계 (Phase 1 실용 접근)

### 3.1 원칙
- **재무·지분·대기업 5조건은 as-of 평가** (2·3·5·6·7·8 + 4는 연 근사)
- **시장(1·9)·관리(10) 3조건은 이벤트 시점 데이터 부재** → 관대 처리 (통과 가정)
- 결과 리포트에 `unmeasured_conditions` 명시 · 사용자가 결과 해석 시 인지

### 3.2 신규 함수 · `backend/powderkeg/backtest.py`

**`async def pit_evaluate(ticker, as_of_date, year=None) -> tuple[bool, dict]`**
- `_as_of_financial(ticker, as_of_date)` · `FinancialSnapshot.reference_date <= as_of_date` 최신
- `_as_of_shareholder(ticker, as_of_date)` · 유사
- 4~6조건 재평가 (screener 로직 재사용 or 인라인)
- 리턴: `(passed_pit, meta)` · meta에 각 조건 판정 값

### 3.3 확장 · `run_stratified_backtest`

- 신규 stratum 값 `powderkeg_pit`
- 기존 `powderkeg_passed`는 유지 (대조군 · 편향 비교용)
- 각 이벤트마다 `pit_evaluate(event.ticker, event.release_date.date())` 실행 · 통과만 표본

### 3.4 API · pit_meta 리포트

응답에 `pit_meta` 추가:
```json
{
  "evaluated": 245, "pit_passed": 87,
  "excluded_no_financial": 158,
  "unmeasured_conditions": ["1_pbr", "9_adv60", "10_no_bad_history"]
}
```

### 3.5 테스트 · `backend/tests/test_powderkeg_pit_backtest.py`

- as-of 재무 조회 (여러 reference_date 중 최신 <= as_of 선택)
- 상폐 종목 (is_delisted=True + release_date < delisted_at) → PIT 통과 케이스
- PIT 통과/탈락 시나리오
- `run_stratified_backtest("A3", "powderkeg_pit")` 흐름 정합

---

## 4. 배포 v1.41

1. 로컬 완결 · 커밋 · push
2. GHA 배포
3. `POST /backtest/{event_type}` 확장 실행 (A3·B3 등 표본 큰 이벤트)
4. **PIT vs non-PIT 결과 비교** — 표본·CAR·validated 게이트 결과 차이 실측
5. 3중 실측: SSR SHA + 신규 API 응답 + PIT 표본 크기

---

## 5. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| 재무 결측 종목 대량 (특히 초기 이벤트) | pit_evaluate 실패 시 통계 excluded_no_financial 로 리포트 · 표본 명시 |
| 5조건만 평가 · 관대 처리로 통과율 과대 | 응답에 unmeasured_conditions 명시 · 향후 Phase 2 확장 명시 |
| 기존 powderkeg_passed 결과와 비교 어려움 | 두 stratum 모두 유지 · 사용자가 시각 비교 |
| big_biz 연 근사 | 그룹 seed 변화가 드물어 무해 · release_date.year로 조회 |

---

## 6. 완결 정의 (Done Criteria)

- [ ] `pit_evaluate` + as-of 헬퍼 함수 · 5조건 평가
- [ ] `run_stratified_backtest` 에 `powderkeg_pit` stratum 추가
- [ ] API 응답에 `pit_meta` 포함
- [ ] pytest 신규 · as-of 조회·PIT 통과·상폐 케이스 시나리오 pass
- [ ] 회귀 없음 (기존 powderkeg_passed stratum 결과 그대로)
- [ ] 배포 v1.41 · A3·B3 이벤트로 PIT vs non-PIT 비교 실측
- [ ] `next-session.md` P2-2 완료 표시

---

## 7. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-23 | v1.0 | 신규 · 사용자 승인 후 저장 |
| 2026-07-23 | v1.1 | 로컬 구현 완료 · pit_evaluate + as-of 헬퍼 + `powderkeg_pit` stratum · pytest 8/8 + 회귀 46/46 pass · 배포 대기 |
