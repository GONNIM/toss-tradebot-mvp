# 📐 Order Manager Interface (OMI) — 상세 스펙

**작성일**: 2026-07-10
**작성 근거**: `01-track-c-roadmap.md` Section 2 (Broker Adapter Pattern) · Phase 1 착수 사전 문서
**상태**: 🟢 **v2 · 2026-07-10 KIS→Toss 전격 전환 반영**
**범위**: Order Manager 인터페이스, 데이터 모델, 예외 계층, Adapter 구현 계약, Signal Router 통합 규약

---

## 0. 스펙 요약

- **언어/스타일**: Python 3.11+, `dataclass` (프로젝트 기존 컨벤션 · Pydantic 사용 안 함)
- **패키지 경로**: `backend/execution/`
- **인터페이스**: `abc.ABC` 기반 `OrderManager` 추상 클래스
- **어댑터**: `PaperAdapter` (Phase 1) · `TossAdapter` (Phase 2)
- **동기 vs 비동기**: **동기(blocking) 기본**. 프로젝트 기존 discovery 서브패키지가 동기 기반이며, APScheduler `BlockingScheduler` 워커 스레드 위에서 동작. Toss API 는 REST 전용이라 asyncio 불필요.

---

## 1. 설계 원칙

1. **브로커 중립**: 시그널 엔진과 Signal Router는 OMI만 참조하며, 어떤 어댑터가 뒤에 연결되었는지 알 필요 없다.
2. **주문 idempotency 필수**: 클라이언트에서 `order_uuid`를 발급, 중복 재시도 시 어댑터가 dedup.
3. **fail-safe 우선**: 어댑터 예외는 반드시 표준 예외 계층으로 정규화. 알 수 없는 예외는 `OrderExecutionError` 로 감싸 상위로.
4. **감사 로그 필수**: 모든 주문 시도(성공/실패/취소)는 `order_audit` 테이블에 기록.
5. **테스트 가능성**: 모든 어댑터는 동일한 contract test 스위트를 통과해야 한다.
6. **Kill Switch 존중**: Order Manager는 매 주문 전 Kill Switch 상태를 확인, 발동 시 즉시 거부.
7. **Read-only 조회는 부작용 없음**: `get_balance` / `get_position` / `get_order_status`는 감사 로그를 남기지 않는다.

---

## 2. Enum 정의

```python
# backend/execution/models.py
from enum import Enum


class BrokerKind(str, Enum):
    PAPER = "paper"            # 시뮬 어댑터 (Phase 1)
    TOSS = "toss"              # Toss Open API (Phase 2~)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"          # 시장가
    LIMIT = "limit"            # 지정가
    # Phase 4+ 확장 여지: STOP, STOP_LIMIT, IOC, FOK


class OrderStatus(str, Enum):
    PENDING = "pending"        # 접수 대기 (idempotency 큐)
    ACCEPTED = "accepted"      # 브로커 접수 완료
    PARTIAL_FILL = "partial"   # 부분 체결
    FILLED = "filled"          # 전량 체결
    CANCELED = "canceled"      # 취소됨
    REJECTED = "rejected"      # 브로커 거부
    ERROR = "error"            # 시스템 에러 (통신·서버·미정)
    KILLED = "killed"          # Kill Switch 발동으로 차단


class MarketState(str, Enum):
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    HALT = "halt"              # 거래 정지
```

---

## 3. 데이터 모델 (dataclass)

