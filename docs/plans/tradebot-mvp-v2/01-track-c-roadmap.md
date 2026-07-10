# 🚀 Toss Tradebot MVP v2 — 트랙 C 통합 로드맵 (구현계획서)

**작성일**: 2026-07-10
**요청자**: 사용자
**작성 근거**: `00-critic-review-2026-07-10.md` Section 5 (트랙 C 확정)
**상태**: 🟢 **로드맵 승인 (2026-07-10) · Phase 0 착수**
**목표**: 트랙 A(실행 채널) + 트랙 B(내실화)를 결합한 단계별 릴리즈 플랜

---

## 0. 요약 (한눈 보기)

**핵심 원칙**
- **브로커 중립 아키텍처**: 시그널 엔진은 Toss/Paper 어느 어댑터에도 종속되지 않는다 (향후 브로커 추가 대비).
- **실 자본 투입 전 3중 안전장치**: Paper 어댑터 · 리스크 예산 룰 · Kill Switch.
- **Phase 단위 완결 배포**: 부분 배포 금지 (`feedback_deploy_only_when_complete`).
- **GitHub Actions 우선 배포**: 수동 SSH 금지 (`feedback_workflow_first_before_manual_deploy`).

**결과물 5축**
1. `backend/execution/` 신규 서브패키지 (OMI + Paper/Toss 어댑터)
2. 리스크 예산·Kill Switch 통합
3. 다중 시그널 병합(Super Signal) + 조건주문(OCO) 익절·손절 자동 세팅
4. 크로스-메뉴 백테스트 인프라
5. Toss REST 폴링 기반 1분봉 실시간 진입 타점 + KR/US 통합 실행

---

## 1. 배경 및 목표

### 1-1. 배경 (`00-critic-review` 확정 + 2026-07-10 KIS→Toss 전환 반영)

- 현 MVP는 '시그널 발굴 ↔ 텔레그램 알림 ↔ UI 대시보드'까지만 존재하며, **매매 실행 레이어가 부재**함.
- 시그널이 정확해도 사용자가 앱을 켜서 수동 주문하는 사이 **수십 초 딜레이 = 상투 확정** — "실현손실 0" 원칙의 구조적 파괴점.
- **토스증권 Open API v1.2.2 가 정식 개방** (2026-07 확인 · 사용자 API 키 발급 완료 2026-07-10). Base `https://openapi.tossinvest.com` · OAuth 2.0 Client Credentials · KR(KRX)+US 통합.
- 토스 API가 KIS 대비 압도적 우위: **① KR/US 단일 계좌·단일 어댑터로 통합** · **② 조건주문 SINGLE/OCO/OTO 표준 지원** (익절+손절 원자 세팅) · **③ REST 만 필요** (기존 FastAPI 스택 정합) · **④ 프로젝트 명칭과 브랜드 정합**.
- 상세: `03-toss-openapi-integration.md` · 메모리 `reference_toss_open_api`.

### 1-2. 목표
- **P0**: 봇 결정 → 거래소 도달 지연을 **1초 이내** 로 단축 (Toss REST 어댑터 실 매매).
- **P1**: 실 자본 투입 전 모든 시그널을 **Paper 어댑터**로 forward test 통과.
- **P2**: 자금 관리 수학(리스크 예산 · Max DD Cap · Kill Switch) 통합.
- **P3**: 시그널 신뢰도의 근거(크로스-메뉴 백테스트) 확보 + **조건주문(OCO)** 로 익절·손절 원자 세팅.
- **P4**: 실시간 진입 타점(Toss `MARKET_DATA` 10/s REST 폴링, 1분봉/현재가) 으로 밈주·주도주 단타 대응.
- **P5**: KR/US 통합 실행 검증 + 조건주문 활용 확장 (재진입 자동화 등).

---

## 2. 아키텍처 설계

### 2-1. Broker Adapter Pattern

