# 02 — 전략 결정 사항 (PRD 작성 직전 합의 정리)

**작성일**: 2026-06-16
**선행 문서**: `01-research-foundation.md` — 사상 계보·저빈도 기법·3 후보
**다음 문서**: `03-PRD-v1.md` — Toss API 가용성 조사 후 작성

---

## 0. 본 문서의 위치

`01-research-foundation.md`에서 제시한 3개 후보 (Core-Satellite / Mebane TAA / All-Weather) 중,
사용자가 자신의 실 수익 경험과 통찰을 반영하여 **Core-Satellite 변형**을 채택.

동시에 자동매매와 분리된 **Discovery 모듈 (Crazy Picks)** 신규 요구가 추가되어
본 문서는 **두 모듈의 결정사항을 모두 포함**하는 단일 합의서.

총 **20개 결정** 확정. 이 결정들이 `03-PRD-v1.md`의 기능 명세 기반이 됨.

---

## 1. 시스템 전체 구조 — 3 모듈 분리

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Toss Tradebot MVP — 3 모듈                              │
├────────────────────────┬─────────────────────────┬─────────────────────────────┤
│  ① 자동매매 코어        │  ② Crazy Picks          │  ③ Moonshot Picks            │
│  (Auto Trading Core)   │  (Discovery #1)         │  (Discovery #2)             │
├────────────────────────┼─────────────────────────┼─────────────────────────────┤
│  ㆍ빅7 + 섹터1위 단타   │  ㆍ시총 ≥ $1B 안정       │  ㆍ시총 $50M~$500M + 카탈리스트│
│  ㆍSPCX 영구 보유       │  ㆍ매일 06:30 KST        │  ㆍ매일 16:50/17:00 KST       │
│  ㆍ-10/-20/-30% 매수    │  ㆍTop 10 + thesis       │  ㆍTop 3 + 매수가 3 옵션      │
│  ㆍ평단 +20% 익절       │  ㆍNext.js (optimus8)    │  ㆍ+ /moonshot CLI + Skill    │
│  ㆍ시간 무한 보유       │  ㆍ사용자 별도 결정       │  ㆍ토스 WTS 수동 매수         │
│  ↓                     │  ↓                       │  ↓                          │
│  자금 1,500만원         │  자금 없음 (정보만)       │  자금 100만원 (카지노)        │
└────────────────────────┴─────────────────────────┴─────────────────────────────┘

총 운영 시드: 1,600만원 (자동매매 1,500 + Moonshot 100)
세 모듈 자금·로직 완전 분리 — 한쪽 실패가 다른 쪽에 영향 0
```

---

## 2. 결정 매트릭스 — 자동매매 코어 (13개)

| # | 항목 | 확정값 | 근거 |
|---|---|---|---|
| 1 | "잃지 말아야" 정의 | **(a) 실현 손실 0** — 매도 시 항상 +수익. 미실현 손실은 견딤 | Buffett 룰 #1·#2 |
| 2 | 시드 구조 | **Core(SPCX 영구) + Satellite(빅7+섹터1위 단타)** | 사용자 진화 통찰 통합 |
| 3 | 시장 비중 | **미국 100%** | 사용자 본인 미국 수익 100%+ 경험 |
| 4 | 종목 universe | **빅7 + 섹터1위 ≈ 15~17개 + SPCX 별도** | 분산 + 관리 가능 균형 |
| 5 | Sentiment 측정 | **가격 추이 검증 우선** (1단계 drawdown). 커뮤니티는 보조 | 사용자 "정확한 것이 장땡" |
| 6 | "떡락" 정량 | **(d) 다단계 -10/-20/-30%** 피라미딩 | 평단가 효율적 하향 |
| 7 | 종목당 노출 | **시드의 10% (100만원)** | 사용자 "포모 안 오는 금액" |
| 8 | 익절 기준 | **평단가 +20%** | "매도 시 항상 +20% 실현" 보장 |
| 9 | 익절 후 행동 | **다음 떡락 신호까지 현금 대기** | 시드는 신호 대기 모드 유지 |
| 10 | 동시 보유 종목 수 | **최대 5개** | 피라미딩 여력 보존 (500만 현금 버퍼) |
| 11 | 타임라인 | **시간 무관, 잃지 않음 우선** | 시간 압박 = 실수 유발 |
| 12 | 가격 기준 | **52주 고가** | 빅테크는 매년 ATH 갱신, 52w가 사실상 ATH |
| 13 | SPCX 매수 트리거 | **(d) 6개월 관망 (2026-12-12 이후) + IPO가 $135 이하** (둘 다 만족) | 신규 IPO 위험 (Lock-up·변동) |

### 2.1 자동매매 코어 운영 원리

```
[Core — SPCX 영구 보유]
조건: 상장 후 6개월 경과 (2026-12-12 이후) AND IPO가 $135 이하 도달
동작: 매수 + 영구 보유 (매도 X)
별도 예산: 추후 결정 (Satellite와 자금 분리 권고)

[Satellite — 빅7 + 섹터1위 15~17개]
매수 트리거: 52주 고가 대비
  -10% 시 1차 매수 (~33만원, 종목당 노출 1/3)
  -20% 시 2차 매수 (~33만원)
  -30% 시 3차 매수 (~34만원)
종목당 최대: 100만 (시드의 10%)
동시 최대 보유: 5종목
익절: 평단가 +20% 도달 시 전량 매도
손절: 절대 없음 (시간 무한 대기)
익절 후: 현금화, 다음 떡락 신호까지 대기

[시드 운영]
총 1,000만원
  └─ 최대 500만 deployed (5종목 × 100만)
  └─ 최소 500만 비상 매수 탄약 (큰 위기 시)
SPCX 별도 예산: TBD
```

### 2.2 종목 universe — 미국 주식 (Magnificent 7 ≡ MANGOS 포괄)

**Core (영구 보유 후보 — 매도 X)**:
- SPCX (SpaceX) — 결정 13 조건 만족 시 매수
  - MANGOS의 S에 해당. Core에서 별도 관리.

**Satellite (단타 +20% 익절 후보)** — 빅7 + 섹터1위:

| 분류 | 종목 (티커) |
|---|---|
| **빅7 (Magnificent 7)** | AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA |
| 반도체 보완 | TSM, AMD, AVGO, ASML |
| Healthcare | LLY, UNH |
| Finance | JPM, V, BRK.B |
| 기타 섹터1위 | XOM (에너지), COST/WMT (소비), NFLX (엔터), LMT (방산) |

→ **약 15~17개 유지**. 우선순위는 빅7 → 반도체 보완 → Finance → Healthcare 순.

#### MANGOS 매핑 (Big 7 ≡ MANGOS 포괄성)

| MANGOS | 우리 universe 매핑 |
|---|---|
| **M**eta (META) | ✅ Big 7 |
| **A**nthropic | ⚠️ 비상장. 간접: AMZN($80억 투자) + GOOGL(투자) — Big 7 포함 |
| **N**vidia (NVDA) | ✅ Big 7 |
| **G**oogle (GOOGL) | ✅ Big 7 |
| **O**penAI | ⚠️ 비상장. 간접: MSFT(49% 실효 지분) — Big 7 포함 |
| **S**paceX (SPCX) | ✅ Core 별도 |

→ Big 7 + SPCX가 **MANGOS를 완전 포괄**. 추가 종목 불필요.

#### Anthropic / OpenAI 상장 모니터링 (사용자 결정 2026-06-17)

- 두 회사 모두 비상장 상태이나 향후 IPO 가능성 있음
- **상장 확인 즉시 universe에 직접 포함** (Satellite 또는 Core 분류는 시점에 결정)
- 모니터링 방식 (TBD): WebSearch 정기 확인 / IPO 캘린더 API / 뉴스 사이트 알림
- 상장 시 SPCX와 유사한 신규 IPO 위험 평가 적용 (Lock-up·ATH 미형성·6개월 관망 등)

### 2.3 시뮬레이션 (사전 추정)

- 평단 +20% 익절 × 시드 6~10회전/연 → 연 +30~50% (대략)
- 10배 도달 추정: log(10)/log(1.35~1.50) ≈ **5~9년**
- 큰 폭락 1~2회 동반 시 추가 +1~2년 → **현실적 6~9년**
- "잃지 않음" 우선이므로 시간 양보 가능 (결정 11과 일관)

---

## 2.5 운영 정책 결정 — Toss API 의존성 보완 (3개)

Toss Open API 정독 결과(`docs/analysis/toss-api-survey.md` v2) 발견한 5건 위험 중
**구현 정책으로 즉시 확정 가능한 3건** 신규 결정.

| # | 항목 | 확정값 | 사유 |
|---|---|---|---|
| **23** | **52주 고가 데이터** | **자동매매 코어**: Toss API 일봉 252개 직접 캐싱·계산 (`/api/v1/candles?interval=1d&count=200`). **Discovery**: Stooq 직접 제공 52w high/low 사용 (계산 불요) | Toss는 미제공 → 일봉 계산 / Stooq는 직접 제공 |
| **24** | **시세 Polling 정책** | **자동매매 코어**: Toss API 60초 polling (Market Data 10 req/sec 전용 사용). **Discovery**: 외부 무료 소스 별도 polling (cron 기반, rate limit 무관) | Toss rate는 자동매매 100% 보장 |
| **25** | **운영 초기 검증 모드** | **소액 모드 (10~50만원)** 시작 후 1주~1개월 후 단계적 확대 | Paper Trading(모의투자) 별도 서버 미제공 → 실거래로만 검증 |

### 2.5.1 결정 23 — 52주 고가 일봉 계산 상세

**필요 사유**:
- 결정 12 (52주 고가 기준 매수 트리거)의 직접 데이터 없음
- 현재가 API에 lastPrice만, high/low 미포함

**구현**:
```
1. 종목별 일봉 200~252개 캐싱 (DB 테이블 `daily_candles`)
2. 매일 1회 갱신 (장 마감 후, 미국: 06:00 KST, 한국: 16:00 KST)
3. 52주 high = MAX(highPrice) over 최근 252거래일
4. 52주 low  = MIN(lowPrice)  over 최근 252거래일
5. 매수 트리거 계산: (현재가 - 52주 high) / 52주 high
```

**Universe 범위 (자동매매 코어)**:
- Satellite 15~17종 + SPCX = 약 16~18종 종목
- 매일 일봉 갱신: 종목당 1 API 호출 × 18종 = 18 calls/일 (충분)

### 2.5.2 결정 24 — Polling 정책 상세

**Market Data Rate Limit**: 10 req/sec (Overview 출처)

**계산**:
- 5종목 × 분당 60회 polling = 300 calls/min = **5 req/sec** (한도 50%)
- Discovery 일 1회 스캔: 별도 부담 (시간 분산)

**Polling 간격**: **60초** (1분봉 갱신 주기와 일치)

**시세 지연 인지**:
- WebSocket 부재로 upbit 대비 응답 지연 ~1분
- 떡락 트리거 감지 지연 최대 1분 → 매수 가격 약간 불리 가능
- 결정 1 "절대 손실 0" 룰 + 시간 무한 보유로 영향 최소화

### 2.5.3 결정 25 — 소액 검증 모드 상세

**Paper Trading 부재 보완** — 실거래로 검증 단계화:

| 단계 | 기간 | 시드 노출 | 목적 |
|---|---|---|---|
| 1 | 1~2주 | **10만원** | 인증·주문·잔고 기본 동작 검증 |
| 2 | 2~4주 | **50만원** | 1회전 매매 + 익절 사이클 검증 |
| 3 | 1~2개월 | **300만원** | 다단계 매수·5종목 동시 운영 검증 |
| 4 | 안정 후 | **1,000만원** | 정식 운영 |

**1단계 진입 조건**:
- 자동매매 코어 로컬 단위 테스트 100% PASS
- 콘솔 검증 6항목 100% 통과
- 사용자 명시 운영 시작 승인

---

## 3. Discovery 모듈 — 2 Sub-modules (Crazy Picks + Moonshot Picks)

Discovery는 자동매매 코어와 분리된 **2개 sub-module**로 운영:

| Sub-module | 자금 | 목표 수익 | Universe | 운영 시점 | 사용자 액션 |
|---|---|---|---|---|---|
| **§3.1 Crazy Picks** | 없음 (정보) | 일반 미친 상승 | 시총 ≥ $1B 안정 | 매일 06:30 KST | 별도 결정 |
| **§3.2 Moonshot Picks** | 100만원 (현금) | **회당 +100% 이상** | **시총 $50M~$500M + 카탈리스트** | **매일 16:50/17:00 KST** | **토스 WTS 수동 매수** |

→ 두 모듈 자금·로직 완전 분리. Moonshot은 시드 100% 소실 OK (사용자 명시 위험 인지).

---

### 3.1 Crazy Picks (Sub-module 1) — 9개 결정 (14~22)

| # | 항목 | 확정값 |
|---|---|---|
| 14 | 랭킹 인자 5개 가중 | **가격 모멘텀 25% + 어닝 모멘텀 20% + 애널리스트 액션 15% + 소셜 sentiment 20% + 뉴스 sentiment(LLM) 20%** |
| 15 | 데이터 소스 | **Toss API 미사용** (자동매매 전용) — Stooq (1차 가격·52w·거래량) + Yahoo (백업) + Finnhub Free 어닝 + FINRA 공매도 + SEC EDGAR Form 4 + Reddit PRAW + PRNewswire/GlobeNewswire RSS |
| 16 | LLM | **Claude Haiku 4.5** (가성비 최강, 월 ~$5~15) |
| 17 | 업데이트 시점 | **매일 06:30 KST** (미장 마감 직후, 종가 확정) |
| 18 | 뷰어 | **Next.js (optimus8 self-host, PM2) + Telegram 알림** 결합 (Polling 기반, 결정 24 참조) |
| 19 | 정확도 추적 | **1주/1개월 성과 자동 기록** (`perf_1w`, `perf_1m` 컬럼) |
| 20 | 종목 필터 | **시총 ≥ $1B / 평균 거래량 ≥ 100만주 / NYSE+Nasdaq / 가격 ≥ $5 / 상장 ≥ 60일** |
| 21 | **섹터 와이트리스트 (양자·보안)** | **13종 강제 포함** — 결정 20 필터 통과 못 해도 매일 스캔에 무조건 포함 |
| 22 | **섹터 부스트 (양자·보안)** | composite_score에 **+10% 배수** — Top 10 진입 가능성 ↑ |

### 3.1.1 섹터 와이트리스트 (결정 21)

**양자컴퓨터 (Quantum Computing) — 5종**:
| 종목 | 티커 | 특징 |
|---|---|---|
| IonQ | IONQ | 미국 양자 대장, 시총 ~$5B |
| Rigetti Computing | RGTI | 양자 클라우드 서비스 |
| D-Wave Quantum | QBTS | 양자 어닐링 1위 |
| Arqit Quantum | ARQQ | 양자 암호 (보안 겸업) |
| IBM (참고) | IBM | 거대 기업, 양자 사업부 |

**사이버보안 (Cybersecurity) — 8종**:
| 종목 | 티커 | 특징 |
|---|---|---|
| CrowdStrike | CRWD | EDR 1위, 시총 ~$100B |
| Palo Alto Networks | PANW | 종합 보안 플랫폼 1위 |
| Zscaler | ZS | Zero Trust 클라우드 |
| Fortinet | FTNT | 네트워크 보안 + 배당 |
| SentinelOne | S | EDR 차세대 |
| Cloudflare | NET | 엣지 보안 + CDN |
| Okta | OKTA | IAM (계정 인증) |
| CyberArk | CYBR | 권한 관리 |

→ 합계 13종. 결정 20 필터(시총·거래량 등) 미통과해도 매일 Discovery 스캔에 강제 포함.

### 3.1.2 섹터 부스트 (결정 22)

- 양자컴퓨터·사이버보안 섹터 종목의 composite_score에 **× 1.10 배수**
- 동일 점수 경쟁 시 양자/보안 종목이 Top 10 진입 우선
- DB에 `sector_boost_applied: bool` 컬럼 추가 (투명성)

**리스크 인지**:
- 양자 종목 변동성 극심 (분기 +100%/-50% 흔함)
- 사이버보안도 거시 충격에 큰 폭락 (2022년 -50%)
- Discovery는 **사용자 수동 매수**이므로 사용자가 최종 위험 판단 — 안전망 유지

### 3.1.3 Crazy Picks 운영 원리 (2026-06-19 데이터 소스 분리 반영)

```
[매일 06:30 KST]
  ↓
미국 주식 스캔 — Stooq (전체 종목, 무료, key 없음)
  필터: 시총 ≥ $1B, 거래량 ≥ 100만주, NYSE+Nasdaq, 가격 ≥ $5, 상장 ≥ 60일
  ↓
5개 인자 가중 점수 계산 (Toss API 미사용)
  ㆍ가격 모멘텀 (Stooq 1m/3m/6m + 52w 직접 제공)          25%
  ㆍ어닝 모멘텀 (Finnhub Free EPS 컨센서스·서프라이즈)      20%
  ㆍ애널리스트 액션 (Finnhub Free 목표가·등급)             15%
  ㆍ소셜 sentiment (Reddit PRAW WSB 멘션 폭증)              20%
  ㆍ뉴스 sentiment (RSS + Claude Haiku LLM 분석)            20%
  ↓
Top 10 선정
  ↓
각 종목별 Claude Haiku로 thesis 자연어 생성
  ㆍ왜 미친 상승 후보인가 (3~5줄)
  ㆍ카탈리스트 (어닝일, 신제품 등)
  ㆍ위험 요소 (1~2줄)
  ㆍ뉴스 요약 (2~3줄)
  ↓
DB 저장 + Next.js 뷰어 갱신 (optimus8) + Telegram 알림
  ↓
1주 후 / 1개월 후 자동으로 실제 성과 추적 (perf_1w, perf_1m)
```

### 3.1.4 Crazy Picks DB 스키마 (초안)

```sql
CREATE TABLE crazy_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_date TEXT NOT NULL,              -- YYYY-MM-DD
    rank INTEGER NOT NULL,                -- 1~10
    ticker TEXT NOT NULL,
    company_name TEXT,
    sector TEXT,
    close_price REAL,
    pct_from_52w_high REAL,
    pct_from_52w_low REAL,
    return_1m REAL,
    return_3m REAL,
    return_6m REAL,
    volume INTEGER,
    avg_volume INTEGER,
    market_cap REAL,
    composite_score REAL,                  -- 5축 가중 합 (0~100)
    factor_breakdown TEXT,                 -- JSON: {"price": 22, "earnings": 18, ...}
    thesis TEXT,                           -- LLM 생성 (~300자)
    catalysts TEXT,                        -- JSON: 어닝일·FDA·발표 등
    risks TEXT,                            -- LLM 생성 (~150자)
    news_summary TEXT,                     -- LLM 생성 (~200자)
    analyst_data TEXT,                     -- JSON: 목표가·등급·변경
    perf_1w REAL,                          -- 추천 후 1주 수익률 (T+7 일 자동 채움)
    perf_1m REAL,                          -- 추천 후 1개월 수익률 (T+30 일 자동 채움)
    created_at TEXT DEFAULT (DATETIME('now', 'localtime'))
);

