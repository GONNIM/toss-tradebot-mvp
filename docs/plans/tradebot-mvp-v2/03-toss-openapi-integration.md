# 🔌 토스증권 Open API — 연동 실측 노트 (v1.2.2)

**작성일**: 2026-07-10 (Phase 0 · KIS→Toss 전격 전환 반영)
**상태**: 🟢 **스펙 확정 · Phase 2 착수 준비 완료**
**출처**: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json (source of truth · 2026-07-10 원문 정독)
**공식 가이드**: https://developers.tossinvest.com/docs
**메모리**: `reference_toss_open_api` (스펙 요약)

---

## 0. Phase 0 완료 상태

| 항목 | 상태 | 비고 |
|---|---|---|
| 토스증권 WTS 로그인 | 🟢 완료 (사용자) | — |
| Open API 클라이언트 등록 | 🟢 **완료 (2026-07-10)** | `client_id` · `client_secret` 발급 |
| 허용 IP 등록 | 🟡 확인 필요 | 서버 배포 IP를 WTS 허용 IP 목록에 등록 필수 |
| API 키 저장 | 🟡 미완 | `.env` `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET` 값 입력 |
| `accountSeq` 확보 | 🟡 미완 | `GET /api/v1/accounts` 최초 호출로 획득 |

---

## 1. API 기본 정보

| 항목 | 값 |
|---|---|
| **Base URL** | `https://openapi.tossinvest.com` |
| **Version** | 1.2.2 (2026-07-10 확인) |
| **연동 방식** | REST 만 (WebSocket 없음) |
| **인증** | OAuth 2.0 Client Credentials Grant |
| **필수 헤더 (계좌/자산/주문)** | `Authorization: Bearer {token}` + `X-Tossinvest-Account: {accountSeq}` |
| **Content-Type** | `application/json` (415 방지) |
| **시장** | KR(KRX·NXT) + US 통합 |

---

## 2. 인증 (OAuth 2.0)

### 2-1. 토큰 발급
```
POST /oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id={TOSS_CLIENT_ID}
client_secret={TOSS_CLIENT_SECRET}
```

**Rate Limit**: `AUTH` 그룹 · 초당 5회

**응답**: `{ "access_token": "...", "token_type": "Bearer", "expires_in": <초> }`

### 2-2. 토큰 캐시 정책
- **캐시 파일**: `TOSS_TOKEN_CACHE_PATH` (기본 `backend/data/toss_token.json`)
- **재발급 트리거**: 만료 **5분 전 pre-emptive refresh** (429 방지)
- **실패 처리**: 재발급 3회 실패 시 Kill Switch 자동 발동 후 알림

### 2-3. 계좌 헤더 값 확보
```
GET /api/v1/accounts
Authorization: Bearer {token}
```
응답의 `accountSeq` (정수) 를 `.env` `TOSS_ACCOUNT_SEQ` 에 저장 → 이후 모든 계좌/주문 API 헤더 값으로 사용.

**계좌 유형**: 현재 지원은 `BROKERAGE` (종합매매 · 국내·해외 통합).

---

## 3. 주문 API (Phase 2 핵심)

### 3-1. 주문 생성
```
POST /api/v1/orders
Authorization: Bearer {token}
X-Tossinvest-Account: {accountSeq}
Content-Type: application/json

{
  "clientOrderId": "ttb-{uuid}",       # 멱등키 (10분 유효 · 36자 · [a-zA-Z0-9_-])
  "symbol": "005930",                   # KR: 6자리 숫자, US: 영문 티커
  "side": "BUY",                        # BUY | SELL
  "orderType": "LIMIT",                 # LIMIT | MARKET
  "timeInForce": "DAY",                 # DAY (기본) | CLS (US LIMIT 만)
  "quantity": "10",                     # decimal string
  "price": "70000",                     # LIMIT 필수, MARKET 금지
  "confirmHighValueOrder": false        # 1억 이상 주문 시 true
}
```

**Rate Limit**: `ORDER` 6/s (**09:00~09:10 KST 는 3/s** — 클라이언트 leaky bucket 필수)

