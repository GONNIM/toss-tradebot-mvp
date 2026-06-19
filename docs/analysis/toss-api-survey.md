# Toss API 가용성 조사 v2.0

**작성일**: 2026-06-17 (v1 작성) → 2026-06-17 (v2 갱신)
**상태**: **사전 신청 완료** → API 오픈 대기
**조사 방식**: WebSearch 4회 + WebFetch 4회 (OpenAPI 스펙 1.1.1 정독)
**관련 문서**:
- 선행: `docs/plans/PRD/02-strategy-decision.md` §6.2
- 후속: `docs/plans/PRD/03-PRD-v1.md` (검증 완료 후 작성)

---

## 0. 본 문서의 위치 + 진행 상태

`02-strategy-decision.md`에서 확정한 22개 결정사항 중 다수는 **Toss Open API 가용성에 의존**.
본 문서는 PRD 작성 직전 외부 의존성 조사 결과.

### 진행 상태
- ✅ **WebSearch·WebFetch 1차 조사** 완료 (v1)
- ✅ **OpenAPI 3.0 스펙 정독** 완료 (v2 — 본 문서)
- ✅ **사용자 사전 신청 완료** (2026-06-17)
- ⏳ **API 오픈 대기 중** ← 현재
- ⏳ 콘솔 검증 6항목 (API 오픈 후 진행)
- ⏳ 02 문서 영향 항목 갱신
- ⏳ 03-PRD-v1.md 작성

---

## 1. 확정 사실 (OpenAPI 3.0 스펙 1.1.1 정독 결과)

### 1.1 API 기본 정보

| 항목 | 값 | 출처 |
|---|---|---|
| Base URL | `https://openapi.tossinvest.com` | OpenAPI Spec |
| 프로토콜 | **REST API only** | OpenAPI Spec |
| WebSocket | **추후 지원 예정** (현재 미지원) | Market Data 설명 |
| 인증 | **OAuth 2.0 Client Credentials Grant** | securitySchemes |
| Token endpoint | `POST /oauth2/token` | OpenAPI Spec |
| Token 유효 기간 | **86,400초 (24시간)** | OAuth response |
| Refresh token | **없음** (24시간마다 재발급) | OAuth Spec |
| 호출 헤더 | `Authorization: Bearer {token}` + `X-Tossinvest-Account` | OpenAPI Spec |
| API 버전 | **1.1.1** | info.version |
| OpenAPI JSON | `openapi.tossinvest.com/openapi-docs/latest/openapi.json` | LLMs.txt |

### 1.2 전체 엔드포인트 (12개 그룹)

| 카테고리 | 엔드포인트 | 용도 |
|---|---|---|
| Auth | `POST /oauth2/token` | 토큰 발급 |
| Market Data | `GET /api/v1/orderbook` | 호가 |
| | `GET /api/v1/prices?symbols=` | 현재가 (최대 200건 다건) |
| | `GET /api/v1/trades` | 최근 체결 |
| | `GET /api/v1/price-limits` | 상/하한가 (미국 null) |
| | `GET /api/v1/candles` | **1분봉·일봉** (`1m`, `1d`) |
| Stock Info | `GET /api/v1/stocks` | 종목 정보 (200건 다건) |
| | `GET /api/v1/stocks/{symbol}/warnings` | 매수 유의 |
| Market Info | `GET /api/v1/exchange-rate` | **KRW↔USD 환율 1분 갱신** |
| | `GET /api/v1/market-calendar/KR` | 국내 장 운영 |
| | `GET /api/v1/market-calendar/US` | 미국 장 운영 |
| Account | `GET /api/v1/accounts` | 계좌 목록 (종합매매만) |
| Asset | `GET /api/v1/holdings` | **보유 주식 (KRW/USD 분리)** |
| Order | `POST /api/v1/orders` | 주문 생성 |
| Order History | `GET /api/v1/orders` | 주문 조회 (OPEN/CLOSED) |

### 1.3 종목 코드 체계

| 시장 | 형식 | 예 |
|---|---|---|
| KRX (국내) | 6자리 숫자 | `005930` (삼성전자), `069500` (KODEX 200) |
| **NASDAQ** | **영문 대문자** | `AAPL`, `NVDA`, `SPCX`, `IONQ`, `CRWD` |

→ 우리 universe(빅7·섹터1위·SPCX·양자 5종·보안 8종) 모두 호출 가능 형식.

### 1.4 주문 ⭐ — 핵심 발견

#### 시장가·지정가 (KR·US 모두 ✅)

