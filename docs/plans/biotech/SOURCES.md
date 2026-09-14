# SOURCES · Biotech Catalyst Radar 데이터 소스 대장

**작성일**: 2026-09-02 (B46)
**갱신**: 소스 상태 변경 시마다

| 소스 | 상태 | 발급/재사용 근거 |
|---|---|---|
| **DART** (opendart.fss.or.kr) | **기존 보유 · 발급 불필요** | `backend/.env:DART_API_KEY` 존재 · 2026-08~ principles 배치 상시 사용 · 20,000 calls/day (키 단위 합산) |
| **SEC EDGAR** (EFTS · submissions API · Archives) | 무인증 · 무료 | **UA 규정 준수 필수**: `TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)` (신원 선언 형식 · Mozilla 위장 금지) + `From: sung2011103@naver.com`. 요청 간격 **0.5s (2 req/s)** 보수적 상향 (B59 · 2026-09-03 · SEC 규정 10 req/s 이내). **403 재발 시 즉시 중단** · UA 순환 금지 · 원인 보고 후 수정 재개. |
| **KRX candle** (FinanceDataReader + pykrx) | **기존 보유 · 무인증** | `backend/discovery/data_sources/krx_price/loader.py` · powderkeg/collectors/krx_* 파이프 존재 |
| **yfinance** | 무인증 · rate limit 관용적 | US 표본 커버율 3/20 = 15% (실측 2026-09-02 · B15-2) · 폐지 종목 대부분 미보유 |
| **EODHD** (개인 무료) | 발급 완료 2026-09-02 · **PASS 철회 (2026-09-04 · B77 재감사 · B78 탐침 공식 확인)** | 20 calls/day · 원 표기 20/20 PASS 는 rows=1 오분류 · **신 기준 창 커버 0/20** · [B78 탐침 2026-09-04] XLRN(2021-11)·CNCE(2023-03)·CALT(2024-09) 명시적 from/to 로 재호출 · 3/3 rows=1 (date 필드 없음 · 에러 페이로드) · **오래된 폐지 종목은 요청 파라미터 무관 데이터 부재** + **활성/최근 폐지는 요청일-365 부터만 반환 (B77)** · 두 특성 모두 무료 티어 부적합 · 유료 플랜 $19.99/mo 부터 |
| **FMP** (Financial Modeling Prep · 개인 무료) | 발급 완료 2026-09-02 | 250 calls/day · US 표본 응답 = 전건 HTTP 403 (**403 = 접근 제한 · 커버리지 자체는 미측정**) · 폐지 접근 무료 티어 제한 추정 · 유료 가격 페이지 403 |
| **Stooq** | 봇 차단 확인 | JS PoW challenge (2026-06-20 관측 · 재확인 2026-09-02) · 접근 불가 |
| **공공데이터포털 KRX** | 미조사 | KR 폐지 커버 부족분 대응 후보 (Phase C 진입 조건) |
| **네이버 금융 API** (`api.stock.naver.com`) | 공개 · US 폐지 미보유 | v4 20 표본 실측 2026-09-02 = 0/20 (활성 AAPL 200 OK · 폐지 전건 409 `Not Exist Master`) · B21 판정선 FAIL |
| **다음 금융 API** (`finance.daum.net`) | 공개 접근 차단 | v4 20 표본 실측 2026-09-02 = 0/20 (전건 403 Forbidden · 인증/봇 차단 추정 · 우회 금지) · B21 판정선 FAIL |
| **토스증권 WTS-cert API** (`wts-cert-api.tossinvest.com`) | 공개 · US 폐지 미보유 | v4 20 표본 실측 2026-09-02 = 0/20 (전건 200 OK · `{"result":null}` · 폐지 심볼 데이터 없음) · B21 판정선 FAIL |
| **ClinicalTrials.gov API** | 무인증 · 무료 | Phase A H1a·H1b 예정 · 미착수 |
| **FDA Drug Approvals Calendar** | 무인증 · 무료 | Phase A H1a 예정 · 미착수 |
| **Tiingo** (개인 무료) | 발급 완료 2026-09-04 · **B85 재판정 v2.1: PASS** | 무료 1,000 req/day · 500 unique symbols/월 · **v2.1 창 커버 18/20 = 90% PASS** (v2 11/20 → v2.1 +7 · 달력/폐지 지연 조정 반영) · AVAILABLE 18 · NOT_FOUND 2 (AKUS/AVEO 등) · 유료 Power $30/mo |
| **Alpha Vantage** (개인 무료) | 발급 완료 2026-09-04 · **미측정 (B86 재분류)** | 무료 25 req/day · v4 20 표본 전건 `RATE_LIMIT_OR_INFO` Note 페이로드 · **응답 본문 미보관 → Note/Information 구분 불가 → FAIL 판정 불가** · 재측정 후순위 (합집합 100% 로 충분) · test3 스크립트에 비정상 응답 본문 200자 보관 컬럼 추가 예정 (재측정 대비) |
| **SimFin v3** (개인 무료) | 발급 완료 2026-09-04 · Auth `Authorization: api-key <key>` header (B82 문서 확인) · **B85 재판정 v2.1: FAIL** | 무료 5,000 US 종목 · 5년 history · 500 credits/월 · endpoint `/api/v3/companies/prices/compact` · **v2.1 창 커버 14/20 = 70% FAIL** (v2 9/20 → v2.1 +5) · AVAILABLE 14 · EMPTY 6 · Tiingo 폴백 후보 (합집합에서 4건 SimFin only 기여) · 유료 Start $15/mo |