### 3-2. 주문 정정 · 취소
- `POST /api/v1/orders/{orderId}/modify` — `OrderModifyRequest` (가격/수량)
- `POST /api/v1/orders/{orderId}/cancel` — body 없음
- 이미 체결·취소·정정된 주문 대상은 `409 already-*` 반환

### 3-3. 주문 조회
⚠️ **status 는 개별 상태가 아닌 그룹 라벨** (2026-07-10 실측):
- `GET /api/v1/orders?status=OPEN` — 진행 중 그룹 (`PENDING · PARTIAL_FILLED · PENDING_CANCEL · PENDING_REPLACE`)
- `GET /api/v1/orders?status=CLOSED` — 종료 그룹 (`FILLED · CANCELED · REJECTED · REPLACED · CANCEL_REJECTED · REPLACE_REJECTED`)
- `status` 는 **필수** · 값이 `PENDING` 등 개별 상태이면 400 `invalid-request`
- `GET /api/v1/orders/{orderId}` — 단일 상세 (개별 `status` 반환)
- 부가 쿼리: `symbol` · `from`/`to` (KST date) · `cursor` (CLOSED 만) · `limit` (CLOSED 만, 기본 20 최대 100)

### 3-4. OrderStatus (10종 · unknown 허용 필수)

| 상태 | 의미 |
|---|---|
| `PENDING` | 체결 대기 |
| `PENDING_CANCEL` | 취소 대기 |
| `PENDING_REPLACE` | 정정 대기 |
| `PARTIAL_FILLED` | 부분 체결 |
| `FILLED` | 전량 체결 |
| `CANCELED` | 취소 완료 (부분 체결 여부는 `execution.filledQuantity` 확인) |
| `REJECTED` | 브로커 거부 |
| `CANCEL_REJECTED` | 취소 거부 (별도 레코드) |
| `REPLACE_REJECTED` | 정정 거부 (별도 레코드) |
| `REPLACED` | 정정됨 (원주문 대체) |

**OMI 매핑 (`02-omi-interface-spec.md` §2)**:
| Toss OrderStatus | OMI OrderStatus |
|---|---|
| `PENDING` · `PENDING_CANCEL` · `PENDING_REPLACE` | `ACCEPTED` |
| `PARTIAL_FILLED` | `PARTIAL_FILL` |
| `FILLED` | `FILLED` |
| `CANCELED` | `CANCELED` |
| `REJECTED` · `CANCEL_REJECTED` · `REPLACE_REJECTED` | `REJECTED` |
| `REPLACED` | (신규 order_uuid 로 재기록) |

---

## 4. 조건주문 API (Phase 3 Super Signal 실행 핵심)

토스 Open API 는 **감시 조건 자동 매매** 를 표준 제공 — 이는 KIS 대비 큰 우위.

### 4-1. 등록
```
POST /api/v1/conditional-orders
Authorization / X-Tossinvest-Account 필수
Content-Type: application/json

{
  "clientOrderId": "ttb-cond-{uuid}",
  "type": "OCO",                        # SINGLE | OCO | OTO
  "symbol": "005930",
  "quantity": "10",                     # 그룹 공통
  "orderType": "LIMIT",                 # LIMIT | MARKET (OCO/OTO 는 LIMIT 만)
  "expireDate": "2026-08-10",           # YYYY-MM-DD 필수
  "first": {
    "condition": {...},                 # 감시 조건 (가격 도달 등)
    "orderPrice": "72000"               # LIMIT 시 필수
  },
  "second": {                           # SINGLE 은 생략, OCO/OTO 는 필수
    "condition": {...},
    "orderPrice": "65000"
  }
}
```

**활용 시나리오**:
- **매수 진입 + 익절 + 손절** 을 OCO 로 한 번에 등록 → 두 조건 중 하나 체결 시 나머지 자동 취소
- **매수 진입 → 조건부 매도** OTO 로 매수 체결 시 매도 조건 활성화

**제약**:
- 동일 종목 OCO/OTO 는 **1개만** (`duplicate-conditional-order`)
- SINGLE 은 종목당 제한 없음
- **Rate Limit**: `CONDITIONAL_ORDER` 5/s