#### 소수점 매수 — **US만 지원** ⭐
```json
POST /api/v1/orders
{
  "symbol": "SPCX",
  "orderAmount": 100.50,   ← 달러 단위 금액 주문
  "orderType": "MARKET"
}
```
- 파라미터: `orderAmount` (달러)
- **정규장 시간에만** (KST 22:30~05:00)
- 소수점 주식수 자동 환산
- SPCX($160대) 매수 시 매우 유용
- 국내 주식은 지원 X

#### 종가 주문 (US만): `CLS` 옵션 가능

#### 주문 라이프사이클
- OPEN: `PENDING`, `PARTIAL_FILLED`, `PENDING_CANCEL`, `PENDING_REPLACE`
- CLOSED: `FILLED`, `CANCELED`, `REJECTED`, `REPLACED`, `CANCEL_REJECTED`

### 1.5 잔고 (홀딩스) — 우리 룰에 적합

```
GET /api/v1/holdings
필수 헤더: X-Tossinvest-Account
응답:
- totalPurchaseAmount: { krw, usd }    ← KRW/USD 분리
- marketValue: { amount, amountAfterCost }
- profitLoss: { 금액, 비율, 수수료 }    ← 평단 +20% 익절 직접 산출 가능
- dailyProfitLoss
- items: [...]                         ← 종목별 상세
```

→ 결정 8 (평단 +20% 익절) 구현 즉시 가능.

### 1.6 Rate Limit (그룹별 정의)

| 그룹 | 설명 | 한도 (Overview 출처) |
|---|---|---|
| AUTH | 토큰 발급 | 5 req/sec |
| MARKET_DATA | 호가·현재가·체결·상하한 | 10 req/sec |
| MARKET_DATA_CHART | 캔들 (별도 관리) | 별도 (미명시) |
| STOCK | 종목 정보·경고 | 미명시 |
| MARKET_INFO | 환율·장 정보 | 미명시 |
| ACCOUNT | 계좌 조회 | 미명시 |
| ASSET | 보유 주식 | 미명시 |
| ORDER | 주문 생성 | 6 req/sec (09:00~09:10 KST 3 req/sec) |
| ORDER_HISTORY | 주문 조회 | 미명시 |

→ 응답 헤더로 남은 한도 표시. 운영 상황 따라 변동.

### 1.7 시장 운영 시간 (KST 기준)

| 시장 | 데이마켓 | 정규장 | 애프터 |
|---|---|---|---|
| KR (KRX+NXT) | 프리 08:00-09:00 | **09:00-15:30** | 15:30-20:00 |
| **US** | 09:00-16:50 | **22:30-05:00 (다음날)** | — |

→ 미국 정규장은 한국 시간 **밤 10:30~새벽 5시**. 자동매매 운영 시간대.

### 1.8 에러 응답 구조

```json
// 성공
{ "result": { ... } }

// 에러 (4xx/5xx)
{
  "error": {
    "requestId": "01HXYZABCDEFG123456789",
    "code": "invalid-request",
    "message": "...",
    "data": { "field": "...", "constraint": {...} }
  }
}

// OAuth 에러
{
  "error": "invalid_client",
  "error_description": "Client authentication failed."
}
```

#### 주요 에러 코드 (정독 확인)
- `invalid-request` (400)
- `invalid_client` (401 — OAuth)
- `stock-not-found` (404)
- `account-header-required` (400 — `X-Tossinvest-Account` 누락)
- `amount-order-outside-regular-hours` (422 — `orderAmount`를 정규장 외에 사용)

### 1.9 환율 API

```
GET /api/v1/exchange-rate
- KRW↔USD
- 1분 갱신
- 참고용 (실제 매매 환전과 별개)
```

---

## 2. 정독으로 발견한 5개 위험 사항

### 위험 1: **52주 고가/저가 API 미제공** 🚨

- 결정 12 (Satellite 매수 트리거 = 52주 고가 대비 -10/-20/-30%)의 직접 데이터 없음
- 현재가 API에 lastPrice만, high/low 미포함
- **해결책**: 일봉 252개로 직접 계산 + 캐싱
  - `GET /api/v1/candles?symbol=AAPL&interval=1d&count=200`
  - 매일 1회 갱신
  - 종목별 DB 캐싱 (SQLite 테이블 `daily_candles`)
- **운영 부담**: 종목 15~17개 + Discovery 100~수백개 = 매일 API 호출량 증가

### 위험 2: **WebSocket 미지원** 🚨

- "추후 지원 예정" 명시
- Market Data 10 req/sec 한도 내 polling 필수
- 계산:
  - 5종목 동시 모니터링
  - 종목당 분당 60회 = 5×60/60 = **5 req/sec** (한도 50%)
