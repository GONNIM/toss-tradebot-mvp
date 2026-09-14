# Biotech Catalyst Radar · 바이오 폭등주 사전 감지 (기획 v2 · 검증 프로젝트)

**작성일**: 2026-09-02
**v2 갱신**: 2026-09-02 · Fable v1 리뷰 NO-GO 반영
**v2.1 갱신**: 2026-09-02 · Fable v2 리뷰 지적(B12·B13) 반영 · 정식 GO
**작성자**: Claude Opus 4.7 · 사용자 승인 후 저장
**상태**: **Phase A 진행 중 · Fable 5 GO (2026-09-02)**
**계기**: Obsidian Note `2026-08-24 · 반도체 몰락 후 주도주 후보 TOP 3` + 사용자 이월 액션 (2026-09-02) + "주가는 실적을 앞서간다" 명제

**참조 이력**:
- L14 Serenity Hunter · 인플루언서 1인 소스 알파 부재 자동 폐기 (2026-08-04) — 본 기획의 반면교사
- `docs/plans/serenity-hunter/RISK-PRINCIPLES.md` — 폐기 아키텍처·마찰 2단계 승계
- `docs/plans/meme-stock-discovery/README.md` — Wendy's 밈주 발견 패턴 (소셜 confluence)
- `docs/plans/activist-radar/README.md` — SC 13D/Form 4 매집 감지 패턴
- 사용자 명시 사례: (1) 유전자 편집 바이오 주가 폭발 (2) 비만치료제 발표 주가 폭발

---

## 0. 본 기획의 정체성 · 안전선

**본 기획은 페이지·UI·알림을 만드는 것이 아니다.** 바이오 섹터에서 "폭등 이전"에 잡을 수 있는 알파가 실제로 존재하는지를 **데이터로 답하는 검증 프로젝트**다.

### 0-☆ 이중 트랙 (WP36 · 2026-09-13 · 사용자 철학 명문화)

**"정답을 찾는 작업이 아니라 가능성을 찾아 돌파하는 작업"** (사용자 원문). 판정 (가능/불가능) 이 아니라 **조그마한 가능성에서 돌파구**를 찾는다. 두 트랙 병행:

| 트랙 | 목적 | 규율 | 산출물 |
|---|---|---|---|
| **탐색 트랙** | 형태·방향·조건 관찰 | 사전 커밋 완화 (탐색 표기 · 알파 주장 없음) | 관찰 목록 · 효과 크기 지도 · "가능성 지도" |
| **확증 트랙** | 알파 존재 통계 검정 | 사전 커밋 · 미래 참조 금지 · 팁 금지 · 반자동 티켓까지 (불변) | 봉인 리포트 · 관문 검수 |

**폐기 정의 수정 (WP36)**: 종전 "알파 부재 → 폐기" → **"이 형태 폐기 · 방향은 가능성 지도에 유지"** (재개 경로 사전 등록 후 확증 트랙 재도전)

**모든 리포트·세션 보고 말미 필수**:
- **가능성 지도 3줄** (WP36 · 의무):
  1. 가장 밝은 자리 (현재 데이터에서 가장 강한 방향·조건)
  2. 죽은 자리 (탐색 완료 · 재도전 시 사전 등록 필요)
  3. 다음에 팔 자리 (다음 세션 우선 탐사 대상)

**"유의하지 않음 ≠ 없음" 규칙 (WP36)**:
- 통계적 유의성 부재 = 알파 부재 아님 (검정력 부족일 수 있음)
- 리포트에 **효과 크기 × 빈도 = 만원당 기대손익** 병기 필수 (예: mean +2% · 히트 40% · 연 8건 → 만원×0.02×8 = 160원/년)

- 알파 존재 확인 시에만 UI 후속 개발 (L14 원칙 승계)
- 히트율 저조 시 결과 리포트 자체가 최고 산출물 (시드 100만원 보전)
- 인플루언서 1인 소스 알파 배제 (L14 실증)
- 폐기 게이트 자동 발동 (`constants.DEPRECATION_OVERRIDE_TICKET` 계승)

### 0-★ 시간축 층 (B123 · 2026-09-06 · "소문에 사서 뉴스에 팔아라")

폭등 이전 알파 발굴을 **정보의 도달 순서**로 분해한다. 검증 프레임은 각 층별로 독립 판정하며, 결합은 개별 알파 확인 이후로 미룬다 (§2-0 · L14 원칙).

| 층 | 정의 | 대표 채널 | 시각 필드 | 담당 가설 |
|---|---|---|---|---|
| **1. 소문** | 공개 뉴스 이전 · 전문가 채널의 선행 언급 | ClinicalTrials.gov 변경 · bioRxiv/medRxiv/PubMed · 학회 초록 · FDA/EMA 캘린더 · Form 4/13D · KR 조회공시 | 소스 발행 시각 (UTC 또는 KR 09:00 기준) | **H8 · 소문 지수 선행성** |
| **2. 뉴스** | 회사 발표 · 규제기관 발표 · 대중 매체 최초 보도 | PR Newswire · Business Wire · Reuters/Bloomberg · 8-K/6-K/KIND | 최초 공개 시각 | H1a·H1b (사전 공지 catalyst) · H3 (activist filing 자체) |
| **3. 뉴스 이후** | 소매 소셜 · 밈주 확산 · 뉴스 후 반응 | Reddit · Twitter/X · apewisdom · 카페·유튜브 | 소셜 스냅샷 시각 | H2 (테마 확산) · H4 (Reddit 첫 언급) |

**격언 분해**:
- "**소문에 사서**" → 층 1 (소문) 신호 상승 시점 진입 = H8
- "**뉴스에 팔아라**" → 층 2 (뉴스) 공개 시점 청산 근거 = H8 검정 3 (D+1~D+30 CI 상한 ≤ 0)
- 뉴스 후 반응 활용 (H2·H4) 은 위 순서와 별개 가설로 병행

**단일 소스 금지 (L14)**: H8 소문 지수는 **채널 ≥2 합류** 시에만 유효 신호. 소매 소셜 (H4) 과 명확히 분리 · L14 폐기된 인플루언서 채널 재도입 아님.

