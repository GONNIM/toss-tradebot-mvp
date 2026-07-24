# P2-2b · 화약고 가설 재검토 · Grid Search · 구현 계획서

**작성일**: 2026-07-24
**우선순위**: 🥇 우선순위 1 · P2-2 pit_passed=0 결과 후속
**예상 소요**: 3~4h
**후속**: 결과에 따라 화약고 조건 재정의 or B안(역설계) 검토

---

## 1. 목적

P2-1b 재무 백필 후 PIT 재실측(A3·B3)에서 `pit_passed=0` 관측. 재무 부재는 해소됐으나 6조건 tight로 대부분 종목 탈락. **어느 조건이 얼마나 완화되면 pit_passed·validated가 생기는지** 실측하여 화약고 조건 재정립 근거 확보.

## 2. Grid 설계

**Dimensions (3×3 = 9 조합)**
- F-Score min: {4, 5, 6}
- owner_pct min: {0.30, 0.35, 0.40}
- (다른 조건 baseline 유지: 5 audit 2년 · 6 cash_reality · 7 op_profit 2/3 · 4 not_big_biz)

**대상 이벤트**: A3 (1,628건) · B3 (2,796건)
**총 실행**: 9 조합 × 2 이벤트 = 18 회

## 3. 설계 (최소 변경)

### 3.1 `run_stratified_backtest` 확장
- `thresholds: Optional[dict] = None` 파라미터 추가
- 내부에서 `pit_evaluate(..., thresholds=thresholds)` 로 전달
- `pit_evaluate` 는 이미 thresholds 지원 (지난 세션 구현 · fscore_min, owner_min 등)

### 3.2 신규 API · `POST /backtest/{event_type}/grid`
- Request:
  ```json
  {"grid": [
    {"piotroski_f_score_min": 4, "major_shareholder_pct_min": 0.30},
    {"piotroski_f_score_min": 5, "major_shareholder_pct_min": 0.30},
    ...
  ]}
  ```
- Response:
  ```json
  {"event_type": "A3", "results": [
    {"thresholds": {...}, "pit_meta": {...},
     "aggregate": {"total_events": N, "valid_events": M, "per_window": {...}},
     "decision": {"validated": bool, "passing_window": ...}},
    ...
  ]}
  ```
- 캐시 없이 즉시 반환 (grid는 실험용)

### 3.3 테스트
- `test_powderkeg_grid_backtest.py` 신규
  - `run_stratified_backtest`에 thresholds 전달 → `pit_evaluate` 반영 정합
  - API 응답 스키마
  - 완화 조합에서 pit_passed 증가 시나리오 (fixture)

## 4. 배포·실측

1. v1.44 · 커밋 · push → GHA
2. 서버 curl · A3·B3 각각 grid API 호출
3. 리포트 매트릭스 (예상):
   | thresholds | A3 pit_passed | A3 valid_events | A3 12m mean_return | B3 pit_passed | B3 valid_events | B3 12m mean_return |
   |---|---|---|---|---|---|---|
   | fscore=6 · owner=0.40 (기존) | 0 | 0 | — | 0 | 0 | — |
   | fscore=5 · owner=0.40 | ? | ? | ? | ? | ? | ? |
   | ... | | | | | | |

## 5. 결과 해석 시나리오

- **A. 특정 완화에서 pit_passed·validated 발생** → 화약고 조건 재정의 근거 · 별건 세션에서 config 갱신
- **B. 모든 완화에서 pit_passed=0** → 구조적 표본 문제 · B안 (역설계 · 이벤트 발생 상위 CAR 종목 관찰) 별건 세션
- **C. pit_passed 늘어나되 CAR 유의미 X** → 조건 완화가 시그널 희석 · 화약고 좁게 유지 결론

## 6. 소요·리스크

| 단계 | 소요 |
|---|---|
| run_stratified_backtest thresholds 확장 | 30분 |
| grid API 신설 + 응답 스키마 | 1h |
| pytest | 1h |
| 배포 + 서버 실행 + 리포트 | 1h |
| **합계** | **~3.5h** |

**리스크**: 결과가 시나리오 B이면 이번 grid search 자체는 pit_passed 증가 실패로 마무리 · 다만 정직한 실측 리포트로 다음 결정 근거 확보 (실패 아님).

## 7. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-24 | v1.0 | 신규 · 사용자 승인 후 저장 |
| 2026-07-24 | v1.1 | 배포 v1.44 (8bec550) + 실측 완결 · A3/B3 6조합 매트릭스 · 시나리오 **B 확증** (완화 후에도 pit_passed A3=1·B3=2 · 구조적 표본 문제) · F-Score가 owner보다 큰 병목 · 화약고 원 목적(관찰 · Tier 1 lock) 정합 결론 |