CREATE INDEX idx_crazy_picks_date ON crazy_picks(pick_date);
CREATE INDEX idx_crazy_picks_ticker ON crazy_picks(ticker);
```

### 3.1.5 Crazy Picks 본질적 한계 (동업자 솔직 보고)

- "예측 시스템"의 적중률은 본질적으로 50%를 크게 넘기기 어려움 (Wall Street 헤지펀드 포함)
- 사용자 수동 매수 결정 = **완벽한 안전장치**. 시스템은 후보 제시, 사람이 최종 판단
- 정확도 추적 (결정 19)로 시스템 신뢰도 정량 검증 → 기대치 자가 조정 가능

---

### 3.2 Moonshot Picks (Sub-module 2) — 12개 결정 (27~36, 40, 41)

| # | 항목 | 확정값 |
|---|---|---|
| 27 | 모듈 명칭 | **Moonshot Picks** |
| 28 | 시드 분리 | **100만원 (현금)** — 자동매매 1,500만 + Crazy 0과 별도 |
| 29 | 위험 허용 | **시드 100% 소실 OK** (사용자 명시) |
| 30 | 운영 시간 | **KST 16:50** 분석 / **17:00** 알림 / 매수 후 60초 polling |
| 31 | Universe | **모든 미국 주식** (페니스톡·마이크로캡·소형주·중형주 포함) — 자동매매 universe와 분리 |
| 32 | 선정 인자 **9가중** (학술 검증 후 재조정 2026-06-18) | 변동성 12% + **카탈리스트 30%** ⬆ + 스퀴즈 6% ⬇ + 소셜 8% ⬇ + 뉴스(LLM) 12% + 기술적 8% + **갭+거래량 12%** ⬆ + 52w 저점 2% ⬇ + **인사이더 매수 10%** ⭐신규 |
| 33 | 매수가 표시 | **3 옵션 동시 표시** — (a) 즉시 / (b) 떡락 -5% / (c) 돌파 +8% — **페니스톡엔 (b) 우선 권고** |
| 34 | 매도 정책 | **+100% 익절** AND **-50% 손절** AND **5일 시간 손절** (3중) |
| 35 | 갱신 빈도 | **유지 + 갱신** (보유 종목 +100% 도달까지 새 후보 매일 알림) |
| 36 | **/moonshot CLI** | **Python + click + rich** (console_scripts 진입점) + Claude Code Skill |
| **40** | **위험 수준 표시** | **HIGH (페니스톡 $<50M) / MED (소형주 $50M~$500M) / LOW (중형주 $500M+)** 각 종목에 명시 + LLM thesis에 **manipulation 위험** 항목 추가 |
| **41** | **인사이더 매수 인자 (SEC Form 4)** | **3+ insiders cluster within 15 days** = 강한 매수 신호 (학술 검증). 단독 insider buy = 부분 신호. **SEC EDGAR 무료 데이터** |

### 3.2.1 Moonshot Picks 운영 원리

```
[매일 KST 16:50] — 미국 프리마켓 오픈 10분 전
  ↓
