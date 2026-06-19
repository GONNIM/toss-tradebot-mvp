# Moonshot Picks 인자 학술 연구 — Phase 1 발굴 결과

**작성일**: 2026-06-18 (v1) → 2026-06-19 (v2)
**상태**: v2 — Phase 1 능동적 발굴 완전 완료 (F1~F7 모두 검증)
**선행 문서**:
- `docs/plans/PRD/02-strategy-decision.md` §3.2 (결정 27~41)
- `docs/analysis/toss-api-survey.md` v2
**관련 결정**: 결정 32 (9 인자 가중), 결정 41 (인사이더 매수)

---

## 0. 본 문서의 위치

Moonshot Picks 모듈은 "회당 +100% 가능 종목"을 발굴하는 **카지노 자금 운영 시스템** (결정 29: 시드 100% 소실 OK).
검증된 학술 데이터 + 우리 환경 (마이크로캡·프리마켓·5일·+100%) 특화 신규 가설을 결합해 가중치를 결정.

**Phase 1 (본 문서)**: 학술 베이스라인 검증 + 신규 가설 발굴
**Phase 2 (운영 1~3개월 후)**: 자체 운영 데이터로 가중치 재조정

---

## 1. 학술 검증 — 5 패턴

### 1.1 F3 — Post Earnings Announcement Drift (PEAD)

**가설**: 어닝 서프라이즈 종목은 발표 후 며칠~몇 주에 걸쳐 같은 방향으로 drift.

**학술 검증** (✅ 강함):
- 발견자: Ball & Brown (1968)
- 최근: Garfinkel, Hribar, Hsiao (2024) — 상위 SUE 데실 long + 하위 데실 short → **3개월 5.1% 위험조정 수익, 연 20%+**
- **마이크로캡에서 drift 가장 강함** (소형주 → 큰 효과 / 대형주 → 약한 효과)
- 차익거래 비용 큰 종목 (마이크로캡 + 애널 미커버)에서 강함

**우리 환경 적합도**: ⭐⭐⭐⭐⭐ — Moonshot universe (모든 미국 주식, 마이크로캡 중심)에 완벽 일치

**채택**: 가중 25% → **30%** ⬆ (Phase 1)

---

### 1.2 F6 — Insider Buying Clusters (SEC Form 4)

**가설**: 임원·이사 다수가 단기간에 자사 주식 매수 = 펀더멘털 강한 신호.

**학술 검증** (✅ 강함):
- 단독 insider buy = **연 +4~8% excess return** (Wharton 등)
- **3+ insiders cluster within 15 days** = 12개월 above-market returns 검증
- 마이크로캡에서 gradient boosting 모델 적용 가능 (2024 연구)
- **한계**: 짧은 holding period (5일)에는 효과 약함, transaction cost·liquidity 제한

**우리 환경 적합도**: ⭐⭐⭐⭐ — 5일 단기 효과는 약하나 신호 자체 강력. **결합 조건**으로 가치 큼.

