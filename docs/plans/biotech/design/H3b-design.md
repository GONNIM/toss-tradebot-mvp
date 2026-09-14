# H3b 사전 등록 (WP33 · 2026-09-12 · **v3 정정 2026-09-13** · 실행 금지 · Fable 승인 대기)

**가설 (v3)**: 시가총액 **$300M~$1B** 대상 **fund 유형** 제출자 신규 **SC 13D filing** → **D+1 ~ D+180** 양의 초과수익.

## 0-3. WP41-3 v3 정정 (2026-09-13 · filer 정확 분류 후)

**WP41-3 지도 v2** (커버율 61.6% · WP41-2 submissions API 정확 분류 · 시총 필터 후 122 events):

| # | Bucket | filer | horizon | n | hit | mean | cluster CI |
|---|---|---|---|---|---|---|---|
| 1 | 300M-1B | individual | 180d | **4** | 50.0% | +41.88% | 폭 넓음 · n 부족 |
| 2 | 300M-1B | **other** | 180d | **19** | **63.2%** | **+23.76%** | [-6.62%, +63.83%] · n<30 |
| 3 | 50M-300M | other | 180d | 7 | 42.9% | +23.06% | n 부족 |
| 4 | **300M-1B** | **fund** | **180d** | **42** | **45.2%** | **+2.85%** | [-14.18%, +22.66%] · **n≥30 유일** |
| 5 | 50M-300M | fund | 180d | 19 | 36.8% | +11.35% | n 부족 |

**중요 발견 (v3)**:
- 이전 WP33-3 top1 (300M-1B / out_of_seed_unknown / 180d · **+15.93%** n=53) 는 **filer 이름 기반 근사 오분류 편향** (WP41-2 submissions API 정확 분류 후 fund/other/individual 로 재분류)
- 정확 분류 후 fund 카테고리 재산출: **표본 42 · mean +2.85%** (5.6배 축소 · §2 임계 +15% 미달)
- **원 관측 알파 사실상 소멸** · WP33-3 결과 사용 금지

**새 관측 후보 (n<30 · 표본 확대 후 재검)**:
- 300M-1B/other/180d · n=19 · hit 63.2% · mean +23.76% · 다음 세션 커버율 확대 후 재검

**다중 검정 경고**:
- H3 (전체) 실패 → H3b v1 (50M-300M) → v2 (300M-1B/out_of_seed) → v3 (fund 정확 분류) = **3회 반복**
- 다음 사전 등록은 α 조정 없이 확증 가능한 강한 근거 필수 (다중 검정 문제 Fable 승인 필요)

**목적**: H3 관문 2 리포트 §5 (버킷 관측) + **WP33-3 EFTS 전수 지도 (2026-09-13 갱신)** 에서 밝은 조건 발견 → **사후 버킷 선택 검정력 편향 방지 위해 사전 등록 후 독립 표본으로 재검**.

**사전 등록 시각**: 2026-09-12 초안 · **2026-09-13 최적 조건 갱신 (WP33-3)** · git_sha `add7af7` · 본 문서 갱신 시각 이후 편입 이벤트만 유효 (전향 검정) 또는 별도 사전 커밋 표본 (기관 확장)

## 0. WP33-3 최적 조건 (2026-09-13 · 지도 산출 결과 · 사전 등록 갱신)

**EFTS SC 13D 전수 (2021-09~2026-09 · SIC 2834/2836 · 총 643건) 지도 top5**:

| Bucket | filer_type | horizon | n | hit | mean net excess | cluster CI |
|---|---|---|---|---|---|---|
| **300M-1B** | **out_of_seed_unknown** | **180d** | **53** | **56.6%** | **+15.93%** | **[-2.31%, +36.74%]** ← 가장 밝음 |
| 50M-300M | out_of_seed_unknown | 180d | 25 | 40.0% | +14.84% | [-10.69%, +41.2%] |
| 50M-300M | seed_activist | 30d | 5 | 40.0% | +12.26% | [-6.21%, +39.69%] · n 부족 |
| 300M-1B | seed_activist | 30d | 6 | 66.7% | +2.41% | [-2.29%, +7.77%] · n 부족 |
| 300M-1B | out_of_seed_unknown | 30d | 53 | 49.1% | +0.87% | [-5.36%, +6.60%] |

**최적 조건 (n ≥ 30 · CI 하한 최대 · 사전 등록)**:
- 시총 **$300M ~ $1B** (H3 §5 관측 소형주보다 한 단계 위 시총대 · WP33-3 실측 근거)
- 제출자 유형 **out_of_seed_unknown** (기존 55 CIK 외 · SEC company_tickers 매치 안 됨 → 개별 filer / 소규모 fund / 신규 등장자 등)
- 창 **D+1 ~ D+180** (180일 지속 창)
- 관측 mean **+15.93%** · hit **56.6%** · **표본 53 · unique_dates 46**

**주의**: H3 §5 소형주 (50M-300M) 관측과 다른 시총대 · WP33-3 전수 지도가 더 신뢰 가능 (표본 53 vs H3 §5 35~49) · **사전 등록 조건을 지도 top1 으로 갱신**

---

## 1. 이벤트 정의 (사전 커밋 · 사후 조정 금지 · WP33-3 갱신 2026-09-13)