### 4-2. 수정 · 취소 · 조회
- `POST /api/v1/conditional-orders/{conditionalOrderId}/modify`
- `DELETE /api/v1/conditional-orders/{conditionalOrderId}`
- `GET /api/v1/conditional-orders?status=OPEN` — 진행 중
- `GET /api/v1/conditional-orders/{conditionalOrderId}` — 상세

---

## 4-3. ⚠️ 응답 래퍼 통일 계약 (2026-07-10 실측)

**OpenAPI JSON 원문 재확인 결과 — 성공 응답은 전 엔드포인트가 `{ "result": ... }` 래퍼로 통일** (29개 중 28개, `ApiResponse` allOf 상속).

```jsonc
// GET /api/v1/accounts 실측
{
  "result": [
    { "accountNo": "16901022098", "accountSeq": 1, "accountType": "BROKERAGE" }
  ]
}
```

- **모든 파서는 `body["result"]` 로 접근**해야 하며, 리스트 반환 엔드포인트도 동일 (예: `accounts.result` 는 배열).
- 실패 응답만 `error` 필드 (§7-1) · `result` 와 동시 등장 안 함.
- TossAdapter 구현 시 공통 응답 언랩퍼 필수.

## 4-4. 자산 조회 쿼리 파라미터 (2026-07-10 실측 · 스펙 재확인)

| 엔드포인트 | 필수 쿼리 | 선택 쿼리 | 실측 오류 예시 |
|---|---|---|---|
| `GET /api/v1/buying-power` | **`currency=KRW\|USD`** | — | 400 `invalid-request { field: "currency" }` 미전달 시 |
| `GET /api/v1/holdings` | — | `symbol` | — |
| `GET /api/v1/sellable-quantity` | `X-Tossinvest-Account` 헤더 + `symbol` 쿼리 | — | — |

**교훈**: 스펙 문서 요약본만 신뢰하지 말고 OpenAPI JSON 원문(`openapi.json`)의 `parameters[].required` 를 반드시 확인. 메모리 `reference_toss_open_api` 갱신 완료.

## 5. 시세·계좌 조회 (실시간성)

토스 API는 **WebSocket 미지원** — Phase 4 실시간 진입은 **REST 폴링** 로 구현.

### 5-1. 폴링 예산 계산 (Rate Limit 이내)
- `MARKET_DATA` 10/s → 시세 조회 여유 있음
- `MARKET_DATA_CHART` 5/s → 캔들 조회 (1분봉·일봉)
- 감시 종목 N개 × 초당 조회 ≤ 10 이어야 함
- **권장**: 종목별 200ms 폴링 (5 종목 동시 = 25 req/s 초과 X → **분할 필요**)
- **실전 안전 마진**: 시세 8 req/s 상한 (2 여유), 캔들 3 req/s 상한

### 5-2. 주요 시세 엔드포인트
- `GET /api/v1/prices?symbols=005930,AAPL` — 현재가 (다중 심볼)
- `GET /api/v1/orderbook?symbol=005930` — 호가
- `GET /api/v1/trades?symbol=005930` — 최근 체결
- `GET /api/v1/candles?symbol=005930&interval=1m` — 1분봉/일봉

### 5-3. 매수 유의사항 (Phase 3 리스크 예산 반영)
- `GET /api/v1/stocks/{symbol}/warnings` — 정리매매·단기과열·투자경고/위험·VI·신주인수권
- 시그널 시 warning 감지 → 리스크 예산 자동 하향

---

## 6. Rate Limits 전략