```python
# backend/execution/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class OrderRequest:
    """시그널 엔진 → Signal Router → OrderManager 입력."""
    ticker: str                          # 종목코드 (한국: 6자리, 미국: 심볼)
    side: OrderSide
    order_type: OrderType
    qty: int                             # 정수(주). 한국 주식은 소수점 없음.
    price: Optional[float] = None        # LIMIT 필수 · MARKET 무시
    # === 메타 ===
    order_uuid: str = field(default_factory=lambda: str(uuid4()))
    signal_source: str = "unknown"       # meme_watch | vip_watch | activist_radar | sector_leaders | super_signal
    signal_id: Optional[str] = None      # 원천 시그널 ID (감사 추적용)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Fill:
    """개별 체결 조각."""
    price: float
    qty: int
    executed_at: datetime
    fee: float = 0.0                     # 수수료 (원 · 실 발생분)


@dataclass
class OrderResult:
    """OrderManager 반환 · 감사 로그 저장 대상."""
    order_uuid: str
    broker_order_id: Optional[str]       # 브로커측 주문 ID (Paper 어댑터는 None 허용)
    status: OrderStatus
    fills: list[Fill] = field(default_factory=list)
    avg_fill_price: Optional[float] = None
    filled_qty: int = 0
    remaining_qty: int = 0
    error_code: Optional[str] = None     # 브로커 원본 코드
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    raw_response: Optional[dict] = None  # 브로커 원본 응답 (디버깅용 · 감사에 dump)


@dataclass(frozen=True)
class Position:
    """종목별 보유 포지션 스냅샷."""
    ticker: str
    qty: int
    avg_price: float
    current_price: float
    unrealized_pnl: float                # 원. 미실현 손익
    unrealized_pnl_pct: float            # fraction (0.05 = +5%)


@dataclass(frozen=True)
class Balance:
    """계좌 잔고 스냅샷."""
    cash: float                          # 주문 가능 현금
    total_equity: float                  # 총 평가금액 (현금 + 포지션 평가)
    positions: list[Position] = field(default_factory=list)


@dataclass(frozen=True)
class MarketInfo:
    """시장 상태 조회."""
    ticker: str
    state: MarketState
    last_price: Optional[float]
    checked_at: datetime
```

---

## 4. 예외 계층

```python
# backend/execution/exceptions.py

class ExecutionError(Exception):
    """OMI 최상위 예외."""


class OrderRejected(ExecutionError):
    """브로커가 명시적으로 거부한 주문 (사유 있음)."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class InsufficientBalance(OrderRejected):
    """잔고 부족."""


class MarketClosed(OrderRejected):
    """시장 외 시간 주문 시도."""


class RateLimitExceeded(ExecutionError):
    """브로커 API rate limit. 재시도 정책 적용 대상."""


class BrokerCommunicationError(ExecutionError):
    """네트워크·타임아웃·5xx. 재시도 대상."""


class KillSwitchActive(ExecutionError):
    """Kill Switch 발동 상태에서 신규 주문 시도."""


class RiskBudgetViolation(ExecutionError):
    """리스크 예산 룰 위반 (종목당 상한·일일 손실 캡 등)."""


class OrderNotFound(ExecutionError):
    """존재하지 않는 order_uuid / broker_order_id 조회 시도."""


class DuplicateOrderError(ExecutionError):
    """동일 order_uuid 중복 제출 (idempotency 위반)."""
```

**정규화 규칙**: 어댑터는 브로커 원본 예외를 반드시 위 계층 중 하나로 감싸야 한다. 알 수 없는 상황은 `ExecutionError` 로 감싸며, `raw_response`를 첨부한다.

---

## 5. OrderManager 추상 클래스

```python
# backend/execution/order_manager.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import (
    Balance,
    BrokerKind,
    MarketInfo,
    OrderRequest,
    OrderResult,
    Position,
)


class OrderManager(ABC):
    """모든 브로커 어댑터가 준수해야 하는 인터페이스."""

    broker_kind: BrokerKind                # 클래스 속성 · 구현체에서 오버라이드

    # ─── 주문 실행 ──────────────────────────────
    @abstractmethod
    def submit_order(self, req: OrderRequest) -> OrderResult:
        """
        주문 제출. 시장가/지정가 공통.

        - idempotency: 같은 `req.order_uuid` 로 재호출 시 이전 결과 반환 (신규 주문 X).
        - 실패 시 예외 (§4) 발생 또는 status=REJECTED/ERROR 반환.
        - Kill Switch 발동 상태이면 KillSwitchActive 예외.
        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """미체결 주문 취소. 이미 체결/취소된 경우 False 반환."""

    # ─── 조회 (부작용 없음, 감사 로그 없음) ─────
    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """단일 주문 현재 상태 조회."""

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]:
        """단일 종목 포지션. 보유 0 이면 None."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """계좌 잔고 스냅샷 (현금 + 전 포지션 평가)."""

    @abstractmethod
    def get_market_info(self, ticker: str) -> MarketInfo:
        """시장 상태 + 최근가 조회."""

    # ─── 라이프사이클 ──────────────────────────
    @abstractmethod
    def health_check(self) -> bool:
        """어댑터 정상 여부. Access Token 재발급 등 부작용 허용."""
```

---

## 6. Adapter 구현 계약

### 6-1. 공통 계약 (모든 어댑터)