**주의**: 개인 무료 키(EODHD·FMP)는 2026-09-02 stdout 노출 사고 발생 · 재발급 없이 사용 중 (사용자 위험 수용). 재발급 결정 시 `backend/.env` 교체 후 `setup_secure_logging` 경로 통해 마스킹 보장.

**B80 통과 기준 v2 (2026-09-04)**: 표본 20종목 각각 응답 시계열이 `(event_date-365 ~ event_date)` 창을 실제 커버해야 커버로 인정. `first_bar ≤ event_date-365` AND `last_bar ≥ event_date`. **창 커버 ≥ 18/20 = PASS**. 응답 존재/rows>0/AVAILABLE 만으로는 커버 불인정 (EODHD 오판정의 교훈).

**B84 판정식 v2.1 (2026-09-04 · 재판정 실행 전 사전 커밋 · v2 대체)**: `first_bar ≤ 창시작+7일` AND `last_bar ≥ 이벤트일-30일`. 근거: (1) 창시작 주말/연휴 시 첫 거래일 최대 수일 뒤 (7일 = 최장 연휴 여유) (2) 인수 종목 거래정지→Form25 지연 (B74 절단 +30일과 동일). **3소스 동일 · 관찰 후 조정 금지**.

---

## H8 소문 지수 채널 실측 (B125 · 2026-09-06 · 각 채널 1건 최소 호출)

