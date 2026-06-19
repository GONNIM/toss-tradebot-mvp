# 03 — PRD v1 (Product Requirements Document)

**작성일**: 2026-06-18
**상태**: **골격 v0.1** (API 무관 영역 우선 작성 / Toss API 오픈 후 v1.0으로 갱신)
**선행 문서**:
- `01-research-foundation.md` — 사상 계보·저빈도 기법
- `02-strategy-decision.md` — 35개 결정 매트릭스 + 1 보류
- `docs/analysis/toss-api-survey.md` v2 — Toss API 가용성 조사
**다음 단계**:
- API 오픈 후 콘솔 검증 6항목 → 본 문서 v1.0 확정
- 설계 단계 (`docs/architecture/`)

---

## 0. 본 문서의 위치

본 문서는 02 결정 사항을 **시스템 요구사항**으로 정형화. 코드 구현 전 마지막 정합성 점검 단계.

**v0.1 (현재) 범위**: API 무관 영역 — 아키텍처, 기술 스택, 디렉터리, 모듈 명세, DB 스키마, 배포 토폴로지
**v1.0 (예정)**: 콘솔 검증 6항목 + 결정 26 환전 정책 확정 후 — 운영 시나리오, SLA, 검수 기준 추가

---

## 1. 시스템 아키텍처 — 3 모듈 + 2 인프라

### 1.1 토폴로지 도식

```
                  ┌──────────────────────────────────┐
                  │      사용자 (운영자 = 동업자)        │
                  │  ㆍ토스 WTS (수동 매수/매도)         │
                  │  ㆍ브라우저 → Next.js (Vercel)       │
                  │  ㆍTelegram (알림 수신)              │
                  │  ㆍ터미널 (/moonshot CLI)            │
                  └────────────▲─────────────────────┘
                               │
                ┌──────────────┼─────────────┐
                │              │             │
        ┌───────▼────────┐  ┌──▼─────────┐  ┌▼─────────┐
        │  Vercel (Edge) │  │ Telegram   │  │ Local Mac │
        │  Next.js 14    │  │ Bot API    │  │ /moonshot │
        │  ㆍ대시보드     │  │            │  │ Python CLI│
        │  ㆍCrazy Picks │  │            │  │           │
        │  ㆍMoonshot    │  │            │  │           │
        │  ㆍ보유/설정    │  │            │  │           │
        └───────▲────────┘  └──▲─────────┘  └▲──────────┘
                │              │             │
                │ HTTPS         │             │
                │ (API Key)     │             │
                │              │             │
        ┌───────▼──────────────┴─────────────┴──────┐
        │  Backend VPS (orionhunter7 같은 24/7 서버)  │
        │  ┌─────────────────────────────────────┐  │
        │  │ Python 3.12 — 5 sub-systems         │  │
        │  │   ① 자동매매 엔진 (live_loop)        │  │
        │  │     - 60s polling                    │  │
        │  │     - 매수/매도 자동 실행            │  │
        │  │   ② Crazy Picks (cron 06:30 KST)    │  │
        │  │   ③ Moonshot Picks (cron 16:50 KST) │  │
        │  │   ④ /moonshot CLI (사용자 호출)      │  │
        │  │   ⑤ FastAPI 게이트웨이              │  │
        │  │     - Next.js에 REST 노출           │  │
        │  └─────────────────────────────────────┘  │
        │              │                             │
        │              ▼                             │
        │  ┌─────────────────────────────────────┐  │
        │  │  SQLite DB (또는 Postgres)          │  │
        │  └─────────────────────────────────────┘  │
        └──────────────▲──────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │      외부 데이터·API          │
        │   ㆍToss Open API (시세·주문) │
        │   ㆍClaude Haiku 4.5 (LLM)   │
        │   ㆍReddit PRAW (sentiment)  │
        │   ㆍFINRA (공매도, 옵션)     │
        └──────────────────────────────┘
```

### 1.2 3 모듈 (02 §1 매핑)

| 모듈 | 자금 | 운영 주기 | 사용자 액션 |
|---|---|---|---|
| **① 자동매매 코어** | 1,500만원 | 60초 polling + 봉 발생 시 | 모니터링만 |
| **② Crazy Picks** | 0원 (정보) | 매일 06:30 KST | Next.js 뷰 / Telegram 확인 |
| **③ Moonshot Picks** | 100만원 | 매일 16:50/17:00 KST + polling | **토스 WTS 수동 매수/매도** |

### 1.3 2 인프라

| 인프라 | 호스팅 | 비용 | 책임 |
|---|---|---|---|
| **Backend + Frontend (통합)** | **optimus8.cafe24.com** | (기존 cafe24 비용) | Python 24/7 + Node.js + DB + cron + FastAPI + Next.js (PM2) |
| Reverse Proxy | Nginx (optimus8 단일 서버) | $0 | Backend·Frontend 단일 도메인 라우팅 + SSL |
| CI/CD | **GitHub Actions** | $0 | git push → SSH deploy 자동화 |