---

## 1. WHY · 문제 정의

### 1-1. 사용자 원문 (2026-09-02)

> 옵션 B가 가장 유사하다. 예전 유전자 편집 관련 바이오 주가 폭발… 그리고 최근 비만치료제 발표 관련 주가 폭발 같은 상황을 찾을 수 있는 체계를 구축한다.

### 1-2. 배경 인사이트

- TikTok @hesschandler · "반도체 몰락 후 주도주 후보 TOP 3 · 금광/AI감시SW/바이오" (2026-08-24)
- 사용자 명제: "주가는 실적을 앞서간다 · 돈이 몰릴 섹터 예측이 우선인가"
- 정직한 답: 매크로 섹터 예측은 컨센서스 흡수로 알파 소실이 잦음. **그러나 바이오 섹터는 임상 이벤트·테마 확산·activist 매집·소셜 시그널 등 여러 leading indicator가 조합 가능**

### 1-3. 사용자 참조 사례 원형

| 원형 | 예시 | 알파 유형 |
|---|---|---|
| **유전자 편집 클러스터** | CRSP·NTLA·BEAM·EDIT 폭등 · Vertex/CRISPR CASGEVY 승인(2023) 후 후발주 확산 | 테마 클러스터형 (첫 종목 → 후발주 lead time 존재?) |
| **비만치료제 클러스터** | LLY(Mounjaro/Zepbound) · NVO(Ozempic/Wegovy) 폭등 · 국내 한미약품·펩트론 후발 | Phase 3 readout catalyst + 후발주 확산 |
| **단일 catalyst 폭등** | FDA PDUFA 승인 · ADCOM 만장일치 · Phase 3 top-line beat | D-30~D-1 정보 leak/기관 매집 |

**본 기획은 이 3원형을 하나의 검증 프레임에 담는다.**

---

## 2. WHAT · 검증할 가설 (9개 · H1a·H1b·H2·H3·H4·H5·H6·H7·H8)

각 가설은 **알파 존재 여부를 데이터로 답할 수 있어야** 한다 (Fable 5 L14 지적 승계).

### 2-0. 임계·판정식 공통 규약 (B3 · Fable 리뷰 v1 반영 · 2026-09-02)

- **net 정의**: 모든 excess(초과수익) 수치는 **왕복 거래비용·슬리피지 차감 후 (net)** 값을 사용한다. gross 수치는 참고만 기록하고 판정에는 쓰지 않는다.
- **판정식 (통과)**: `bootstrap 95% 신뢰구간 하한 > 0` **이면서** `net excess 평균 ≥ 임계` 두 조건 동시 충족 시 알파 확인.
- **지표 서열**: 1차 지표 = **평균 net excess**, 2차 지표 = **히트율**. 1차가 임계 미달이면 2차와 무관하게 알파 부재로 판정.
- **폐기 조건**: 통과 조건의 여집합. 특히 `bootstrap 95% CI 하한 ≤ 0` 이면 히트율이 임계를 넘더라도 알파 없음으로 자동 폐기.

### H1a · 사전 공지 catalyst (PDUFA · ADCOM) — 사전 30일 초과수익 존재
- **정의**: **날짜가 사전 공개된 이벤트만 포함**. FDA PDUFA date · 사전 공지된 ADCOM meeting date. 사전 공개 캘린더 부재 이벤트(accelerated review 등)는 원천 배제.
- **검증**: 각 catalyst 이벤트 D-30~D-1 구간 · 시가총액 $50M~$5B 바이오 · IWM/XBI benchmark 대비 net excess return
- **알파 임계**: net excess ≥ +2% · 히트율 ≥ 30% (Fable 리뷰 v1 반영 · 2026-09-02)
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 OR 히트율 < 20%
- **데이터 소스**: FDA Drug Approvals Calendar · biopharmcatalyst.com 크롤(가능시)

### H1b · Phase 3 readout guidance window — 회사 가이던스 시작일 기준 초과수익
- **정의**: **회사가 제시한 guidance window(발표 예상 기간)의 시작일을 기준점**으로 사용. 실제 발표일 기준 측정 금지(look-ahead bias 배제).
- **검증**: guidance start D-30~D-1 구간 · 시가총액 $50M~$5B 바이오 · IWM/XBI benchmark 대비 net excess return
- **알파 임계**: net excess ≥ +2% · 히트율 ≥ 30% (Fable 리뷰 v1 반영 · 2026-09-02)
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 OR 히트율 < 20%
- **데이터 소스**: ClinicalTrials.gov API · 회사 IR 공시(8-K guidance) · 자체 파싱

**H1a·H1b 합산 금지**: 두 가설의 리포트는 별도 산출하며 이벤트 표본을 합산·pooled 통계로 처리하지 않는다. 각각 독립 알파 판정.

### H2 · 테마 클러스터 확산 lead time — 첫 대표주 폭등 후 후발주 진입 여지
- **정의**: 특정 테마(유전자편집·비만치료제·항암ADC·GLP-1·RSV백신 등)의 대표주 20D +50% 폭등 이벤트 후 · 동일 테마 후발주(peer group)의 D+1~D+30 return
- **검증**: subsector 분류 내 대표주가 20거래일 +50% 를 기록한 사건을 코드로 전수 추출한다. 사람은 사후에 제외 사유만 기록하며, 사건을 추가로 집어넣지 않는다. peer group 매핑은 subsector 분류 그대로 승계 · 애널리스트 리포트 등 재량 소스로 사건 추가 금지.
- **알파 임계**: 후발주 net excess ≥ +5% · 대표주 폭등 감지→후발주 진입 lead time 5거래일 이상 (Fable 리뷰 v1 반영 · 2026-09-02)
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 OR 코드 전수 추출 사건의 50% 초과에서, 대표주 폭등 감지 시점(D+1)에 후발주 peer group 평균 net excess 가 이미 0 이하 (확산 소진 판정)
- **데이터 소스**: subsector 분류(SIC/NAICS/자체 subsector 테이블) · 종가 데이터
- **표본 출처**: 코드 전수 추출 규칙 = `대표주 시총 ≥ $500M AND 20D return ≥ +50%` · 룰만 사전 확정 · 사후 사건 인입 금지

