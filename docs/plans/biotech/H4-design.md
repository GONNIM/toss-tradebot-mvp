# H4 검증 설계서 초안 (B108-3 · 2026-09-06 · 사후 조정 금지)

**연계**: `README.md` §2 H4 정의 · §2-0 판정식 · §3-5 백테스트 사양 v1

**상태**: 초안 · Fable 검수 대기 · 실행 없음 (SEC 대기 국면 병행 준비)

---

## 1. H4 정의 (README §2 그대로)

- **첫 언급**: apewisdom + 자체 크롤 (r/biotechstocks · r/RegenerativeMed · r/CRISPRPharma 등) 에서 특정 티커의 **첫 언급 (first mention)** 발생
- **창**: **D+1 ~ D+10 net return** (밈주 초단기 특성)
- **benchmark**: XBI (§3-5 · 참고 IWM 병기)
- **알파 임계 (README §2 커밋값 그대로)**:
  - **진성 사례 net excess ≥ +3%**
  - **히트율 ≥ 30%**
  - **HOT 임계 위양성률 ≤ 5%**

## 2. 이벤트 정의 (사전 커밋)

**이벤트 = 한 티커에 대한 첫 언급 시각 (UTC)**
- 첫 언급 이전 시계열에 해당 티커 mention 이 0 이어야 함
- 재발 이벤트 (같은 티커 두번째 이후) 는 **본 백테스트 제외** (첫 언급 알파 검증이 목적)
- 다중 subreddit 동일 티커 첫 언급 시 최초 subreddit 만 채택

**대상 티커 (biotech 필터)**:
- `backend/data/biotech_ticker_set_add7af7.csv` (B108-2 · 304 · H3 SIC 2834/2836 ∪ XBI holdings)
- 이 목록 외 티커의 mention 은 H4 이벤트로 인정하지 않음 (독립 이름공간)

## 3. 데이터 소스 (사전 커밋)

**social**:
- `apewisdom` (기존 파이프 · `backend/discovery/data_sources/apewisdom.py`)
- 자체 크롤 (r/biotechstocks 등 · Reddit 승인 제약으로 실행 여부 미정 · 초안에서는 apewisdom 만 표준)

**social 시계열 저장**:
- 기존 `meme_score_history` DB (2026-07-03~2026-08-13 · 1,042,500 rows · 1,305 tickers) 은 **score** 이력 (mention 자체 아님)
- 첫 언급 판정을 위해 **mention time series 별도 수집 필요** (H4 실행 전제)
- MVP: `meme_score_history` 의 첫 진입 (score>0 · 이전 부재) 로 근사 시도 · 편향 명시

**가격**:
- 1차: `backend/data/h3_prices_merged_add7af7.csv` (382,820 rows · 286 tickers · yfinance+tiingo+simfin) 재사용
- 부족분: yfinance 재수집 (XBI holdings 만 있고 h3_prices 부재 티커)
- **adj_close** 사용 · **raw close 는 mcap 산출 시만**

**benchmark**:
- `backend/data/benchmarks_add7af7.csv` (XBI · IWM · 1,677 rows · 2020-01-01~2026-09-04)

## 4. 백테스트 사양 (README §3-5 승계 · 30d/180d → 10d)

**진입·창**
- 진입: **D+1 종가 (adj_close)** · 미래 참조 배제 (§3-5 동일)
- 창: **D+1 ~ D+10** (H4 전용 · 밈주 초단기)

**benchmark·net excess**
- 주 벤치 **XBI** · 참고 병기 **IWM**
- **net = 왕복 거래비용 1.0% 차감** (1차 판정)
- 민감도 **0.5% / 2.0% / 5.0%** 병기

**판정식 (§2-0)**
- bootstrap **10,000회 · seed 42**
- block bootstrap (티커 클러스터 재추출) 병기
- `alpha_confirmed` = `mean_net_excess ≥ +3% AND hit_rate ≥ 30% AND CI_iid_95_lo > 0`
- §2-0 서열: **1차 mean · 2차 hit**

**HOT 임계 위양성률 (H4 고유)**
- HOT 정의: score ≥ 0.75 (기존 밈주 파이프 `confluence.py` 준용)
- 위양성 정의: HOT 진입 후 **D+1 ~ D+10 net excess ≤ 0**
- 진성 정의: HOT 진입 후 D+1~D+10 net excess ≥ +3%
- 판정: **위양성 rate ≤ 5%** (H4 알파 임계 3항 중 1항)