→ **단일 서버 통합 배포 (사용자 결정 2026-06-19, 결정 42)**. Vercel 미사용 — 데이터 주권 + 외부 의존성 ↓.

---

## 2. 기술 스택

### 2.1 Backend (Python)

| 영역 | 선택 | 사유 |
|---|---|---|
| 언어 | **Python 3.12+** | upbit 패턴 일관 + 데이터/금융 라이브러리 풍부 |
| Web 프레임워크 | **FastAPI** | async, 자동 OpenAPI, TypeScript-친화 |
| 스케줄러 | **APScheduler** | cron + interval, Python 네이티브 |
| DB ORM | **SQLAlchemy 2.0** | 또는 `sqlite3` 직접 (간단 MVP) |
| HTTP 클라이언트 | **httpx** | async 지원, requests 호환 |
| LLM SDK | **anthropic** (공식) | Claude Haiku 4.5 |
| CLI | **click + rich** | /moonshot CLI 진입점 (결정 36) |
| 데이터 처리 | **pandas + numpy** | upbit 패턴 |
| 차트 (백엔드) | — (Frontend에서) | — |

### 2.2 Frontend (Next.js)

| 영역 | 선택 | 사유 |
|---|---|---|
| 프레임워크 | **Next.js 14+** (App Router) | Vercel 최적화, React 19 |
| 언어 | **TypeScript** | 타입 안전, FastAPI OpenAPI 연동 |
| 스타일 | **Tailwind CSS 4** | 빠른 개발 |
| 컴포넌트 | **shadcn/ui** (Radix UI 기반) | 무료, copy-paste, 커스터마이징 자유 |
| 데이터 페치 | **TanStack Query (React Query)** | 캐싱, 자동 refetch |
| 차트 (가격/캔들) | **TradingView Lightweight Charts** (35KB) | 결정 39 — 금융 차트 표준, 매우 가벼움 |
| 차트 (통계·자산) | **Recharts** (~90KB) | 결정 39 — shadcn/ui 어울림, 라인·바·파이 |
| 폼 | **React Hook Form + Zod** | 검증 |
| 인증 | **NextAuth.js (Google Provider)** + Gmail 화이트리스트 + 자체 API Key | 결정 38 — 본인 Gmail 1개만 허용 |

### 2.3 DB ✅ 결정 37 확정 (2026-06-18)

| 단계 | DB | 사유 |
|---|---|---|
| **MVP (1~3개월)** | **SQLite** ⭐ | 단순, 백업 쉬움, upbit 패턴 일관, 단일 파일 |
| **운영 안정 후** | **Supabase Postgres** | 무료 500MB Tier, Vercel 친화, 자동 백업 |

**추상화**: `backend/services/db.py`에서 SQLAlchemy 2.0 ORM 사용. DB 전환 시 connection string만 변경.

```python
# MVP
DATABASE_URL = "sqlite:///./data/tradebot.db"

# 운영 안정 후
DATABASE_URL = "postgresql+asyncpg://..."  # Supabase Pooler 권고
```

### 2.4 인프라·DevOps (결정 42·43 확정 2026-06-19)

| 영역 | 선택 |
|---|---|
| **통합 호스팅** | **optimus8.cafe24.com** (Backend + Frontend 단일 서버) |
| Backend 프로세스 | Python 3.12 + FastAPI + APScheduler (systemd `tradebot-backend.service`) |
| Frontend 프로세스 | Next.js 14 production server + **PM2** (`pm2 start tradebot-frontend`) |
| Reverse Proxy | **Nginx** — `/api/*` → FastAPI :8000, `/*` → Next.js :3000 |
| SSL | Let's Encrypt + certbot (자동 갱신) 또는 cafe24 무료 SSL |
| **CI/CD** | **GitHub Actions** `.github/workflows/deploy.yml` — push to main → SSH deploy |
| SSH 인증 | **키 기반** (GitHub Secrets에 private key, 비밀번호 인증 비활성화) |
| 시크릿 관리 | 서버 `.env` (chmod 600) — frontend·backend 동일 서버라 통합 |
| 모니터링 | Telegram 알림 (결정 43, upbit 패턴) |
| 백업 | `scripts/backup.sh` (upbit 패턴 차용) |
| Git | GitHub |
| 배포 흐름 | git push main → GitHub Actions → SSH → `git pull && npm install && npm run build && pm2 restart` |

---

## 3. 디렉터리 구조