### H3 · Biotech Activist/Insider 매집 — SC 13D/Form 4 사전 신호

**1차 실행 (WP30 · 2026-09-12 · 사전 커밋)**:
- **13D_new + 13G_new 346 events (B98 확정)** 만 · Form 4 (F4_buy) 는 별도 리포트로 분리
- **F4_buy 사후 합산 금지**: submissions.json form=4 접근 오류 확인 후 EFTS 기반 재수집 (WP28-2) 완결 시 별도 리포트
- 알파 판정 = 13D_new + 13G_new 통합 표본 기준 · Form 4 는 추후 confirmation 신호
- **정의**: 바이오 특화 activist (RA Capital · Baker Bros · Perceptive Advisors · Deep Track Capital · Farallon Capital · OrbiMed · Redmile) 의 SC 13D/13G 신규 filing · Form 4 임원 매수
- **백테스트 이벤트 정의 (B51 · 2026-09-02 · 고정)**: **신규 SC 13D · 신규 SC 13G · Form 4 취득 거래 (transaction code P 등 매수 계열) 의 3종만**. 13D/A·13G/A 정정과 Form 4 매도·기타 코드는 이벤트 제외 (census 집계에는 포함되나 신호로 쓰지 않음).
- **검증**: 지난 5년 바이오 activist filing 후 D+1~D+180 net excess return · benchmark XBI
- **알파 임계**: net excess ≥ +5% (30일) OR ≥ +15% (180일) · 히트율 ≥ 35% (Fable 리뷰 v1 반영 · 2026-09-02)
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 (양 구간 모두)
- **데이터 소스**: SEC EDGAR 기존 파이프 확장 (`backend/discovery/activist/sec_poller.py` 읽기 참조 · biotech 독립 구현 원칙 · 응용 격리 B47)

### H4 · Reddit 소셜 시그널 첫 언급 — 밈주 발견 패턴 바이오 적용
- **정의**: r/biotechstocks · r/RegenerativeMed · r/CRISPRPharma 등 · apewisdom + 자체 크롤 · 특정 티커 첫 언급 후 D+1~D+10 net return
- **검증**: 지난 3년 · Wendy's 패턴 (`docs/plans/meme-stock-discovery/03-backtest-report.md`) 바이오 서브셋 재실행 · benchmark XBI 대비 net excess
- **알파 임계**: 진성 사례 net excess ≥ +3% · 히트율 ≥ 30% · HOT 임계 위양성률 5% 이하 (Fable 리뷰 v1 반영 · 2026-09-02)
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 OR HOT 임계 위양성률 ≥ 10% OR 진성 사례 히트율 < 15%
- **데이터 소스**: apewisdom (US) · KRX 바이오 소셜은 관측 데이터 부재 · KR 트랙 제외

### H5 · 해외 촉매 → 국내 연계 (WP24-2 · 2026-09-12 · **관문 2 확정 · deprecation_triggered=true · alpha_confirmed=false**)

**상태 (2026-09-12 · WP24-2)**: 봉인 결과 = 전 창 alpha_pass False · 클러스터 10 · pre +0.22% (hit 50.8%) · imm -0.52% (hit 29% · CI [-1.23%, +0.09%]) · sus -0.67% · **"미국 GLP-1 승인 뉴스에 국내 관련주 매수 = 알파 없음 · 뉴스 직후 약세 경향"** · B8 대립가설 방향 부분 지지. 리포트: `docs/plans/biotech/verification/H5-report-20260912.md` · params v3: `backend/data/h5_params.json` · 재개 조건 = 촉매 풀 확장 (마찰 2단계 · §3-3).

---

### H5 · 해외 촉매 → 국내 연계 (B115·B116 · 2026-09-06 · 정식 편입 · 원본 정의)
- **정의**: **해외 (주로 FDA/EMA) 촉매 이벤트일 D-day 기준** 국내 (KOSDAQ150 바이오 서브셋) 에서 연계된 종목의 초과수익. 국내 자체 촉매는 KR-TRACK 의 H1-KR (별도 트랙).
- **연계 유형 4분류 (사전 커밋)**:
  1. **License-in/out**: 국내 기업이 해외 기업으로부터 기술이전 받은 파이프라인의 해외 이벤트 (예: 현대약품 · 라이선싱 계약 이력)
  2. **직접 매출/유통**: 국내 기업이 해외 승인 약물의 국내 유통·공급 계약 (식약처 품목허가 매핑)
  3. **동일 클래스 (Class effect)**: 동일 작용기전 국내 개발 파이프라인 (비만치료제 GLP-1 20건 케이스 · 후발주 확산)
  4. **부품·CDMO 공급**: 해외 승인 약물의 원료·CMO 공급사 (계약 공시 확인분만)
- **창**: **D-5 ~ D-1 (사전)** · **D+1 ~ D+5 (즉시)** · **D+1 ~ D+20 (지속)** 3구간 별도 산출
- **benchmark**: **KOSDAQ150** (KR 트랙 · IWM/XBI 아님)
- **비용**: 왕복 **0.5%** (KR 소형주 스프레드 반영 · US 1.0% 와 별도)
- **알파 임계 (사전 커밋)**: 3구간 각각 net excess ≥ 임계 (구간별 임계는 B128 H5-design 확정) · CI 하한 > 0
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 (전 구간) OR 연계 유형 매핑 없이 사후 추가 (룰 위반)
- **데이터 소스**: 식약처 품목허가 DB (한국의약품안전관리원) + DART 라이선싱 공시 + FDA 승인 캘린더 + `docs/plans/biotech/H5-design.md`
- **B8 대립가설 (KR 이식 금지 승계)**: KR 바이오는 "호재 공시 당일 매도" 관측 → H5 검정은 매수·매도 방향 모두 판정 (net excess 부호 자체가 결과)
- **H8 와 연계**: H5 이벤트는 H8 이벤트 풀에 편입 · 조회공시 (H8 국내 채널) 를 소문 지수 원천으로 사용