모든 미국 주식 스캔 — Stooq (전체 종목, 무료, Toss API 미사용)
대상: NYSE + NYSE American + Nasdaq (OTC 제외)
필수 필터:
  ㆍ가격 ≥ $0.10 (sub-penny 제외)
  ㆍ거래량 ≥ 50만주/일 (유동성 최소)
  ㆍ상장 ≥ 30일
  (시총 제한 거의 없음 — 페니스톡·마이크로캡 포함 모든 가능성)
  ↓
9개 인자 가중 점수 계산 (학술 검증 후 재조정 2026-06-18)
  ㆍ변동성 (30일 일평균 ≥ 10%)                       12%
  ㆍ카탈리스트 임박 (PEAD 학술 검증) ⬆               30%
    - 어닝 D-7 (PEAD, Ball & Brown 1968, Garfinkel 2024)
    - FDA PDUFA 일정 D-7 ~ D-1 (Event Study 검증)
    - FDA AdCom (Advisory Committee) 결과 발표일
    - M&A 루머 / 보도자료 (PRNewswire / GlobeNewswire)
    - 데이터: BiopharmaWatch FDA Calendar (무료) + SEC EDGAR
  ㆍ공매도 스퀴즈 (SI ratio ≥ 4.17) ⬇                6%
  ㆍ소셜 sentiment (WSB 단순 멘션 수) ⬇              8%
  ㆍ뉴스 sentiment (Claude Haiku 분석)               12%
  ㆍ기술적 돌파 (52w 신고가 근접 / 거래량 평균 ×3)    8%
  ㆍ갭 + 거래량 폭증 ⬆ (전일 +50% 갭 + 거래량 10×)  12%
  ㆍ52w 저점 근접 + 거래량 (저점 30% 내 + 5×)        2%
  ㆍ인사이더 매수 ⭐NEW (3+ cluster 15일 내 SEC Form 4) 10%
  ↓
