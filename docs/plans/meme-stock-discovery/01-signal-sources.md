# 01. 시그널 소스 명세

**작성일**: 2026-06-25
**결정 기준**: 00 문서의 Q1=B / Q2=A / Q3=A / Q4=A / Q5=B 사용자 승인
**상태**: 명세 완료 — 02 (Confluence 점수 설계) 진행 가능

> **트랙 분리**: 미국(US) 트랙 = 모델 학습 + 실 운영. KRX 트랙 = 변형
> 패턴(테마주·작전주) 별도 운영. 두 트랙 모두 5요소 confluence 구조를
>공유하지만 데이터 소스가 다름.

---

## 1. 5요소 매핑 — 트랙별

### 1.1 미국(US) 트랙

| 요소 | 데이터 소스 | 라이브러리 | 임계값 (1차) |
|---|---|---|---|
| ① 공매도 잔고 | FINRA Short Interest + Yahoo `shortPercentOfFloat` | `yfinance` + FINRA CSV | ≥ 15% |
| ② 소셜 모멘텀 | Reddit (WSB/stocks/pennystocks) + Stocktwits sentiment + Google Trends | `praw` + `requests` + `pytrends` | z-score ≥ +3σ (24h) |
| ③ 유동성 폭주 | Yahoo Finance 일별 거래량 | `yfinance` | z-score ≥ +5σ (20D) |
| ④ Oversold + 반전 | 일봉 종가에서 RSI(14) + 단기 반등 (1D %) | 자체 계산 | RSI ≤ 30 AND 1D ≥ +5% |
| ⑤ Catalyst | Yahoo `tradingHalt` + 가격 변동률 ≥ ±10% | `yfinance` + 자체 | gap up ≥ +15% 시 자동 검출 |

### 1.2 KRX (한국) 트랙

| 요소 | 데이터 소스 | 라이브러리 | 임계값 (1차) |
|---|---|---|---|
| ① 공매도 잔고 | KRX 공매도 잔고 일별 공시 | `pykrx.stock.get_shorting_balance_by_ticker` | ≥ 5% (한국 평균 낮음) |
| ② 소셜 모멘텀 | Google Trends KR + (후속) 네이버·디시 | `pytrends` | z-score ≥ +3σ (24h) |
| ③ 유동성 폭주 | KRX 일별 거래량 | `pykrx` | z-score ≥ +5σ (20D) |
| ④ Oversold + 반전 | 일봉 RSI + 1D 반등 | 자체 계산 | RSI ≤ 30 AND 1D ≥ +5% |
| ⑤ Catalyst | KRX VI 발동·관리종목·거래정지 공시 | DART OpenAPI + KRX 공식 | VI 발동 시 자동 |

---

## 2. 데이터 소스별 명세

### 2.1 Reddit (US 트랙 핵심)

> ⚠️ **2025-11 정책 변경**: Reddit self-service API key 발급 폐지. 모든
> OAuth credentials manual approval 필요 (7일 응답). 대안으로 **공개 JSON
> endpoint** 사용 (무인증, 정책 부합).
>
> 결정: **B + A 병행** (Q26, 2026-06-26):
> - B = 공개 JSON endpoint 즉시 진행 (Phase 1c MVP)
> - A = Developer Support form 신청 → 7일 후 OAuth 발급 시 전환

| 항목 | 값 (Phase 1c MVP — 공개 JSON) |
|---|---|
| **공식 안내** | https://www.reddit.com/dev/api/ · Responsible Builder Policy |
| **라이브러리** | `httpx` (직접 JSON fetch) |
| **인증** | 없음 (공개 endpoint) |
| **Rate limit** | 60 QPM (IP 기반) — 우리 사용 ~0.8 QPM (1.3%) |
| **User-Agent** | `toss-tradebot-mvp:meme-watch:v0.1 (by /u/Gonnim)` |
| **Endpoint** | `https://www.reddit.com/r/{subreddit}/new.json?limit=100` |
| **모니터 대상** | r/wallstreetbets, r/stocks, r/pennystocks, r/Shortsqueeze |
| **수집 방식** | 5분 주기 batch + 종목 ticker 정규식 (`\$([A-Z]{1,5})`) |
| **카운트 단위** | 24시간 윈도우 언급 횟수 + upvote(score) 가중 |
| **저장** | `meme_social_signal` (ticker, source="reddit", count, weighted_score) |
| **정책 부합** | 공개 데이터만, 본문 저장 X, AI 학습 X, 재배포 X |