### H6 · 분야 순위 point-in-time (v2 · WP10 · 2026-09-08)
- **정의**: 분기 종료 시점에 알려진 **바이오 서브분야 (테마) 순위** 만 사용. 사후 관측 순위 사용 금지 (look-ahead bias 배제).
- **테마 사전 v1 (사전 커밋 · 6종 · 사용자 지시 · 사후 추가 금지)**:
  - 비만·GLP-1
  - 탈모
  - 장수·회춘
  - 식사대용·대사
  - 동면·저체온
  - 신경·기억 (alzheimer·dementia 제외 · 아밀로이드 대조군 전용)
- **대조군 (2종 · 별개 절 · 순위 산정 미참여 · v2)**: NASH 초기 · 아밀로이드
- **SF 감시 목록 (v2 · 재정의)**: **공상과학 (Sci-Fi)** · 상장 순수주 부재 · 알파 주장 없음 · 전환 신호 (임상 단계 상승·등록 급증·대형사 진입) 발생 시 정식 편입 후보 (Selection Fatigue 용어 폐기)
- **소급 규칙 (v2)**: v1 사전 6종은 2015Q1 부터 적용 · 추가 테마는 추가일 이후 시점만 유효
- **키워드 서로소 (v2)**: 신경·기억에서 alzheimer/dementia 제거 · GLP-1 겹침 방지 (비만·GLP-1 vs 식사대용·대사 GLP-1 combination)
- **매핑 (v2 · 수동 CSV 폐기)**: CT.gov 스폰서 point-in-time · 분기 t 에 테마 키워드 매치 임상 스폰서 회사 = 테마 소속
- **검증 (v2 · 이벤트 창 방식 폐기)**: 분기 리밸런싱 (상위 3분위 vs 하위 3분위 바스켓 → 다음 1분기 · 4분기 로그 초과수익 vs XBI · block bootstrap)
- **알파 임계**: 1분기 창 + 4분기 창 두 창 모두 상-하 로그 CI 하한 > 0 (한 창만 통과 = 부분 지지)
- **폐기 조건**: 두 창 모두 CI 하한 ≤ 0 OR 순위 사후 조정 발견
- **H7 연계**: H6 상위 3분위 = H7 진입 필터 (H7-design v2 §2)
- **부속**: `docs/plans/biotech/H6-design.md` v2 · 사전 커밋 12항 · WP10 실측 (6 테마 + 2 대조군 · 48분기)

### H7 · 초기 매집 바스켓 (v2 · WP11 · 2026-09-08 · 사용자 전략 복원)
- **정의 (v2 정정 · 사용자 원래 전략 복원)**: **유망 분야 초기 종목 매집 후 폭발 시점 분할 매도** 전략. 개인 매집을 activist filer 분포와 이론적 정합만 확인하며 **울프팩 정의 (n_filers ≥ 3) 는 삭제** · n_filers 는 참고 지표로만 유지.
- **진입 규칙 v2 (사전 커밋 · 사후 조정 금지)**:
  - **1차 (기본)**: `H6 상위 3분위 분야 ∈ ticker` **AND** `시총 $50M~$300M` **AND** `개발 단계 1~2상 (CT.gov Phase 1 or Phase 2)`
  - **변형 (선택)**: 1차 + `H8 소문 지수 상위 50%` (강화 필터 · 별도 판정)
- **보유 규칙 v2 (사전 커밋)**: 최장 **≤36개월** · 그 이후는 재평가 (재편입 별도 세션)
- **청산 사다리 v2 (사전 커밋 · D+180 무촉매 청산 삭제)**:
  1. **단계 전환 전 50% 청산**: 임상 단계 전환 (1상 → 2상 → 3상 · PDUFA 확정 등) 발표 **직전 (전영업일 종가)** 에 포지션 50% 청산
  2. **단계 전환 후 50% 청산**: 전환 발표 후 종가 (D-day close)
  3. **가격 사다리 (병행 · 사전 커밋)**: 진입가 대비 **3배 도달 시 33% 청산** · **10배 도달 시 33% 청산** · 잔여 34% 는 단계 전환 사다리 종료 시 청산
- **판정 지표 v2 (사전 커밋 · 히트율 임계 삭제)**:
  - **로그 수익률 기대값 (mean log return)**
  - **로그 수익률 중앙값 (median log return)**
  - **≥10x 도달 비율** (표본 중 10x 이상 도달 종목 %)
  - **≤-80% 손실 비율** (표본 중 -80% 이하 종목 %)
  - **로그 수익률 95% CI 하한 > 0** (bootstrap 10,000 · seed 42 · block bootstrap)
  - **히트율 임계 삭제** (5% 승률 + 100x 종목 존재로도 알파 성립 가능한 승수 분포 특성 반영)
- **비용 v2 (사전 커밋)**: **총 왕복 1.0%** · 분할 매도는 **분할분 비례** (50/50 → 0.5% + 0.5% 근사 · 진입 1회 + 청산 분할 = 총 1.0% 근사) · 민감도 0.5/2.0/5.0% 병기
- **폐기 조건**: 로그 CI 하한 ≤ 0 OR 로그 중앙값 ≤ 0 (양 조건 모두)
- **실행 금지 조건**: H6·H8 개별 알파 확인 전까지 H7 실행 금지 (개별 → 확증 → 결합 순서)
- **부속**: `docs/plans/biotech/H7-design.md` v2 · Tiingo supported_tickers universe skeleton v2