각 종목 위험 수준 자동 분류 (결정 40):
  ㆍHIGH (시총 < $50M, 페니스톡·마이크로캡)
  ㆍMED  (시총 $50M~$500M, 소형주)
  ㆍLOW  (시총 $500M+, 중형주)
  ↓
Top 10 선정 → Top 3 확정
  ↓
각 Top 3 종목에 매수가 3 옵션 + 매도가 + 손절선 산출
  - 페니스톡(HIGH)엔 (b) 떡락 대기 우선 권고 (결정 33)
  + Claude Haiku로 thesis (3줄), 카탈리스트, 위험, 뉴스 요약
  + manipulation 위험 평가 (1~5, HIGH 종목 우선)
  ↓
DB 저장 (moonshot_picks 테이블)

[KST 17:00] — 미국 프리마켓 오픈
  ↓
Telegram 알림 + Next.js 페이지 갱신 (Vercel)
  ↓
사용자가 토스 WTS에서 수동 매수 (Top 3 중 선택, 3 매수가 옵션 중 선택)

[60초 polling — 매수 후]
  ↓
가격 모니터링
  +100% 도달 → 매도 알림 (사용자 토스 WTS 수동 매도)
  -50% 도달 → 손절 알림
  5일 경과 → 시간 손절 알림
```

### 3.2.2 Moonshot Picks DB 스키마 (초안)

```sql
CREATE TABLE moonshot_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_date TEXT NOT NULL,                   -- YYYY-MM-DD
    rank INTEGER NOT NULL,                     -- 1~10 (Top 3은 rank ≤ 3)
    ticker TEXT NOT NULL,
    company_name TEXT,
    sector TEXT,
    market_cap REAL,
    current_price REAL,
    high_52w REAL,
    low_52w REAL,

    -- 9개 인자 점수 (결정 32 — 2026-06-18 학술 검증 후 9 인자 재조정)
    score_volatility REAL,
    score_catalyst REAL,
    score_squeeze REAL,
    score_social REAL,
    score_news REAL,
    score_technical REAL,
    score_gap_volume REAL,                     -- 갭 + 거래량 폭증
    score_low_rebound REAL,                    -- 52w 저점 근접 + 거래량
    score_insider REAL,                        -- ⭐ 신규 (결정 41): SEC Form 4 cluster
    composite_score REAL,                      -- 가중 합 (0~100)

    -- 위험 분류 (결정 40)
    market_cap_category TEXT,                  -- 'MICRO' / 'SMALL' / 'MID'
    risk_level TEXT,                           -- 'HIGH' / 'MED' / 'LOW'
    manipulation_risk INTEGER,                 -- 1~5 (LLM 평가, 5=매우 의심)

    -- 매수가 3 옵션
    buy_price_a REAL,                          -- 즉시 진입
    buy_price_b REAL,                          -- 떡락 -5%
    buy_price_c REAL,                          -- 돌파 +8%

    -- 매도 정책
    target_sell_multiplier REAL DEFAULT 2.0,   -- +100% 익절
    stop_loss_multiplier REAL DEFAULT 0.5,     -- -50% 손절
    time_stop_days INTEGER DEFAULT 5,           -- 5일 시간 손절

    -- LLM 생성
    thesis TEXT,                               -- ~3줄
    catalysts TEXT,                            -- JSON (어닝/FDA 일정)
    risks TEXT,
    news_summary TEXT,

    -- 추적 (사용자가 매수한 종목)
    user_bought BOOLEAN DEFAULT 0,
    user_buy_price REAL,                       -- 사용자 실제 매수가
    user_buy_option TEXT,                      -- 'a' / 'b' / 'c'
    user_sold BOOLEAN DEFAULT 0,
    user_sell_price REAL,
    user_realized_pnl REAL,
    user_sell_trigger TEXT,                    -- 'TARGET' / 'STOP_LOSS' / 'TIME_STOP'

    -- 자동 추적
    max_price_after REAL,                      -- 추천 후 최고가
    perf_1d REAL,
    perf_3d REAL,
    perf_5d REAL,

    created_at TEXT DEFAULT (DATETIME('now', 'localtime'))
);

CREATE INDEX idx_moonshot_picks_date ON moonshot_picks(pick_date);
CREATE INDEX idx_moonshot_picks_ticker ON moonshot_picks(ticker);
CREATE INDEX idx_moonshot_picks_bought ON moonshot_picks(user_bought);
```

### 3.2.3 /moonshot CLI 명세 (결정 36 상세)

**기술 스택**:
- Python 3.12+ / click (CLI) / rich (컬러·박스·라이브)
- 진입점: `setup.py` console_scripts → `pip install -e .` 후 `moonshot` 명령 즉시 사용

**명령어**:

```bash
moonshot                       # 오늘 Top 3 (기본)
moonshot top                   # Top 10 전체
moonshot detail <TICKER>       # 종목 상세 (thesis + news + 매수가 3 옵션)
moonshot history [N]           # 최근 N일 이력 (기본 7)
moonshot perf                  # 추천 적중률 통계 (1d/3d/5d)
moonshot live                  # 실시간 가격 갱신 (60초 polling)
moonshot positions             # 현재 사용자 보유 종목
moonshot --help                # 도움말

옵션:
  --json                       # JSON 출력 (jq 등 도구 연동)
  --no-color                   # 컬러 끄기 (로그 파이프 시)
  --date YYYY-MM-DD            # 특정 날짜 조회
```

**출력 형식 (`moonshot`)**:

```
🌙 Moonshot Picks 2026-06-19 (KST 16:55)
═══════════════════════════════════════════════════════════