**실패 폴백**: 공개 endpoint 차단/rate limit 발생 시 → Stocktwits + Google
Trends 가중치 재정규화 + 운영 ERROR 로그 (메모리 [[partner_accountability]]).

**OAuth 전환 (후속)**: A 승인 후 `praw` 도입 + `REDDIT_CLIENT_ID/SECRET`
secrets 추가 + Phase 1c 의 fetch 함수만 교체 (signal 산출 로직 그대로).

### 2.2 Stocktwits (US 보조)

| 항목 | 값 |
|---|---|
| **공식 문서** | https://api.stocktwits.com/developers/docs |
| **라이브러리** | `httpx` (REST) |
| **인증** | 무인증 (rate limit 200 QPH) — Partner key 시 ↑ |
| **엔드포인트** | `GET /streams/symbol/{ticker}.json` |
| **수집 방식** | 매 5분 — 종목별 최근 30개 메시지의 `sentiment` (`Bullish` / `Bearish` / null) 비율 |
| **카운트 단위** | (Bullish − Bearish) / total — sentiment delta |
| **저장** | `meme_social_signal` 테이블 (source="stocktwits") |

### 2.3 Google Trends (양 트랙)

| 항목 | 값 |
|---|---|
| **공식 문서** | https://trends.google.com/trends/ (비공식 API) |
| **라이브러리** | `pytrends` |
| **인증** | 없음 |
| **Rate limit** | 비공식 — 5분에 ~10건 안전 |
| **수집 방식** | 종목명 24시간 검색량 (geo="US"/"KR") |
| **카운트 단위** | 0~100 정규화된 검색량 |
| **저장** | `meme_social_signal` 테이블 (source="google_trends") |

**실패 폴백**: pytrends 차단 시 → 단순 skip + Confluence 가중치 재정규화.

### 2.4 FINRA Short Interest (US ①)

| 항목 | 값 |
|---|---|
| **공식 문서** | https://www.finra.org/finra-data/short-sale-volume-daily |
| **수집 방식** | 격주 발표 CSV 다운로드 (Settlement Date 기준) |
| **카운트 단위** | shortInterest / float — % |
| **저장** | `meme_short_interest` 테이블 (ticker, pct, settlement_date) |
| **보완** | Yahoo `Ticker.info["shortPercentOfFloat"]` 일별 estimate 병행 |

### 2.5 KRX 공매도 (KRX ①)

| 항목 | 값 |
|---|---|
| **공식 문서** | https://data.krx.co.kr/ (KRX 정보데이터시스템) |
| **라이브러리** | `pykrx.stock.get_shorting_balance_by_ticker(date, ticker)` (이미 의존성에 있음) |
| **카운트 단위** | 공매도 잔고 / 상장주식수 × 100% |
| **저장** | `meme_short_interest` 테이블 |
| **주의** | KRX 공매도는 한국 평균 5% 미만 — 임계값을 미국(15%)보다 낮춰야 |

### 2.6 Yahoo Finance 거래량 (US ③④⑤)

| 항목 | 값 |
|---|---|
| **공식 문서** | https://pypi.org/project/yfinance/ |
| **라이브러리** | `yfinance` |
| **인증** | 없음 |
| **수집 방식** | `Ticker(ticker).history(period="60d", interval="1d")` |
| **계산** | 20일 거래량 평균·표준편차 → 당일 거래량의 z-score |
| **저장** | `meme_volume_snapshot` 테이블 (ticker, date, volume, z_score, return_1d, rsi_14) |