- **운영 가능**. 단 upbit 대비 응답 지연 ~1분

### 위험 3: **Paper Trading 별도 서버 없음** 🚨

- 단일 프로덕션 서버만 (`openapi.tossinvest.com`)
- 모의투자 모드 ❌
- **완화 방안**:
  1. 첫 운영 시 매우 소액 (예: 10만~50만원)으로 검증
  2. 1주~1개월 운영 후 점진적 시드 확대
  3. 1000만 한 번에 노출 절대 X

### 위험 4: **환전 API 없음** 🚨

- 환율 조회만 가능 (참고용 1분 갱신)
- KRW 잔고로 USD 주식 매수 시 자동 환전 여부 **API 측면 불명**
- 토스에는 "통합증거금" 같은 기능이 있을 수 있음 (콘솔 확인 필요)
- **시나리오 1**: 통합증거금 운영 → KRW 잔고로 USD 매수 가능 (자동 환전)
- **시나리오 2**: 사전 환전 필요 → 운영 복잡도 ↑, 환율 변동 위험 분리 필요

### 위험 5: **신규 IPO 별도 플래그 없음**

- 종목 `status` 필드: `ACTIVE` / `INACTIVE` 만 정의
- SPCX 같은 신규상장 별도 표시 X
- API 측면에서 SPCX가 `ACTIVE`이면 거래 가능, `INACTIVE`이면 불가
- 콘솔에서 SPCX 검색·매수 화면 진입 가능 확인 필요

---

## 3. 사용자 콘솔 검증 체크리스트 — v2 (10 → 6 축소)

**v1 항목 중 OpenAPI 정독으로 확정된 4건 제거**:
- ❌ #4 소수점 매수 (확정: ✅ US만, `orderAmount` 정규장만)
- ❌ #5 Paper Trading (확정: ❌ 없음)
- ❌ #9 52주 고가 (확정: ❌ 직접 API 없음, 일봉 계산 필요)
- ❌ #11 WebSocket (확정: ❌ 추후 지원)

**축소된 6항목 (API 오픈 후 진행)**:

```
□ 1. ✅ developers.tossinvest.com 가입·API 신청 ← 완료 (2026-06-17)
     ⏳ API 오픈 대기 (승인 소요 시간 사용자 후속 보고)

□ 2. 토스 앱 → 해외주식 검색·매수 화면 진입 가능 확인
     - SPCX (Core)
     - IONQ·RGTI·QBTS·ARQQ (양자 와이트리스트)
     - CRWD·PANW·ZS·FTNT·S·NET·OKTA·CYBR (보안 와이트리스트)
     - 빅7 + 섹터1위

□ 3. 통합증거금 여부 (위험 4 핵심)
     - KRW 잔고로 USD 주식 매수 시 자동 환전?
     - 또는 사전 USD 환전 필요?

□ 4. API 사용료 (무료/유료)

□ 5. 자동매매 약관 (home.tossinvest.com/ko/terms/v2?id=752 본문)
     - "자동매매" / "시스템 트레이딩" / "프로그램 매매" / "API" 키워드 검색
     - 명시 허용 또는 금지 조항

□ 6. 실시간 vs 15분 지연 시세 정책
     - API 응답에 시세 지연 표시?
     - 약관에 시세 지연 명시?
```

→ API 오픈 후 사용자가 부분적으로 보고. 결과 받는 즉시 본 문서 v3로 갱신.

---

## 4. 외부 데이터 의존성 재평가 (Toss API 확정 후)

### 4.1 yfinance — **완전 대체 가능** ✅
- Toss API의 `/api/v1/candles` 일봉 + `/api/v1/prices` 현재가로 모든 가격 데이터 대체
- yfinance 의존성 0 제안
- **02 문서 결정 15 갱신 필요**: "yfinance + FINRA + Reddit PRAW" → "**Toss API 시세** + FINRA + Reddit PRAW"

### 4.2 Reddit PRAW (Discovery sentiment)
- 무료 60 calls/min — Discovery 일 1회 스캔 충분
- 신청: reddit.com/prefs/apps → script 앱 등록 → `client_id` + `client_secret`
- 평가: ✅ **그대로 사용**

### 4.3 FINRA 공매도 데이터
- 무료 공개. https://www.finra.org/finra-data/browse-catalog
- Discovery short interest 인자 추가 시 활용
- 평가: ✅ **옵션 사용**

### 4.4 어닝·애널리스트 데이터 (Discovery 결정 14)