#1 ABCD                                         ⭐⭐⭐ 87/100
   섹터: Biotech │ 시총: $320M
   카탈리스트: 어닝 D-1 (06-20 장 마감 후)
   현재가: $4.50  │  52w High: $8.20  │  52w Low: $2.10

   📈 매수가 옵션:
     (a) 즉시 진입: $4.50
     (b) 떡락 대기: $4.27  (-5%)
     (c) 돌파 진입: $4.85  (+8%)

   🎯 목표 매도: 매수가 × 2.00  (a=$9.00 / b=$8.54 / c=$9.70)
   🛑 손절선: 매수가 × 0.50  /  5일 시간 손절

   💡 Thesis: Phase 3 임상 결과 발표 임박. 옵션 활동 평소 5×.
       WSB 멘션 7일 +420%. 공매도 18%, float 작아 스퀴즈 가능.

───────────────────────────────────────────────────────────
#2 EFGH ... (동일 형식)
#3 IJKL ... (동일 형식)
═══════════════════════════════════════════════════════════
오늘 Top 3 │ 시드 100만원 분배 권고: 사용자 결정
다음 갱신: 2026-06-20 16:50 KST
```

### 3.2.4 Claude Code Skill (결정 36 부속) — **2026-06-19 placeholder 생성됨** ✅

**위치**: `.claude/skills/moonshot.md` (프로젝트 로컬, git 추적)

**기능**: Claude 세션 내에서 `/moonshot` 입력 → Bash로 `moonshot $ARGS` 호출 → 출력 마크다운 재포맷 후 보고

**현재 상태**: 🚧 Placeholder
- CLI 미설치 상태에서는 안내 메시지 표시
- PRD v1.0 구현 후 `moonshot` CLI 설치 → Skill 자동 활성화

**구현된 명령 매트릭스** (Skill 파일 §사용 참조):

| 명령 | Bash 실행 |
|---|---|
| `/moonshot` | `moonshot` (Top 3) |
| `/moonshot top` | `moonshot top` (Top 10) |
| `/moonshot detail <TICKER>` | `moonshot detail <TICKER>` |
| `/moonshot history [N]` | `moonshot history [N]` |
| `/moonshot perf` | `moonshot perf` |
| `/moonshot live` | `moonshot live` (짧은 시간만) |
| `/moonshot positions` | `moonshot positions` |

**출력 재포맷**: rich 컬러 박스 → 마크다운 표·인용·강조 (Skill 파일 §출력 가이드 예시 참조)

**.gitignore 갱신**: `!.claude/skills/` 추가 — Skill 파일 git 추적 가능

### 3.2.5 Telegram 알림 vs CLI 출력 — 동일 데이터 보장

| 출구 | 형식 |
|---|---|
| Telegram | HTML (parse_mode='HTML', `<b>`·`<pre>` 태그) |
| CLI (`moonshot`) | rich 컬러 (ANSI) — 박스·이모지 |
| Next.js (optimus8 self-host) | React 카드 컴포넌트 (Tailwind) |

**모두 동일 DB 데이터**(`moonshot_picks` 테이블) **사용**. 형식만 다름. 사용자가 어느 채널로 보든 동일 정보·동일 매수가·동일 매도가.

### 3.2.6 Moonshot Picks 본질적 한계 (동업자 솔직 보고)

- **"회당 +100% 가능 종목"은 카지노 자금 운영의 본질**
- Wall Street 헤지펀드도 단일 매매 +100% 적중률 매우 낮음
- **페니스톡 평균 수익률 음수** (Bradshaw·Bushee·Miller 등 학술 연구) — 매주 +200% 가는 종목 있지만 동시에 -50~-90% 가는 종목 더 많음
- 시드 100% 소실 가능성 인정 (결정 29) — 사용자 명시 수용
- **다행한 안전장치**:
  1. 자동매매 코어와 자금 완전 분리 (영향 0)
  2. 사용자 토스 WTS 수동 매수 (시스템 자동 매수 X — 사용자 최종 판단)
  3. -50% 손절선 + 5일 시간 손절 (시드 보존 시도)
  4. 적중률 추적 (`perf_1d/3d/5d`)으로 시스템 신뢰도 정량 검증
  5. **위험 수준 (HIGH/MED/LOW) 명시** (결정 40) — 사용자 위험 인지 보조
  6. **페니스톡엔 매수 옵션 (b) 떡락 대기 우선 권고** (결정 33) — 시가 매수 함정 회피

→ **사용자가 동의한 위험 인지 상태에서 가능한 한 정밀 발굴 시도**. 카지노 칸막이 운영.

### 3.2.7 첫 백테스트 사례 (2026-06-17 실증)

운영 시작 전 시스템 검증 사례 — 사용자 토스 WTS에서 직접 목격한 +200% 급등주:

| 종목 | 시총 | 시작 → 시가 → 일중 고점 → 종가 | 카탈리스트 | 우리 시스템 통과? |
|---|---|---|---|---|
| **EHGO** | $2.8M | $1.32 → $4.81 → $7+ → $5.56 (+321%) | AI 파트너십 발표 | ✅ Top 3 추정 (HIGH 위험) |
| **AZTR** | $3.85M | 일중 +200% (사용자 보고) → 종가 -5% | CEO 주주서한 + $10.5M 자금조달 | ✅ Top 10 추정 (HIGH 위험) |

**시사점**:
- Universe 확대(결정 31 재정의)로 두 사례 모두 사전 발굴 가능했음
- 핵심 인자: **카탈리스트 (보도자료) + 갭 + 거래량 폭증**
- 매수 옵션 (b) 떡락 대기 권고: EHGO $4.81 → $4.57 진입이 합리적
- Phase 2 운영 데이터 누적 시 인자 가중치 재조정 + 신규 패턴 발굴 cycle

**개선 후보 (운영 후 검토)**:
- 보도자료 실시간 모니터링 (PR Newswire / GlobeNewswire / SEC EDGAR)
- 프리마켓 갭 5분 단위 추적 (NY 04:00~09:30)
- 페니스톡 manipulation 식별 (paid promoter, pump & dump 신호)

### 3.2.8 신규 가설 5종 (H1~H5) — Phase 2 검증 대상

학술 데이터 부족한 우리 환경 (마이크로캡·프리마켓·5일·+100%) 특화 후보 가설:

#### H1 — 마이크로캡 보도자료 + 갭업 (EHGO 패턴)
```
조건:
  시총 < $50M
  AND 회사 발표 (PRNewswire/GlobeNewswire) 24h 내
  AND 시가 ≥ 전일 종가 × 1.5 (+50% 갭업)
  AND 거래량 ≥ 평균 20배
→ 강한 매수 신호 (단 매수 옵션 (b) 떡락 대기 우선, (a) 시가 매수 비권고)
```

#### H2 — 프리마켓 갭 + 모멘텀 지속
```
조건:
  프리마켓 최고가 ≥ 전일 종가 × 2.0
  AND NY 06:00 (KST 19:00) 시점 가격 유지 또는 상승
→ 정규장 진입 시 추가 상승 가능성
```

#### H3 — 52w 저점 + 첫 거래량 폭증 (AZTR 패턴 + F7 결합 v2 강화)
```
기본 조건:
  가격 ≤ 52w low × 1.20 (저점 +20% 내)
  AND 거래량 ≥ 평균 5배 (5일 연속 증가)
  AND 카탈리스트 ≥ 약 (보도자료·임상 등)

⭐ F7 강화 조건 (2026-06-19 v2 추가):
  + 갭다운 -10% 이상 발생 후 종가 ≥ 시가 (intraday reversal)
  + 거래량 ≥ 평균 3배
  → Capitulation reversal 결합 신호