### 2.7 pykrx 거래량 (KRX ③④⑤)

이미 sector_leaders 모듈에서 사용 중. 재활용.

---

## 3. 환경 설정 — secrets

`backend/.env` (운영에는 평문 금지, GitHub Actions secrets에 등록):

```bash
# US 트랙
REDDIT_CLIENT_ID=<set>
REDDIT_CLIENT_SECRET=<set>
REDDIT_USER_AGENT=toss-tradebot-mvp/meme-watch:v1 by /u/<user>

# KRX 트랙 — 신규 키 불필요 (pykrx 무인증)
# DART_API_KEY=<set>  # 후속 ⑤ catalyst event 용
```

> ⚠️ Global guard rail §1 — .env 평문 자격증명 금지. `.env.example`은
> placeholder만, 실제 값은 운영 .env 또는 GitHub Secrets.

---

## 4. 종목 universe — 어디서 가져오나

| 트랙 | universe 출처 | 크기 |
|---|---|---|
| US | S&P 500 + Russell 2000 + Yahoo `most_actives` + Reddit 언급 종목 합집합 | ~2,500 |
| KRX | KOSPI + KOSDAQ 전체 | ~2,500 |

**1차 MVP**: US는 Russell 2000 + Reddit 언급, KRX는 KOSDAQ 전체로 축소.

---

## 5. 시그널 → DB 스키마 (제안)

신규 테이블 4개. SQLAlchemy 2.0 async + sqlite (기존 토스 DB와 같이).

```python
class MemeUniverse(Base):
    """추적 대상 종목 마스터."""
    __tablename__ = "meme_universe"
    id: Mapped[int] = mapped_column(primary_key=True)
    market: Mapped[str]      # "US" / "KRX"
    ticker: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    sector: Mapped[Optional[str]]
    market_cap: Mapped[Optional[float]]
    is_active: Mapped[bool] = mapped_column(default=True)


class MemeSocialSignal(Base):
    """소셜 시그널 — 5분 batch 누적."""
    __tablename__ = "meme_social_signal"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(index=True)
    source: Mapped[str]        # "reddit" / "stocktwits" / "google_trends"
    fetched_at: Mapped[datetime] = mapped_column(index=True)
    mention_count: Mapped[int]
    weighted_score: Mapped[float]   # upvote/score 가중
    sentiment_delta: Mapped[Optional[float]]  # stocktwits 전용
    window_hours: Mapped[int]  # 24 (24h 누적) / 1 (실시간)


class MemeShortInterest(Base):
    """공매도 잔고."""
    __tablename__ = "meme_short_interest"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(index=True)
    market: Mapped[str]        # "US" / "KRX"
    as_of_date: Mapped[date]
    pct_of_float: Mapped[float]
    days_to_cover: Mapped[Optional[float]]
    source: Mapped[str]        # "finra" / "krx" / "yahoo_estimate"


class MemeVolumeSnapshot(Base):
    """일봉 거래량·반등·RSI 스냅샷."""
    __tablename__ = "meme_volume_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(index=True)
    snapshot_at: Mapped[datetime] = mapped_column(index=True)
    volume: Mapped[float]
    volume_z_20d: Mapped[float]
    return_1d_pct: Mapped[float]
    rsi_14: Mapped[Optional[float]]
    halt_triggered: Mapped[bool] = mapped_column(default=False)
```

---

## 6. 시그널 갱신 잡 — APScheduler

`backend/discovery/data_sources/meme/scheduler.py` 신규.

| 잡 ID | trigger | 동작 |
|---|---|---|
| `meme_social_5min` | 5분마다 (장중만) | Reddit + Stocktwits + Google Trends fetch → social_signal |
| `meme_volume_5min` | 5분마다 (장중만) | yfinance + pykrx 현재 거래량 → volume_snapshot |
| `meme_short_daily` | 매일 06:00 KST | FINRA + KRX 공매도 잔고 → short_interest |
| `meme_universe_weekly` | 매 일요일 03:00 KST | Russell 2000 + KOSDAQ 종목 마스터 갱신 |