OpenAPI 스펙에 어닝·애널리스트 데이터 미포함. 별도 소스 필요:
- **무료 옵션**: Yahoo Finance(불안정) / Stooq / SEC EDGAR (공시 직접)
- **유료 옵션**: Finnhub Free Tier (60 calls/min) / Polygon Starter
- **사용자 결정 필요** (별도 라운드)

---

## 5. 우리 전략에 미치는 영향 — 02 갱신 항목 검토

### 5.1 즉시 갱신 가능 (정독 확정)

| 02 섹션 | 현 상태 | 갱신안 |
|---|---|---|
| §3 결정 15 (데이터 소스) | "100% 무료 — yfinance + FINRA + Reddit PRAW" | "**Toss API 시세 (확정)** + FINRA + Reddit PRAW + 어닝/애널리스트 소스 결정 보류" |
| §3 결정 18 (뷰어) | "Streamlit + Telegram" | 변경 없음. polling 방식 명시 |
| 신규 결정 23 (구현 정책) | — | **52주 고가 일봉 계산** (252거래일 캐싱) |
| 신규 결정 24 (구현 정책) | — | **Polling 60초 간격** (WebSocket 부재 보완) |
| 신규 결정 25 (운영 정책) | — | **소액 검증 모드** (Paper Trading 부재 보완, 초기 10~50만원) |

### 5.2 콘솔 검증 결과 후 갱신

| 02 섹션 | 결정 필요 조건 |
|---|---|
| §3 결정 13 (SPCX) | 콘솔 #2 SPCX 거래 가능 확인 후 진행 |
| §3 결정 21·22 (양자·보안 와이트리스트) | 콘솔 #2 13종 거래 가능 확인 |
| §6.2 영구 모니터링 | 자동매매 약관 검증 결과로 명문화 |
| 신규 결정 26 (환전 정책) | 콘솔 #3 통합증거금 확인 후 |

---

## 6. 다음 단계

### 6.1 즉시 진행 가능 (API 오픈 무관)

1. **02 문서 즉시 갱신** (§5.1 표 항목) — 사용자 승인 후
2. PRD 골격 (`03-PRD-v1.md`) **초안 작성 가능 영역만 우선** (모듈 구조, 기술 스택, DB 스키마 등)
3. 외부 데이터 어닝/애널리스트 소스 결정 (§4.4)

### 6.2 API 오픈 후 진행

1. 콘솔 검증 6항목 (§3) 진행
2. 본 문서 v3로 갱신 (검증된 사실 반영)
3. 02 문서 §5.2 항목 갱신
4. PRD v1 최종 완성
5. 설계 단계 (`docs/architecture/`)

---

## 7. Sources

### 공식 문서 (정독 완료)
- [토스증권 Open API 가이드 (메인)](https://developers.tossinvest.com/docs) — SPA 로딩
- [LLMs.txt 메타 문서](https://developers.tossinvest.com/llms.txt) — fetch 성공
- [OpenAPI Overview Markdown](https://openapi.tossinvest.com/openapi-docs/overview.md) — **fetch 성공**
- [**OpenAPI 3.0 JSON Spec v1.1.1**](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json) — **정독 완료** ⭐
- [Open API 서비스 이용 약관](https://home.tossinvest.com/ko/terms/v2?id=752) — fetch 실패, 사용자 검증 필요

### 보도·블로그 (보조)
- [토스증권 OpenAPI 오픈 — Braindetox](https://braindetox.kr/posts/toss_securities_openapi_2026.html)
- [토스증권 Open API 완벽 가이드 2026 — Pulse Know](https://www.pulse-know.com/toss-invest-open-api-guide-2026/)
- [SPCX 토스 사는법 — Naver Economic News](https://naver.economic-news24.com/2026/06/13/spcx-toss-buy-spacex-ipo-date/)

### 외부 데이터 평가
- [Why yfinance Keeps Getting Blocked — Trading Dude](https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01)
- [Reddit API Pricing 2026 — Octolens](https://octolens.com/blog/reddit-api-pricing)
- [FINRA Data Catalog](https://www.finra.org/finra-data/browse-catalog)

---

## 8. 변경 이력

| 날짜 | 변경 | 비고 |
|---|---|---|
| 2026-06-17 | **v1.0 초안** — WebSearch 4회 + WebFetch 3회 결과 종합 | 사용자 콘솔 검증 10항목 대기 |
| 2026-06-17 | **v2.0 갱신** — OpenAPI 3.0 스펙 1.1.1 정독 결과 반영 / 콘솔 검증 10→6 축소 / 위험 5건 정리 / 02 갱신 항목 구체화 / **사용자 사전 신청 완료** 상태 기록 | API 오픈 대기 |