### H8 · 소문 지수 선행성 — 전문가 채널 사전 언급 (B123·B124 · 2026-09-06 · B127 v2 · 2026-09-06)
- **정의 (B127 v2 · 2026-09-06 · 창 겹침 수정 P1-1)**: 촉매 이벤트일(D-day) 기준 **D-180 ~ D-31** 구간의 전문가 채널 신호로 산정 (검정 1 수익 창 D-30~D-1 과 겹침 배제 · 미래 참조 방지). 채널 = AACT 스냅샷 · 프리프린트 · PubMed · 학회 초록 · 연방관보 (FDA AdCom 공고) · Form 4/13D · KR 조회공시. **채널 ≥2 합류** 시만 유효 (단일 소스 금지 · L14 승계).
- **소문 지수 정규화 (B127 v2 · P1-2)**: 원시 신호 합은 회사 규모 편향 → **티커별 기준선 D-360 ~ D-181 대비 증가율**: `index = (D-180~D-31 신호 수 - D-360~D-181 신호 수) / max(D-360~D-181 신호 수, 1)` · 사전 커밋 · 사후 조정 금지 · z-점수 대안 재검토 시 별도 세션 승인.
- **검증 3검정**:
  1. **선행성**: 촉매 이벤트별 소문 지수 상/하 절반 비교 · D-30~D-1 net excess 차이 · bootstrap 95% CI
  2. **시차 분포**: 첫 전문가 언급 → 회사 발표 → 최대 상승일 시차 중앙값·사분위
  3. **뉴스에 팔기**: 소문→뉴스 구간 수익 vs 뉴스 이후 D+1~D+30 수익 분리 · 후자 CI 상한 ≤ 0 이면 "뉴스에 팔기" 지지
- **알파 임계**: 검정 1 CI 하한 > 0 AND 검정 3 후자 CI 상한 ≤ 0 (사전 커밋 · 사후 조정 금지)
- **폐기 조건**: 검정 1 차이 CI 하한 ≤ 0 AND 검정 3 불지지
- **데이터 소스**: `docs/plans/biotech/H8-design.md` (v2.1 · WP4 · 사전 커밋 17항 · 채널 7종 접근성 SOURCES.md 확인)
- **이벤트 풀**: H1a (사전 공지 ADCOM · WP2 실측 457건 · `H1a-design.md`) · FDA 승인 · H5 국내 촉매 (v2.1 확정 · KST 캘린더일 배정)
- **H4 와 분리**: H8 = 전문가 채널 · H4 = 소매 소셜 · 절대 결합·이중계상 금지 · L14 인플루언서 재도입 아님

### Confluence 가설 (H1~H8 결합) · Phase B 이관 대상
- H1a·H1b·H2·H3·H4·H5·H6·H7·H8 중 알파 확인된 가설만 confluence 결합 검토
- 개별 알파 없으면 confluence 무의미 (개별 → 확증 → 결합 순서 강제)
- H7 은 이미 H6·H8 결합 규칙 · H6·H8 개별 알파 확인 후에만 H7 실행

---

## 3. HOW · 검증 프로토콜 (L14 승계)

### 3-1. 순서 (재작업 방지)
1. Universe 정의 (US 바이오 · 시총 $50M~$5B · 상장폐지·인수 종목 포함)
2. Data pipeline · 각 가설별 이벤트/시그널 백테스트 데이터 수집
3. Baseline benchmark 산출 (IWM · XBI · KOSDAQ150 for KR)
4. Net excess return 계산 (§2-0 규약 · gross 는 참고 기록만)
5. Confidence 예측력 검정 (top-bottom decile diff)
6. Fable 5 반박 응답 (원칙 6차 반복까지 열어둠)
7. 알파 확인 시에만 페이지 후속 개발 (Phase B)

### 3-2. 검증 산출물 (모든 가설 공통)
- `docs/plans/biotech/verification/H{1a,1b,2,3,4}-report-YYYYMMDD.md`
- 각 리포트 항목: 이벤트/시그널 정의 · sample n · 백테스트 창 · benchmark · net excess 평균 · bootstrap 95% CI 하한 · 히트율 · buckets(market cap/subsector · 2축 고정) · 결론 · Fable 반박 응답
- **버킷 정의 변경 금지 (B5)**: 백테스트 실행 후 버킷 정의(market cap 구간·subsector 분류)를 결과에 맞춰 변경 금지. 사전 확정 정의만 사용.

### 3-3. 폐기 아키텍처
- 각 가설 리포트에 `deprecation_triggered: bool` 필드
- true 시 해당 가설 자동 폐기 · 후속 개발 금지
- 재개 조건: 마찰 2단계 (RISK-PRINCIPLES §11 이력 append + 오버라이드 티켓 발급)

### 3-4. 백테스트 전처리 (B93 · 2026-09-04)
- **이벤트별 [D-30, D+180] 가격 실존 검사** · 미충족 이벤트는 표본 제외 + **제외 수 리포트 명시 필수** (역합병 전신 가격 오염 차단 · 재활용 심볼 편향 방지)

### 3-★ 보안 상시 규칙 (2026-09-06 · B105 · 예외 없음)
- **IP 차단 시 서버 실행·네트워크 변경 등 IP 교체로 접근하지 않는다 (우회 금지 · 대기와 탐침만)**. 재개 확인은 `biotech_sec_probe.py` 로 단일 요청 (최소 2h 간격 · 권장 +2h→+6h→+24h · 200 확인 시에만 세션 재개 · 403 즉시 종료 · UA 순환 금지).

### 3-5. 백테스트 사양 v1 (실행 전 사전 커밋 · 2026-09-06 · 사후 조정 금지)

**진입·창**
- 진입: **D+1 종가 (adj_close)** · 미래 참조 배제
- 창: **D+1~D+30** (단기) 및 **D+1~D+180** (장기) 별도 산출

**benchmark·net excess**
- 주 벤치: **XBI** · 참고 병기 **IWM**
- **net = 왕복 거래비용 1.0% 차감** (1차 판정)
- **민감도 표: 0.5% / 2.0% / 5.0% 병기** (사후 조정 근거 금지)

**판정식 (§2-0 규약)**
- bootstrap 이벤트 단위 **10,000회 · seed 고정** (재현성)
- **강건성**: 종목 클러스터 재추출 (block bootstrap) 병기
- 판정: `bootstrap 95% CI 하한 > 0` AND `net excess 평균 ≥ 임계`

**버킷 (사전 확정 · 사후 변경 금지)**
- market cap: **[$50M,$300M) / [$300M,$1B) / [$1B,$5B]**
- subsector: SIC 2834 · 2836 (기타는 별도)
- 2축 교차

**mcap 산출**
- **mcap = companyfacts 발행주식수 × 원시 종가** (filing 시점 기준)
- adj_close 아닌 raw close 사용 (사후 조정 방지)

**이벤트 적격**
- **[D-30, D+180] 가격 실존** (B93) · 미충족 이벤트 표본 제외 + **제외 수 리포트 명시**