```
toss-tradebot-mvp/
├── README.md
├── CLAUDE.md
├── .gitignore
├── .claude/
│   └── context/project-rules.md
│
├── backend/                            ⭐ Python 백엔드 (별도 패키지)
│   ├── pyproject.toml                  # console_scripts: moonshot
│   ├── .env                            # 자격증명 (600 권한)
│   ├── core/
│   │   ├── strategy_engine.py          # 봉 처리 메인
│   │   ├── strategy_incremental.py     # 매수 트리거 (52주 -10/-20/-30%)
│   │   ├── position_state.py
│   │   ├── indicator_state.py
│   │   ├── reconciler.py               # Toss 주문 reconcile
│   │   └── filters/                    # 매수/매도 필터
│   ├── engine/
│   │   ├── live_loop.py                # 60초 polling 메인 루프
│   │   ├── engine_manager.py           # 사용자별 엔진 lifecycle
│   │   └── candle_cache.py             # 52주 고가 일봉 캐싱 (결정 23)
│   ├── discovery/                      ⭐ 신규 모듈
│   │   ├── crazy_picks.py              # 매일 06:30 KST cron
│   │   ├── moonshot_picks.py           # 매일 16:50 KST cron
│   │   ├── scoring.py                  # 5/6 인자 가중 합
│   │   ├── catalysts.py                # 어닝/FDA/M&A 캘린더
│   │   └── sentiment.py                # Reddit PRAW
│   ├── services/
│   │   ├── toss_api.py                 # OAuth + REST 래퍼
│   │   ├── error_messages.py           # upbit 패턴 차용
│   │   ├── notifier.py                 # Telegram
│   │   ├── llm.py                      # Anthropic Claude Haiku
│   │   ├── db.py                       # SQLite/Postgres 추상화
│   │   └── exchange_rate.py            # 환율 (결정 26 환전 정책에 따라)
│   ├── api/                            # FastAPI (Next.js에 REST 노출)
│   │   ├── main.py
│   │   ├── routes/
│   │   │   ├── dashboard.py
│   │   │   ├── crazy.py
│   │   │   ├── moonshot.py
│   │   │   ├── positions.py
│   │   │   └── settings.py
│   │   ├── auth.py                     # API key 미들웨어
│   │   └── schemas.py                  # Pydantic
│   ├── cli/                            ⭐ /moonshot CLI 진입점
│   │   ├── __init__.py
│   │   └── moonshot.py                 # click + rich
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── scripts/                        # 운영 유틸
│   │   ├── backup.sh                   # upbit 패턴 차용
│   │   ├── rollback.sh
│   │   ├── watchdog.sh                 # journalctl tradebot stale 감지
│   │   └── server/                     # 서버 cron 스크립트
│   │       └── *.sh
│   └── data/                           # SQLite + 캔들 캐시
│       └── tradebot.db
│
├── frontend/                           ⭐ Next.js (Vercel 배포)
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                    # Landing
│   │   ├── dashboard/page.tsx          # 자동매매 대시보드
│   │   ├── crazy/page.tsx              # Crazy Picks Top 10
│   │   ├── moonshot/page.tsx           # Moonshot Picks Top 3
│   │   ├── positions/page.tsx          # 보유 종목 + 손익
│   │   ├── settings/page.tsx           # 파라미터
│   │   ├── logs/page.tsx               # 감사 로그
│   │   └── api/                        # Next.js API Routes (proxy)
│   │       └── [...]/route.ts          # FastAPI 호출 wrapper
│   ├── components/
│   │   ├── ui/                         # shadcn/ui 컴포넌트
│   │   ├── charts/                     # TradingView Lightweight Charts
│   │   ├── PickCard.tsx                # Crazy/Moonshot 공용
│   │   ├── BuyOptionsPanel.tsx         # 매수가 3 옵션 (Moonshot)
│   │   └── ...
│   ├── lib/
│   │   ├── api.ts                      # FastAPI 호출 helper
│   │   ├── auth.ts                     # NextAuth 설정
│   │   └── utils.ts
│   ├── public/
│   └── styles/
│
├── docs/                               # 본 문서들
│   ├── README.md
│   ├── analysis/
│   │   └── toss-api-survey.md
│   └── plans/PRD/
│       ├── 01-research-foundation.md
│       ├── 02-strategy-decision.md
│       └── 03-PRD-v1.md                ⭐ 본 문서
│
└── scripts/                            # 프로젝트 루트 운영 도구
    ├── server/                         # 서버 측 cron 등 (.gitignore !scripts/**/*.sh)
    └── backup.sh
```

---

## 4. 모듈 명세 — 5 sub-systems

### 4.1 ① 자동매매 엔진 (`backend/engine/live_loop.py`)

**책임**: 60초 주기로 시세 polling → 매수 트리거 평가 → Toss 주문 → 잔고 reconcile → Telegram 알림

