# B83 축소 검증안 초안 (전 소스 FAIL 분기 · 2026-09-04)

**작성**: 2026-09-04 · **실행**: **없음** · Fable 검수 후 사용자 결정
**전제**: B58 3소스 실측 결과 · Tiingo 11/20 · AV 0/20 · SimFin 9/20 · **전 소스 FAIL** (18/20 통과선 미달)

## 1. 실측 요약 (v4 표본 20 · B80 창 커버 기준)

| 소스 | 창 커버 | 상태 분포 |
|---|---|---|
| Tiingo | 11/20 (55%) | AVAILABLE 18 · NOT_FOUND 2 · 부분커버 7 |
| Alpha Vantage | 0/20 (0%) | RATE_LIMIT_OR_INFO 20 (전건) |
| SimFin | 9/20 (45%) | AVAILABLE 14 · EMPTY 6 · 부분커버 5 |

### 1-1. 합집합 커버율
- **Tiingo ∪ SimFin: 12/20 = 60%** (교집합 8 · Tiingo only 3 · SimFin only 1)
- 남은 미커버 8건: AKUS · MYOV · XLRN · CNCE · TALS · SYRS · KZR · CARM

### 1-2. 집단별 커버율
| cohort | n | Tiingo | AV | SimFin |
|---|---|---|---|---|
| acquired | 15 | 9 | 0 | 7 |
| bankrupt | 3 | 1 | 0 | 2 |
| delisted | 2 | 1 | 0 | 0 |

### 1-3. AV 전건 실패 원인
- 20/20 `RATE_LIMIT_OR_INFO` · Note/Information 페이로드
- 무료 티어 실질 데이터 미제공 · 25/day 한도 이전에 이미 차단

## 2. 축소 검증안 (실행 없이 규모 추정만)

**전제**: 표본 20건 대신 · **데이터 도달 범위 내 이벤트만** 대상

### 2-1. 표본 규모 추정
- **커버 가능 (Tiingo ∪ SimFin ∪ EODHD 창 안)**: **12/20 = 60%**
- 원장 140 delisted 바이오 → 60% 적용 시 **~84건 커버 가능 · 나머지 ~56건 미커버**
- 실 원장 다양성 감안 시 60~70% 범위 예상

### 2-2. 시나리오별 표본
1. **엄격 (Tiingo ∪ SimFin 만)**: 표본 12/20 · 원장 대비 ~84/140
2. **완화 (창 커버 아닌 last≥event 만)**: Tiingo/SimFin AVAILABLE 합계 · 18+14=... unique ~17/20 = 85%
3. **최소 (event date 자체 커버)**: AV rate limit 무관 · Tiingo/SimFin AVAILABLE

### 2-3. 대안 데이터 소스 후보 (조사만 · 실행 없이)
- Nasdaq Data Link (Quandl 후신)
- Polygon.io (무료 티어 있음 · 2년 · rate limit)
- Financial Modeling Prep 유료
- IEX Cloud (재출시 상태 확인 필요)
- Wall Street Journal / MarketWatch 개인 접근

## 3. Fable 검수 대기 사항

- 축소 검증안 (2-1) 채택 시 표본 크기 축소로 통계 유의성 재검토 필요
- 알파 임계 (net excess ≥ +2% · 히트율 30%) · 표본 크기 감소 시 bootstrap CI 하한 판정 어려워짐
- 대안 소스 조사 승인 여부 (실행은 별건)

## 4. 실행 없이 산출된 결정 항목

- [ ] Fable: 축소 검증안 (60% 커버) 로 진행 vs 대안 소스 조사 우선
- [ ] 사용자: 유료 소스 도입 결정 (별건 · 결제 진행은 사용자 판단 후)
- [ ] 실행 스크립트 준비 (Fable 승인 후 · 별건)

## 5. 관련 CSV

- `backend/data/biotech_coverage_test3_add7af7_2026-09-04.csv` (20 표본 · 3소스 실측)
- `backend/data/h3_delisted_ledger_v2_add7af7.csv` (원장 140)
- `docs/plans/biotech/SOURCES.md` (EODHD 철회 · 신 소스 실측 반영)