| 채널 | 접근성 | 이력 깊이 | 시각 필드 | 인증 | 실측 결과 (호출 1건) |
|---|---|---|---|---|---|
| **CT.gov API v2** | 무료 · 무인증 | 5년+ (studyFirstPostDate 부터 · NCT04760288 확인) | `lastUpdatePostDateStruct.date` · `studyFirstPostDateStruct.date` · `startDateStruct` · `primaryCompletionDateStruct` · `completionDateStruct` | 없음 | GET `/api/v2/studies/{nct}` **200** · 5개 날짜 필드 · **버전 diff 별도 endpoint 부재** (`/history` 404) · HTML 페이지 `/study/{nct}/history` 200 (스크레이핑 필요) |
| **AACT 스냅샷** (WP13 · 2026-09-08 실측) | 무료 · 무인증 · **2.5 GB/일** | 2017년~ 현재 · 매일 · Duke CTTI | zip 안 studies.study_first_posted_date · last_update_posted_date · study_verified_date (point-in-time 재구성 필드) | 없음 | GET `https://aact.ctti-clinicaltrials.org/static/exported_files/daily/YYYY-MM-DD?source=web` **200** · `application/zip` · PK magic 확인 · 예: 2026-09-08 = 2.34 GB · 파일 `YYYYMMDD_export_ctgov.zip` · pipe-delimited flatfiles + PostgreSQL pgdump 둘 다 선택 가능 · **H8 채널 1 사용 가능 확정** · 실 다운로드는 별건 (용량 크므로 점진적) |
| **bioRxiv/medRxiv** | 무료 · 무인증 | 2013년~ (DOI 기반 조회) | `date` (일 단위) | 없음 | GET `api.biorxiv.org/details/biorxiv/{doi}/na/json` **200** · fields (title·authors·doi·**date**·version·type) · 30/page pagination · rate limit 미명시 |
| **PubMed E-utilities** | 무료 · 이메일 권장 (tool·email param) | 1966년~ (전 논문) | `pdat` (publication date · YYYY/MM/DD) | 무인증 3 req/s · API key 시 10 req/s | GET `esearch.fcgi?db=pubmed&term=...&mindate=YYYY/MM/DD&maxdate=YYYY/MM/DD&datetype=pdat` **200** · `pembrolizumab AND biotech[Title/Abstract]` 2024-01 = count 0 (표본 검색어 협소 · endpoint 동작 확인) |
| **openFDA drug API** | 무료 · API key 선택 | 1939년~ (drugsfda 29,315건) | `submissions.submission_status_date` · `products` array | 무인증 40/min·1000/day · key 240/min·120k/day | GET `api.fda.gov/drug/drugsfda.json` **200** · fields (submissions·application_number·sponsor_name·products) · date range 필터 syntax `[YYYYMMDD+TO+YYYYMMDD]` 재확인 필요 (기본 syntax 500) |
| **FDA AdCom 캘린더** | 무료 · **abuse detection 차단 관측** | 1990s~2017 (아카이브 별도) | 회의일자 (HTML 렌더링) | 없음 | GET `fda.gov/advisory-committees/advisory-committee-calendar` → **404 abuse-detection-apology** (봇 감지 · UA 문제 가능성 · 재실측 필요) · 다운로드 CSV/ICS/RSS 미제공 |
| **EMA CHMP 하이라이트** | **URL 확인 실패 (404)** | 미확인 | 미확인 | 미확인 | 후보 URL `ema.europa.eu/en/committees/chmp/chmp-meetings-highlights` **404** · 정식 경로 재조사 필요 |
| **DART OpenAPI (KR)** | 무료 · **crtfc_key 등록 필수** | 2000년대 초~ (전자공시 전체) | `rcept_dt` (접수일 YYYYMMDD) | crtfc_key 필수 (기존 보유 · 표 상단 참조) | GET `opendart.fss.or.kr/api/list.json` (마스킹 키) **200** · `status="010" · "등록되지 않은 인증키입니다."` (endpoint 정상 · 인증 게이트 확인) · 조회공시 filter = `pblntf_ty` code 필요 (재조사) |
| **KIND 조회공시 (KR)** | 공개 웹 · **JS 렌더링 · 봇 감지** | 상장기업 전체 (2000년대~) | 공시일 (HTML) | 없음 | GET `kind.krx.co.kr/disclosure/inquiryDsclList.do` · GET **404** (경로 변경) · **정확한 URL 및 ajax POST 스펙 재조사 필요** · 조회공시 표본 10건은 대안 접근 후 재보고 |

**요약 (B125 판정)**:
- **직접 실측 통과 (즉시 사용 가능)**: 3채널 = CT.gov · bioRxiv · PubMed · openFDA (openFDA date filter syntax 만 재확인)
- **인증·재조사 필요**: 3채널 = DART (기존 키 사용) · FDA AdCom (봇 감지 우회 필요 · UA 순환 금지 · 정정: HTML 스크레이핑 대안 조사) · EMA CHMP (정식 URL 재조사)
- **접근 실패 (조사 필요)**: 1채널 = KIND (조회공시 검색 endpoint 확정 실패 · 표본 10건 미확보)
- **H8 채널 ≥2 합류 조건 (README §0-★)**: 즉시 사용 가능 4채널 만으로도 충족 가능 (인증·조사 필요 채널은 후속 편입)
- **조회공시 표본 10건**: **미확보** (KIND endpoint 확정 실패) · DART 조회공시 code 확인 후 재실측 예정