**핵심 흐름** (결정 1·6·7·8·10·11·12 적용):
```
loop every 60s:
    for each ticker in (Satellite + SPCX):
        candle = toss_api.get_candle(ticker, '1d', count=200)  # 52주 고가 계산
        high_52w = max(candle.high for last 252)
        current = toss_api.get_price(ticker)

        drawdown = (current - high_52w) / high_52w

        # 매수 트리거 (결정 6)
        if drawdown <= -0.10 and not buy_tier_1_done:
            buy_amount = seed * 0.10 / 3   # 종목당 10%, 1/3씩
            toss_api.create_order(ticker, buy_amount, MARKET)
            telegram.send(LIVE_BUY)
        elif drawdown <= -0.20 and not buy_tier_2_done:
            ...
        elif drawdown <= -0.30 and not buy_tier_3_done:
            ...

        # 익절 트리거 (결정 8)
        if position.avg_price > 0:
            pnl_pct = (current - position.avg_price) / position.avg_price
            if pnl_pct >= 0.20:
                toss_api.create_order(ticker, position.qty, MARKET, side='SELL')
                telegram.send(LIVE_SELL)

        # 손절: 절대 없음 (결정 1·11)
```

**입출력**:
- 입력: Toss API (시세·잔고) / DB (종목 universe·포지션)
- 출력: Toss API (주문) / DB (audit·orders) / Telegram

### 4.2 ② Crazy Picks (`backend/discovery/crazy_picks.py`)

**책임**: 매일 06:30 KST에 미국 전체 종목 스캔 → 5인자 가중 → Top 10 → LLM thesis → DB → Next.js·Telegram

**핵심 흐름** (결정 14·15·16·17·20·21·22):
```
cron: 06:30 KST
  universe = filter(
    market_cap >= 1B,
    avg_volume >= 1M,
    exchange in (NYSE, NASDAQ),
    price >= $5,
    listed_days >= 60
  ) + sector_whitelist[양자 5 + 보안 8]   # 결정 21

  for ticker in universe:
    score = (
      price_momentum_score(ticker) * 0.25 +
      earnings_momentum_score(ticker) * 0.20 +
      analyst_action_score(ticker) * 0.15 +
      social_sentiment_score(ticker) * 0.20 +
      news_sentiment_score_llm(ticker) * 0.20
    )
    if ticker in sector_whitelist:
        score *= 1.10   # 결정 22 부스트

  top10 = sorted(universe, by score, desc)[:10]

  for ticker in top10:
    thesis = claude_haiku.generate(prompt={
      'why_crazy_potential': True, 'catalysts': True,
      'risks': True, 'news_summary': True
    })

  db.insert('crazy_picks', ...)
  notifier.send_telegram(top10_summary)
  nextjs_revalidate('/crazy')   # ISR 트리거

  # T+7 / T+30 perf 자동 추적 (결정 19)
  for past_pick in db.query('crazy_picks WHERE date in (T-7, T-30)'):
    past_pick.perf_1w = ...; past_pick.perf_1m = ...
```

### 4.3 ③ Moonshot Picks (`backend/discovery/moonshot_picks.py`)

**책임**: 매일 16:50 KST에 소형주·카탈리스트 스캔 → 6인자 가중 → Top 3 → 매수가 3 옵션 → DB → CLI·Next.js·Telegram

**핵심 흐름** (결정 27~36, 40 — 2026-06-18 결정 31·32·33·40 갱신 반영):
```
cron: 16:50 KST
  universe = filter(
    exchange in (NYSE, NYSE_AMERICAN, NASDAQ),  # OTC 제외
    price >= 0.10,                                # sub-penny 제외
    avg_volume >= 500_000,                        # 유동성 최소
    listed_days >= 30
  )
  # 시총 제한 거의 없음 — 페니스톡·마이크로캡 포함 모든 가능성

  for ticker in universe:
    # 9 인자 가중 (학술 검증 후 재조정 2026-06-18)
    score = (
      volatility_30d * 0.12 +
      catalyst_imminent * 0.30 +         # PEAD 학술 강함 ⬆
      short_squeeze * 0.06 +              # 사전 예측 어려움 ⬇
      social_sentiment * 0.08 +           # WSB 알파 약함 ⬇
      news_sentiment_llm * 0.12 +
      technical_breakout * 0.08 +
      gap_volume_spike * 0.12 +           # 갭 + 거래량 폭증 ⬆
      low_rebound_volume * 0.02 +
      insider_buying_cluster * 0.10       # ⭐ NEW (결정 41, F6 학술 검증)
    )

    # 위험 분류 (결정 40)
    if market_cap < 50_000_000:
        risk_level = 'HIGH'   # 페니스톡·마이크로캡
    elif market_cap < 500_000_000:
        risk_level = 'MED'    # 소형주
    else:
        risk_level = 'LOW'    # 중형주

  top10 = sorted(..., desc)[:10]
  top3 = top10[:3]

  for ticker in top3:
    current = toss_api.get_price(ticker)
    buy_price_a = current                            # 즉시 (HIGH 위험 종목엔 비권고)
    buy_price_b = current * 0.95                     # 떡락 -5% (HIGH 종목 우선 권고)
    buy_price_c = current * 1.08                     # 돌파 +8%
    target_sell = current * 2.00                     # +100%
    stop_loss = current * 0.50                       # -50%

    # LLM thesis + manipulation 위험 평가 (결정 40)
    thesis = claude_haiku.generate(
      include_manipulation_risk=True,  # paid promoter / pump & dump 신호
      risk_level=risk_level
    )
    db.insert('moonshot_picks', {
      ...,
      market_cap_category: 'MICRO' if market_cap < 50e6 else 'SMALL' if market_cap < 500e6 else 'MID',
      risk_level: risk_level,
      manipulation_risk: thesis.manipulation_risk,   # 1~5
      ...
    })

  notifier.send_telegram(top3_detail)
  nextjs_revalidate('/moonshot')

# KST 17:00 — 사용자 토스 WTS 수동 매수
# user_bought = True 설정 시 → 60s polling 시작

loop every 60s (user_bought = True):
  current = toss_api.get_price(ticker)
  if current >= target_sell:
    notifier.send_telegram(SELL_TARGET_REACHED)
  elif current <= stop_loss:
    notifier.send_telegram(STOP_LOSS_REACHED)
  elif now - pick_date >= 5 days:
    notifier.send_telegram(TIME_STOP_REACHED)
```

