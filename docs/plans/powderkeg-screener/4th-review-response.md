# Phase 7 화약고 스크리너 · 4차 리뷰 대응 · 실측 검증

**작성일**: 2026-07-18
**작성자**: Claude Opus 4.7 (사용자 검증 지시)
**대상 리뷰**: 4차 전문가 캡처화면·문서·관측 전수 대조 (사용자 전달)
**목적**: 5개 지적사항 실측 검증 · 즉시 3건 라이브 반영 + 중장기 백로그 확정

---

## 0. 요약 (Executive Summary)

- **리뷰어 정확도**: 8/9 완전 확증 + 1 부분 정정 (약 89%)
- **결자해지 · 배포 논쟁 종결**: 리뷰어가 3회에 걸쳐 받은 것은 캐시된 구버전 → 반박문 §1 배포 완결 주장 옳음 · **P0 커밋 해시 인프라 유효성 실증**
- **즉시 3건 라이브 반영** (커밋 `b64b0e4` + hotfix `d39ad26`):
  1. P4-2a · 태광 등 13 그룹 big_biz_seed 확장 (태광·태영·부영·대방·KG·SM·반도홀딩스·호반건설 + 2025 신규 5)
  2. P4-3 · 금융업(은행·증권·보험 18종) 스크리너 원천 배제
  3. P4-hotfix · sector 필드 API 응답 노출 (P2-4e 배포 후 누락 버그 정정)
- **신규 발견 버그 hotfix**: `_compute_tier`가 conditions={}인 조기 return 종목을 `tier_1_passed`로 오판정 → `total==0 → rejected` 추가

---

## 1. 리뷰 지적 판정 매트릭스

| # | 지적 | 실측 판정 | 대응 커밋 |
|---|---|---|---|
| 0 | 배포 논쟁 · 반박 수용 | ✅ 확증 · CDN/캐시 로 리뷰어 구버전 관측 · P0 인프라 유효 | (없음) |
| 1a | 3상태 분리 태광 표기 정합 | ✅ 확증 | (v1.29 완료) |
| 1b | v1.13 seed 확장 · 하림지주 big_biz | ✅ 확증 | (v1.13 완료) |
| 1c | 에이스침대 PBR 0.505 배제 | ✅ 확증 · 발굴 조건 정확 | (없음) |
| 1d | 퍼널 정직성 (0개 원인 표기) | ✅ 확증 | (v1.18 완료) |
| 2 | 서희 provenance 부재 | ✅ 확증 · UI 미노출 · Run diff 없음 | P4-1 백로그 |
| 2b | contract_liab=0 수집 실패 가능성 | ⚠️ **부분 정정** · CFS 응답에 계정 자체 부재 (파싱 실패 아님) · OFS fallback 필요 | P2-3b 백로그 |
| 3 | 퍼널 결측 3색 필요 | ✅ 확증 · 감사 54% 가짜 진단 | P4-4 백로그 |
| 4 | 유니버스 26 = 재무 백필 미실행 | ✅ 확증 · 이미 인지 | P2 실행 (사용자 트리거) |
| 5a | 태광 조건 ④ 오통과 | ✅ 확증 · 즉시 정정 | **P4-2a · `b64b0e4`** |
| 5b | 금융업 원천 제외 | ✅ 확증 · 즉시 정정 | **P4-3 · `b64b0e4` + hotfix `d39ad26`** |
| 5c | 변별력 0 조건 (①·⑩) | ✅ 확증 | P4-5·P4-6 백로그 |

---

## 2. 서희 contract_liab=0 · 리뷰어 예측 부분 정정

### 리뷰어 주장
> "분양·공사를 하는 건설사의 계약부채가 0이라는 건 재무 현실상 거의 불가능하고, 계정과목 매칭 실패(수집 갭)일 가능성이 높습니다."

### 실측 (raw_json.diag_bs_liab_items 16개 완전 조회)
서희 2024 CFS · 부채 관련 원 계정 (P2-4b hotfix 이후 진단 저장):
- 자본과부채총계 1.54조 · 유동부채 461억 · 차입금등(유동) 774억 · 유동 리스부채 84억
- 유동충당부채 134억 · 당기법인세부채 400억 · 기타유동금융부채 145억 · 기타 유동부채 31억
- 부채총계 5,668억 · 비유동부채 1,060억 · 확정급여부채 7억 · 차입금등(비유동) 206억
- 비유동 리스부채 63억 · 비유동충당부채 743억 · 기타비유동금융부채 40억 · 기타 비유동 부채 0

**"계약·선수·예수" 계정 하나도 없음** — 서희는 CFS(연결)에 계약부채 계정 자체가 없다.