→ 매집·반등 후보 (학술 + 실증 결합)
```

#### H4 — 소셜 폭증 + 카탈리스트 결합 (학술 ⊕ 실증)
```
조건:
  WSB 24h 멘션 ≥ 평균 5배 (단순 카운트)
  AND 카탈리스트 D-7 내 (어닝/FDA/M&A)
  AND 가격 모멘텀 5d +10%
→ 단독 WSB는 약하나 결합 시 강함
```

#### H5 — 공매도 + Float 작음 + 가격 시작 (Squeeze 학술 셋업)
```
조건:
  SI ratio ≥ 4.17 (AMC 학술 threshold)
  AND Float < 20M주
  AND 5일 모멘텀 ≥ +10%
→ Short Squeeze 발생 학술 임계 부합
```

**검증 절차** (Phase 2):
1. 자체 운영 데이터 1~3개월 누적
2. 각 가설별 추천 종목 perf_1d/3d/5d 분석
3. 가설 채택·기각·가중 조정 결정
4. 채택 시 결정 32 가중치 재배분 또는 신규 결정 추가

---

## 4. 두 모듈 자금 분리

```
사용자 총 자산
  │
  ├─ 자동매매 코어: 1,500만원
  │     ㆍSatellite (빅7+섹터1위 단타): 1,000만원
  │     ㆍSPCX Core (영구 보유): 500만원
  │
  ├─ Moonshot Picks: 100만원 (현금, 카지노 칸막이)
  │     ㆍ위험 허용: 100% 소실 OK
  │     ㆍ사용자 토스 WTS 수동 매수
  │
  └─ Crazy Picks: 자금 없음 (정보만)
        ㆍ시스템 후보 제시
        ㆍ사용자가 본인 별도 자금으로 수동 매수

총 시드: 1,600만원
```

→ **세 영역 자금·로직 모두 완전 분리**:
- 자동매매 코어 ↔ Moonshot ↔ Crazy 어느 한쪽 실패가 다른 쪽 자금에 영향 0
- Moonshot 시드 100% 소실해도 자동매매 1,500만 무영향
- Crazy Picks는 자금 없으므로 시스템 오류도 손실 0

---

## 5. SPCX 특수 처리 (결정 13 상세)

SPCX는 2026-06-12 IPO 직후 종목이라 빅7과 다른 위험 프로파일:

### 5.1 신규 IPO 위험
- **Lock-up 기간**: 보통 90~180일. 만료 시점에 내부자 대량 매도 → 큰 하락 가능
- **첫 실적 발표**: 상장 후 1~2분기 첫 실적 공개. 시장 반응 큰 변동
- **ATH 미형성**: 상장 며칠 만에 "사상 최고가" 기준점 없음. 첫 1년은 다른 기준 필요
- **Elon Musk 변수**: Tesla 사례 — 트윗 한 줄에 -10%
- **정부 계약 의존**: NASA, 국방부 매출 비중. 정치 리스크

### 5.2 매수 조건 (둘 다 만족)
1. **상장 후 6개월 경과** (2026-12-12 이후)
2. **IPO가 $135 이하 도달**

→ 이 시점은 Lock-up 만료 + 가격 충분히 하락 + 시장 평가 안정화. "공모가도 못 받는 수준" = 항복 신호.

### 5.3 매수 후 동작
- **분할 매수** (다른 Satellite와 동일 3단계: $135 / $115 / $95 등)
- **매도 X** (영구 보유)
- **별도 예산** (Satellite 1,000만과 분리, 별도 결정 필요)

---

## 6. 잔여 결정·작업 (PRD 작성 전 완료 필요)

### 6.1 잔여 결정 — 확정 (2026-06-16)
- **SPCX 별도 예산**: **+500만원** (Satellite 1,000만과 자금 분리)
  - 시드 운영 총합: Satellite 1,000만 + SPCX 500만 = **1,500만원**
  - SPCX 매수 조건 (결정 13) 도달 시 분할 매수에 사용
  - 분할 매수 단계는 Satellite와 동일 패턴 적용 (-10/-20/-30%) 추정 — 구현 시 확정
- **빅7 + 섹터1위 우선순위**: **전체 15~17개 동시 감시**
  - 모든 종목 동시 감시, -10% 도달 종목이 자연 우선
  - 동시 5 슬롯 제한이 분산 보장 (결정 10)
  - 사용자 사전 등급화 없음 — 시장 변동성이 자연 필터
- **Claude API 키**: 사용자 보유 확인
  - 위치: `/Users/gonnim/Project-MVP/Source/upbit-tradebot-mvp/.env` 의 `ANTHROPIC_API_KEY`
  - OpenAI 키(`OPENAI_API_KEY`)도 백업 보유
  - 구현 단계에서 toss `.env`로 복사 또는 공통 위치 참조 방식 결정 (TBD)
  - 평문 자격증명 노출 절대 금지 (글로벌 가드레일 §1.2)

### 6.2 영구 모니터링 항목 (2026-06-17~)
- **Anthropic / OpenAI 상장 모니터링**
  - 두 회사 IPO 시 즉시 universe 직접 포함
  - 모니터링 방식 (TBD 구현 시 결정): WebSearch 정기 / IPO 캘린더 API / 뉴스 알림
  - 상장 시 신규 IPO 위험 평가 적용 (Lock-up·ATH 미형성·관망 기간 등)

### 6.3 Toss API 콘솔 검증 6항목 (2026-06-17 신청 완료 → API 오픈 후 진행)

`docs/analysis/toss-api-survey.md` v2 §3 참조. API 오픈 즉시 사용자가 진행:

```
□ 1. ✅ developers.tossinvest.com 가입·API 신청 ← 완료 (2026-06-17)
     ⏳ 승인 소요 시간 후속 보고 필요

□ 2. 토스 앱 → 해외주식 검색·매수 화면 진입 가능 확인
     - SPCX (Core)
     - IONQ·RGTI·QBTS·ARQQ (양자 와이트리스트 4종)
     - CRWD·PANW·ZS·FTNT·S·NET·OKTA·CYBR (보안 와이트리스트 8종)
     - 빅7 + 섹터1위 (Satellite)

□ 3. 통합증거금 여부 (결정 26 확정 직결)
     - KRW 잔고로 USD 주식 매수 시 자동 환전?
     - 또는 사전 USD 환전 필요?

□ 4. API 사용료 (무료/유료)

□ 5. 자동매매 약관 (home.tossinvest.com/ko/terms/v2?id=752)
     - "자동매매" / "시스템 트레이딩" / "프로그램 매매" / "API" 키워드 검색
     - 명시 허용 또는 금지 조항

