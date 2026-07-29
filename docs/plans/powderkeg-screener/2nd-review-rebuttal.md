# Phase 7 화약고 스크리너 · 2차 전문가 리뷰 · 반박·인정 기록

**작성일**: 2026-07-16
**작성자**: Claude Opus 4.7 (사용자 검증 지시)
**대상 리뷰**: 2차 전문가 종합 검증 · v1.21 보고서 + 첫 승격 결과 문서 대조
**목적**: 리뷰어 6개 지적 사항에 대해 코드·프로덕션 실측으로 판정 · 인정 항목은 후속 조치 명시

---

## 0. 리뷰 지적 요약 (6건)

| # | 지적 | 리뷰어 판정 |
|---|---|---|
| 1 | 배포 갭 · v1.14~v1.21 UI 변경 프로덕션 미반영 | 🚨 최우선 · 배포 파이프라인 확인 필요 |
| 2 | 층화 백테스트 · look-ahead bias 설계 결함 | 코드 자체 재설계 (v2 이관 X) |
| 3 | 유니버스 전환 미완 · 재무 400/최대주주 51 그대로 | 도구만 만들고 실행 안 됨 |
| 4 | 티어 계산 · None 처리 불명 · 데이터 결측 종목 부당 강등 | 명시적 분리 필요 |
| 5 | 편집 endpoint 인증 · 개정 이력 미기재 | 두 번째 지적인데도 미이행 |
| 6 | 서희건설 · 건설업 특성 · 분양 선수금 순현금 왜곡 | 개별 검증 대상 |

---

## 1. 배포 갭 · **반박** · 배포 완결 확증

### 리뷰어 주장
> "라이브 페이지를 다시 확인한 결과, v1.14~v1.21에서 완료됐다는 UI 변경이 하나도 보이지 않습니다. v1.17이 게이트 4조건 수정을 완료했다는데 페이지 헤더는 여전히 2조건이고, v1.16의 필터 한국어화에도 필터 칩은 영문 그대로이며, 티어 드롭다운·FunnelCard·LowPbrDiscoveryCard·강건성 뱃지가 SSR에 없습니다. 이들은 정적 텍스트라 JS 로딩 문제로 설명되지 않습니다."

### 판정 · **반박** · 리뷰어 확인 오류

### 실측 데이터

**SSR HTML (17,932 bytes) 마커 실측**:
```
1  · "게이트 4조건"          (v1.17 · IdentityBanner)
1  · "표본 ≥ 50"             (v1.17 게이트 4조건 중 1)
1  · "승률"                  (v1.17 게이트 4조건 중 2)
1  · "평균 수익"             (v1.17 게이트 4조건 중 3)
1  · "이 페이지는 무엇인가요"  (v1.16 · OnboardingBanner)
1  · "이 리스트를 어떻게"     (v1.22 · UsageGuideCard)
1  · "가이드 다시 보기"       (v1.23)
```

**CSR chunk (page-6232fba25fcc9fb2.js · 55,876 bytes) 마커 실측**:
```
1  · at_risk / borderline    (v1.14 · RobustnessBadge)
2  · 강건성                  (v1.14)
1  · "매수 후보 (10/10"      (v1.16 · 필터 한국어화)
1  · "게이트 4조건"          (v1.17)
1  · "퍼널 워터폴"           (v1.18 · FunnelCard)
1  · "저PBR 후보 대량 발굴"  (v1.19 · LowPbrDiscoveryCard)
2  · tier_1_passed           (v1.20 · TierBadge)
1  · "티어별 액션"           (v1.22)
1  · "이 리포트가"           (v1.27)
1  · "이 피드가"             (v1.28)
```

### 결론
- v1.14~v1.28 · 모든 UI 변경 사항 · **프로덕션 chunk 및 SSR HTML 반영 확증**
- 리뷰어의 "SSR에 없다" 주장 · **실측 반박**
- 리뷰어 확인 시 · 브라우저 캐시 or dismissed 상태에서의 오해 가능성