---

## B127 · v2 채널 교체 (2026-09-06 · 봇 감지 대안 공식 소스)

| 교체 사유 | v1 채널 | v2 대체 | 실측 |
|---|---|---|---|
| CT.gov API 는 point-in-time 재구성 불가 (현재 상태만) | ClinicalTrials.gov API v2 | **AACT 스냅샷** (Aggregate Analysis of ClinicalTrials.gov · Duke CTTI · 매월 static) | 후속 실측 예정 · CT.gov API 는 현재 상태 조회용만 유지 |
| FDA AdCom 캘린더 페이지 봇 감지 차단 (404 abuse-detection) | fda.gov/advisory-committees/advisory-committee-calendar | **연방관보 (Federal Register API)** `federalregister.gov/api/v1/documents.json` · 공고일 = 사전 공지 시각 | B130 실측 완료 (아래) |

## B129 · DART 조회공시 실측 (2026-09-06 · 실키)

- **인증 확인**: `opendart.fss.or.kr/api/list.json` HTTP 200 · `status=000` · 정상 응답 확인 (기존 DART_API_KEY · SET len=40 · 원문 미출력)
- **검색**: `pblntf_ty=I` (거래소공시) · 2025-01-01 ~ 2026-09-05 · 3개월 창 7분할 · pagination
- **호출 수**: **203회** · 조회공시 raw **135건** · 바이오 근사 매치 (제약/바이오/메디/테라/젠/셀트/라이프/이뮨/펩트/온코/파마) **9건**
- **표본 저장 10건**: `backend/data/h8_kr_inquiry_sample_add7af7.csv` · 필드 (rcept_dt·corp_code·corp_name·report_nm·rcept_no·flr_nm)
- **요구일 파싱 성공률 (근사)**: **6/10 = 60%** (report_nm 안 날짜 매치 또는 "답변" 포함 기준)
- **표본 예시**:
  - 20250326 · 올리패스 · 조회공시요구(현저한시황변동)에대한답변(미확정)
  - 20250331 · 티에스넥스젠 · 조회공시요구(풍문또는보도)(감사의견 비적정설)
  - 20250630 · 한미사이언스 · 조회공시요구(풍문또는보도)에대한답변(미확정)
  - 20250624 · 동성제약 · 조회공시요구(풍문또는보도)
  - 20250624 · 동성제약 · 매매거래정지및정지해제(풍문등조회공시)
- **판정**: **H8 채널 7 (DART 조회공시)** = **사용 가능** (요구·답변 쌍 모두 확인) · 요구일 정확 파싱은 답변 본문 XML 파싱 필요 (별건 · 사후 개선)

## B130 · Federal Register API 실측 (2026-09-06 · H1a·H8 채널 5 후보 · 무인증)

| 필드 | 값 |
|---|---|
| Base URL | `https://www.federalregister.gov/api/v1/documents.json` |
| 검색 파라미터 | `conditions[term]=Advisory Committee` · `conditions[agencies][]=food-and-drug-administration` |
| 인증 | 없음 (무료 · 공개) |
| 이력 깊이 | 1994년~ (Federal Register 창간 기준 · 실측 2021~2026 = 457건) |
| 시각 필드 | `publication_date` (YYYY-MM-DD) |
| 응답 필드 | `title` · `publication_date` · `type` · `abstract` · `agencies` · `html_url` · `document_number` (10/10 = **100% 충족**) |
| 회의일 abstract 언급 | 4/10 (연도 매치 기반 근사) |