**alpha_confirmed 판정 (기계 · B100 · H3 커밋값)**
- 임계 dict (§2 H3 사후 조정 금지):
  - `h_30d`: `mean_net_excess ≥ +5.0%` AND `hit_rate ≥ 35.0%` AND `ci_iid_95_lo > 0`
  - `h_180d`: `mean_net_excess ≥ +15.0%` AND `hit_rate ≥ 35.0%` AND `ci_iid_95_lo > 0`
- §2-0 서열: **1차 mean · 2차 hit** (mean 미달 시 hit 무관 alpha 부재)
- 리포트 상태: **"Fable 검수 대기"** (사람 최종 확정 전까지 자동 세팅 무효)

**B99·B101 창 단축·진입/청산 규약 (2026-09-06 · 실데이터 투입 전 커밋)**
- **창 단축 청산 (B99)**: exit 목표일 이후 바 부재 · 마지막 바 < 목표일 → 마지막 바로 청산 · `window_shortened=True` · `actual_days` 기록. 요약에 horizon 별 shortened 카운트. **인수 프리미엄 (H3 대표 성공 결말) 이 180d 통계에서 체계적으로 탈락하지 않도록 함** (Fable P1-1 반영).
- **진입 지연 배제 (B101-1)**: `entry_date > event_date + 7d` (달력) 이면 이벤트 제외 · `excluded["entry_lag"]` 카운트.
- **exit overshoot 플래그 (B101-2)**: `exit_date > 목표일 + 15d` 이면 `overshoot=True` 플래그 (제외 아님 · 요약 카운트).
- **subsector 축 (B101-3)**: SIC 2834 (Pharmaceutical Preparations) · 2836 (Biological Products) · other 3축 버킷 병기.

---

## 4. 데이터 소스 현실성 조사 (Fable 반박 예상 지점)

| 소스 | 접근성 | 예상 리스크 |
|---|---|---|
| ClinicalTrials.gov API | 무료·공개 | Phase 3 completion date ≠ readout date · 시차 클레임 필요 |
| FDA Drug Approvals Calendar | 공식 발표 있음 · PDUFA date는 사전 공개 | 일부 accelerated review 는 사전 캘린더 없음 |
| biopharmcatalyst.com | 유료 · 무료 tier 제한 | 크롤 차단 · 자체 크롤로 대체 필요 |
| SEC EDGAR (SC 13D/Form 4) | 기존 파이프 활용 | 바이오 activist CIK 확장 필요 (기존 40 → 60+) |
| apewisdom | 기존 파이프 활용 | 바이오 서브셋 필터링 필요 |
| DART (KR 바이오 임상) | 활성 · KIND 공시 별도 | KR 바이오 임상 공시 형식 비정형 · 파서 개발 부담 |
| **가격 소스 · yfinance** | 무료 · rate limit | **v4 표본 실측 = 3/20 = 15.0% (2026-09-02 · git_sha `add7af7`)** · cohort 세부: acquired 0/15 · bankrupt 2/3 · delisted 1/2. B21 통과선 18/20 **FAIL**. 왜곡 방향: 생존 편향으로 net excess 과대 추정. 이력: 구표본 실측 2/20 (2026-09-02 초기 · PRQR 오류 포함 · B22에서 폐기 · 참고용). 스크립트 `backend/scripts/biotech_coverage_test2.py`. |
| **가격 소스 · Stooq** | 프로젝트 기존 파이프 | 상장폐지 바이오 커버율 = **0/20 = 0.0% (실측 2026-09-02 · git_sha `add7af7`)** · JS PoW 봇 차단으로 무인증 HTTP GET 불가 (2026-06-20 관측과 일치 · `backend/discovery/data_sources/yahoo.py:5-6` 코멘트). Phase A 실질 사용 불가. |
| **가격 소스 · EODHD (개인 무료)** | 무료 20 calls/day (페이지 표기) | **PASS 철회 (2026-09-04 · B77 재감사 · B80 신 기준 창 커버 0/20 · 무료 티어 1년 제한 강력 지지)** · 근거: 실 데이터 4/20 (SYRS·KZR·CARM·LIPO) 전건 first=2025-09-02(실행일-365) · 원 20/20 PASS 는 rows=1 오분류 (B79). 이력: DEMO 0/20 (2026-09-02 초기). 유료 플랜: EOD Historical Data — All World $19.99/mo · EOD+Intraday $29.99/mo · Fundamentals $59.99/mo · ALL-IN-ONE $99.99/mo. |
| **가격 소스 · FMP (Financial Modeling Prep · 개인 무료)** | 무료 250 calls/day · 500MB / 30d bandwidth (페이지·리뷰 표기) | **v4 표본 응답 = 20건 전건 HTTP 403 Forbidden (2026-09-02 · git_sha `add7af7`)** · **403 = 접근 제한 · 커버리지 자체는 미측정** (키 유효하나 delisted 종목 접근이 무료 티어에서 제한 추정). B21 통과선 18/20 **FAIL (접근 자체 실패)**. 사용량 ≤20 calls (재시도 1회 상한). 이력: 무키 커버율 0/20 (초기 · 401). 유료 플랜 가격 = 공개 페이지 접근 차단(403) · 3rd-party 요약만 존재. |

**커버율 실측 결과 (Fable B4 대응 · 2026-09-02)**: yfinance 는 액티브 티커 위주로 delisted/acquired 는 데이터에서 자동 삭제됨. Stooq 는 봇 차단으로 접근 불가. Phase A 백테스트를 이 상태로 진행하면 결과가 survivorship bias 로 오염된다. 대체 소스(CRSP/Compustat·paid) 도입 여부는 Fable·사용자 협의 후 결정. **본 게이트 트리거로 H3 착수 일시 중단 (2026-09-02).**

**B21 · 대체 소스 통과 기준 (실측 전 사전 확정 · 2026-09-02)**: 표본 20종목 중 18종목 이상(90%)에서 필요 구간 일별 가격 존재. 후보 = EODHD · FMP (Financial Modeling Prep). CRSP·Compustat·Refinitiv 는 기관용이라 제외. 무료 티어 검증만 진행 · 결제·구독 금지 · 실측치 보고 후 사용자가 결제 결정.