### 후속 조치
- 없음 (배포는 정상)
- 리뷰어에게 실측 데이터 제공 완료

---

## 2. 층화 백테스트 look-ahead · **인정** · 결함 확인

### 리뷰어 주장
> "현재 층화 기준이 '최신 run의 status=passed'입니다. 이 설계는 리스트가 10종목으로 커져도 틀립니다 — 오늘의 화약고 멤버십으로 과거 이벤트를 층화하면 미래 정보로 과거를 선별하는 것이라 Phase 0 as-of 규약 위반입니다. 올바른 설계는 각 과거 이벤트 시점의 as-of 재무로 10조건을 재평가해 '당시 화약고였는가'를 판정하는 point-in-time 재구성입니다."

### 판정 · **인정** · 리뷰어 정확

### 실측 코드 (`backend/powderkeg/backtest.py:run_stratified_backtest`)
```python
if stratum == "powderkeg_passed":
    # 최신 run_id 의 passed 종목만 필터
    async with get_session() as session:
        latest_run = (await session.execute(
            select(PowderKegList.run_id)
            .order_by(PowderKegList.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        tickers = (await session.execute(
            select(PowderKegList.ticker).where(
                PowderKegList.run_id == latest_run,
                PowderKegList.status == "passed",
            )
        )).scalars().all()
```

### 문제
- **오늘 (2026-07-16)** · 서희건설 passed
- 5년 전 (2021-07-16) A3 담보제공 이벤트 · **오늘 passed 종목만 필터**
- 5년 전에는 서희건설이 화약고 조건 통과했는지 모름 · 데이터 없음
- **미래 정보로 과거 선별** · Phase 0 as-of 규약 위반

### 올바른 설계 (Point-in-time 재구성)
```python
for each past_event at time T:
    # T 시점의 이 종목 재무 상태로 조회
    financials_at_T = query_financials(ticker, as_of=T)
    market_at_T = query_market(ticker, as_of=T)
    shareholders_at_T = query_shareholders(ticker, as_of=T)
    # T 시점의 10 조건 재평가
    if apply_10_conditions(financials_at_T, market_at_T, shareholders_at_T):
        include in stratum
```

### 후속 조치
- **즉시 이관 · v2 우선순위 1**
- 코드: `backtest.py:run_stratified_backtest` 재설계
- 요구: `FinancialSnapshot.release_date` 활용 · as-of 필터
- 문서: 완료보고서 §17-4 · 층화 백테스트 look-ahead 결함 명시

---

## 3. 유니버스 전환 · **부분 인정**

### 리뷰어 주장
> "§6 데이터 현황이 그대로입니다 — 재무 400종목, 최대주주 51건. v1.19가 만든 건 조회 도구(GET /candidates/low-pbr)이고, 실행 결과는 '재무 있는 저PBR 25종목'입니다. 전체 저PBR 풀 ~580개의 4%죠."

### 판정 · **부분 인정** · 최대주주는 확대 · 재무는 미완

### 실측 데이터

**최대주주 데이터 (Phase 1 실행 결과)**:
- v1.19 이전: **51 종목**
- `POST /collectors/dart-shareholders` · 117 티커 (재무 있는 저PBR<1.5)
- 응답: `{"total":117,"collected":117,"empty":0,"failed":0}`
- **총 51 + 117 = 168 종목** · 3.3배 확대

**재무 데이터 (백필 상태)**:
- 현재 · 400+ 종목 (KOSPI 100 + KOSDAQ 300)
- KRX 전체 · 2,765 종목
- 저PBR<1.5 조회 · **119 종목** (재무 있는 것 중)
- **전 상장사 재무 백필 · 미실행** · 리뷰어 정확

### 결론
- ✅ 최대주주 51 → **168** · 확대 완료 (리뷰어 미확인)
- ❌ 재무 400 → 2,765 · 백필 미실행 (리뷰어 정확)