```
┌─────────────────────────────────────────────────────────────┐
│  시그널 엔진 (기존 + 이번 로드맵 확장)                        │
│  Meme Watch · VIP Watch · Activist Radar · Sector Leaders   │
│  Super Signal (다중 시그널 병합)                              │
└──────────────────────┬──────────────────────────────────────┘
                       │ SignalEvent
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Signal Router (신규)                                         │
│  · 시그널 우선순위 판정                                        │
│  · 리스크 예산 룰 통과 여부 체크                                 │
│  · Kill Switch 상태 확인                                       │
│  · 브로커 선택 (Paper / Toss)                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ OrderRequest
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Order Manager Interface (OMI) [ABC]                         │
│  submit_order(req) -> OrderResult                            │
│  cancel_order(broker_order_id) -> bool                       │
│  get_order_status(broker_order_id) -> OrderResult            │
│  get_balance() -> Balance                                    │
│  get_position(ticker) -> Position                            │
│  get_market_info(ticker) -> MarketInfo                       │
└─────┬────────────────────────────────┬──────────────────────┘
      │                                │
      ▼                                ▼
┌──────────────┐              ┌──────────────────┐
│PaperAdapter  │              │TossAdapter       │
│ Phase 1 필수  │              │ Phase 2 실전      │
│ 시뮬 체결      │              │ Toss Open API    │
└──────────────┘              │ + 조건주문(OCO)   │
                              └──────────────────┘
```

### 2-2. 데이터 모델 (요약)

| 모델 | 용도 | 저장소 |
|---|---|---|
| `OrderRequest` | 시그널 → 어댑터 입력 | 인메모리 |
| `OrderResult` | 어댑터 → 감사 로그 | SQLite (신규 테이블 `order_audit`) |
| `Position` | 종목별 보유 상태 | 어댑터 API + 로컬 캐시 |
| `RiskBudget` | 종목별 최대 할당 자본 | JSON (`data/risk_budget.json`) |
| `KillSwitchState` | 긴급 정지 플래그 | JSON (`data/kill_switch.json`) |

### 2-3. Kill Switch 트리거 (자동)
- 일일 총 손실 > 임계값 (기본 -3%)
- 특정 종목 손실 > `MAX_TICKER_DD` (기본 -5%)
- API 에러율 > 임계값 (60초 window, 20% 초과)
- 수동 API `POST /api/v1/execution/kill-switch`

Kill Switch 발동 시: **모든 신규 주문 차단** · 기존 미체결 취소 · Telegram 🚨 즉시 발송 · 사용자 수동 해제 필요.

---

## 3. Phase 0 — 사전 준비 (🟢 대부분 완료 · 2026-07-10)

**기간**: 준비 단계 · 실 자본 리스크 없음

### 3-1. 사용자 수행 상태
1. ✅ **토스증권 실계좌 존재** (기존 계좌 활용)
2. ✅ **Toss Open API 클라이언트 등록 완료** — WTS → 설정 > Open API → `client_id` · `client_secret` 발급 (2026-07-10)
3. 🟡 **허용 IP 등록** — 서버 배포 IP (optimus8.cafe24.com)를 WTS 허용 IP 목록에 등록 필요
4. 🟡 **API 키 로컬 저장** — `.env` `TOSS_CLIENT_ID` · `TOSS_CLIENT_SECRET`
5. 🟡 **`accountSeq` 확보** — `GET /api/v1/accounts` 최초 호출로 획득 → `.env` `TOSS_ACCOUNT_SEQ`
6. ✅ **env 스키마 확정** (`.env.example` 갱신 완료):
   ```
   EXECUTION_ENABLED=false
   EXECUTION_BROKER=paper                    # paper | toss
   EXECUTION_MAX_ORDER_AMOUNT=100000         # 원, Phase 2 소액 상한
   EXECUTION_DAILY_LOSS_LIMIT=-0.03          # -3%
   EXECUTION_TICKER_DD_LIMIT=-0.05           # -5%
   EXECUTION_PER_TICKER_MAX_PCT=0.10         # 종목당 10%
   TOSS_CLIENT_ID=                           # 파일 상단 재사용
   TOSS_CLIENT_SECRET=                       # 파일 상단 재사용
   TOSS_ACCOUNT_SEQ=                         # GET /api/v1/accounts 응답
   TOSS_TOKEN_CACHE_PATH=data/toss_token.json
   TOSS_CLIENT_ORDER_PREFIX=ttb              # 멱등키 프리픽스
   ```

### 3-2. Claude 산출물 (완료)
- ✅ `.env.example` 갱신 (Execution + Toss 스키마)
- ✅ Toss Open API 스펙 정독 및 문서화 (`03-toss-openapi-integration.md`)
- ✅ 프로젝트 메모리 등록 (`reference_toss_open_api`)