| 요구사항 | 상세 |
|---|---|
| **idempotency** | `submit_order` 는 `order_uuid` 기반 dedup. `data/execution_idempotency.json` 또는 SQLite 로 24h 캐시. |
| **감사 로그** | `submit_order` / `cancel_order` 는 결과 즉시 `order_audit` 테이블 INSERT. |
| **예외 정규화** | §4 계층으로 감싸서 raise. 원본은 `raw_response` 첨부. |
| **Kill Switch** | `submit_order` 첫 단계에서 `KillSwitch.is_active()` 체크. |
| **rate limit** | Toss 응답 `Retry-After` 헤더 우선, 없으면 지수 백오프 (1s → 2s → 4s + jitter, 최대 3회). 실패 시 `RateLimitExceeded`. 09:00~09:10 KST 자동 감지 후 스로틀. |
| **로깅** | 모든 요청/응답을 `EXECUTION_LOG_LEVEL` 이상에서 기록 (민감 정보 마스킹). |

### 6-2. PaperAdapter (Phase 1)

- **시세**: 실 Toss API 시세 위임 (`TossAdapter.get_market_info`). 초기엔 mock 가능.
- **체결 시뮬**:
  - `MARKET` → 현재가로 즉시 fill (fee = 시장가 × qty × 0.00015 · Toss `GET /api/v1/commissions` 실측 후 보정)
  - `LIMIT` → 다음 tick 시세와 비교, 매수/매도 방향 매칭 시 fill. 미매칭이면 pending 유지.
- **잔고**: `data/paper_balance.json` 로컬 파일. 초기 자본 `PAPER_INITIAL_CASH=10000000` (기본 1000만 원).
- **broker_order_id**: `paper-{yyyymmddhhmmss}-{seq}` 형식.

### 6-3. TossAdapter (Phase 2 · 실전 어댑터)

- **인증**: `POST /oauth2/token` (grant_type=client_credentials) 으로 Access Token 발급. `TOSS_TOKEN_CACHE_PATH` 캐시, **만료 5분 전 pre-emptive refresh**.
- **필수 헤더**: `Authorization: Bearer {token}` + `X-Tossinvest-Account: {TOSS_ACCOUNT_SEQ}`
- **주문 API**: `POST /api/v1/orders` (단일 엔드포인트 · KR/US 통합)
  - Body 필드: `clientOrderId` · `symbol` · `side`(BUY/SELL) · `orderType`(LIMIT/MARKET) · `timeInForce`(DAY/CLS) · `quantity` · `price` · `confirmHighValueOrder`
  - **idempotency**: `clientOrderId` 10분 유효 · 36자 이내 · `[a-zA-Z0-9_-]`. OMI 의 `order_uuid` 를 프리픽스 붙여 사용 (`ttb-{uuid8}`)
- **정정/취소**: `POST /api/v1/orders/{orderId}/modify` · `POST /api/v1/orders/{orderId}/cancel`
- **조건주문** (Phase 3 Super Signal 실행): `POST /api/v1/conditional-orders` (SINGLE/OCO/OTO)
- **rate limit**: `ORDER` 6/s · **09:00~09:10 KST 는 3/s**. 클라이언트 leaky bucket 필수. 429 시 `Retry-After` 헤더 준수 + 지수 백오프.
- **시장 시간 게이팅**: `GET /api/v1/market-calendar/KR` · `/US` 로 정규장/애프터 판정. `422 order-hours-closed` → `MarketClosed` 예외.
- **에러 매핑** (03-toss-openapi-integration.md §7-2 상세):
  - `422 insufficient-buying-power` / `insufficient-sellable-quantity` → `InsufficientBalance`
  - `422 order-hours-closed` → `MarketClosed`
  - `422 idempotency-key-conflict` → `DuplicateOrderError`
  - `429 *rate-limit-exceeded` → `RateLimitExceeded`
  - `409 already-*` → `OrderRejected` (상태 조회로 확정)
  - `401 invalid-token`/`expired-token` → **자동 토큰 재발급 후 재시도 (예외 X)**
  - `403 forbidden` / `edge-blocked` → `ExecutionError` (허용 IP 미등록 등 · Kill Switch 후보)
  - `5xx` → `BrokerCommunicationError`
- **감사 로그**: `error.requestId` (= `X-Request-Id` 헤더) 필수 기록.

---

## 7. Signal Router 통합 규약