**B80 · 소스 통과 기준 v2 (실측 전 사전 확정 · 2026-09-04)**: 표본 20종목 각각에 대해 **응답 시계열이 `(event_date-365 ~ event_date)` 창을 실제 커버해야 커버로 인정** (응답 존재 · rows>0 · AVAILABLE 상태만으로는 커버 불인정 · EODHD 오판정의 교훈). 창 커버 조건: `first_bar ≤ event_date-365` AND `last_bar ≥ event_date`. **창 커버 ≥ 18/20 = PASS**. B21 기준(응답 존재)은 사문화 · v2 로 대체.

**B84 · 판정식 v2.1 (2026-09-04 · 재판정 실행 전 사전 커밋)**: 창 커버 = `first_bar ≤ 창시작+7일` AND `last_bar ≥ 이벤트일-30일`. **근거**: (1) 창시작이 주말/연휴이면 첫 거래일은 최대 수일 뒤 (달력 요인 · 7일 = 최장 연휴 여유) (2) 인수 종목은 거래정지 후 Form25 제출까지 지연 발생 (B74 절단 +30일과 동일 값). **결과 관찰 후 조정이나 소스별 차등 적용 금지 · 3소스 동일 적용**. v2 는 사문화 · v2.1 로 대체.

**B24 · 표본 무결성 v3 재검증 (2026-09-02 · Fable 행 단위 검수 반영)**: v2 EFTS 전문검색 첫 hit 채택 방식은 filer CIK 미대조로 오매칭 (GBT·AVEO·KDMN). v3 는 CIK 확정 후 회사 자체 제출 이력(`data.sec.gov/submissions/CIK.json`)만 조회 · filer CIK 일치 강제. 결과: CIK 21/21 · filer 일치 20/21 · verified 20/21 · KDMN 미검증(권위 기록 창 안에 없음 · 표본 제외). 날짜 정정 3건 (AVEO Δ197d · SYRS Δ119d · HGEN Δ227d). 유형 정정 2건 (CALT·CARM 각각 `ACQUIRED` → `DELISTED(사유 미확인)`). 파산 보충 1건 (LIPO · Item 1.03 확인). 최종 verified 20 · 인수 15 · 파산 3 · 폐지 2 → 파산·부실폐지 합계 5 · **목표 15/5 도달**. v3 CSV: `backend/data/biotech_coverage_samples_v3_add7af7.csv`. `coverage_test2.py` 로더 prefix v2 → v3 갱신.

**B27·B28·B29 · 표본 마감 v4 (2026-09-02)**: CALT (6-K ±60d 4건) · CARM (8-K ±60d 1건) 유형 확정 시도 · filing metadata (items · primaryDocDescription) 로 인수/자진폐지 특정 실패 → 지시대로 `DELISTED(사유 미확인)` 유지 (근거는 filing 본문 파싱 필요 · 별도 세션 이관). LIPO 제출 이력 전체 Form 25 확인: `EXISTS` 2025-10-06 accession `0001354457-25-000985` · 표본 유지. `coverage_test2.py` 에 B29 집단별 분리 커버율 추가 (cohort_acquired · cohort_failed · cohort_delisted). loader prefix v3 → v4 갱신. v4 CSV: `backend/data/biotech_coverage_samples_v4_add7af7.csv`. **키 수령 즉시 실측 실행 승인 (사후 Fable 검수)**.

---

## 5. 완료 기준 (DoD · Phase A 검증)

### 5-1. 신호 품질 DoD (필수)
- [ ] H1a·H1b·H2·H3·H4 각각 백테스트 완료 · 리포트 산출
- [ ] Universe 오염 (survivorship/look-ahead bias) 명시 · benchmark 대조
- [ ] 각 가설별 평균 net excess · bootstrap 95% CI 하한 · 히트율 산출 (§2-0 판정식 적용)
- [ ] 실제 100만원 매매 시나리오 · 소형주 슬리피지 반영 · 시총 컬럼 노출
- [ ] Fable 5 리뷰 문항(§7) 응답 · 6차 반복까지 열어둠

### 5-2. 폐기 게이트 필수
- [ ] 각 가설 리포트 결론 · `alpha_confirmed: bool` + 근거 수치
- [ ] alpha_confirmed=false 시 후속 개발 금지 · 시드 100만원 보전 리포트 산출

### 5-3. 기술 DoD
- [ ] 검증 스크립트 재현 가능 (git_sha 각인)
- [ ] pytest 커버 (데이터 파이프 · 백테스트 로직)
- [ ] 데이터 소스 rate limit·차단 대응 명시

---

## 6. Phase 로드맵

| Phase | 내용 | 기간 | 배포 |
|---|---|---|---|
| **A · 검증** (본 문서 범위) | H1a·H1b·H2·H3·H4 백테스트 + 리포트 + Fable 리뷰 통과 | 3~5주 | 없음 (로컬 산출물만) |
| **B · UI 후속** (알파 확인 가설 한정) | 알파 있는 가설만 페이지 개발 · confluence 검토 | 2~3주 | 완결 후 단일 배포 |
| C · 확장 (선택) | KR 바이오 임상 파이프 · Telegram 알림 · watchlist 통합 | TBD | 별도 승인 |

**배포 정책**: Phase A 산출물은 배포 없음 · Phase B 로컬 완결 후 단일 배포 (`feedback_deploy_only_when_complete`)

---

## 7. Fable 5 리뷰 요청 문항

### Q1 · 방법론 반박
- H1 임상 catalyst 검증에서 look-ahead bias 어떻게 배제? (PDUFA date 는 사전 공지되지만 Phase 3 readout date 는 사전 추정)
- Universe 정의에 상장폐지·인수·SPAC 합병 종목 처리 방침?

### Q2 · 학술 근거 반박
- H1 학술 참조: Kim(2019) FDA drug approval abnormal returns · Ahern & Sosyura(2015) rumor stocks. 다른 논문 반박 있는가?
- H2 테마 클러스터 확산 lead time · 학술 표본 존재 여부?