---

## 4. Phase 1 — 안전장치 우선 (2주)

**목표**: 실 자본 없이 시뮬레이션까지 완전 동작 · 모든 안전장치 선(先) 배포

### 4-1. 신규 서브패키지 `backend/execution/`

```
backend/execution/
├── __init__.py
├── models.py                # OrderRequest, OrderResult, Position, Balance, RiskBudget
├── order_manager.py         # OMI (ABC)
├── signal_router.py         # 시그널 → OMI 라우팅 + 리스크 체크
├── risk_budget.py           # 종목별 예산·Kelly·Vol Targeting
├── kill_switch.py           # 자동/수동 트리거 + 상태 파일
├── audit.py                 # order_audit 테이블 관리
└── brokers/
    ├── __init__.py
    ├── base.py              # OMI 재선언 (편의)
    ├── paper_adapter.py     # 시뮬레이션 어댑터 (Phase 1 필수)
    └── toss_adapter.py      # Toss Open API 실전 어댑터 (Phase 2)
```

### 4-2. Signal Router 통합 지점

기존 시그널 발생점 (예시):
- `backend/discovery/meme_stock/notifier.py`
- `backend/discovery/vip/vip_watch.py`
- `backend/discovery/activist/radar.py`
- `backend/discovery/sector/…`

→ 시그널 emit 시 `SignalRouter.route(SignalEvent)` 호출 추가.  
Router는 텔레그램 알림과 **병행**하며, `EXECUTION_ENABLED=false` 시 라우팅 스킵(기존 동작 무영향).

### 4-3. 리스크 예산 룰 (진짜 공백 #2)

**초기 룰 (Phase 1 · 단순)**:
- 종목별 최대 자본 할당: 총 자본의 `PER_TICKER_MAX_PCT` (기본 10%)
- 전체 미실현 손실 캡: 일일 `-3%` 초과 시 신규 매수 차단
- 종목별 Max DD: `-5%` 도달 시 자동 청산 신호

**Phase 3 확장 여지**: Kelly Criterion, Vol Targeting.

### 4-4. Paper 어댑터 상세
- 실 Toss API 시세(`GET /api/v1/prices` · `MARKET_DATA` 10/s) 를 사용하되 주문만 시뮬레이션 (fill 가정: 시장가 즉시 · 지정가는 다음 tick 매칭)
- 수수료율은 `GET /api/v1/commissions` 실측 후 보정 (KR·US 시장별)
- 감사 로그(`order_audit`)에 브로커 `paper` 태그로 기록
- 백테스트 인프라와 상당수 코드 공유 (Phase 3에서 재활용)

### 4-5. Kill Switch API
- `GET /api/v1/execution/kill-switch/status`
- `POST /api/v1/execution/kill-switch` (수동 발동)
- `DELETE /api/v1/execution/kill-switch` (수동 해제)
- Frontend `/execution` 신규 페이지에 표시 (Phase 3에서 확장)

### 4-6. Phase 1 완료 기준 (DoD)
- [ ] `EXECUTION_BROKER=paper` 로 밈주 시그널 감지 → 시뮬 매수 → 익절/손절/Kill Switch 동작 확인
- [ ] `order_audit` 테이블에 감사 로그 완전 기록
- [ ] 리스크 예산 초과 시 시그널 차단 및 텔레그램 통지
- [ ] `EXECUTION_ENABLED=false` 시 기존 밈주/VIP/Activist 시그널 알림 무영향 (회귀 없음)
- [ ] GitHub Actions 배포 통과

---

## 5. Phase 2 — Toss Open API 실전 연동 (3주)

**목표**: Paper 어댑터로 계약 통과 → 실계좌 smoke test → 소액 검증 5거래일 → 자동매매 실전 진입

**전제**: 별도 sandbox 미제공 → **처음부터 실계좌 소액**으로 검증 (KIS 대비 리스크가 크므로 안전장치를 더 엄격히).