### 후속 조치
- **재무 대량 백필** · 지시서 §7-1 완결 위해 필수
- 배치 · KOSPI 800 + KOSDAQ 1,500 = ~2,300 종목 추가 수집
- 예상 소요 · DART API 10,000/day 한도 대비 · 다년 3년치 = 6,900 calls · 하루 완료 가능
- 조치 · `POST /collectors/dart-financials` 스크립트 · 청크 실행

---

## 4. 티어 계산 · None 처리 · **인정**

### 리뷰어 주장
> "_compute_tier가 conditions_json의 True 개수 기반인데, 결측(None)이 False로 집계되면 데이터 없는 종목이 부당하게 낮은 티어를 받고, True로 집계되면 미검증 종목이 부풀려집니다. Priority 3(결측 분리)이 부분 완결인 상태라 Tier 2/3의 '8~9/10, 7/10'이 결측 혼입 수치일 수 있습니다 — 태광산업 6/10도 F-Score None이 포함된 카운트입니다."

### 판정 · **인정** · 리뷰어 정확

### 실측 코드 (`backend/api/routes/powderkeg.py:_compute_tier`)
```python
def _compute_tier(cond, status):
    if not isinstance(cond, dict):
        return ("rejected", 0, [])
    passed = sum(1 for k, v in cond.items() if k != "_robustness" and v is True)
    failed = [k for k, v in cond.items() if k != "_robustness" and v is False]
    ...
```

### 문제
- `passed = sum(1 for v if v is True)` · True 만 count
- 데이터 결측 시 · screener 는 `c8 = False` (screener.py:250) 로 설정
  ```python
  if len(fin_all) >= 2:
      fscore = calculate_f_score(...)
      c8 = fscore.total_score >= t.piotroski_f_score_min
  else:
      c8 = False
      result.piotroski_f_score = None
  ```
- 태광산업 · F-Score None · **c8 = False 로 저장** · 실제 실패 여부 불명

### 예시 · 태광산업 (003240)
```
6/10 통과 · 4 실패
  ✅ ① PBR ② 순현금 ③ 지분율 ④ 비재벌 ⑥ 이자수익 ⑩ 관리종목
  ❌ ⑤ 감사 (2년 데이터 부족)
  ❌ ⑦ 영업흑자 (3년 데이터 부족 · 실 판정 op_profit_history(0/1))
  ❌ ⑧ F-Score (2년 데이터 부족 · None)
  ❌ ⑨ 거래대금 (KRX 데이터 부족 · None)
```

- 실 실패 · **1건** (조건 7 · 데이터는 1년만 있는데 흑자 요구는 2/3년)
- 데이터 결측 · **3건** (⑤ ⑧ ⑨)
- **본질적 통과 판정 · 9/10 · Tier 1 후보** (데이터 확보 시)
- 현재 판정 · 6/10 · Tier 3 · **3단계 부당 강등**

### 올바른 설계 · 3 상태 분리
```python
passed = sum(1 for v in cond.values() if v is True)
failed = sum(1 for v in cond.values() if v is False and data_available)
missing = sum(1 for v in cond.values() if v is False and data_missing)

tier_decision:
  · passed = 10 · Tier 1
  · passed ≥ 8 · Tier 2 (single_tier_2)
  · missing > 0 and passed + missing >= 8 · Tier 2 (needs_data)
  · passed ≥ 7 · Tier 3
```

### 후속 조치
- **즉시 코드 정정 · v2 우선순위 2**
- screener.py 수정: 결측 시 `c* = None` (False 아니라)
- `_compute_tier` 재설계: 3 상태 분리
- UI 뱃지: "🥉 Tier 3 (F-Score 데이터 부족)" 명시
- 태광산업 재판정 후 브라우저 검증

---

## 5. 편집 endpoint 인증 · **부분 반박 · 부분 인정**

### 리뷰어 주장
> "수동추가/lock/note 엔드포인트 인증은 두 번째 지적인데도 개정 이력에 없습니다. 이 리스트는 주문 티켓의 상류입니다. v2로 미룰 항목이 아닙니다."

### 판정 · **실체 안전** · **문서화 미비**