### 4.4 ④ /moonshot CLI (`backend/cli/moonshot.py`)

**책임**: 사용자가 터미널에서 `moonshot [command]` 실행 → 동일 DB 조회 → rich 출력

**명령어** (결정 36):
- `moonshot` — 오늘 Top 3
- `moonshot top` — Top 10
- `moonshot detail <TICKER>` — 종목 상세
- `moonshot history [N]` — 최근 N일
- `moonshot perf` — 적중률 통계
- `moonshot live` — 60초 polling
- `moonshot positions` — 보유 종목

**진입점**: `pyproject.toml` console_scripts → `pip install -e ./backend` 후 즉시 사용

### 4.5 ⑤ FastAPI 게이트웨이 (`backend/api/main.py`)

**책임**: Next.js Frontend에 REST API 노출

**주요 라우트** (예시):
```
POST /api/v1/auth/login                  → JWT 발급
GET  /api/v1/dashboard/summary           → 총 자산·일일 손익
GET  /api/v1/crazy/picks?date=...        → Crazy Picks Top 10
GET  /api/v1/moonshot/picks?date=...     → Moonshot Picks Top 3
GET  /api/v1/positions                   → 보유 종목
POST /api/v1/positions/manual            → 수동 매수 등록 (Moonshot)
GET  /api/v1/settings                    → 파라미터 조회
PUT  /api/v1/settings                    → 파라미터 수정
GET  /api/v1/logs?level=...              → 감사 로그
```

**인증**: API Key 헤더 (`X-API-Key`) — Next.js와 공유

---

## 5. 통합 DB 스키마

### 5.1 자동매매 코어 테이블 (upbit 패턴 차용 + Toss 적응)

```sql
-- 계좌·잔고
accounts (user_id, krw_balance, usd_balance, total_value, updated_at)
account_positions (user_id, ticker, qty, avg_price, currency, ...)

-- 주문·체결
orders (id, user_id, ticker, side, price, qty, state, requested_at, executed_at, ...)
audit_trades (id, ticker, type, reason, price, entry_price, ...)

-- 봉·평가
audit_buy_eval (id, ticker, bar_time, ...)
audit_sell_eval (id, ticker, bar_time, ...)
daily_candles (ticker, date, open, high, low, close, volume)   ⭐ 신규 (결정 23)

-- 운영
engine_status (user_id, is_running, last_heartbeat, ...)
logs (id, user_id, timestamp, level, message)
```

### 5.2 Discovery 테이블

```sql
crazy_picks (...)                       -- 02 §3.1.4 정의
moonshot_picks (...)                    -- 02 §3.2.2 정의
moonshot_positions (...)                ⭐ 신규 — 사용자 수동 매수 추적
```

### 5.3 보조 테이블

```sql
ticker_universe (symbol, market, category, sector, active)   -- 자동매매·Discovery 공통
notification_log (id, channel, title, body, sent_at, dedupe_key)
```

---

## 6. 외부 의존성 (확정 + TBD)