### 5-1. TossAdapter 구현
- HTTP 클라이언트: `httpx` (프로젝트 표준) · 자체 구현 (`mojito` 같은 3rd-party 없음)
- **인증**: `POST /oauth2/token` (grant_type=client_credentials) · 캐시 파일 (`TOSS_TOKEN_CACHE_PATH`) · **만료 5분 전 pre-emptive refresh**
- **필수 헤더**: `Authorization: Bearer` + `X-Tossinvest-Account: {TOSS_ACCOUNT_SEQ}`
- **주문 idempotency**: `clientOrderId` = `ttb-{uuid8}` (10분 유효 · 36자 · `[a-zA-Z0-9_-]`)
- **rate limit** (`reference_toss_open_api` §Rate Limits):
  - `ORDER` 6/s · **09:00~09:10 KST 는 3/s** (자동 감지·스로틀)
  - 클라이언트 leaky bucket · `Retry-After` 우선 · 지수 백오프 1s→2s→4s + jitter
- **에러 매핑** (03-toss-openapi-integration.md §7-2):
  - `422 insufficient-buying-power` / `insufficient-sellable-quantity` → `InsufficientBalance`
  - `422 order-hours-closed` → `MarketClosed`
  - `422 idempotency-key-conflict` → `DuplicateOrderError`
  - `429 rate-limit-exceeded` → `RateLimitExceeded`
  - `401 invalid-token`/`expired-token` → **자동 재발급 후 재시도** (예외 X)
  - `403 forbidden` → `ExecutionError` (허용 IP 미등록 · Kill Switch 후보)

### 5-2. 시장 시간 게이팅
- `GET /api/v1/market-calendar/KR` · `/US` 로 정규장/Pre/After 판정 (30분 캐시)
- 정규장 외 주문은 로컬 게이팅으로 즉시 거부 (텔레그램 통지 · Kill Switch 아님)
- `422 order-hours-closed` 는 방어선 (로컬 게이팅이 실패한 경우만 발생해야 함)

### 5-3. 검증 프로토콜 (Toss는 sandbox 없음 → 엄격)

**5-3-1. Smoke Test (실계좌 · Paper 어댑터 계약 통과 직후)**
1. 최소 수량 지정가 매수 — 1주 · 현재가 -5% (미체결로 남을 가격) → `PENDING` 확인
2. `GET /api/v1/orders/{orderId}` 로 status 조회 정확도
3. `POST /orders/{orderId}/cancel` → `CANCELED` 확인
4. `POST /orders/{orderId}/modify` (가격 변경) → `REPLACED` 확인 후 재취소
5. 시장가 매도 1주 (실 보유 종목 있을 시) → `FILLED` 확인
6. 429 유발: 초당 7회 시도 → `X-RateLimit-Remaining` · `Retry-After` 파싱 검증

**5-3-2. 실계좌 소액 forward test (5거래일)**
- `EXECUTION_MAX_ORDER_AMOUNT=100000` (10만 원) 하드 상한 코드 레벨 강제
- 밈주/VIP/Activist 실시간 시그널을 실계좌에서 forward test
- 매일 09:00 사용자 손절 리뷰 · 일일 실현손실 -1% 초과 시 즉시 중단 (`DAILY_LOSS_LIMIT=-0.03` 보다 보수적)
- 매일 종료 후 감사 로그 요약 텔레그램 발송

### 5-4. Frontend `/execution` 페이지
- 감사 로그 조회 (최근 100건 · `X-Request-Id` 표시)
- 미체결 주문 현황 · 취소 버튼
- Kill Switch 상태 토글
- 리스크 예산 현황
- Toss API 응답 헤더 대시보드 (`X-RateLimit-*` 실시간)

### 5-5. Phase 2 완료 기준 (DoD)
- [ ] Smoke Test 6단계 전부 통과 (실계좌 · 최소 수량)
- [ ] 실계좌 소액 5거래일 forward test 완료 (실현손실 < 1만 원)
- [ ] Access Token pre-emptive refresh 자동 동작 확인
- [ ] `X-Request-Id` + Toss `error.code` 모든 감사 로그에 정확히 기록
- [ ] Kill Switch 실측 발동 시나리오 1회 이상 검증
- [ ] Frontend `/execution` 페이지 반영
- [ ] 09:00~09:10 rate limit 스로틀 실측 확인

---

## 6. Phase 3 — 진짜 공백 채우기 (3주)

**목표**: `00-critic-review` Section 3에서 도출한 진짜 공백 6건 중 #3, #4, #5 해소