| 그룹 | 한도 | 클라이언트 안전 상한 | 용도 |
|---|---|---|---|
| `AUTH` | 5/s | 1/s (토큰 캐시 사용) | 토큰 발급 |
| `ACCOUNT` | 1/s | 0.5/s | 계좌 조회 (초기 accountSeq 확보만) |
| `ASSET` | 5/s | 3/s | 잔고 (30초 주기) |
| `ORDER` | 6/s (피크 3/s) | 4/s (피크 2/s) | 매매 실행 · 09:00~09:10 별도 처리 |
| `ORDER_HISTORY` | 5/s | 3/s | 미체결 조회 |
| `ORDER_INFO` | 6/s (피크 3/s) | 4/s | buying-power · sellable-quantity |
| `CONDITIONAL_ORDER` | 5/s | 3/s | 조건주문 등록/취소 |
| `MARKET_DATA` | 10/s | 8/s | 시세 폴링 |
| `MARKET_DATA_CHART` | 5/s | 3/s | 캔들 (분봉) |
| `STOCK` | 5/s | 3/s | 종목 정보 (warnings 등) |

**구현 원칙**:
- 클라이언트 측 **leaky bucket** 으로 그룹별 상한 강제 (안전 마진 20~30%)
- 09:00~09:10 KST **자동 감지** → `ORDER` / `ORDER_INFO` 를 3/s 로 스로틀
- 429 수신 시 `Retry-After` 우선, 없으면 지수 백오프 1s → 2s → 4s (+jitter)
- 3회 재시도 실패 → OMI `RateLimitExceeded` 예외 → Kill Switch 트리거 후보

---

## 7. 에러 처리 · OMI 예외 매핑

### 7-1. Envelope
```json
{ "error": { "requestId": "...", "code": "...", "message": "...", "data": {...} } }
```
`requestId` == 응답 헤더 `X-Request-Id` (누락 시 `x-amz-cf-id`).

### 7-2. Toss code → OMI 예외 매핑

| HTTP | Toss code | OMI 예외 | 재시도 |
|---|---|---|---|
| 400 | `invalid-request` | `OrderRejected` | ✗ |
| 400 | `account-header-required` | `ExecutionError` (설정 오류) | ✗ |
| 400 | `confirm-high-value-required` | `OrderRejected` (요청 재구성 필요) | ✗ |
| 401 | `invalid-token` · `expired-token` | 자동 토큰 재발급 후 재시도 (예외 X) | ✓ |
| 401 | `edge-blocked` (Authorization 누락) | `ExecutionError` (버그) | ✗ |
| 403 | `forbidden` · `edge-blocked` | `ExecutionError` (IP 미등록 등 · 알림) | ✗ |
| 404 | `stock-not-found` | `OrderRejected` | ✗ |
| 404 | `account-not-found` | `ExecutionError` (설정 오류) | ✗ |
| 404 | `order-not-found` | `OrderNotFound` | ✗ |
| 409 | `request-in-progress` | idempotency 활용 · 잠시 후 재조회 | ✓ (500ms) |
| 409 | `already-filled` · `already-canceled` · `already-modified` · `already-rejected` | `OrderRejected` (상태 조회로 확정) | ✗ |
| 415 | `unsupported-content-type` | `ExecutionError` (버그) | ✗ |
| 422 | `insufficient-buying-power` | `InsufficientBalance` | ✗ |
| 422 | `insufficient-sellable-quantity` | `InsufficientBalance` (매도) | ✗ |
| 422 | `order-hours-closed` | `MarketClosed` | ✗ |
| 422 | `stock-restricted` | `OrderRejected` | ✗ |
| 422 | `price-out-of-range` | `OrderRejected` (data.tickSize 참조 후 재요청) | ✗ |
| 422 | `opposite-pending-order-exists` | `OrderRejected` (기존 취소 후 재시도 결정 필요) | ✗ |
| 422 | `idempotency-key-conflict` | `DuplicateOrderError` | ✗ |
| 422 | `account-restricted` | `ExecutionError` (Kill Switch 후보) | ✗ |
| 422 | `duplicate-conditional-order` | `OrderRejected` (기존 조건 조회) | ✗ |
| 422 | `condition-already-met` | `OrderRejected` (가격 재설정) | ✗ |
| 429 | `rate-limit-exceeded` · `edge-rate-limit-exceeded` | `RateLimitExceeded` | ✓ (Retry-After) |
| 500 | `internal-error` | `BrokerCommunicationError` | ✓ (백오프) |
| 500 | `maintenance` | `BrokerCommunicationError` (Kill Switch 후보) | ✓ (긴 대기) |