- **필터 1 (filer)**: **EFTS 전수 SC 13D · 제출자 불문** (seed 55 CIK 포함/제외 무관 · seed 55 는 별도 sub-analysis) · **제출자 유형 = out_of_seed_unknown 우선** (SEC company_tickers 미매치 filer)
- **필터 2 (이벤트 유형)**: SC 13D 신규만 (/A 제외 · 13G 제외 · 사전 등록 대상은 13D 만)
- **필터 3 (시총)**: **$300M ~ $1B** (D-day 시점 · companyfacts nearest_shares × D+1 종가 · WP33-3 지도 최적 · 이전 $50M~$300M 는 부수 관측)
- **필터 4 (biotech SIC)**: SIC 2834 또는 2836

## 2. 창·판정식 (사전 커밋 · WP33-3 갱신)

- **창**: **D+1 ~ D+180** (WP33-3 최적 · 이전 D+1~D+30 은 부수 관측)
- **진입**: D+1 종가 (adj_close)
- **benchmark**: XBI
- **비용**: 왕복 1.0% (100 bps) · 민감도 (0.5/2.0/5.0%) 병기
- **bootstrap**: 10,000회 · seed 42 · date-cluster 1차 · block-ticker 2차 · iid 3차
- **알파 통과** (§2-0 승계):
  - mean net excess ≥ **+15.0%** (§2 H3 180d 임계)
  - CI(date-cluster) 하한 > 0
  - hit_rate ≥ 35%

## 3. 폐기 조건

- CI 하한 ≤ 0 OR mean < +5% OR hit_rate < 35%
- 3항 중 1항 미달 시 폐기 (관문 2 미통과)

## 4. 표본 확장 옵션 (택 1 · 사전 승인 필요)

**A. 기관 확장** (권장):
- 기존 7 기관 (RA Capital · Baker Bros · Perceptive · Deep Track · Farallon · OrbiMed · Redmile) 외 **소형 healthcare-focused hedge fund 13+ 추가** (총 20+)
- 후보 (Fable 검토 후 확정): Great Point Partners · Palo Alto Investors · Wellington Capital Healthcare · Casdin Capital · EcoR1 Capital · Ally Bridge · Longitude Capital · Frazier Life Sciences · Aisling Capital · Terra Magnum Capital · vivo Capital · Adage Capital · Column Group
- **표본**: 확장 20+ 기관의 SC 13D 신규 (2021-09-01 ~ 2026-09-01 · 사후 재추출 금지)

**B. 전향 검정**:
- 2026-09-12 이후 기존 7 기관 SC 13D 신규만 · burn-in ≥ 12개월 후 재판정

## 5. 관측 참고 (알파 판정 무관 · WP33-3 갱신)

**WP33-3 EFTS 전수 지도 (2026-09-13)**:
- 300M-1B / out_of_seed_unknown / 180d · n=53 · mean **+15.93%** · hit **56.6%** · CI [-2.31%, +36.74%] (가장 밝음 · 사전 등록 조건)
- 50M-300M / out_of_seed_unknown / 180d · n=25 · mean +14.84% · hit 40% (부수)
- 300M-1B / out_of_seed_unknown / 30d · n=53 · mean +0.87% · hit 49.1% (30d 는 효과 미미)

WP32 §5 버킷 (기존 관측 · seed 55 만):
- 50M-300M / 2834 pharma · 30d +5.22% · 180d +10.7%

→ **사전 등록 최적 = 300M-1B / out_of_seed / 180d** · WP33-3 실측이 지지 · 관측 편향 없이 재검 필수 (다중 검정 명시)

## 6. 사전 커밋 항목 (총 8항)

1. 이벤트 = SC 13D 신규만 (13G 제외)
2. 시총 필터 $50M~$300M (D-day 시점)
3. biotech SIC 2834/2836
4. 창 D+1~D+30 단일
5. 진입 D+1 종가 · XBI 벤치 · 비용 1.0%
6. bootstrap 3종 (date-cluster 1차 · 종목 2차 · iid 3차 · seed 42 · 10000회)
7. 알파 임계 mean ≥ +5% AND CI 하한 > 0 AND hit ≥ 35%
8. 표본 확장 옵션 A/B 택 1 · Fable 사전 승인 필수 · **버킷 관측 재사용 금지 (H3 §5 는 참고 서술만)**

## 7. 실행 순서 (승인 후)

1. Fable 사전 등록 승인
2. 옵션 A 또는 B 확정 · 기관 목록/전향 시작일 확정
3. 표본 수집 (B98 확장 or 전향 수집기)
4. dry-run · 표본 n · 버킷 분포 (관측만)
5. 본 실행 · 봉인 (h3b_seal_report)
6. verification/H3b/H3b-report-YYYYMMDD.md
7. Fable 최종 검수

## 8. 위험·주의

- **사후 편향 방지**: H3 §5 관측이 알파 기준 근처 · 표본 사후 재추출 금지 (재추출 시 재발부터 다시 사전 등록)
- **버킷 미세 조정 금지**: $50M~$300M 구간은 사전 커밋 · 관측 후 조정 (예: $75M~$250M) 금지
- **다중 검정 보정**: H3 (전 표본) 실패 후 H3b 로 재도전 = 다중 검정 · Fable 사전 승인 시 명시 (강제 α 조정 없이 진행 승인 요청)

---

**부속**:
- `docs/plans/biotech/verification/H3/H3-report-20260912.md` §5 (버킷 관측)
- `backend/data/h3_seal_report_add7af7.json` (원본 봉인)
- `docs/plans/biotech/README.md` §2 H3