### 6-1. 다중 시그널 병합 — Super Signal (#4)
- **엔진**: `backend/discovery/super_signal/`
- **로직**: 30일 window에서 특정 티커가 Meme + VIP + Activist 중 2개 이상 히트 시 `SUPER_SIGNAL` 승격
- **스코어**: `intensity = Σ(hit_score × source_weight)` — source_weight는 활동주(Activist) > VIP > Meme 순 조정
- **자동 실행 (Toss 조건주문 활용)**: SUPER_SIGNAL 감지 시 **`POST /api/v1/conditional-orders` OCO 등록** — 익절 조건 + 손절 조건을 원자 세팅, 하나 체결 시 나머지 자동 취소
  - 예: WEN $60 매수 진입 후 OCO(익절 $66 / 손절 $57) 조건 등록 → 인간 개입 없이 자동 청산
  - `duplicate-conditional-order` 방어: 등록 전 기존 OCO 조회
- **알림**: `[SUPER-SIGNAL · TICKER · Meme+VIP+Activist · 92 · OCO 등록]` 전용 태그
- **UI**: `/execution` 또는 `/super-signals` 신규 카드 (조건주문 상태 표시)

### 6-2. 알림 피로도 프로파일 (#5)
- **프로파일 종류**:
  - `SCOUT` — 모든 시그널 (기본, 하드코어 유저)
  - `SNIPER` — SUPER_SIGNAL + URGENT만
  - `WATCH` — INFO 이상 전부, 30분 배치
- **env**: `TELEGRAM_PROFILE=SCOUT`
- **동적 조정**: 향후 자산 규모/성향 UI 연동 (Phase 4+)

### 6-3. 크로스-메뉴 백테스트 인프라 (#3)
- **엔진**: `backend/backtest/`
- **재활용**: Paper 어댑터 코드 재사용 (fill 시뮬레이션)
- **데이터**: 기존 Meme Watch 30일 히스토리 + Activist events + Sector Leaders 스냅샷
- **결과**: 시그널별 승률·평균 수익·MDD 리포트 (`docs/analysis/backtest/`)
- **UI**: `/backtest` 페이지 (선택 티커 시그널 시나리오 재생)

### 6-4. Phase 3 완료 기준 (DoD)
- [ ] Super Signal 실 감지 로그 10건+
- [ ] 3개 프로파일 각각 텔레그램 검증
- [ ] Sector Leaders + Activist 백테스트 리포트 1회 산출

---

## 7. Phase 4 — 실시간성 강화 (2주)

**목표**: 진짜 공백 #6 (1분봉 실시간 진입 타점) 해소 + 기존 채택안 통합
**제약**: Toss API 는 **REST 전용, WebSocket 없음** → 폴링 최적화 전략

### 7-1. Toss REST 폴링 최적화 (WebSocket 대체)
- **시세 폴링 예산 계산**:
  - `MARKET_DATA` 10/s → 안전 상한 8/s
  - `MARKET_DATA_CHART` (캔들) 5/s → 안전 상한 3/s
  - `GET /api/v1/prices?symbols=A,B,C` 다중 심볼 동시 조회로 요청 수 절감
- **1분봉 실시간 감지**:
  - `GET /api/v1/candles?symbol=X&interval=1m` 을 30초 주기 폴링
  - 새 캔들 진입 감지 시 volume spike · price breakout · 호가 불균형 판정
- **적응형 폴링**: 시그널 후보 종목만 200ms 폴링, 나머지는 30초

### 7-2. Sector Leaders — RS 랭킹 병행 (기존 리뷰 채택)
- 20일 신고가 필터 + 상대강도(Relative Strength) 랭킹 병행
- 토스 API `GET /api/v1/rankings` (거래대금·거래량·등락률) + `GET /api/v1/candles` 로 자체 계산
- 기존 FinanceDataReader 병행 유지 (대안 소스 확보)

### 7-3. Meme Watch — 분봉 RSI Spike 조사 → 결정
- Toss 캔들 API (1분봉) 로 RSI 계산 가능성 검토 (`MARKET_DATA_CHART` 5/s 이내 통과 여부)
- 통과 시 6번째 지표로 편입, 실패 시 기록 후 기각

### 7-4. Phase 4 완료 기준 (DoD)
- [ ] 시그널 후보 5개 티커 200ms 폴링 안정 (rate limit 이내)
- [ ] 시그널 → 주문 접수 지연 1초 이내 실측
- [ ] Sector RS 랭킹 상위 10 산출 자동화
- [ ] Meme 분봉 RSI 채택/기각 결정 문서화