### 7-3. 감사 로그 필수 필드
- `error.requestId` → `order_audit.raw_response.requestId`
- `error.code` → `order_audit.error_code`
- `error.message` → `order_audit.error_message`
- `error.data` 전체 → `order_audit.raw_response`

---

## 8. 실전 검증 프로토콜 (Phase 2)

### 8-1. Pre-flight (Phase 1 완료 후, 실 주문 전)

- [ ] `TOSS_CLIENT_ID` · `TOSS_CLIENT_SECRET` 저장 완료
- [ ] `GET /oauth2/token` 성공 (Postman/curl)
- [ ] `GET /api/v1/accounts` 로 `accountSeq` 확보
- [ ] `.env` `TOSS_ACCOUNT_SEQ` 저장
- [ ] `GET /api/v1/holdings` · `GET /api/v1/buying-power` 정상 응답
- [ ] 서버 배포 IP 를 WTS 허용 IP 에 등록 (production 배포 시)

### 8-2. Smoke Test (Paper 어댑터로 계약 통과 후)

1. **최소 수량 지정가 매수** — 1주 · 현재가 -5% (미체결로 남을 가격)
2. **주문 조회 정확도** — `GET /api/v1/orders/{orderId}` 로 status 확인
3. **주문 취소** — 성공 확인 (`CANCELED`)
4. **정정** — 가격 변경 후 재취소
5. **시장가 매도** — 실 보유 종목 1주 (실전 fill 확인)
6. **Rate limit** — 초당 7회 주문 시도 → 429 발생 확인 + `Retry-After` 파싱

**모든 단계에서 감사 로그(`order_audit`) 정확히 기록되어야 함.**

### 8-3. 실전 소액 검증 (5거래일)

- `EXECUTION_MAX_ORDER_AMOUNT=100000` 하드코딩 (10만 원 상한)
- 매일 09:00 사용자 손절 리뷰
- 일일 실현손실 -1% 초과 시 즉시 중단 (`EXECUTION_DAILY_LOSS_LIMIT=-0.03` 보다 보수적)
- 매일 종료 후 감사 로그 요약 텔레그램 발송

---

## 9. 09:00~09:10 KST 특별 처리

Toss API 는 개장 직후 10분간 `ORDER` / `ORDER_INFO` rate 를 **6/s → 3/s** 로 강제 다운. 
클라이언트 어댑터가 자동 감지·스로틀 필요.

```python
# 예시 로직 (kis 조각이 아님, Toss 전용)
def order_rate_limit() -> int:
    now = datetime.now(tz=KST)
    if now.time() < time(9, 10) and now.time() >= time(9, 0):
        return 3  # 개장 직후
    return 6
```

---

## 10. 참조 링크

- **공식 개발자 사이트**: https://developers.tossinvest.com/docs
- **OpenAPI JSON (source of truth)**: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
- **Overview MD**: https://openapi.tossinvest.com/openapi-docs/overview.md
- **API Reference MD**: https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md
- **LLM 안내**: https://developers.tossinvest.com/llms.txt
- **프로젝트 메모리**: `reference_toss_open_api`

---

## 11. 결정 로그

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-07-10 | KIS Developers 취소 · **Toss Open API 전격 채택** | 사용자 Toss API 키 발급 완료 + Toss가 KR/US 통합 + 조건주문(SINGLE/OCO/OTO) 표준 지원 |
| 2026-07-10 | WebSocket 없음 → 시세는 REST 폴링 | `MARKET_DATA` 10/s 여유로 5종목 동시 감시 가능 |
| 2026-07-10 | 조건주문을 Phase 3 Super Signal 실행 핵심으로 지정 | OCO로 익절+손절 원자 세팅 → 봇 결정 반영 |
| 2026-07-10 | Phase 2 실전 검증 소액 상한 10만 원 유지 | KIS 계획 그대로 계승 |

---

## 참조

- 전신 문서: `01-track-c-roadmap.md` · `02-omi-interface-spec.md`
- 규정: `feedback_partner_accountability` (Toss API 실패 시 requestId + code 로 근본 해결까지 추적)