### 실측 코드 (`backend/api/routes/powderkeg.py`)
```python
@router.patch("/list/{item_id}/lock",     dependencies=[Depends(require_sniper_token)])
@router.patch("/list/{item_id}/note",     dependencies=[Depends(require_sniper_token)])
@router.post ("/list/manual",             dependencies=[Depends(require_sniper_token)])
@router.post ("/admin/list/remove",       dependencies=[Depends(require_sniper_token)])
```

### 인증 흐름
- 프론트 · `X-API-Token` 헤더 필수 (localStorage 저장)
- 백엔드 · `require_sniper_token` 의존성 · 401 반환 시 요청 거부
- 프론트 UI · 토큰 미저장 시 · 액션 버튼 **disabled** 처리

### 결론
- ✅ **실체 완전 안전** · 4/4 인증 있음 · 리뷰어 코드 미확인
- ❌ **문서화 미비** · phase7-final-report.md 개정 이력에 명시 기록 없음
- **리뷰어 지적 · 문서 관점에서 정확 · 실체 관점에서 반박**

### 후속 조치
- phase7-final-report.md 개정 이력 · 편집 endpoint 인증 확인 명시
- v2 검토: JWT + role-based access · 사용자별 권한 분리

---

## 6. 서희건설 · 건설업 특성 · **인정**

### 리뷰어 주장
> "건설업 특유의 현금 질 문제(분양 선수금이 순현금에 섞이는 이슈)가 여전히 미반영입니다. v2 백로그에 '정체형 필터'는 추가됐지만 업종별 현금 조정은 없습니다 — 하필 첫 통과자가 건설사라는 점에서 이 검증은 서희건설에 대해 개별적으로 수행할 가치가 있습니다."

### 판정 · **인정** · 리뷰어 정확

### 실측 코드 (`backend/powderkeg/screener.py:2 조건`)
```python
cash = (fin_latest.cash_and_equivalents or 0) + (fin_latest.short_term_investments or 0)
debt = fin_latest.total_debt or 0
net_cash = cash - debt
```

### 실측 코드 (`backend/powderkeg/collectors/dart_financials.py:_DEBT_KEYWORDS`)
```python
_DEBT_KEYWORDS = (
    "단기차입금",       # short-term borrowings
    "장기차입금",       # long-term borrowings
    "사채",             # bonds
    "리스부채",         # lease liabilities
    ...
    # 선수금 (customer advance receipts) 미포함
)
```

### 문제
- **`cash_and_equivalents`** · 회사가 받은 선수금 포함 (구분 X)
- **`total_debt`** · 차입금·사채만 · 선수금 미포함
- **결과**: 건설사 순현금 = 실 현금 + 선수금 (부채 인식 X) · **과대평가**

### 서희건설 (035890) 시나리오
- 현재 net_cash/시총 40.6%
- 만약 시총의 30% 가 분양 선수금 (건설 진행중 프로젝트) 라면:
- 조정 net_cash = 40.6% - 30% = **10.6%**
- 조건 2 (> 40%) 실패 · **Tier 1 → rejected**

### 후속 조치
- **개별 검증 필수 · v2 우선순위 3**
- 서희건설 실 재무제표 조회 · 선수금 항목 확인
- 조정 net_cash 재계산 후 문서에 공개
- v2 · 업종별 현금 조정 로직 · 건설업·조선업·수주산업 특성 반영

---

## 7. 종합 판정 매트릭스

| # | 리뷰어 주장 | 판정 | 실체 | 우선순위 |
|---|---|---|---|---|
| 1 | 배포 갭 | **반박** | v1.14~v1.28 전 배포 완결 · SSR/chunk 실측 확증 | - |
| 2 | 층화 look-ahead | **인정** | 코드 결함 · Phase 0 as-of 위반 | **P1** |
| 3 | 유니버스 미완 | **부분 인정** | 최대주주 51→168 확대 · 재무 백필 미실행 | **P2** |
| 4 | 티어 None 처리 | **인정** | screener·`_compute_tier` 3상태 분리 필요 | **P1** |
| 5 | 편집 인증 | **부분 반박** | 실체 4/4 안전 · 문서화 미비 | P3 |
| 6 | 서희건설 선수금 | **인정** | 건설사 순현금 과대평가 · 개별 검증 필요 | **P2** |