---

## 8. Phase 5 — 확장 및 진화 (2주+)

**목표**: KR/US 통합 실행 검증 + 조건주문 활용 확장 + 재진입 전략

### 8-1. KR/US 통합 실행 검증
- 단일 어댑터로 KRX 종목(005930 등) + US 종목(WEN, AAPL 등) 동시 매매
- 통화 환산 (`GET /api/v1/exchange-rate`) 을 리스크 예산에 통합
- 시장 시간 관리: KRX 09:00~15:30 KST + NYSE 22:30~05:00 KST (서머타임 자동)

### 8-2. 조건주문 활용 확장
- **재진입 자동화**: 청산 후 재진입 조건(전일 종가 -3% 등)을 SINGLE 조건주문으로 등록
- **분할 매수**: OTO(부모: 진입 조건 → 자식: 분할 매도 조건) 로 익절 구간별 분할 매도
- **트레일링 스톱 시뮬**: 지속 폴링으로 계산된 트레일 가격을 조건주문 수정(`modify`) 으로 반영 (Toss는 native trailing 미제공)

### 8-3. 브로커 확장 대비
- OMI 준수하는 신규 어댑터 추가 여지 확보 (예: 향후 다른 REST API 지원 증권사)
- Frontend `/execution` 브로커 선택 UI

### 8-4. Phase 5 완료 기준 (DoD)
- [ ] KR + US 종목 각 1건 이상 실계좌 매매 성공
- [ ] OCO 조건주문 실 발동 감지 1건 이상
- [ ] 재진입 SINGLE 조건주문 실 발동 감지 1건 이상

---

## 9. 리스크 및 안전장치 매트릭스

| 리스크 | 방어 층 |
|---|---|
| 봇 오작동으로 대량 매수/매도 | ① 리스크 예산 룰 ② 종목당 상한 ③ Kill Switch ④ Phase 2 소액 하드 상한 |
| 시장 폭락 시 연쇄 손절 | 일일 손실 캡 -3% Kill Switch |
| Access Token 만료 실패 | 재발급 자동화 + 실패 시 Kill Switch 발동 |
| 중복 주문 (재시도) | 클라이언트 `order_uuid` idempotency |
| 인프라 장애 (서버 재기동) | 미체결 주문 자동 재조회 + 사용자 확인 요청 |
| Toss rate limit 초과 (특히 ORDER 6/s, 피크 3/s) | 클라이언트 leaky bucket + `Retry-After` 준수 + 09:00~09:10 자동 스로틀 |
| 허용 IP 미등록으로 403 | 서버 배포 IP 사전 등록 · health_check 실패 시 Kill Switch |
| 로직 버그로 무한 매매 | Phase 2 실계좌 진입 전 Paper 계약 테스트 10건+ 강제 통과 · Smoke Test 6단계 |

---

## 10. 파일 트리 예상

```
toss-tradebot-mvp/
├── backend/
│   ├── execution/                    # 신규 (Phase 1~2)
│   │   ├── models.py
│   │   ├── order_manager.py
│   │   ├── signal_router.py
│   │   ├── risk_budget.py
│   │   ├── kill_switch.py
│   │   ├── audit.py
│   │   └── brokers/
│   │       ├── base.py
│   │       ├── paper_adapter.py
│   │       └── toss_adapter.py
│   ├── backtest/                     # 신규 (Phase 3)
│   │   ├── engine.py
│   │   ├── replay.py
│   │   └── reports.py
│   ├── discovery/
│   │   ├── super_signal/             # 신규 (Phase 3)
│   │   │   ├── merger.py
│   │   │   ├── scoring.py
│   │   │   └── notifier.py
│   │   ├── meme_stock/               # 기존 (Phase 4에서 분봉 편입)
│   │   ├── vip/                      # 기존 (Signal Router 연결)
│   │   ├── activist/                 # 기존 (Signal Router 연결)
│   │   └── sector/                   # 기존 (Phase 4에서 RS 랭킹)
│   └── api/routers/
│       ├── execution.py              # 신규 (Phase 1~2)
│       ├── backtest.py               # 신규 (Phase 3)
│       └── super_signals.py          # 신규 (Phase 3)
├── frontend/app/
│   ├── execution/                    # 신규 (Phase 2)
│   ├── backtest/                     # 신규 (Phase 3)
│   └── super-signals/                # 신규 (Phase 3)
├── data/
│   ├── risk_budget.json              # 신규
│   ├── kill_switch.json              # 신규
│   └── order_audit.db (SQLite)       # 신규
└── docs/plans/tradebot-mvp-v2/
    ├── 00-critic-review-2026-07-10.md   # 완료
    ├── 01-track-c-roadmap.md            # 본 문서
    ├── 02-omi-interface-spec.md         # OMI 상세 스펙
    ├── 03-toss-openapi-integration.md   # Toss API 스펙 및 실전 프로토콜
    └── README.md
```