### 원인 후보
- (a) 서희 CFS 특성 · 계약부채가 사실상 미미 or 다른 항목(예: "기타 유동부채" 31억)에 포함
- (b) `dart_financials.fs_div_preference=("CFS","OFS")` · CFS 성공하면 break → OFS 별도 재무제표 미확인
- **가능성**: OFS(별도)에는 계약부채 계정 있을 수 있음

### 대응
- **P2-3b 백로그** · `fs_div` fallback 개선 · CFS 성공해도 특정 필수 계정(계약부채 등) 없으면 OFS 병합 시도
- 리뷰어 예측 "수집 실패"는 부분적으로만 참 (설계상 CFS만 조회 · OFS 미확인)

---

## 3. 즉시 3건 · 라이브 검증 (커밋 `b64b0e4` + hotfix `d39ad26`)

### 3.1 P4-2a · big_biz_seed 대량 확장

`big_biz_seed.py` v1.34:
- 기존 51 그룹 · 파일 주석에 v2 확장 대상 명시됐던 8 그룹 즉시 추가
  - 태광 · 태영 · 부영 · 대방 · KG · SM · 반도홀딩스 · 호반건설
- 2025 FTC 신규 지정 5 그룹 병기 (엘아이지·대광·사조·빗썸·유코카캐리어스)
- 커버리지 · 51/88 → **64/92 (약 70%)**
- FTC seed refresh 실측: `deleted:136, inserted:154` · +18 티커

**태광 실측**:
```
003240 태광산업  tier=tier_2_needs_data  c4=False (이전 True)  reject: big_biz_group,audit:no_data<2yrs...
032190 다우데이타 tier=cash_suspect      c4=False (신규)      reject: big_biz_group,cash_suspect...
```
✅ 태광·다우데이타 (태광 계열) 조건 ④ 정정 확증. 4차 리뷰 지적 즉시 해소.

### 3.2 P4-3 · 금융업 원천 배제

`screener.py:screen_ticker` 최상단:
```python
if is_financial_industry(ticker):
    fi = financial_industry_info(ticker)
    result.name = fi[0] if fi else ticker
    result.order_industry_sector = f"금융({fi[1]})" if fi else "금융"
    result.reject_reasons.append(f"financial_industry:net_net_inapplicable · sector={...}")
    return result
```

- 은행·증권·보험 18종 (P2-4e `FINANCIAL_INDUSTRY_TICKERS`) 데이터 조회·10 조건 스킵
- 기업은행 예수부채·다우데이타 지주 연결·LS증권 예수금 왜곡 원천 차단

**실측**:
```
024110 기업은행  tier=rejected  sector=금융(은행)  reject: financial_industry:net_net_inapplicable
078020 LS증권    tier=rejected  sector=금융(증권)  reject: financial_industry:net_net_inapplicable
```

### 3.3 P4-hotfix · sector 필드 API 응답 노출

P2-4e 배포됐으나 `/list` 응답에 `order_industry_sector` 미노출 버그.
`routes/powderkeg.py:get_powderkeg_list`에서 ticker 로 order/financial 시드 실시간 판별:

```python
oi = order_industry_info(r.ticker)
fi = financial_industry_info(r.ticker)
if oi is not None:   sector = oi[1]              # "건설"/"조선"/"플랜트"
elif fi is not None: sector = f"금융({fi[1]})"   # "금융(은행/증권/보험)"
else:                sector = None               # 자동 판별 은 reject_reasons 참조
```

**실측**: 서희 `sector=건설`, 기업은행 `금융(은행)`, LS증권 `금융(증권)` UI 응답 확증.

### 3.4 신규 버그 발견 · `_compute_tier` `total==0` hotfix (커밋 `d39ad26`)

P4-3 배포 후 관측: 금융업 조기 return 종목이 UI 에 **`tier_1_passed`로 오표시**.

원인:
- 조기 return 시 `result.conditions = {}` (dict 미채움)
- `_compute_tier` · `passed = 0, total = 0` · `passed == total` 조건 매치 → `tier_1_passed` 오판정
- **매수 후보로 UI 표시** · 위험 (실제는 rejected)

hotfix:
```python
if total == 0:
    return ("rejected", 0, [], [])
```

**hotfix 후 실측** (커밋 `d39ad26`):
```
024110 기업은행  tier=rejected  ← 정정 확증
078020 LS증권    tier=rejected  ← 정정 확증
```

tier 분포 · `{cash_suspect: 2, tier_3_watch: 12, tier_2_needs_data: 1, tier_2_near: 1, rejected: 10}`
(이전 rejected 9 → 10 · 기업은행 or LS증권 이동)

---

## 4. 후속 백로그 (P4-1·4·5·6 + 부수)