장중 정의:
- US: 22:30~05:00 KST (DST 자동 보정)
- KRX: 09:00~15:30 KST

---

## 7. 외부 API 실패 시 정책 (메모리 [[feedback_partner_accountability]])

| 시나리오 | 정책 |
|---|---|
| Reddit 401/429 | 로그 ERROR + 30초 재시도 → 1회 실패 후 Stocktwits·Google Trends 가중치 ↑ 재정규화 (Confluence 점수 그대로 계산 가능) |
| Stocktwits rate limit | 5분 skip → 다음 cycle |
| pytrends 차단 (Captcha) | 1시간 backoff → 차단 지속 시 운영자 알림 (logs 모듈에 ERROR) |
| FINRA CSV 미발표 | Yahoo estimate fallback |
| KRX 공매도 미공시 | 직전 값 carry-forward + WARN 로그 |
| Yahoo Finance 다운 | pykrx US (없음 — yfinance만 가능) → 잡 skip + 다음 cycle |

> ⚠️ "(timeout)" 빈 값으로 마무리 금지. 모든 실패는 `logs` 테이블에
> `module="meme_signal"` 로 기록, 로그 페이지 자동 갱신 이력 탭에 노출.

---

## 8. 개발 우선순위 (Phase 1 MVP)

| Phase | 범위 | 예상 |
|---|---|---|
| **1a** | DB 스키마 + Universe 잡 + KRX 공매도 잡 (가장 안정) | 2~3일 |
| **1b** | yfinance 거래량 + RSI/return 계산 | 1~2일 |
| **1c** | Reddit 클라이언트 (US 트랙 핵심) | 2일 |
| **1d** | Stocktwits + Google Trends | 1일 |
| **1e** | Confluence 점수 (02 문서) | 1일 |
| **1f** | UI (`/meme-watch`) | 2~3일 |
| **2** | DART 공시 + KRX VI · FINRA 격주 | 후속 |

**총 ~10~12일** (1인 기준, 외부 API 인증 등록 시간 포함).

---

## 9. 미해결 사항 — 사용자 결정 대기

### Q6. Reddit 앱 등록 누가?
- A. 사용자가 Reddit 계정으로 직접 등록 (https://www.reddit.com/prefs/apps) — 5분 작업
- B. 새 dedicated 계정 생성

→ **A 권장** (계정 분리는 의미 없음).

### Q7. universe 크기 (1차)
- A. US Russell 2000 + KOSDAQ 전체 (≈4,500 종목) — Reddit 모니터 부담 ↑
- B. US 시총 ≤ 5B + KOSDAQ 시총 ≤ 1조원 (≈1,500) ← **추천** (밈주는 작은 종목 위주)
- C. US Reddit 언급 종목만 + KOSDAQ 거래량 상위 100

### Q8. catalyst event ⑤ 1차 포함?
- A. Phase 1 포함 (가용한 만큼: yfinance gap up + KRX VI)
- B. Phase 2 로 분리 ← **추천** (구현 난이도 ↑, 다른 4 시그널만으로도 충분)

### Q9. KRX 트랙의 소셜 시그널
- A. Google Trends 만 (1차) ← **추천**
- B. + 네이버종토방·디시 크롤링 즉시
- C. KRX 트랙은 소셜 시그널 제외, 공매도·거래량만

### Q10. UI 우선순위
- A. `/meme-watch` 페이지 + Top 10 워치리스트
- B. + 알림 (push) 후속
- C. + 차트 시각화 (5요소 레이더 차트)

→ **A 1차 + C 빠르게 추가 권장**.

---

## 10. 빠른 답변 예시

> "Q6=A, Q7=B, Q8=B, Q9=A, Q10=A, 진행"

이렇게 답주시면 다음 단계 (02-confluence-design.md) 작성합니다.