```python
# backend/execution/signal_router.py

@dataclass(frozen=True)
class SignalEvent:
    """시그널 엔진 → Router 입력. 시그널 서브패키지가 정의."""
    ticker: str
    action: str                          # "buy" | "sell" | "hold"
    strength: int                        # 0~100 (시그널 강도)
    source: str                          # meme_watch | vip_watch | activist_radar | sector_leaders | super_signal
    signal_id: str
    metadata: dict = field(default_factory=dict)


class SignalRouter:
    def __init__(self, order_manager: OrderManager, risk_budget: RiskBudget, kill_switch: KillSwitch): ...

    def route(self, event: SignalEvent) -> Optional[OrderResult]:
        """
        1. EXECUTION_ENABLED=false → 즉시 return None (기존 알림 흐름만).
        2. Kill Switch 발동 → 로그·알림 후 return None.
        3. Risk Budget 통과 여부 확인 → 실패 시 로그·알림 후 return None.
        4. SignalEvent → OrderRequest 변환 (강도 → 수량 매핑 등).
        5. order_manager.submit_order(req) 호출.
        6. 결과 감사 로그 + 텔레그램 요약 알림 (별건, 기존 알림과 별도 태그).
        """
```

**중요**: 기존 시그널 엔진(meme_watch, vip_watch, activist_radar 등)은 **텔레그램 알림과 병행**해서 `SignalRouter.route()`를 호출한다. `EXECUTION_ENABLED=false` 상태에서는 완전 무영향 (return None). 즉, 회귀 위험 zero.

---

## 8. Kill Switch / Risk Budget 상호작용

### 8-1. Kill Switch

```python
# backend/execution/kill_switch.py
class KillSwitch:
    def is_active(self) -> bool: ...
    def activate(self, reason: str) -> None: ...       # 자동/수동 공통
    def deactivate(self, actor: str) -> None: ...      # 수동 해제만
    def status(self) -> KillSwitchState: ...           # active + reason + activated_at
```

**자동 발동 트리거** (백그라운드 워커가 매 tick 감지):
- 일일 누적 손실 > `EXECUTION_DAILY_LOSS_LIMIT`
- 어댑터 `health_check()` 3연속 실패
- API 에러율 > 20% (60s window)
- 브로커 예외 `RateLimitExceeded` 5회 연속

**해제 요건**: 수동만 허용 (`DELETE /api/v1/execution/kill-switch`). 자동 해제 없음.

### 8-2. Risk Budget

```python
# backend/execution/risk_budget.py
class RiskBudget:
    def check(self, req: OrderRequest, balance: Balance) -> RiskCheckResult:
        """
        - 종목당 상한: 현 포지션 + 신규 주문액 <= total_equity * PER_TICKER_MAX_PCT
        - 종목 Max DD: 현 포지션 unrealized_pnl_pct <= TICKER_DD_LIMIT
        - 매수 진입 차단: 일일 손실 캡 70% 초과 시
        """
```

Phase 3에서 Kelly Criterion, Vol Targeting 확장 예정. Phase 1은 단순 상한만.

---

## 9. 감사 로그 스키마

```sql
-- backend/data/tradebot.db · 신규 테이블
CREATE TABLE IF NOT EXISTS order_audit (
    order_uuid TEXT PRIMARY KEY,
    broker_kind TEXT NOT NULL,          -- paper | toss
    broker_order_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                 -- buy | sell
    order_type TEXT NOT NULL,           -- market | limit
    qty INTEGER NOT NULL,
    price REAL,
    signal_source TEXT,                 -- meme_watch | vip_watch | ...
    signal_id TEXT,
    status TEXT NOT NULL,               -- 최종 상태
    filled_qty INTEGER NOT NULL DEFAULT 0,
    avg_fill_price REAL,
    total_fee REAL NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    submitted_at TEXT,                  -- ISO8601 UTC
    completed_at TEXT,
    raw_response TEXT,                  -- JSON dump (디버깅)
    created_at TEXT NOT NULL            -- ISO8601 UTC (INSERT 시각)
);

CREATE INDEX IF NOT EXISTS idx_order_audit_ticker ON order_audit(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_audit_signal ON order_audit(signal_source, signal_id);
CREATE INDEX IF NOT EXISTS idx_order_audit_broker ON order_audit(broker_kind, created_at DESC);
```

---

## 10. Contract Test 요구사항

모든 어댑터는 `backend/tests/execution/test_contract.py` 스위트를 통과해야 한다.