**버킷 (§3-5 승계)**
- market cap: [$50M,$300M) / [$300M,$1B) / [$1B,$5B]
- subsector: SIC 2834 · 2836 · XBI-only (SIC 미확인 XBI 편입 티커)

**이벤트 적격 [D-30, D+10] 가격 실존** (§3-4 준수 · 창 단축 시 [B99] shortened 규약)

**비용 모형**
- 왕복 1.0% (§3-5 동일 · 밈주 회전 특성 반영 시 사후 조정 시 별도 승인)

## 5. 사전 커밋 항목 (실행 후 변경 금지)

1. **알파 임계 3항** · net excess ≥ +3% · hit ≥ 30% · HOT 위양성 ≤ 5%
2. **HOT 정의** · score ≥ 0.75 (기존 confluence 준용 · 재정의 금지)
3. **첫 언급 정의** · 이전 시계열 mention 0 (재발 제외)
4. **subsector 축** · SIC 2834 / 2836 / XBI-only
5. **비용 모형** · 왕복 1.0%
6. **표본 필터** · biotech_ticker_set_{sha}.csv 외 티커 이벤트 인정 불가

## 6. 예상 표본 (B108-4 dry-run · 호출 0회 · 2026-09-06)

**입력**:
- `biotech_ticker_set_add7af7.csv` **n=304**
- `meme_score_history` DB · 2026-07-03~2026-08-13 · 41일 · distinct tickers **n=1,305**
- `h3_prices_merged_add7af7.csv` distinct tickers **n=286**

**교집합**:
- biotech ∩ score_history = **8 tickers**
- biotech ∩ h3_prices_merged = **210 tickers**

**첫 언급 후보 표본 (창 [D-30, D+10] 가격 실존 검사 후)**:
- **eligible n = 6**
- excluded_no_price = 2 · excluded_no_pre_window = 0 · excluded_no_post_window = 0
- subsector 분해: SIC 2834 = 3 · 2836 = 3 · other/xbi-only = 2
- 첫 언급 시각 범위: 2026-07-05 ~ 2026-08-11

**판정 (B108-4 결론)**:
- 예상 표본 **n=6** · bootstrap 10,000 판정에 **크게 부족** (§3-5 미달)
- 원인: `meme_score_history` 는 실 운영 시작(2026-06-25) 이후 41일 · 이력 부재
- 시사: MVP 착수 전 (a) mention 시계열 확장 수집 또는 (b) 수동 사례 방식 재활용 필요
- **판단은 초안 검수 시 결정** · 현 초안은 데이터 부재 사실 명시로 종결

## 7. 알려진 편향·리스크

- **social 시계열 부재**: 2026-07-03 이전 apewisdom 이력 없음 · 3년 이력 재구성 불가 · Wendy's 방식 (수동 사례) 병행 필요 여부 별도 판단
- **subreddit 편중**: apewisdom 은 12+ 서브레딧 종합 · 바이오 전용 서브 커버율 별도 조사 필요
- **첫 언급 정의 취약**: `meme_score_history` score>0 진입은 mention 자체가 아닌 confluence 진입 · 근사 편향 존재
- **HOT 정의 이식 위험**: 기존 밈주 HOT 임계가 바이오에 동일 유효한지 별도 검증 필요 (H4 실행 후 사후 조정 금지 · 초안 커밋 후 이의 있을 시 재초안)

## 8. 실행 순서 (승인 후)

1. Fable 초안 검수
2. mention 시계열 수집기 신설 (apewisdom snapshot 저장) 또는 `meme_score_history` 근사 결정
3. 첫 언급 이벤트 목록 산출 (`h4_events_{sha}.csv`)
4. 백테스트 엔진 사용 (`biotech_h3_backtest.py` 재사용 여부 판단 · 30d/180d → 10d + HOT 위양성 로직 추가)
5. 결과 리포트 + Fable 반박 응답

---

**부속**:
- `backend/data/biotech_ticker_set_add7af7.csv` · 304 티커 · H3 SIC 155 + XBI-only 83 + 교차 66
- 밈주 파이프 자산 인벤토리: B108-1 표 (review-log)
