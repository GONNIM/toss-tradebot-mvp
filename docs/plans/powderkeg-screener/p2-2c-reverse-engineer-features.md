# P2-2c · 역설계 · 이벤트 CAR 상위·하위 재무 특성 대조 · 구현 계획서

**작성일**: 2026-07-24
**우선순위**: 🥇 우선순위 1 · P2-2b 결과 후속 · 정체성 v2.0 반영
**예상 소요**: ~5h
**후속**: 결과에 따라 화약고 조건 config 재정의 · 별건 세션

---

## 1. 목적

- 정체성 v2.0 (identity.md · 2026-07-24 갱신): **투자 이익 창출** 목적 명시
- P2-2b 결과: 화약고 조건은 매우 좁은 니치 · 완화만으로는 표본 확보 불가
- **역설계 접근**: 이벤트 종목의 실제 12m CAR 분포에서 상위 vs 하위 재무 특성 대조 → **데이터가 말하는 조건**을 화약고 조건 재정의 근거로 확보

---

## 2. 데이터 흐름

1. **대상 이벤트**: A3 (담보제공 · 1,628건) · B3 (지분변동 · 2,796건)
2. `run_event_study_from_db` 로 각 이벤트 12m CAR 계산 (기존 로직 재사용)
3. CAR 상위 N% (기본 20%) · 하위 N% 종목 추출
4. 각 종목의 이벤트 시점 as-of 재무·최대주주 조회 (`_as_of_financials`, `_as_of_shareholder` · P2-2 재사용)
5. 특성 매트릭스 리포트 · 상위 vs 하위 통계 비교

---

## 3. 특성 (as-of 조회 가능한 것)

| 특성 | 원천 | as-of |
|---|---|---|
| owner_pct | MajorShareholder | ✅ |
| piotroski_f_score | FinancialSnapshot (2년) | ✅ |
| op_profit_years_positive | FinancialSnapshot (3년) | ✅ |
| audit_ok | audit_opinion (2년 적정) | ✅ |
| cash_current | cash+short_term (as-of) | ✅ |
| total_debt | total_debt (as-of) | ✅ |
| total_equity | total_equity (as-of) | ✅ |
| revenue | revenue (as-of) | ✅ |
| interest_income | interest_income (as-of) | ✅ |
| is_big_biz | ftc_big_biz (연 근사) | ✅ |
| is_delisted | 상폐 여부 (P2-1 백필) | ✅ |
| **pbr, net_cash_ratio** | 시가총액 as-of 없음 | ⚠️ limitation · 응답에서 계산 skip |

---

## 4. 설계

### 4.1 신규 함수 · `backend/powderkeg/backtest.py`

**`list_event_features_by_car(event_type, top_pct=0.20, window="12m", since=None) -> dict`**
- 이벤트 순회 · `compute_event_return` 로 CAR 계산
- CAR by window 정렬 → top N · bottom N
- 각 이벤트에 대해 as-of 특성 추출
- feature_summary: 각 특성의 평균·중앙값 (상위 vs 하위)

리턴 스키마:
```python
{
    "event_type": "A3",
    "window": "12m",
    "top_pct": 0.20,
    "total_events": 1628,
    "events_with_return": 1200,
    "top_n": 240,
    "bottom_n": 240,
    "top_events": [{"ticker": ..., "release_date": ..., "car": 0.42, "features": {...}}, ...],
    "bottom_events": [...],
    "feature_summary": {
        "owner_pct": {"top_mean": 0.55, "bottom_mean": 0.30, "diff": 0.25},
        "piotroski_f_score": {"top_mean": 6.2, "bottom_mean": 4.1, "diff": 2.1},
        ...
    },
}
```

### 4.2 신규 API · `GET /backtest/{event_type}/reverse-engineer?top_pct=0.20&window=12m`
- 인증 없음 (조회 · 화면 대시보드용 확장 여지)
- 응답 그대로 반환

### 4.3 테스트 · `test_powderkeg_reverse_engineer.py` (신규)
- CAR 계산·정렬 정합
- 상위/하위 종목 추출
- feature 추출 정합 (as-of 조회)
- API 응답 스키마

---

## 5. 배포·실측·리포트

1. v1.45 · 커밋·push
2. `GET /backtest/A3/reverse-engineer?top_pct=0.20`
3. `GET /backtest/B3/reverse-engineer?top_pct=0.20`
4. **핵심 리포트**:
   - 상위 종목 CAR 평균 vs 하위 종목 CAR 평균
   - **각 특성의 상위 vs 하위 차이** (예: "상위 종목 owner 평균 55% · 하위 30% · 임계 45%로 조정 권장")
   - 화약고 조건 재정의 후보 발굴

---

## 6. 소요·리스크

| 단계 | 소요 |
|---|---|
| identity.md 갱신 (0단계) | 20분 |
| list_event_features_by_car 함수 | 2h |
| API + 응답 스키마 | 40분 |
| pytest | 1h |
| 배포 + 실측 + 리포트 | 1h |
| **합계** | **~5h** |

**리스크**:
- as-of 시장 데이터(net_cash·pbr) 부재 → limitation 명시 · 후속 Phase 2에서 해소
- 상위 20% 표본이 작을 수 있음 (예상 60~100) · 통계 유의성 미보장 · 트렌드 관찰용
- CAR 계산 자체가 주가 데이터에 의존 · 오래된 이벤트는 실패 (이미 실측에서 확인)

---

## 7. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-24 | v1.0 | 신규 · 사용자 승인 (역설계 진행 · 정체성 v2.0 반영) 후 저장 |