| 테스트 | 검증 |
|---|---|
| `test_submit_market_buy_and_fill` | 시장가 매수 → status=FILLED, filled_qty=qty |
| `test_submit_limit_buy_pending` | 지정가 매수 (시장가 미매칭) → status=ACCEPTED, remaining=qty |
| `test_duplicate_order_idempotency` | 같은 order_uuid 재전송 → 이전 결과 반환, 신규 주문 X |
| `test_insufficient_balance` | 잔고 초과 주문 → InsufficientBalance 예외 |
| `test_cancel_pending_order` | 미체결 주문 취소 → 성공, status=CANCELED |
| `test_cancel_filled_order_returns_false` | 이미 체결된 주문 취소 → False |
| `test_get_balance_returns_positions` | 잔고에 모든 활성 포지션 포함 |
| `test_market_closed_rejected` | 정규장 외 주문 → MarketClosed 예외 (Toss `422 order-hours-closed`) |
| `test_kill_switch_blocks_new_orders` | Kill Switch 발동 상태 → KillSwitchActive 예외 |
| `test_health_check_ok` | 정상 상태에서 True |

Paper 어댑터는 mock 시세로 전부 통과 가능. Toss 어댑터는 실 API 키 필요 (CI에서 skip 마킹 · 로컬 검증만).

---

## 11. 파일 배치

```
backend/execution/
├── __init__.py                # OrderManager, OrderRequest 등 재export
├── models.py                  # §2 §3 데이터 모델 전부
├── exceptions.py              # §4 예외 계층
├── order_manager.py           # §5 ABC
├── signal_router.py           # §7 Router
├── risk_budget.py             # §8-2 RiskBudget
├── kill_switch.py             # §8-1 KillSwitch
├── audit.py                   # §9 order_audit CRUD
├── idempotency.py             # order_uuid 24h 캐시
└── brokers/
    ├── __init__.py
    ├── paper_adapter.py       # PaperAdapter (Phase 1)
    └── toss_adapter.py        # TossAdapter (Phase 2 실전 어댑터)

backend/tests/execution/
├── test_contract.py           # 어댑터 공통 계약 스위트
├── test_paper_adapter.py      # Paper 전용
├── test_signal_router.py      # Router 로직
├── test_risk_budget.py        # 리스크 예산 룰
└── test_kill_switch.py        # Kill Switch 동작
```

---

## 12. 확정 결정 (2026-07-10 사용자 승인 · 자유도 리뷰 반영)

**설계 원칙**: `feedback_configurability_first` — 하드코딩 default 대신 실시간 소스 동기화 + UI 편집 override 우선.

| # | 항목 | 결정 |
|---|---|---|
| 1 | Paper 초기 자본 | **Toss API 실계좌 sync (buying-power + holdings) → `data/paper_balance.json` 저장.** 사용자 UI에서 `재싱크` 버튼으로 재동기화. Toss API 실패 시 `PAPER_INITIAL_CASH` env fallback (기본 10_000_000). 자동 주기 sync 없음. |
| 2 | 감사 로그 DB | 기존 `backend/data/tradebot.db` 확장 · `order_audit` 테이블 신설 |
| 3 | Signal Router 호출 시점 | 시그널 감지 직후 (텔레그램 알림과 병행 · 동기 호출) |
| 4 | Kill Switch 알림 | 기존 텔레그램 봇에 `🚨 URGENT` 태그로 발송 (프로파일 무관) |
| 5 | 조건주문 활용 범위 (Phase 3) | Super Signal 매수 진입 시 OCO 로 익절+손절 원자 세팅 |
| 6 | **파라미터 override 계층** | 3층: 종목별 > 시그널별 > global > env fallback. `backend/data/execution_params.json` 파일 기반 · hot reload · UI 편집. |
| 7 | **`/execution/params` UI 스코프** | **Phase 1**: 익절(TP) · 손절(SL) · 트레일링(arm/giveback) 3개 임계값 × 3개 탭(global · 종목별 · 시그널별). 리스크 예산(per_ticker_max_pct · daily_loss_limit · ticker_dd_limit)은 Phase 3에서 UI 노출 (Phase 1은 JSON 직접 편집만). |

---

## 참조

- 전신 문서: `01-track-c-roadmap.md`
- 후속 문서: `03-toss-openapi-integration.md` (Toss API 스펙 확정 · Phase 2 실전 진입 프로토콜)
- 프로젝트 컨벤션: `backend/discovery/activist/` · `backend/discovery/vip/` (dataclass · 파일 기반 상태)
- 규정: `feedback_deploy_only_when_complete` · `feedback_partner_accountability` (Toss 에러 code + requestId 로 근본 해결까지 추적)
- 프로젝트 메모리: `reference_toss_open_api`