- **실측 총 건수 (2021-01-01 ~ 2026-09-05 · FDA · "Advisory Committee")**: **457건**
- **표본 10건 필드 충족률**: **100%** (title · publication_date · type · abstract · agencies · html_url · document_number 전건)
- **표본 상위 3건**:
  - 2026-08-21 · Advisory Committee; Oncologic Drugs Advisory Committee; Renewal
  - 2026-08-20 · Advisory Committee; Cardiovascular and Renal Drugs Advisory Committee; ...
  - 2026-07-28 · Pediatric Advisory Committee (PAC); Notice of Meeting; Establishment of ...
- **판정**: **H8 채널 5 (연방관보)** = **채택** (FDA 캘린더 스크레이핑 폐기) · H1a AdCom 이벤트 원천 1순위 · abstract 회의일 파싱 정규식 후속 개발 필요

---

## 커뮤니티 채널 실측 (WP48-1 · 2026-09-13)

| 채널 | 접근성 | 실측 결과 (2026-09-13) | 순찰기 편입 |
|---|---|---|---|
| **Reddit /new.json** (r/biotechplays · pennystocks · wallstreetbets · stocks) | **403 봇 차단** (HTML body 반환 · UA 관계없음) | 4/4 subreddits = 403 · 공식 OAuth 스크립트 앱 필요 (100 QPM) | 사용자 OAuth 키 수령 전까지 apewisdom fallback |
| **apewisdom** (레딧 종합 aggregator) | 무인증 · 무료 · 30분 폴링 | 200 · top ~300 · biotech 매치 6종 (WP48-0) | ✅ WP48-0/-2 편입 |
| **StockTwits API** (`api.stocktwits.com/api/2/streams/symbol/{TICKER}.json`) | **무인증 · 200 OK** · 각 심볼 최근 30 messages | 5/5 티커 = 200 · 각 30 msgs (SLS·AMGN·RARE·MRNA·EXEL) | ✅ WP48-2 편입 |
| **InvestorHub AdvFN boards** (`investorshub.advfn.com/boards/board.aspx?board_id=27` 등) | **403 접근 차단** · JS render + 봇 감지 · 우회 금지 | board_27 = 403 · 스크레이핑 불가 | 제외 |

**결론 (WP48-1)**:
- 즉시 사용 가능: apewisdom · StockTwits (2 채널)
- 대기: Reddit (사용자 OAuth 앱 등록 필요)
- 제외: InvestorHub (봇 차단 · 우회 금지)


## 커뮤니티 채널 재실측 (WP48-1 정정 v2 · 2026-09-13)

**Reddit API 정책 (사용자 확인)**: 셀프서비스 API 종료 (2025-11 책임있는 개발자 정책 · 2026-06-05 갱신 · 사전 승인 필수 · 2~4주 · 거절 다수) · 공개 /new.json 은 2026-05-30 부로 403. **레딧 공식 API 는 설계 전제에서 제외** · 제3자 스크래핑 서비스 사용 금지 (우회) · 승인 요청은 사용자 선택 사항.

| 채널 | 접근성 | 실측 결과 (2026-09-13 재실측) | v2 편입 |
|---|---|---|---|
| **Reddit /new.json** | **403** (2026-05-30 이후 봇 차단) | 4/4 subreddits = 403 · UA 관계없음 | **제외** (API 승인 요청은 사용자 선택) |
| **Reddit RSS `/r/<sub>/new/.rss`** | ✅ **200 OK** (application/atom+xml · 48KB) | r/biotechplays/new/.rss · 최근 25 posts | ✅ **편입** (하루 1회 · 선언 UA · 간격 준수) |
| **StockTwits API** | ✅ 무인증 200 · 심볼당 30 messages | 5/5 티커 통과 | ✅ 편입 (후보당 1회) |
| **apewisdom** | ✅ 무인증 200 · top ~300 | 기존 사용 | ✅ 편입 (후보 존재 여부 확인) |
| **InvestorHub AdvFN boards** | **403** (봇 차단) | board_27 = 403 · stock-price 페이지 = 403 · 우회 금지 | **제외** |

**v2 편입 채널**: apewisdom · StockTwits · **Reddit RSS** (3 채널) · 후보 종목만 하루 1회 확인.