### Q3 · 표본 편향
- H1 PDUFA 표본 연 60~80건 · 5년 300~400건 · buckets 통계 유의성 확보 방안?
- H2 테마 클러스터 수동 라벨링 20~30개 · confirmation bias? (v1 지적 · v2 에서 반영 완료 · §2-0/§2 H2 참조)

### Q4 · Confluence 함정
- H1~H4 confluence 결합 시 정보 겹침 (예: activist 매집이 임상 catalyst 정보 기반이면 이중계상)?
- Wolf pack pattern (`docs/plans/activist-radar/README.md`) 재활용 시 바이오 특성 반영?

### Q5 · 폐기 게이트 자의성
- 알파 임계 (excess adjusted ≥ +2%, 히트율 ≥ 30%) 근거? (v1 지적 · v2 에서 반영 완료 · §2-0/§2 H2 참조)
- L14 임계 (top-bottom diff 10.99pp fail) 승계할 항목?

### Q6 · 우선순위
- H1~H4 중 우선 착수 순서 · 폐기 후보?
- 사용자 참조 사례(유전자편집·비만치료제)에 가장 근접한 가설?

---

## 8. 열린 질문 · 리스크

- **바이오 소형주 슬리피지**: $50M 시총 이하 종목 · 실 매수 시 스프레드 5%+ 가능 · 백테스트 conservative 처리 방안
- **KR 바이오 임상 공시 파서**: KIND(한국거래소) 공시 · 정형화 부족 · Phase A 스코프 밖 검토
- **인플루언서 편향 재발 방지**: 본 기획은 TikTok 팁 계기지만 검증 대상은 팁이 아닌 leading indicator · 최종 알파 판정도 데이터 기반 (L14 원칙)
- **비만치료제 클러스터의 특수성**: LLY/NVO 는 이미 대형주 · 후발주(펩트론·한미) 진입 시점 판별 난이도 · H2 결론에 반영 필수
- **유전자편집 클러스터의 stall**: CRSP/NTLA 는 CASGEVY 승인 후 오히려 조정 진입 · 초기 폭등과 후속 조정 구분 명시
- **KR 이식 금지 조항** (B8 · 2026-09-02 추가): 2026-08 시중 관찰(출처: TikTok @guess8282 · 2026-08-27 · **인플루언서 1인 의견이므로 사실 판정 아님**)에 따르면 KR 바이오는 호재 공시 당일 매도 패턴이 보고된다. 따라서 Phase A 의 US 검증 결과가 GO 이더라도 **KR 시장 적용은 별도 KR 백테스트 (Phase C · KIND/DART 파서 필요) 통과 전까지 금지**한다. 영상 언급 개별 종목은 watchlist·universe·문서 어디에도 편입 금지 · 시점 전망(예: 하반기 재평가)도 문서 기록 금지.
- **폐지 종목 가격 시계열 절단 규칙** (B74·B76 · 2026-09-03 추가): 폐지 종목 가격 시계열은 `form25_date + 30d` 에서 절단해 사용 (재활용 심볼 오염 차단 · OTC 지속 지분 인정). 절단으로 인해 폐지 직전 filing 의 D+180 창 일부가 짧아질 수 있으며 리포트에 **창 단축 종목 수**를 명시한다. 적격 규칙: `first_bar ≤ form25_date - 90d` (폐지 이전 커버) · 미커버는 재활용 심볼 판정으로 quarantine.
- **생존 편향 정량화** (B91 · 2026-09-04): 원장 140 · 가격 확보 87 (kept 46 + simfin_kept 41) · 미가격 53 (B60_pending 31 + unrecoverable 22). event_type 데이터 부재로 정성적 판정 어려움 · v4 표본 20개 매핑 시: 가격 확보 7건 전부 ACQUIRED · 미가격 2건 (ACQUIRED 1 · BANKRUPT 1). 표본 매핑률 낮아 편향 방향 판정 불가 · 추가 event_type 라벨링 필요 (별건).
- **생존 편향 현행화** (B103 · 2026-09-06 · 원장 v5 반영): 원장 140 · **가격 확보 92 (kept 50 + simfin_kept 42) · 미가격 48 (B60_pending 35 + unrecoverable 13)**. event_type 라벨링(B95)은 SEC 세션 대기 (2026-09-06 SEC 403 차단 · [[b104_probe_protocol]] 준수). **라벨링 후 재산출 예정** (BANKRUPT/ACQUIRED/OTHER_DELISTED 3분류 · 미가격 48건 구성 비교 → 편향 방향 확정).
- **H4 burn-in 게이트** (WP7 · 2026-09-08): apewisdom biotech 필터 스냅샷 수집 시작 · **burn-in 60일 (또는 이벤트 60건 · 6개월 중 먼저 도달)** 게이트 통과 후에만 H4 백테스트 착수. 초기 스냅샷 (2026-09-08 08:48 UTC) = 300 mentions 중 biotech hits 6건 · 향후 hits 누적 상황 관측 필수.

---

## 9. 스코프 밖 (Phase C 이관)

- Telegram 알림 (임상 D-7 리마인더 등)
- 개인 watchlist 통합
- 실시간 크론 (D-day 알림)
- KR 바이오 임상 공시 파서
- Confluence UI (다중 시그널 결합 뷰)

---

## 10. 진행 원칙 재확인

1. **UI/알림보다 알파 존재 여부 데이터 검증 먼저** (L14 승계)
2. **검증 결과가 무의미하면 그 사실이 프로젝트 최고 산출물** (시드 100만원 보전)
3. **Fable 5 리뷰어 무조건 GO 낼 때까지 반복** (조건부 GO/ExitPlanMode 승인도 통과 아님 · `feedback_iterate_until_reviewer_pass`)
4. **판정→결과 폐루프 강제** (자동매매 절대 금지 · 반자동 티켓까지만 · `docs/plans/toss-tradebot-tobe/identity.md`)
5. **부분 배포 금지** (Phase B 완결 후 단일 배포 · `feedback_deploy_only_when_complete`)

---

**다음 액션**: 사용자 승인 → Fable 5 에게 본 문서 리뷰 의뢰 → 반박 응답 반복 → GO 획득 후 Phase A 착수