### P4-1 · 서희 provenance UI 공개 · Run diff 로그 (중대)
- 스크리너 run 간 diff · 종목별 조건값 변화 + 원인 필드 (rcept_no · 파싱 매핑 변경 · 임계 변경)
- 신규 테이블 `PowderKegRunDiff` · UI 뱃지 · 사용자가 "왜 서희가 강등됐는가?" 자체 조회
- 서희 40.6% → 16.3% 산출 근거 UI 노출 (현재는 `3rd-review-response.md §12` 문서에만 있음)

### P4-4 · 퍼널 3색 분리 (통과/실패/결측)
- FunnelCard · 종목별 conditions dict를 True/False/None 3색 재집계
- 감사의견 54% 가짜 진단 (수집 갭이 실패로 합산) 해소
- API 응답에 조건별 요약 통계 (`condition_stats`) 추가 가능

### P4-5 · 조건 ⑩ 실데이터 (관리종목·거래정지 이력)
- v1 근사 (True 고정) 제거
- KRX 관리종목·거래정지 목록 수집기 신규
- 조건 판정 로직 · 3년 이력 조회

### P4-6 · 조건 ① 발굴 조건 별도 표기
- PBR은 발굴 필터 · 항상 100% 통과
- 퍼널·티어 뱃지에서 "발굴 조건"으로 분리 노출 · 정보량 있는 조건과 구분

### P2-3b · dart_financials CFS/OFS fallback
- 서희 계약부채 CFS 부재 · OFS 확인 필요 (4차 리뷰 §2b 예측 검증)
- CFS 성공해도 특정 필수 계정 없으면 OFS 병합 시도

### P2 실행 (사용자 API 트리거)
- 재무 대량 백필 · 저PBR 유니버스 (~580 종목) · ~10,900 콜 · 2~3일 분할
- 백필 후 태광·서희 등 재판정으로 실제 티어 확정

### P4-2b · 조건 ④ 정의 재검토 (정책 결정)
- 리뷰어 제안: 상호출자제한(자산 11.6조+ · 46 그룹) vs 공시대상(5조+ · 92 그룹) 세분화
- 대재벌만 제외 · 중견 지주그룹은 허용 검토
- 태광 캘리브레이션 결과와 정합 여부 재검토

### v2 인증 아키텍처 (P3 → v2)
- localStorage → httpOnly 쿠키
- JWT + 24h 만료 + refresh + jti blacklist
- role-based access
- `sniper_api_access` 감사 테이블

---

## 5. 검증 원칙 갱신 (본 리뷰 학습)

### 신규 원칙
1. **UI 노출 검증 병행** — 로직·API 검증만으론 부족. sector 필드처럼 API 응답 dict 에서 누락되는 실체적 버그 존재. UI 실측 후 정합 확인 필수.
2. **파일 주석 = 인지된 백로그** — big_biz_seed.py 처럼 "v2 확장 대상 · 태광 등 8 그룹" 명시된 주석은 즉시 실행 가능한 태스크. 리뷰어 지적으로 다시 발견됐다면 우선순위 재검토.
3. **조기 return 로직의 하방 영향** — 조기 return 시 dict 미채움 등 상태 미정합은 다운스트림 로직(_compute_tier 등)에서 오판정 유발. 조기 return 경로마다 하방 로직 재검증.

### 기존 원칙 재확인
- 실측 우선 (문서·설명 대신 코드·URL·DB)
- 3중 실측 (SSR + 응답 헤더 + 소스 트리) → **UI + API + DB + reject_reasons 문자열** 확장
- 파싱·데이터 소스 이슈는 원 계정명·금액까지 실측 (raw_json.diag)

---

## 6. 참고 · 관련 문서

- [`phase7-final-report.md`](./phase7-final-report.md) — 완료 보고서
- [`2nd-review-rebuttal.md`](./2nd-review-rebuttal.md) — 2차 반박문 (§6·§9 서희 정정 대상 · 3차 리뷰 후속)
- [`3rd-review-response.md`](./3rd-review-response.md) — 3차 재재반박 대응 (v1.8 · P0/P1/P2 완결)
- [`first-passed-result.md`](./first-passed-result.md) v1.1 — 서희 승격 취소
- **본 문서** · 4차 리뷰 대응 · 즉시 3건 + hotfix 라이브 반영 (2026-07-18)

---

## 7. 개정 이력

| 날짜 | 버전 | 변경 | 커밋 |
|---|---|---|---|
| 2026-07-18 | v1.0 | 최초 작성 · 4차 리뷰 5개 지적 실측 판정 · 즉시 3건 (P4-2a·P4-3·P4-hotfix) 라이브 반영 · `_compute_tier total==0` hotfix · 후속 P4-1/4/5/6 백로그 | (pending) |