| 서비스 | 용도 | 상태 | 비용 (월) |
|---|---|---|---|
| **Toss Open API** | **자동매매 전용** (시세·잔고·주문) | ⏳ 사전 신청 완료, 오픈 대기 | 미언급 (TBD) |
| **Stooq** | **Discovery 1차** (가격·52w·거래량, 전체 미국 종목) | ✅ 무료, key 없음 | $0 |
| **Yahoo Finance** | Discovery 백업 (불안정) | ⚠️ 자주 429 | $0 |
| **Finnhub Free** | Discovery 어닝 캘린더·애널리스트 | ✅ 60/min | $0 |
| **SEC EDGAR** | Discovery Form 4 (인사이더 매수) | ✅ 무료 공식 | $0 |
| **FINRA** | Discovery 공매도 SI% | ✅ 무료 공식 | $0 |
| **PRNewswire / GlobeNewswire RSS** | Discovery 보도자료 | ✅ 무료 RSS | $0 |
| **BiopharmaWatch** | Discovery FDA Calendar | ✅ 무료 | $0 |
| **Reddit PRAW** | Discovery 소셜 sentiment | ✅ 무료 60/min | $0 |
| **Anthropic Claude Haiku 4.5** | LLM thesis (Crazy·Moonshot) | ✅ API 키 보유 (upbit .env) | $5~15 |
| **Telegram Bot API** | 알림 | ✅ upbit 자산 재활용 | $0 |
| **Backend VPS** | optimus8.cafe24.com (Backend + Frontend 통합) | ✅ (기존 cafe24 비용) | (기존) |

→ **추가 월 운영비**: 약 **$5~15 (Anthropic API만 신규)**. 다른 모든 데이터 소스 무료.

---

## 7. 데이터 흐름

### 7.1 자동매매 (실시간)

```
[60s 주기]
Toss API → backend/engine/live_loop.py → 매수 판단
   → Toss API (주문) → DB (orders) → Telegram → FastAPI → Next.js
```

### 7.2 Crazy Picks (일 1회)

```
[06:30 KST cron]
backend/discovery/crazy_picks.py
   → Toss API (시세) + Reddit + Claude
   → DB (crazy_picks) → Telegram → Next.js revalidate
```

### 7.3 Moonshot Picks (일 1회 + polling)

```
[16:50 KST cron]
backend/discovery/moonshot_picks.py
   → 카탈리스트 스캔 + Claude
   → DB (moonshot_picks) → Telegram + Next.js + CLI 동일 데이터

[17:00 KST 사용자 수동 매수]
사용자 → Toss WTS → DB (moonshot_positions.user_bought=True)

[60s polling 후]
backend/discovery/moonshot_picks.py:monitor_loop()
   → Toss API (시세) → 목표/손절/시간 체크
   → Telegram (사용자 수동 매도)
```

### 7.4 /moonshot CLI (사용자 호출)

```
사용자 터미널: $ moonshot
   → backend/cli/moonshot.py
   → DB 조회 (moonshot_picks WHERE pick_date=today)
   → rich 출력
```

---

## 8. 배포 토폴로지

### 8.1 통합 단일 서버 배포 (결정 42 확정 2026-06-19)

| 영역 | 위치 | 배포 방식 |
|---|---|---|
| Backend (Python FastAPI + cron) | **optimus8.cafe24.com** (포트 8000, systemd `tradebot-backend.service`) | GitHub Actions SSH deploy |
| Frontend (Next.js production) | **optimus8.cafe24.com** (포트 3000, PM2 `tradebot-frontend`) | GitHub Actions SSH deploy |
| Reverse Proxy (Nginx) | **optimus8.cafe24.com** (포트 80/443) | `/api/*` → Backend, `/*` → Frontend |
| DB | optimus8 동일 머신 | SQLite 파일 (또는 Postgres 마이그) |
| Telegram | API only | — |
| /moonshot CLI | 사용자 로컬 Mac + optimus8 둘 다 | `pip install -e ./backend` |

### 8.1.0 GitHub Actions Deploy Workflow (결정 42 상세)

`.github/workflows/deploy.yml`:
```yaml
name: Deploy to optimus8
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup SSH
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.DEPLOY_SSH_KEY }}
      - name: Add host fingerprint
        run: ssh-keyscan -H ${{ secrets.DEPLOY_SSH_HOST }} >> ~/.ssh/known_hosts
      - name: Deploy
        run: |
          ssh ${{ secrets.DEPLOY_SSH_USER }}@${{ secrets.DEPLOY_SSH_HOST }} << 'EOF'
            cd /home/tradebot/toss-tradebot-mvp
            git pull origin main

            # Backend
            cd backend
            source venv/bin/activate
            pip install -r requirements.txt
            sudo systemctl restart tradebot-backend

            # Frontend
            cd ../frontend
            npm install
            npm run build
            pm2 restart tradebot-frontend
          EOF
```