□ 6. 실시간 vs 15분 지연 시세 정책
```

### 6.4 잔여 결정 — 콘솔 검증 후 확정 (1개 보류)

| # | 항목 | 보류 사유 |
|---|---|---|
| **26** | **환전 정책** | 콘솔 #3 통합증거금 결과 따라 분기 — (a) 자동 환전 / (b) 사전 환전 절차 정의 |

### 6.5 기술 스택·인프라 결정 (2026-06-18 확정, PRD v0.1 작성 중)

PRD v0.1 작성 과정에서 추가로 확정된 3 결정:

| # | 항목 | 확정값 |
|---|---|---|
| **37** | **DB** | **SQLite (MVP 1~3개월) → Supabase Postgres 마이그 (운영 안정 후)** |
| **38** | **Frontend 인증** | **Google OAuth + Gmail 화이트리스트** — `ALLOWED_EMAIL=suauncle@gmail.com` (NextAuth.js Google Provider, 본인 Gmail 1개만 허용) |
| **39** | **차트 라이브러리** | **TradingView Lightweight Charts (가격 캔들) + Recharts (통계·자산 추이) 결합** |

#### 결정 37 — DB 단계화 상세
- **MVP**: SQLite (`backend/data/tradebot.db`), upbit 패턴 일관, 단일 파일 백업 쉬움
- **운영 안정 후**: Supabase Postgres (무료 500MB Tier), Vercel 친화, 자동 백업, 다중 클라이언트
- 마이그 시점: 사용자 결정 (운영 1~3개월 후)
- 추상화: `backend/services/db.py`에서 SQLAlchemy 2.0 ORM 사용 → DB 전환 시 connection string만 변경

#### 결정 38 — Google OAuth 화이트리스트 상세
- **Gmail 주소 확정**: `suauncle@gmail.com` (사용자 2026-06-19 확정)
- 구현: `frontend/app/api/auth/[...nextauth]/route.ts` 의 `signIn` 콜백
  ```typescript
  callbacks: {
    signIn: async ({ user }) => user.email === process.env.ALLOWED_EMAIL
  }
  ```
- 환경변수 (optimus8 서버 .env): `ALLOWED_EMAIL=suauncle@gmail.com`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `NEXTAUTH_SECRET`
- 외부인 로그인 차단 보장

### 6.5.2 추가 인프라·운영 결정 (2026-06-19 확정)

| # | 항목 | 확정값 |
|---|---|---|
| **42** | **Frontend 호스팅 + CI/CD + 도메인** | **`optimus8.cafe24.com` self-host** (Vercel 미사용, 추가 서브도메인 X) + **GitHub Actions SSH deploy** (git push → 자동 빌드·배포) |
| **43** | **운영 모니터링** | **Telegram 알림만** (Sentry 등 미추가, upbit 패턴 일관). Phase 2에 검토. |
| **44** | **API 스펙** | **FastAPI 자동 생성 OpenAPI 3.0** (`/docs` Swagger UI + `/openapi.json` 자동 노출, 별도 작업 X) |
| **45** | **외부 데이터 소스 — 무료 최대 활용 (Toss API 분리)** | **자동매매 코어**: Toss API 전용 (시세·주문·잔고). **Discovery**: Toss API 미사용. Stooq (1차 가격·52w) + Yahoo (백업) + Finnhub Free 어닝 + SEC EDGAR Form 4 + FINRA 공매도 + Reddit PRAW + PRNewswire/GlobeNewswire RSS + BiopharmaWatch FDA Calendar. 모두 무료. |

#### 결정 42 — Frontend self-host + CI/CD 상세
- **호스팅**: optimus8.cafe24.com 서버에 Node.js + PM2로 Next.js production 실행
- **도메인**: **`optimus8.cafe24.com`** (cafe24 호스팅 기본 도메인 그대로, 2026-06-19 사용자 확정)
  - cafe24 자체가 이미 `optimus8.cafe24.com` 형태의 호스팅 서브도메인 구조
  - 추가 서브도메인 (`tradebot.optimus8...`) 셋업 X — 단순화
  - 향후 사용자가 별도 도메인 등록 시 매핑 가능 (Phase 2)
- **Reverse Proxy**: Nginx (Backend FastAPI + Frontend Next.js 단일 서버 단일 도메인 라우팅)
  - `/api/*` → FastAPI :8000
  - `/*` → Next.js :3000
- **SSL**: cafe24 무료 SSL 또는 Let's Encrypt + certbot (자동 갱신)
- **CI/CD**: GitHub Actions workflow `.github/workflows/deploy.yml`
  - Trigger: `push to main`
  - Steps: SSH → `git pull && npm install && npm run build && pm2 restart tradebot-frontend`
  - **SSH 키 기반 인증** (GitHub Secrets에 private key, 비밀번호 X)
  - 가드레일 §1: 자격증명 GitHub Actions에서 절대 출력·로그 X
- **장단점**:
  - ✅ 단일 서버 관리, 외부 의존성 ↓, 데이터 주권, **셋업 단순**
  - ⚠️ Vercel CDN·최적화·자동 deploy 포기 → 빌드 시간 ↑

#### 결정 43 — 운영 모니터링 상세
- **알림 채널**: Telegram만 (Bot API)
- **알림 종류** (upbit 패턴 차용):
  - 자동매매 매수/매도 (Critical)
  - 매수/매도 실패 (Critical)
  - Discovery cron 결과 (Info)
  - 시스템 stale (Warning, watchdog cron)
  - 시드 손익 일/주간 다이제스트
- **Phase 2 추가 후보** (필요 시): Sentry 5K events/월 무료 Tier

#### 결정 44 — FastAPI 자동 OpenAPI 상세
- FastAPI는 모든 라우트의 OpenAPI 3.0 스펙 자동 생성
- 접근: `https://optimus8.cafe24.com/docs` (Swagger UI), `/redoc` (Redoc), `/openapi.json` (raw spec)
- 별도 작성·유지 부담 0
- Frontend (Next.js) TypeScript 타입 자동 생성 가능 (openapi-typescript)

#### 결정 45 — 외부 데이터 무료 소스 매트릭스 (2026-06-19 Toss API 분리)

**자동매매 코어 전용** (Toss API):
| 카테고리 | 1차 | 2차 백업 |
|---|---|---|
| 미국 시세 | Toss API | — |
| 잔고·주문 | Toss API | — |

**Discovery 전용 (Toss API 미사용)**:
| 카테고리 | 1차 (안정) | 2차 (보조) | 3차 (실험) |
|---|---|---|---|
| 미국 가격·52w | **Stooq** (무료, key 없음, 전체 종목) | Yahoo Finance (불안정) | Finnhub Free |
| 어닝 캘린더 | **Finnhub Free** (60/min) | Yahoo Finance | Earningswhispers (스크래핑) |
| 공시 (Form 4) | **SEC EDGAR** (무료 공식) | OpenInsider | — |
| 공매도 SI% | **FINRA** (무료 공개) | Stockgrid (스크래핑) | — |
| 뉴스·보도자료 | **PRNewswire RSS** + **GlobeNewswire RSS** | Finnhub News | Yahoo Finance News |
| FDA Calendar | **BiopharmaWatch** | FDA Calendar (SEC) | ClinicalTrials.gov |
| 소셜 | **Reddit PRAW** (60/min) | StockTwits API (무료 한도) | X 검색 (제한 큼) |
| 옵션 (Phase 2 후보) | — | — | Polygon Starter $29/월 |

→ **모든 1차 + 2차 무료**. Phase 2까지 운영비 $0 (Anthropic LLM 제외).

#### 분리 사유 (2026-06-19 결정 변경)

- Toss API 주 가치 = **자동매매 (주문 실행)**, Discovery에 묶을 이유 없음
- Stooq는 52w 고가/저가 **직접 제공** (Toss는 일봉으로 계산해야)
- Stooq는 **전체 미국 종목 커버** (Toss는 universe 불확실)
- Toss API rate limit 자동매매 코어가 100% 사용 가능 — 안정성 ↑
- Discovery는 cron 기반 (일 1회) → 외부 소스 rate 무관

---

#### 결정 39 — 차트 라이브러리 결합 사용
- **TradingView Lightweight Charts** (Apache 2.0, 35KB):
  - `/positions`, `/moonshot`, `/crazy` 의 가격 캔들 차트
  - Moonshot 매수가 3 옵션 overlay 표시
  - 평단가·52w 고가/저가 horizontal line
- **Recharts** (MIT, ~90KB):
  - `/dashboard` 의 자산 추이 (Area), 일일 손익 (Bar), 보유 비중 (Pie)
  - shadcn/ui 디자인 시스템과 자연 어울림
- 총 번들: ~125KB (수용 가능)

### 6.2 잔여 조사
- **Toss Open API 공식 문서 조사**
  - 미국 주식 (개별주 + ETF) 거래 가능 여부
  - SPCX 거래 가능 여부
  - 시세 조회 API
  - 잔고·주문 조회 API
  - 약관: 자동매매 허용 여부
  - paper trading 모드 가능 여부
- **외부 데이터 소스 검증**
  - yfinance 라이브러리 작동 확인
  - Reddit PRAW 무료 API 한도 확인
  - FINRA 공매도 데이터 접근

### 6.3 다음 단계 (PRD 흐름)
1. 본 문서 (`02-strategy-decision.md`) 검토 후 확정
2. Toss API + 외부 데이터 가용성 조사 → 결과를 `docs/analysis/toss-api-survey.md`에 기록
3. `03-PRD-v1.md` 초안 작성 (시스템 구조 + 모듈 명세 + 기술 스택)
4. PRD 확정 → 설계 단계 (`docs/architecture/`)
5. 구현 단계 (`core/`, `engine/`, `services/`)
6. 테스트 단계 (`tests/`)
7. 운영 진입

---

## 7. 변경 이력

| 날짜 | 변경 | 비고 |
|---|---|---|
| 2026-06-16 | 초안 작성 — 13개 코어 결정 + 7개 Discovery 결정 + SPCX 특수 처리 | 사용자 승인 후 저장 |
| 2026-06-16 | 잔여 결정 3건 확정 — SPCX 예산 +500만 / 전체 동시 감시 / Claude API 키 보유 확인 (upbit .env) | §6.1 갱신 |
| 2026-06-17 | MANGOS 포괄 라벨 명시 + Anthropic/OpenAI 상장 모니터링 + 결정 21/22 (양자·보안 와이트리스트 13종 + 부스트 ×1.10) | §2.2 / §3 / §6.2 / 결정 매트릭스 9→11 |
| 2026-06-18 | Toss OpenAPI 1.1.1 정독 반영 — §2.5 신설(결정 23/24/25 운영 정책) + 결정 15·18 갱신 + §6.3 콘솔 검증 6항목 + 결정 26(환전) 보류 | 결정 매트릭스 22→25 + 보류 1 |
| 2026-06-18 | **Moonshot Picks 신규 모듈 신설** — §3 재구성 (3.1 Crazy + 3.2 Moonshot) + 결정 27~36 (10개) + DB 스키마 + /moonshot CLI 명세 + Claude Code Skill + §1 다이어그램 3 모듈로 확장 + §4 자금 분리 갱신 (총 시드 1,000→1,600만) | 결정 매트릭스 25→35 + 보류 1 |
| 2026-06-18 | **Frontend Streamlit → Next.js + Vercel 전환** — 결정 18 갱신 + §1·§3.1.3·§3.2.1·§3.2.5 표기 변경. 사유: Streamlit 유연성 부족, Next.js로 production-grade 대시보드 | — |
| 2026-06-18 | **기술 스택 3 결정 확정** (PRD v0.1 작성 중) — §6.5 신설 — 결정 37 (DB: SQLite→Supabase) + 결정 38 (Google OAuth + Gmail 화이트리스트) + 결정 39 (TradingView Lightweight + Recharts 결합) | 결정 매트릭스 35→38 + 보류 1 |
| 2026-06-18 | **Moonshot Universe 재정의 — 페니스톡 포함 모든 미국 주식** (사용자 명시: "최대한 모든 가능성에 투자"). 결정 31 갱신 (시총 제한 거의 없음, 최소 필터만) + 결정 32 갱신 (6→8 인자, 갭+거래량 + 52w 저점 추가) + 결정 33 갱신 (페니스톡엔 (b) 떡락 대기 우선) + 결정 40 신설 (HIGH/MED/LOW 위험 수준 + manipulation 평가) + §3.2.7 신설 (EHGO·AZTR 첫 백테스트 케이스) | 결정 매트릭스 38→39 + 보류 1 / 03 §4.3 동기 |
| 2026-06-18 | **Phase 1 능동적 발굴 — 5 패턴 학술 검증 후 가중치 재조정** (PEAD ⬆ 25→30%, 갭+거래량 ⬆ 8→12%, 스퀴즈 ⬇ 10→6%, 소셜 ⬇ 15→8%) + 결정 32 갱신 (8→9 인자) + 결정 41 신설 (인사이더 매수 SEC Form 4, 가중 10%) + §3.2.8 신설 (H1~H5 신규 가설 5종 Phase 2 검증 대상) + DB 스키마 score_insider 컬럼 추가 | 결정 매트릭스 39→41 + 보류 1 / docs/analysis/moonshot-factor-research.md 생성 (별도) |
| 2026-06-19 | **Phase 1 완전 완료 — F5·F7 추가 검증**. F5 (FDA·임상) ✅ → 결정 32 카탈리스트 sub-category 명시 (PDUFA·AdCom 추적). F7 (갭다운 안정화) ⚠️ 약함 → §3.2.8 H3 결합 sub-condition으로 통합. **결정 32 가중치 변경 없음**. F1~F7 모든 패턴 학술 검증 완료 — Phase 1 종료, Phase 2 운영 데이터 대기. | docs/analysis/moonshot-factor-research.md v2 갱신 |
| 2026-06-19 | **잔여 결정 4건 확정 (결정 42·43·44·45) + 결정 38 ALLOWED_EMAIL 값 명시** — Frontend 호스팅을 **Vercel → optimus8 self-host + GitHub Actions CI/CD**로 전환 (사용자 결정). 운영 모니터링 Telegram만. FastAPI 자동 OpenAPI. 외부 데이터 무료 최대 활용. 결정 38 ALLOWED_EMAIL=suauncle@gmail.com 확정. §6.5.2 신설. | 결정 매트릭스 41→45 + 보류 1 (결정 26 환전) |
| 2026-06-19 | **도메인 확정 — `optimus8.cafe24.com` 그대로 사용** (결정 42 부속). cafe24 기본 호스팅 도메인 (이미 서브도메인 구조)을 그대로 활용, 추가 서브도메인 셋업 X. 02·03 도메인 표기 통일. | 잔여 결정 3→2건 (콘솔 검증·결정 26 환전만 남음) |
| 2026-06-19 | **/moonshot Claude Code Skill placeholder 생성** (.claude/skills/moonshot.md, 114줄). CLI 미설치 시 안내 메시지, PRD v1.0 구현 후 자동 활성화. 02 §3.2.4 Skill 위치·구조 정정. .gitignore `!.claude/skills/` 추가. | Skill placeholder 완성 |
| 2026-06-19 | **데이터 스택 분리 — Discovery에서 Toss API 미사용** (사용자 본질 통찰). Toss API = 자동매매 코어 전용 (주문 실행). Discovery (Crazy + Moonshot) = Stooq + Finnhub Free + SEC EDGAR + FINRA + Reddit PRAW + RSS 등 외부 무료 소스 1차. 결정 15·23·24·45 모두 갱신. §3.1.3·§3.2.1 운영 원리 동기. | 자동매매 Toss rate 100% 보장 / Discovery 데이터 풍부도 ↑ |