---

## 11. 성공 지표 (KPI)

| Phase | 정량 지표 | 정성 지표 |
|---|---|---|
| Phase 1 | Paper 시뮬 20건 성공 · 회귀 0건 | Kill Switch 신뢰도 확보 |
| Phase 2 | Smoke Test 6단계 통과 · 실계좌 5거래일 실현손실 < 1만 원 · 주문 접수 지연 < 2초 | 자동매매 최초 실전 진입 |
| Phase 3 | Super Signal 감지 10건+ · OCO 조건주문 등록 5건+ · 백테스트 승률 리포트 산출 | 시그널 근거의 정량적 신뢰도 |
| Phase 4 | 주문 지연 < 1초 · 5개 티커 200ms 폴링 안정 | 밈주·주도주 단타 대응력 |
| Phase 5 | KR + US 각 1건 이상 실 매매 · 조건주문 자동 발동 감지 | 통합 실행 검증 완료 |

---

## 12. 결정 로그

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-07-10 | 트랙 C 확정 | `00-critic-review` Section 5 사용자 승인 |
| 2026-07-10 | Broker Adapter Pattern 채택 | 브로커 중립 · 향후 확장 대비 |
| 2026-07-10 | ~~KIS Developers 우선~~ (취소) | Toss API 실전 확보로 무의미 |
| 2026-07-10 | **Toss Open API v1.2.2 전격 채택** | 사용자 API 키 발급 완료 + KR/US 통합 + 조건주문 SINGLE/OCO/OTO 표준 지원 + 프로젝트 명칭 정합 |
| 2026-07-10 | Paper 어댑터 Phase 1 필수 | 실 자본 투입 전 계약 통과 확보 |
| 2026-07-10 | Phase 2 소액 상한 10만 원 하드코딩 | 초기 실전 리스크 캡 |
| 2026-07-10 | Toss REST 폴링 채택 (WebSocket 없음) | `MARKET_DATA` 10/s 여유로 5종목 200ms 폴링 가능 |
| 2026-07-10 | Phase 3 Super Signal 실행은 조건주문(OCO) | 익절+손절 원자 세팅 → 인간 개입 제거 |

---

## 13. 다음 액션 (사용자 승인 대기)

**Claude 요청**:
1. **본 로드맵 (Toss 전환 반영) 승인 여부** — 수정/조정할 축(Pivot)이 있는지
2. **`.env` 실 값 저장** — `TOSS_CLIENT_ID` · `TOSS_CLIENT_SECRET` (수동, Claude 직접 접근 금지)
3. **허용 IP 등록 확인** — 서버 배포 IP 를 WTS 허용 IP 목록에 등록 완료 여부
4. **Phase 1 착수 시점** — OMI 인터페이스 + Paper 어댑터 코드 착수 승인

---

## 참조

- **전신 문서**: `00-critic-review-2026-07-10.md`
- **후속 문서**: `02-omi-interface-spec.md` · `03-toss-openapi-integration.md`
- **관련 메모리**: `reference_toss_open_api` · `project_sector_leaders_progress` · `project_meme_stock_discovery` · `project_wen_vip_watch` · `project_activist_radar` · `reference_tossbot_deploy` · `reference_sops_age_workflow`
- **규정**: `feedback_plan_doc_protocol` · `feedback_deploy_only_when_complete` · `feedback_workflow_first_before_manual_deploy` · `feedback_partner_accountability` · `feedback_keep_alternatives_alongside`
- **Toss 개발자 사이트**: https://developers.tossinvest.com/docs · https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