**보안 가이드** (글로벌 가드레일 §1 준수):
- SSH 비밀번호 인증 비활성화 (`PasswordAuthentication no` in `/etc/ssh/sshd_config`)
- root SSH 비활성화 (`PermitRootLogin no`)
- 비root 운영 계정 `tradebot` 신설 + sudo (선택)
- GitHub Secrets만 자격증명 보유 — workflow yml에 평문 금지
- SSH 키는 deploy 전용으로 생성 (사용자 개인 키와 분리)

#### 8.1.1 서버 보안 권고 (2026-06-19 가드레일 발동 후 권고)

- **자격증명**: 평문 코드·문서·git 절대 노출 금지 (글로벌 CLAUDE.md §1)
- **SSH 접근**:
  - root 직접 로그인 비활성화 권고 (`PermitRootLogin no` in `/etc/ssh/sshd_config`)
  - 키 기반 인증 전환 (비밀번호 인증 비활성화)
  - 비root 운영 계정 (예: `tradebot`) + sudo 권한 부여
- **방화벽**:
  - 80/443 (HTTPS) 외 모든 포트 차단
  - SSH는 비표준 포트 + fail2ban 권고
- **HTTPS**:
  - cafe24 무료 SSL 또는 Let's Encrypt
  - Backend FastAPI는 nginx reverse proxy 뒤에 위치 (cafe24 nginx 또는 caddy)
- **자격증명 회전**:
  - 모든 비밀번호 정기 변경 (최소 90일)
  - `.env` 파일 chmod 600
  - 글로벌 가드레일 §1.4 — Vault·Secrets Manager 권고 (장기)

### 8.2 환경 변수 (시크릿)

#### Backend `.env` (chmod 600)
```
# Toss API
TOSS_CLIENT_ID=c_...
TOSS_CLIENT_SECRET=s_...
TOSS_ACCOUNT_ID=...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Reddit
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...

# Next.js 통신용
INTERNAL_API_KEY=...

# DB
DATABASE_URL=sqlite:///./data/tradebot.db
```

#### 통합 .env (optimus8 서버, Frontend + Backend 단일 파일) — chmod 600

```
# Backend — Toss API
TOSS_CLIENT_ID=c_...
TOSS_CLIENT_SECRET=s_...
TOSS_ACCOUNT_ID=...

# Backend — Anthropic / OpenAI
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Backend — Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Backend — Reddit
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...

# Backend — DB
DATABASE_URL=sqlite:///./data/tradebot.db

# Frontend — NextAuth (결정 38)
NEXTAUTH_SECRET=...
NEXTAUTH_URL=https://optimus8.cafe24.com   # 또는 사용자 제공 서브도메인

# Frontend — Google OAuth (결정 38)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Frontend — 화이트리스트 (결정 38)
ALLOWED_EMAIL=suauncle@gmail.com   # 사용자 확정

# Frontend ↔ Backend 통신
NEXT_PUBLIC_API_BASE_URL=https://optimus8.cafe24.com   # nginx /api/* 라우팅
INTERNAL_API_KEY=...
```

#### GitHub Secrets (CI/CD용, 결정 42)

```
DEPLOY_SSH_KEY=...           # 서버 ssh private key (비root 운영 계정)
DEPLOY_SSH_HOST=optimus8.cafe24.com
DEPLOY_SSH_USER=tradebot     # 비root 운영 계정 권고
```

**NextAuth signIn 콜백** (결정 38):
```typescript
// frontend/app/api/auth/[...nextauth]/route.ts
callbacks: {
  signIn: async ({ user }) =>
    user.email === process.env.ALLOWED_EMAIL,  // suauncle@gmail.com
}
```

→ 외부인이 Google 로그인해도 `signIn` 콜백에서 false 반환 → 접근 차단.

→ 가드레일: 시크릿은 절대 Git 커밋 X. `.env` `.gitignore` 포함.

### 8.3 도메인·CORS (결정 42 확정 2026-06-19)

- **단일 도메인 (Backend + Frontend) 확정 2026-06-19**: `https://optimus8.cafe24.com`
  - cafe24 호스팅 기본 도메인 그대로 사용 (이미 서브도메인 구조)
  - 추가 서브도메인 셋업 X — 단순
  - Frontend (Next.js): `https://optimus8.cafe24.com/` (루트)
  - Backend (FastAPI): `https://optimus8.cafe24.com/api/v1/*`
  - 둘 다 Nginx reverse proxy 뒤
- **CORS**: 단일 origin이라 사실상 same-origin → CORS 설정 단순. 단 `/api/auth/callback/google` 등 NextAuth 콜백 도메인 등록 필요 (Google Cloud Console)

---

## 9. 검수 기준 (Acceptance Criteria)

PRD v1.0 확정 시 추가. 현재 v0.1엔 골격만:

