# P2-2d · 화약고 조건 v2 · F-Score 완화 + 규모 필터 신설

**작성일**: 2026-07-27
**우선순위**: 🥇 우선순위 1 · P2-2c 역설계 결과 후속
**예상 소요**: ~4.5h
**후속**: 재평가 · Tier 변동 관찰 · 다음 세션에서 UI 조정 or 임계 재조정

---

## 1. 목적 (정체성 v2.0 정합)

P2-2c 역설계에서 확증된 실 데이터 근거로 화약고 조건 재정의:
- **F-Score 상위 CAR 평균 4.65 (A3), 4.29 (B3)** → 임계 6은 과도 tight
- **operating_income 상위 921억 vs 하위 67억 (A3)** → 규모 필터 강력 신호
- **revenue 상위 6,797~11,216억 vs 하위 1,657~3,109억** → 규모 필터 보강

## 2. 변경 사항

### 2.1 `backend/powderkeg/config.py`
- `piotroski_f_score_min`: 6 → **4**
- 신설 · `revenue_min_krw`: **300,000,000,000** (3,000억)
- 신설 · `operating_income_min_krw`: **10,000,000,000** (100억)

### 2.2 `backend/powderkeg/screener.py`
- 신설 조건 11 · `c11 = (op_income >= op_min) OR (revenue >= rev_min)`
- `result.conditions["11_size_filter"]`
- reject_reasons 리포트

### 2.3 카운트·라벨 갱신 (10 → 11)
- `_compute_tier` (있으면 · 없으면 UI 계산) passed 카운트 임계
- CONDITION_LABEL_SHORT · `"11_size_filter": "규모"`

### 2.4 UI (`frontend/app/powderkeg/page.tsx`)
- 조건 라벨 · F-Score `⑧ F-Score ≥ 4`
- 신규 조건 · `⑪ 규모 (매출 3000억 or 영업익 100억)`

### 2.5 테스트
- 기존 `_seed_ideal_powder_keg` 값 통과 확인
- 신규 조건 11 pass/fail 시나리오

## 3. 배포·재평가

1. v1.46 · 커밋·push
2. `POST /screener/run` · Tier 1 lock 11 + 대상 유니버스
3. Tier 변동 관찰

## 4. 리스크

| 리스크 | 완화 |
|---|---|
| Tier 1 lock 11 종목 규모 미달 → tier 강등 | locked=True 리스트 유지 · 사용자 판단 |
| 신규 승격 종목 대량 → UI 노이즈 | Tier 필터로 조회 |
| 소형 화약고 원 목적 배제 | 정체성 v2.0 (투자 이익)에 정합 |

## 5. 완결 정의

- [ ] config.py 임계값 3건
- [ ] screener.py 조건 11
- [ ] tier 카운트·라벨 정합
- [ ] UI 라벨
- [ ] 회귀 pytest 통과
- [ ] 배포 v1.46 · 재평가 · Tier 리포트

## 6. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-27 | v1.0 | 신규 · 사용자 승인 후 저장 |