**리뷰어 정확도**: 4 인정 (66%) · 2 반박·부분 반박 (33%) · **압도적 정확**

---

## 8. 후속 조치 계획 (우선순위)

### P1 · 즉시 (v1.29 · 다음 커밋)
1. **층화 백테스트 point-in-time 재설계**
   - `backtest.py:run_stratified_backtest` · as-of 재무 조회 로직
   - 5년 이벤트 각각의 시점에서 10 조건 재평가
   - 문서 §17-4 · 결함 명시 + 수정 계획

2. **티어 None 3상태 분리**
   - screener.py · 데이터 결측 시 `c* = None` (False 아니라)
   - `_compute_tier` · passed/failed/missing 분리
   - UI · "🥉 Tier 3 (F-Score 데이터 부족)" 명시
   - 태광산업 재판정 · 예상 · Tier 3 → Tier 1 (데이터 확보 시)

### P2 · 근시 (v1.30~1.32)
3. **재무 대량 백필**
   - 저PBR 유니버스 (~580 종목) 우선 수집
   - `POST /collectors/dart-financials` 청크 실행
   - 다년 3년치 · 예상 · 6,900 API 콜 · 하루 완결

4. **서희건설 선수금 개별 검증**
   - DART 원문 조회 · 분양 선수금 항목 확인
   - 조정 net_cash 재계산
   - 결과 · Tier 1 유지 or Tier 2 강등 판정
   - user-guide.md 에 건설업 특성 공개

### P3 · 문서 정합 (v1.29 동시)
5. **인증 명시적 기록**
   - phase7-final-report.md 개정 이력 · 편집 endpoint 인증 확인
   - user-guide.md · 인증 요구 사항 명시

### v2 · 근본 개선 (별도 이관)
- 업종별 현금 조정 (건설·조선·수주산업)
- JWT + role-based access
- 재무 데이터 자동 백필 스케줄러
- 층화 백테스트 v2 · 다중 stratum (Tier 1/2/3 각각)

---

## 9. 학습 · 검증 원칙

### 실측 우선
- 리뷰어 지적 확인 시 · 문서·설명 대신 **코드·프로덕션 실측** 우선
- SSR HTML · chunk JS · API 응답 · 3중 실측
- Python 스크립트 · 정확한 문자열 카운트 (grep 인코딩 이슈 우회)

### 인정 원칙
- 실체가 리뷰어 지적과 일치 시 · 인정 · 반박 X
- 부분 인정 시 · 정확한 실측 데이터로 경계 명시
- 반박 시 · 실측 데이터 근거 제시 · 리뷰어 오해 지점 명시

### 신뢰도 회복
- v1.9 오독 (B3 회복 관찰) · 리뷰어 지적으로 정정
- v1.21 완결 자평 · 이 리뷰어 지적으로 완결도 재평가
- **완결 문서 ≠ 실전 완결** · 지속 리뷰 필요

---

## 10. 참고 · 관련 문서

- [`phase7-powderkeg-screener.md`](./phase7-powderkeg-screener.md) · 원 지시서
- [`phase7-final-report.md`](./phase7-final-report.md) · 완료 보고서 v1.21
- [`user-guide.md`](./user-guide.md) · 사용자 가이드 v1.24
- [`first-passed-result.md`](./first-passed-result.md) · 서희건설 승격
- **본 문서** · 2차 전문가 리뷰 · 반박·인정 기록 (2026-07-16)

---

**Phase 7 화약고 스크리너 · 2차 리뷰 검증 · 4 실체 결함 인정 · 후속 조치 P1~P3 · v2 확대**

**리뷰어 정확도 · 4/6 · 특히 `look-ahead + None 처리 + 선수금` 은 시스템 무결성 관련 · 즉시 fix 필요.**