- 자동매매: 첫 매수 → 익절 1 사이클 완주 (소액 모드 결정 25)
- Crazy Picks: 7일간 매일 Top 10 자동 생성·LLM thesis 포함
- Moonshot: 7일간 매일 Top 3 자동 생성·매수가 3 옵션 산출
- /moonshot CLI: 7개 명령어 모두 동작
- Next.js: 6개 페이지 모두 정상 렌더 + 모바일 반응형
- Telegram: 모든 이벤트 (매수·매도·익절·손절·Top 10·Top 3) 알림 도착

---

## 10. 잔여 결정 (v1.0 확정 전 필요)

본 v0.1 후 다음 항목 확정 필요 (**2건만 남음**):

1. ⏳ **콘솔 검증 6항목** — Toss API 오픈 후 사용자 진행
2. ⏳ **결정 26 환전 정책** — 통합증거금 결과 따라

**도메인 확정** ✅ 2026-06-19 — `optimus8.cafe24.com` 그대로 사용 (결정 42)

**확정 완료 (2026-06-18 ~ 2026-06-19)**:
- ✅ DB: SQLite (MVP) → Supabase (운영) — 결정 37
- ✅ 인증: Google OAuth + Gmail 화이트리스트 (`suauncle@gmail.com`) — 결정 38
- ✅ 차트: TradingView Lightweight + Recharts 결합 — 결정 39
- ✅ Frontend 호스팅: **optimus8 self-host + GitHub Actions CI/CD** — 결정 42
- ✅ 운영 모니터링: Telegram only — 결정 43
- ✅ API 스펙: FastAPI 자동 OpenAPI — 결정 44
- ✅ 외부 데이터: 무료 최대 활용 (Toss + Stooq + Finnhub Free + FINRA + SEC EDGAR + RSS) — 결정 45

---

## 11. 변경 이력

| 날짜 | 변경 | 비고 |
|---|---|---|
| 2026-06-18 | **v0.1 골격 작성** — API 무관 영역. 아키텍처·기술 스택·디렉터리·모듈 명세·DB 스키마·배포 토폴로지. Frontend는 Next.js + Vercel 채택 (Streamlit 미사용) | API 오픈 후 v1.0으로 갱신 예정 |
| 2026-06-18 | **v0.1 갱신** — 결정 37/38/39 확정 (DB SQLite→Supabase / Google OAuth + Gmail 화이트리스트 / TradingView Lightweight + Recharts) — §2.3/§2.4·§8 환경변수·§10 잔여 결정 축소 (8→7) | — |
| 2026-06-18 | **v0.1 갱신** — Moonshot Universe 재정의 반영 (모든 미국 주식 + 8 인자 + 위험 수준 표시) — §4.3 운영 흐름 의사코드 갱신 | EHGO·AZTR 백테스트 사례 02 §3.2.7로 영구 기록 |
| 2026-06-18 | **v0.1 갱신 — Phase 1 능동적 발굴 반영** — 9 인자 학술 검증 가중치 재조정 (PEAD 25→30%, 갭+거래량 8→12%, 스퀴즈 10→6%, 소셜 15→8%) + 인사이더 매수 인자 신규 10% (결정 41) — §4.3 의사코드 9 인자 동기화 | docs/analysis/moonshot-factor-research.md v1 생성 |
| 2026-06-19 | **v0.1 갱신 — Backend 서버 호스팅 확정**: `optimus8.cafe24.com` (toss-tradebot 전용, upbit `orionhunter7`과 분리). §8.1 + §8.3 갱신. 서버 보안 권고 §8.1.1 신설 (가드레일 발동 후) | 자격증명은 문서·코드·git 노출 절대 금지 |
| 2026-06-19 | **v0.1 대규모 갱신 — Vercel 미사용 / optimus8 단일 서버 통합** (결정 42). Frontend도 optimus8 self-host (Next.js + PM2 + Nginx). GitHub Actions SSH deploy 워크플로우 §8.1.0 신설. §2.2·§2.4·§8.1·§8.2 환경변수 통합·§8.3 도메인 갱신. §10 잔여 결정 7→3건 축소. 결정 38 `ALLOWED_EMAIL=suauncle@gmail.com` 확정. 결정 43·44·45 (모니터링·OpenAPI·외부 데이터) 확정. | 02 §6.5.2 동기 |
| 2026-06-19 | **도메인 확정 — `optimus8.cafe24.com` 그대로** (서브도메인 추가 X). §8.3 + §10 정정. **잔여 결정 3→2건 축소** (콘솔 검증·환전 정책만 남음). | 02 도메인 표기 동기 |
| 2026-06-19 | **데이터 스택 분리 (사용자 본질 통찰) — Discovery는 Toss API 미사용**. Toss API = 자동매매 코어 전용 (주문 실행). Discovery = Stooq + Finnhub Free + SEC EDGAR + FINRA + Reddit PRAW + RSS 등 무료 외부 1차. §6 외부 의존성 매트릭스 재구성. | 02 결정 15·23·24·45 동기 |