**데이터 소스**: SEC EDGAR Form 4 (무료, https://www.sec.gov/cgi-bin/browse-edgar)

**채택**: **신규 인자 결정 41 (가중 10%)** ⭐

---

### 1.3 F1 — Short Squeeze

**가설**: 높은 SI% + 작은 Float + 가격 모멘텀 시작 = 매도 압력 폭발 → 폭등.

**학술 검증** (⚠️ 사후 가능, 사전 어려움):
- 학술 모델: SI ratio ≥ 4.17 → 700% 가격 점프 가능성 (AMC 사례)
- 핵심 신호: SI%, Float, days-to-cover, 소셜 sentiment
- **"predicting next short squeeze is highly risky"** (학술 합의)
- 발생 시점·강도 fat tail — 통계 예측 어려움

**우리 환경 적합도**: ⭐⭐⭐ — 결합 신호로만 가치, 단독은 약함

**채택**: 가중 10% → **6%** ⬇ (단독 약함 반영)

---

### 1.4 F4 — WSB Reddit Sentiment

**가설**: WallStreetBets 멘션 폭증 = 밈주식 운동 시작 = 폭등 후보.

**학술 검증** (⚠️ risk-adjusted 알파 약함):
- **VanEck BUZZ ETF** (WSB 추종): 2021-2024 동안 **S&P 500 대비 -15.16% underperform**
- 일반적으로 risk-adjusted 알파 부족
- 단, **volume of comments + Google Trends** 같은 단순 메트릭이 sentiment 분석보다 강함
- 특정 케이스 (GME, AMC)에는 매우 강함 — fat tail 가능

**우리 환경 적합도**: ⭐⭐ — 단순 멘션 수만 활용. 결합 신호로 가치.

**채택**: 가중 15% → **8%** ⬇ + **측정 방식 단순화** (sentiment 분석 X, 단순 멘션 카운트)

---

### 1.5 F2 — Gamma Squeeze (Option Flow)

**가설**: 옵션 콜 OI 폭증 + 비정상 거래량 = 마켓 메이커 헤징 → 가격 상승 피드백.

**학술 검증** (⚠️ 대형주만 효과):
- 0DTE 옵션이 S&P 500 옵션 거래량의 48% (2024)
- 학술: gamma exposure 패턴 91.2% 검출 가능 (3가지 framing: positioning·pinning·0DTE)
- **단기·일중** 가격 movement에 강함
- **마이크로캡·페니스톡엔 옵션 시장 부재** → 적용 불가

**우리 환경 적합도**: ⭐ — 페니스톡엔 옵션 시장 없음. 대형주만 효과.

**채택**: **조건부 적용** (시총 $500M+ 종목에만). 가중 6%로 유지 (스퀴즈 통합).

**데이터 비용**: Polygon $30/월 (Phase 2 결정 보류)

---

### 1.6 F5 — FDA · 임상 발표 (v2 추가 검증)

**가설**: FDA 의사결정(PDUFA), AdCom, Phase 3 발표 등 binary catalyst.

**학술 검증** (✅ 검증됨):
- **Event Study** (PMC 2013, 2022): 발표 당일 평균 위험조정 수익률
  - Positive 결과 (16/24, 67%): +0.8% (대형 바이오 기준)
  - Negative 결과 (8/24, 33%): -2.0%
- **소형주 바이오 binary**: 발표 시 ±50~80% 변동성 (fat tail)
- **사전 정보 누출 패턴**: D-120 ~ D-3 동안 winners +27% vs losers -4% (PubMed 2000 연구)
- PDUFA dates 등 일정 미리 알려짐 → **사전 추적 가능**

**우리 환경 적합도**: ⭐⭐⭐⭐ — 소형주 바이오 fat tail. 일정 기반 미리 추적.

**채택**: **F3 카탈리스트 30% 내 sub-category로 통합** (별도 가중 X)
- 어닝 D-7 (PEAD)
- **FDA PDUFA 일정 D-7 ~ D-1**
- **FDA AdCom 결과 발표일**
- M&A 루머·보도자료

**데이터 소스**:
- BiopharmaWatch FDA Calendar (무료)
- SEC EDGAR (Phase 3 진행 공시)
- ClinicalTrials.gov (임상 일정)

---

### 1.7 F7 — 갭다운 안정화 (v2 추가 검증)

**가설**: 일중 -20% 갭다운 + 종가가 시가 상회 + 거래량 평균 3배 = 패닉셀링 후 반등.

**학술 검증** (⚠️ 약함):
- 정량 학술 통계 부족 — 대부분 practitioner perspective
- 검증된 패턴:
  - "Wide-range reversal candle + volume spike" = capitulation 신호
  - "Volume > 3x avg + price down >5% + no catalyst" = 부분 반등 가능
- S&P 500 사례: 갭다운 -2.4% → 일중 +2.6% reversal (5% 일중 swing)

**우리 환경 적합도**: ⭐⭐ — 마이크로캡엔 자주 발생하나 noise 큼

**채택**: **별도 인자 X. H3 (52w 저점 + 거래량) 결합 sub-condition으로 통합**
- H3 강화 조건 추가:
  - 갭다운 -10% 이상 발생 후 종가 ≥ 시가 (intraday reversal)
  - 거래량 ≥ 평균 3배
→ Capitulation reversal 신호

---

## 2. 학술 검증 후 가중치 재조정

```
[원본 8 인자]                         [Phase 1 검증 후 9 인자]
변동성           15% │ ▶ 12%
카탈리스트       25% │ ▶ 30%  ⬆ (PEAD 학술 가장 강함)
스퀴즈           10% │ ▶ 6%   ⬇ (사전 예측 어려움)
소셜 (WSB)       15% │ ▶ 8%   ⬇ (BUZZ ETF 알파 약함)
뉴스 (LLM)       15% │ ▶ 12%
기술 돌파         8% │ ▶ 8%   (유지)
갭+거래량 폭증    8% │ ▶ 12%  ⬆ (EHGO 사례 부합)
52w 저점          4% │ ▶ 2%
인사이더 매수 ⭐   - │ ▶ 10%  ⭐ NEW (F6, 결정 41)
                          ─────
                          100%
```

→ 02 §3.2 결정 32 갱신 완료 (2026-06-18).

---

## 3. 우리 환경 특화 신규 가설 5종 — Phase 2 검증 대상

학술 연구가 부족한 영역 (마이크로캡 + 프리마켓 + 5일 + +100% fat tail).

### H1 — 마이크로캡 보도자료 + 갭업

**근거**: EHGO 2026-06-17 사례 (시총 $2.8M, AI 파트너십 발표, +321% 종가).

```
조건:
  시총 < $50M
  AND 회사 발표 (PRNewswire/GlobeNewswire) 24h 내
  AND 시가 ≥ 전일 종가 × 1.5 (+50% 갭업)
  AND 거래량 ≥ 평균 20배
→ 강한 매수 신호
권고: 매수 옵션 (b) 떡락 대기 우선, (a) 시가 매수 비권고
데이터: PRNewswire/GlobeNewswire RSS + Toss API 시세
```

### H2 — 프리마켓 갭 + 모멘텀 지속

**근거**: 페니스톡 갭업 후 정규장 추가 상승 패턴.

```
조건:
  프리마켓 최고가 ≥ 전일 종가 × 2.0
  AND NY 06:00 (KST 19:00) 시점 가격 유지 또는 상승
→ 정규장 진입 시 추가 상승 가능성
데이터: 프리마켓 시세 (Toss API 또는 외부)
```

### H3 — 52w 저점 + 첫 거래량 폭증 (F7 결합 v2 강화)

**근거**: AZTR 2026-06-17 일중 +200% 추정 사례 (저점 부근 반등) + F7 갭다운 안정화 패턴 결합.

```
기본 조건:
  가격 ≤ 52w low × 1.20 (저점 +20% 내)
  AND 거래량 ≥ 평균 5배 (5일 연속 증가)
  AND 카탈리스트 ≥ 약 (보도자료·임상 등)

⭐ F7 강화 조건 (v2 추가):
  + 갭다운 -10% 이상 발생 후 종가 ≥ 시가 (intraday reversal)
  + 거래량 ≥ 평균 3배
  → Capitulation reversal 신호 결합

→ 매집·반등 후보 (학술 + 실증 결합)
데이터: Toss API 일봉/분봉 + 거래량
```

### H4 — 소셜 폭증 + 카탈리스트 결합

**근거**: F4 단독은 약하나 F3 (PEAD)와 결합 시 강함 (학술 ⊕ 실증).

```
조건:
  WSB 24h 멘션 ≥ 평균 5배 (단순 카운트, sentiment 분석 X)
  AND 카탈리스트 D-7 내 (어닝/FDA/M&A)
  AND 가격 모멘텀 5d +10%
→ 결합 fat tail 후보
데이터: Reddit PRAW + 어닝 캘린더
```

### H5 — 공매도 + Float 작음 + 가격 시작

**근거**: F1 학술 모델 (AMC SI ratio 4.17 → 700% 가능성).

```
조건:
  SI ratio ≥ 4.17 (학술 임계)
  AND Float < 20M주
  AND 5일 모멘텀 ≥ +10%
→ Short Squeeze 발생 임계 부합
데이터: FINRA SI 데이터 + Toss API Float
```

---

## 4. Phase 2 검증 절차 (운영 1~3개월 후)

```
1. 자체 운영 데이터 누적
   - 매일 16:50 KST Top 10 추천 → DB 저장
   - perf_1d/3d/5d 자동 추적

2. 각 가설별 적중률 분석
   - H1: 마이크로캡 보도자료 + 갭업 종목의 5일 +100% 도달 비율
   - H2~H5: 동일 분석

3. 학술 베이스라인 5 패턴도 자체 데이터로 재검증
   - PEAD: 우리 universe에서 실제 PEAD 작동 빈도
   - Insider: 5일 단기 효과 보강 가능성

4. 가설 채택·기각·가중 조정 결정
   - 채택: 결정 32 가중치 재배분 또는 신규 결정 추가
   - 기각: §3.2.8에서 결과 기록 후 제거
```

---

## 5. 동업자 솔직 보고 — 한계 인정

### 5.1 학술 데이터의 한계
- 대부분 학술 연구 = 대형주 + 정규장 + 월 보유 중심
- 우리 환경 (마이크로캡 + 프리마켓 + 5일 + +100% fat tail) 학술 데이터 빈약
- **자체 운영 데이터가 궁극 근거** (Phase 2)

### 5.2 가중치는 추정치
- 9 인자 가중 (12+30+6+8+12+8+12+2+10=100)은 학술 + 추정 결합
- 실제 최적 가중은 운영 데이터로만 결정 가능
- Phase 2 운영 1~3개월 후 ML (gradient boosting 등)로 재조정

### 5.3 신규 가설 H1~H5는 검증되지 않음
- 학술 백테스트 없음 (학술 데이터 없는 영역)
- 우리 자체 운영 데이터로만 검증 가능
- 채택 = "후보로 기록 + Phase 2 검증" 의미

### 5.4 카지노 자금 운영의 본질
- "+100% 가능 종목"은 fat tail
- 평균 음수 가능성 인지 (결정 29 시드 100% 소실 OK)
- 시드 보존 안전장치: -50% 손절, 5일 시간 손절, manipulation 위험 표시 (결정 40)

---

## 6. 변경 이력

| 날짜 | 변경 | 비고 |
|---|---|---|
| 2026-06-18 | v1 초안 — 5 패턴 학술 검증 (F1·F2·F3·F4·F6) + 9 인자 가중치 + H1~H5 신규 가설 | Phase 2 검증 대기 |
| 2026-06-19 | **v2 — F5·F7 추가 검증 완료**. F5 (FDA·임상) ✅ 검증 → F3 카탈리스트 sub-category로 통합 (PDUFA Calendar 추적). F7 (갭다운 안정화) ⚠️ 학술 약함 → H3 결합 sub-condition으로 통합. **결정 32 가중치 변경 없음**. F1~F7 모든 패턴 Phase 1 검증 완료. | Phase 1 능동적 발굴 완료 / Phase 2 운영 데이터 대기 |
| 2026-06-19 | **v3 — 데이터 스택 분리**. Discovery는 **Toss API 미사용** (자동매매 코어 전용). 모든 데이터 소스 외부 무료 (Stooq·Finnhub Free·SEC EDGAR·FINRA·Reddit PRAW·RSS). 운영비 $5~15/월 (Anthropic Haiku 한정). | 02 결정 15·23·24·45 동기 |

---

## 7. Sources

### 학술 논문 / 검증
- [Post-Earnings Announcement Drift — UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)
- [Quantpedia — Post-Earnings Announcement Effect](https://quantpedia.com/strategies/post-earnings-announcement-effect)
- [Insider Cluster Buying — MarketTriage](https://markettriage.com/insider-trading-signals)
- [Estimating the Returns to Insider Trading — Wharton](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/9919.pdf)
- [WallStreetBets — Alpha Architect](https://alphaarchitect.com/wallstreetbets/)
- [Short Squeeze AMC GME Analysis — UBPLJ](https://www.ubplj.org/index.php/jpm/article/download/1967/1731/6635)
- [Gamma Exposure Patterns — Barchart](https://www.barchart.com/education/understanding_gamma)
- [Reddit Sentiment Stock Prediction — arXiv](https://arxiv.org/pdf/2507.22922)
- [Stock Returns and Clinical Trial Results: Event Study — PMC 2013](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3737210/)
- [Sponsor Stock Prices to Clinical Trial Outcomes: Event Study — PMC 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9439234/)
- [Biotech Insider Trading Pre-Announcement — PubMed 2000](https://pubmed.ncbi.nlm.nih.gov/10736971/)
- [Price Gap Anomaly in US Stock Market — ResearchGate 2020](https://www.researchgate.net/publication/339811620_Price_gap_anomaly_in_the_US_stock_market_The_whole_story)

### 데이터 소스 (무료)
- [SEC EDGAR Form 4 Filings](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4)
- [FINRA Short Interest Data](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files)
- [Reddit PRAW Documentation](https://praw.readthedocs.io/)
- [PRNewswire RSS](https://www.prnewswire.com/rss/)
- [GlobeNewswire RSS](https://www.globenewswire.com/rss/)

### 실증 사례 (영구 기록 — 02 §3.2.7 참조)
- [EHGO Stock Rockets — StocksToTrade](https://stockstotrade.com/news/eshallgo-inc-ehgo-news-2026_06_17/)
- [Azitra (AZTR) Stock Overview — StockAnalysis](https://stockanalysis.com/stocks/aztr/)
