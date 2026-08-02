# 02 · Backend Architecture · Serenity Integration

> **의존**: [README.md](./README.md) · [01-ui-spec.md](./01-ui-spec.md)
>
> **범위**: 데이터 파이프라인 · Supabase 스키마 SQL DDL · z.ai 프롬프트 · Python 스코어링 함수 · Cron 스케줄

## 1. 데이터 흐름 (End-to-End)

```
[serenity-tracker Git submodule / local sync]
  ├─ data/aleabitoreddit_tweets.json (6,222 트윗 아카이브)
  ├─ data/ticker_stats.txt
  └─ references/{theses.md, methodology.md, track-record.md}
       ↓
       ↓  L1 · serenity_crawler.py (매일 06:00 KST)
       ↓
[Supabase · serenity_tweets] ← 신규 트윗 upsert
       ↓
       ↓  L2 · serenity_extractor.py (매일 07:00 KST · z.ai GLM-5.2)
       ↓
[Supabase · serenity_signals] ← 트윗별 (ticker, sentiment, thesis_type) 추출
       ↓
       ↓  L3 · serenity_scorer.py (매일 08:00 KST)
       ↓
[Supabase · discovery_serenity_scores] ← 티커별 15원칙 총 스코어 + auto_avoid
       ↓
       ↓  L4 · serenity_backtest.py (매주 월 00:00 KST)
       ↓
[Supabase · serenity_backtest] ← signal → 실 주가 (yfinance) 대조

Frontend (Next.js) ← Supabase RLS-protected read
```

## 2. Supabase 스키마 (SQL DDL)

**위치**: `backend/alembic/versions/XX_serenity_integration.py` (Alembic migration)

### 2.1 신규 테이블 4개

```sql
-- ============================================================
-- L1 · serenity_tweets — 전체 트윗 아카이브
-- ============================================================
CREATE TABLE serenity_tweets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tweet_id BIGINT UNIQUE NOT NULL,
  url TEXT NOT NULL,
  posted_at TIMESTAMPTZ NOT NULL,
  text TEXT NOT NULL,
  reply_to_id BIGINT,
  quoted_id BIGINT,
  metrics JSONB,                    -- likes, views, retweets
  raw_json JSONB,                   -- 원본 트윗 JSON 전체 보존
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_serenity_tweets_posted_at ON serenity_tweets(posted_at DESC);
CREATE INDEX idx_serenity_tweets_reply_to ON serenity_tweets(reply_to_id) WHERE reply_to_id IS NOT NULL;

-- ============================================================
-- L2 · serenity_signals — 트윗별 z.ai 추출 signal (ticker × sentiment)
-- ============================================================
CREATE TYPE serenity_sentiment AS ENUM ('bullish', 'bearish', 'neutral', 'calibration');
CREATE TYPE serenity_thesis_type AS ENUM ('new_bottleneck', 'reaffirmation', 'watchlist', 'victory_lap');
CREATE TYPE serenity_evidence_type AS ENUM (
  'earnings', 'contract', 'insider_buy', 'sellside_upgrade',
  'macro', 'policy', 'ownership_disclosure', 'watchlist', 'other'
);

CREATE TABLE serenity_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tweet_id BIGINT NOT NULL REFERENCES serenity_tweets(tweet_id),
  ticker TEXT NOT NULL,             -- e.g. 'NBIS', 'SIVE'
  sentiment serenity_sentiment NOT NULL,
  thesis_type serenity_thesis_type,
  evidence_type serenity_evidence_type,
  confidence NUMERIC(3, 2) NOT NULL, -- 0.00 - 1.00 · z.ai 자기 판단
  extracted_reasoning TEXT,          -- z.ai 요약 1-2줄
  extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tweet_id, ticker)
);
CREATE INDEX idx_serenity_signals_ticker_time ON serenity_signals(ticker, extracted_at DESC);
CREATE INDEX idx_serenity_signals_sentiment ON serenity_signals(sentiment, extracted_at DESC);

-- ============================================================
-- L3 · discovery_serenity_scores — 티커별 15원칙 스코어 (매일 갱신)
-- ============================================================
CREATE TYPE financing_tier AS ENUM ('S', 'A', 'B', 'C', 'D', 'F');

CREATE TABLE discovery_serenity_scores (
  ticker TEXT PRIMARY KEY,
  -- 원칙 1 · Bottleneck
  bottleneck_score SMALLINT CHECK (bottleneck_score BETWEEN 0 AND 10),
  bom_pct NUMERIC(5, 2),                  -- 다운스트림 BOM 내 비율 %
  -- 원칙 3 · Contract ARR
  contracted_arr_multiple NUMERIC(5, 2),
  -- 원칙 4 · Mag7
  mag7_customer_count SMALLINT CHECK (mag7_customer_count BETWEEN 0 AND 7),
  -- 원칙 5 · GAAP Margin
  gaap_gross_margin NUMERIC(5, 2),        -- %
  -- 원칙 6 · Qualification
  is_pre_ramp BOOLEAN,
  -- 원칙 7 · Dilution
  active_atm_pct_of_mc NUMERIC(5, 2),     -- % · > 40% = auto_avoid
  -- 원칙 8 · Financing Tier
  financing_tier financing_tier,
  -- 원칙 9 · Short Squeeze
  short_interest_pct NUMERIC(5, 2),
  is_profitable BOOLEAN,
  -- 원칙 11 · Institutional Lag
  institutional_holdings_delta_30d NUMERIC(5, 2),  -- Δ % over 30d
  -- 원칙 13 · Conviction Tier (Serenity 명시)
  serenity_tier financing_tier,           -- reuse enum · 실 tier
  -- 원칙 14 · Anti-patterns
  anti_pattern_flags TEXT[],              -- e.g. {'non_gaap_abuse', 'sbc_high'}
  -- 종합
  total_score INT NOT NULL DEFAULT 0,
  auto_avoid BOOLEAN NOT NULL DEFAULT FALSE,
  domain_tags TEXT[],                     -- {'optical_cpo', 'inp_substrates', ...}
  last_signal_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_scores_total_desc ON discovery_serenity_scores(total_score DESC) WHERE auto_avoid = FALSE;

-- ============================================================
-- L4 · serenity_backtest — signal → 실 주가 대조 (주간 재계산)
-- ============================================================
CREATE TABLE serenity_backtest (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES serenity_signals(id),
  ticker TEXT NOT NULL,
  signal_date DATE NOT NULL,
  price_at_signal NUMERIC(12, 4),
  return_5d NUMERIC(6, 2),                -- %
  return_10d NUMERIC(6, 2),
  return_30d NUMERIC(6, 2),
  return_60d NUMERIC(6, 2),
  return_180d NUMERIC(6, 2),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (signal_id)
);
CREATE INDEX idx_backtest_ticker_date ON serenity_backtest(ticker, signal_date DESC);
```

### 2.2 RLS (Row Level Security)

Toss Tradebot 기존 인증 정책 확인 후 다음 정책 중 선택:
- **Option A** — Public read (Influencer 페이지 인증 없음)
- **Option B** — Authenticated read only (기존 admin 게이트 재활용)

```sql
-- Option B 예시
ALTER TABLE serenity_tweets ENABLE ROW LEVEL SECURITY;
ALTER TABLE serenity_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovery_serenity_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE serenity_backtest ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated read all"
ON serenity_tweets FOR SELECT
TO authenticated
USING (true);
-- (동일 정책을 나머지 3 테이블에 반복)
```

## 3. 크롤러 · L1 (`backend/discovery/serenity/crawler.py`)

### 3.1 책임
- `~/GON-Dev/serenity-tracker/data/aleabitoreddit_tweets.json` 로드
- 신규 tweet_id 필터 (기존 DB max tweet_id 이후만)
- `serenity_tweets` 테이블에 upsert

### 3.2 스켈레톤

```python
"""Serenity 트윗 아카이브 → Supabase serenity_tweets 동기화.

로컬 serenity-tracker (yan-labs/serenity-aleabitoreddit) 의
data/aleabitoreddit_tweets.json 을 읽어 신규 트윗만 upsert.

Cron: 매일 06:00 KST
전제:
  - serenity-tracker 는 별도 git submodule 또는 로컬 clone (경로 env `SERENITY_TRACKER_DIR`)
  - update.py 는 사용자 수동 실행 (인증 필요 · X 계정 접근)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.services.supabase_client import get_supabase_admin

DEFAULT_TRACKER_DIR = Path(os.environ.get(
    "SERENITY_TRACKER_DIR",
    Path.home() / "GON-Dev" / "serenity-tracker",
))


def load_archive_tweets(tracker_dir: Path = DEFAULT_TRACKER_DIR) -> list[dict]:
    archive_path = tracker_dir / "data" / "aleabitoreddit_tweets.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Serenity 아카이브 없음: {archive_path}")
    with archive_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def sync_tweets(tracker_dir: Path = DEFAULT_TRACKER_DIR) -> dict:
    """신규 트윗만 upsert. 반환: {'inserted': N, 'skipped': M}."""
    supabase = get_supabase_admin()

    # 기존 DB 최대 tweet_id (증분 pull)
    max_row = supabase.table("serenity_tweets") \
        .select("tweet_id") \
        .order("tweet_id", desc=True) \
        .limit(1) \
        .execute()
    max_id = max_row.data[0]["tweet_id"] if max_row.data else 0

    tweets = load_archive_tweets(tracker_dir)
    new_tweets = [t for t in tweets if int(t["id"]) > max_id]

    inserted = 0
    for chunk_start in range(0, len(new_tweets), 500):
        chunk = new_tweets[chunk_start:chunk_start + 500]
        rows = [_to_row(t) for t in chunk]
        supabase.table("serenity_tweets").upsert(rows, on_conflict="tweet_id").execute()
        inserted += len(rows)

    return {"inserted": inserted, "skipped": len(tweets) - inserted}


def _to_row(t: dict) -> dict:
    return {
        "tweet_id": int(t["id"]),
        "url": t.get("url") or f"https://x.com/aleabitoreddit/status/{t['id']}",
        "posted_at": t["created_at"],  # ISO string · yan-labs 스키마 확인 후 조정
        "text": t.get("text") or t.get("full_text") or "",
        "reply_to_id": int(t["in_reply_to_status_id"]) if t.get("in_reply_to_status_id") else None,
        "quoted_id": int(t["quoted_status_id"]) if t.get("quoted_status_id") else None,
        "metrics": {
            "likes": t.get("public_metrics", {}).get("like_count"),
            "views": t.get("public_metrics", {}).get("impression_count"),
            "retweets": t.get("public_metrics", {}).get("retweet_count"),
        },
        "raw_json": t,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    result = sync_tweets()
    print(f"Serenity 트윗 sync 완료: {result}")
```

## 4. Extractor · L2 (`backend/discovery/serenity/extractor.py`)

### 4.1 책임
- `serenity_tweets` 에서 `serenity_signals` 에 아직 없는 트윗 조회
- z.ai GLM-5.2 로 각 트윗 → 여러 ticker × sentiment × thesis_type 추출
- `serenity_signals` upsert

### 4.2 z.ai 프롬프트

```python
SYSTEM_PROMPT = """당신은 Serenity(@aleabitoreddit)의 AI/반도체 supply-chain 논지를 분석하는 어시스턴트입니다.

# Serenity 프레임 요약 (methodology.md)

## 15원칙
1. Bottleneck hunting — sole-source · pricing power · small cap
2. Multi-hop BOM / OSINT supply-chain mapping
3. Signed-contract ARR vs. market-cap mismatch — take-or-pay 계약 signing → flip to high conviction
4. Mag7 customer-concentration filter — Mag7 노출 = 담보 · single-customer = 리스크
5. GAAP-margin war — non-GAAP 무시 · 정직한 discloser 저평가
6. Qualification cycle vs. TTM revenue — pre-volume ramp 진입
7. Dilution / ATM calendar as disqualifier — 큰 ATM = 실격
8. Counterparty / financing-quality spectrum — NBIS > CIFR/WULF > IREN > CRWV
9. Short-squeeze setup (profitable-grower)
10. Tariff/macro-shock-as-buy — algo risk-off = 진입
11. Institutional lag — 리테일 4-6주 리드 · 기관 2-4주 lag
12. Vega/IV mispricing (options)
13. Conviction tiering (S/A/B/C/D/F)
14. Anti-patterns — TA·layer 혼동·Reddit sentiment·insider sales bear·cult 밸류에이션
15. 14점 체크리스트

# Serenity 도메인 sub-sector 맵 (theses.md 발췌)
- Optical/CPO: SIVE · LITE · COHR · POET · AAOI · TSEM · GFS · TSM · Innolight · Ayar
- InP substrates: AXTI · IQE
- Compound semi: XFAB · Win Semi · SOI
- Memory/HBM: MU · SNDK · SK Hynix · Samsung
- Neocloud: NBIS (S) · CIFR/WULF (A · Fluidstack colo) · IREN (avoid · $6B ATM) · CRWV (F · $1.3B/y interest)
- AI power: VST · CEG · PWR · ETN · XLU
- Robotics: CCXI · Agility · JBL · Apptronik · Figure · Boston Dynamics
- Space: RKLB · ASTS · SPCX

# 감성 3분류 (Serenity 실 사용)
- bullish: 명시 매수·홀드·촉매 발생·매도 반대
- bearish: 명시 매도·avoid·ATM overhang·anti-pattern
- neutral: watchlist·no-position·supplier map만
- calibration: 이전 논지 재조정·overreach 경고 (예: AAOI CPO design win 없음)

# 작업
다음 트윗을 분석하여 JSON 응답:

{
  "signals": [
    {
      "ticker": "NBIS",
      "sentiment": "bullish" | "bearish" | "neutral" | "calibration",
      "thesis_type": "new_bottleneck" | "reaffirmation" | "watchlist" | "victory_lap",
      "evidence_type": "earnings" | "contract" | "insider_buy" | "sellside_upgrade" | "macro" | "policy" | "ownership_disclosure" | "watchlist" | "other",
      "confidence": 0.85,
      "reasoning": "1-2줄 요약"
    }
  ]
}

# 원칙
- Multi-hop supply chain 논지 감지 시 explicit 종목 외에도 관련 종목 추출 (예: LITE 언급 시 upstream AXTI 관련성 판정 · confidence 낮게)
- Anti-pattern 감지 시 sentiment 재조정
- Serenity "no position" · "exploratory" 명시 시 confidence < 0.5
- Layer 혼동 (substrate ≠ epiwafer ≠ feedstock) 감지 시 warning 필드 추가
- 신뢰도 낮으면 signals 빈 배열 반환 (강제 추출 금지)
"""


def extract_signals(tweet_text: str, tweet_context: dict | None = None) -> list[dict]:
    """z.ai GLM-5.2 로 트윗 → signals 추출."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["ZAI_API_KEY"],
        base_url=os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"),
    )
    model = os.environ.get("ZAI_MODEL", "glm-5.2")

    user_block = f"# 트윗\n{tweet_text}"
    if tweet_context:
        user_block += f"\n\n# 컨텍스트\n{json.dumps(tweet_context, ensure_ascii=False)}"

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ],
        extra_body={"thinking": {"type": "disabled"}},  # z.ai 확장 파라미터
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    return parsed.get("signals", [])
```

### 4.3 실행 함수

```python
def process_pending_tweets(batch_size: int = 100) -> dict:
    """serenity_signals 미처리 트윗 배치 처리."""
    supabase = get_supabase_admin()

    # 아직 signal 추출 안 된 트윗 · 최근 순
    pending = supabase.rpc("get_pending_serenity_tweets", {"limit_n": batch_size}).execute()
    # RPC 없으면 raw SQL: SELECT t.* FROM serenity_tweets t
    #                    LEFT JOIN serenity_signals s ON s.tweet_id = t.tweet_id
    #                    WHERE s.id IS NULL ORDER BY t.posted_at DESC LIMIT batch_size

    inserted = 0
    for tweet in pending.data:
        try:
            signals = extract_signals(tweet["text"], {"posted_at": tweet["posted_at"]})
        except Exception as e:
            print(f"⚠️ 추출 실패 tweet_id={tweet['tweet_id']}: {e}")
            continue

        for s in signals:
            supabase.table("serenity_signals").upsert({
                "tweet_id": tweet["tweet_id"],
                "ticker": s["ticker"].upper(),
                "sentiment": s["sentiment"],
                "thesis_type": s.get("thesis_type"),
                "evidence_type": s.get("evidence_type"),
                "confidence": s.get("confidence", 0.5),
                "extracted_reasoning": s.get("reasoning"),
            }, on_conflict="tweet_id,ticker").execute()
            inserted += 1

    return {"processed_tweets": len(pending.data), "inserted_signals": inserted}
```

## 5. Scorer · L3 (`backend/discovery/serenity/scorer.py`)

### 5.1 15원칙 스코어링 공식

```python
def compute_serenity_score(row: dict) -> tuple[int, bool]:
    """티커별 총 스코어 + auto_avoid 판정.

    row 는 discovery_serenity_scores 후보 dict.
    """
    score = 0
    auto_avoid = False

    # ── Positive ────────────────────────────────────────────
    score += (row.get("bottleneck_score") or 0) * 10          # 최대 100
    score += (row.get("mag7_customer_count") or 0) * 15       # 최대 105
    if (row.get("gaap_gross_margin") or 0) > 60:
        score += 30
    if row.get("is_pre_ramp"):
        score += 40
    if (row.get("contracted_arr_multiple") or 0) > 3:
        score += 50
    if (row.get("institutional_holdings_delta_30d") or 0) < 0:  # 기관 미catch-up = edge
        score += 30

    # ── Negative ────────────────────────────────────────────
    atm_pct = row.get("active_atm_pct_of_mc") or 0
    if atm_pct > 30:
        score -= 100
    score -= len(row.get("anti_pattern_flags") or []) * 20

    # ── Auto-avoid rules ───────────────────────────────────
    if atm_pct > 40:
        auto_avoid = True
    if row.get("financing_tier") in ("D", "F"):
        auto_avoid = True
    if row.get("serenity_tier") == "F":
        auto_avoid = True
    if len(row.get("anti_pattern_flags") or []) >= 3:
        auto_avoid = True

    return score, auto_avoid
```

### 5.2 갱신 파이프라인

```python
def refresh_all_scores() -> int:
    """모든 티커의 스코어 재계산 (매일 08:00 KST)."""
    supabase = get_supabase_admin()

    # 최근 90일 signal 있는 티커만 대상
    tickers_rows = supabase.rpc("get_active_serenity_tickers", {"days": 90}).execute()

    updated = 0
    for row in tickers_rows.data:
        ticker = row["ticker"]

        # 기존 컬럼 + 신규 signal 합쳐 aggregate
        # (bottleneck_score · financing_tier 등은 사용자 수동 편집 또는 별도 소스)
        signals_agg = supabase.rpc("aggregate_serenity_signals", {"target_ticker": ticker}).execute()
        agg = signals_agg.data or {}

        # 계산용 dict 구성
        candidate = {
            **agg,  # bottleneck_score · mag7_customer_count 등 사용자·시스템 수동/자동 필드
            "anti_pattern_flags": agg.get("anti_pattern_flags") or [],
            "domain_tags": agg.get("domain_tags") or [],
        }

        score, avoid = compute_serenity_score(candidate)

        supabase.table("discovery_serenity_scores").upsert({
            "ticker": ticker,
            **candidate,
            "total_score": score,
            "auto_avoid": avoid,
            "updated_at": "now()",
        }, on_conflict="ticker").execute()
        updated += 1

    return updated
```

## 6. Backtest · L4 (`backend/discovery/serenity/backtest.py`)

### 6.1 책임
- 미처리 signal (backtest 없음)에 대해 signal_date 기준 실 주가 fetch (yfinance)
- 5·10·30·60·180일 후 return 계산
- `serenity_backtest` upsert

### 6.2 스켈레톤

```python
"""Serenity signal → 실 주가 대조 백테스트.

Cron: 매주 월요일 00:00 KST
Data source: yfinance (yahoo finance · rate limit 유의)
"""

import yfinance as yf
from datetime import datetime, timedelta

def backtest_signal(signal_row: dict) -> dict | None:
    """개별 signal 백테스트."""
    ticker = signal_row["ticker"]
    signal_date = signal_row["extracted_at"][:10]  # 'YYYY-MM-DD'

    # yfinance 는 티커 심볼 정합 필요 (예: SEK-listed 는 별도)
    # 한국·중국 티커는 별도 매핑 필요 (backend/services/ticker_map.py)
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(
            start=signal_date,
            end=(datetime.fromisoformat(signal_date) + timedelta(days=200)).date().isoformat(),
        )
        if hist.empty:
            return None

        signal_price = float(hist.iloc[0]["Close"])
        returns = {}
        for days in (5, 10, 30, 60, 180):
            if len(hist) > days:
                future_price = float(hist.iloc[days]["Close"])
                returns[f"return_{days}d"] = round(
                    (future_price - signal_price) / signal_price * 100, 2
                )
        return {
            "signal_id": signal_row["id"],
            "ticker": ticker,
            "signal_date": signal_date,
            "price_at_signal": round(signal_price, 4),
            **returns,
        }
    except Exception as e:
        print(f"⚠️ backtest 실패 {ticker} @{signal_date}: {e}")
        return None


def refresh_backtests() -> int:
    """미처리 signal 배치 백테스트."""
    supabase = get_supabase_admin()

    pending = supabase.rpc("get_pending_backtests").execute()
    inserted = 0
    for signal in pending.data:
        result = backtest_signal(signal)
        if result:
            supabase.table("serenity_backtest").upsert(
                result, on_conflict="signal_id"
            ).execute()
            inserted += 1
    return inserted
```

## 7. Cron 스케줄 (`backend/scheduler/serenity_jobs.py`)

기존 Toss Tradebot scheduler 패턴 재사용 · 4 job 등록:

```python
# 매일 06:00 KST · 트윗 아카이브 sync
@scheduler.scheduled_job("cron", hour=6, minute=0, timezone="Asia/Seoul", id="serenity_crawler")
def job_crawler():
    from backend.discovery.serenity.crawler import sync_tweets
    result = sync_tweets()
    logger.info(f"Serenity crawler: {result}")

# 매일 07:00 KST · z.ai signal 추출
@scheduler.scheduled_job("cron", hour=7, minute=0, timezone="Asia/Seoul", id="serenity_extractor")
def job_extractor():
    from backend.discovery.serenity.extractor import process_pending_tweets
    result = process_pending_tweets(batch_size=200)
    logger.info(f"Serenity extractor: {result}")

# 매일 08:00 KST · 스코어 갱신
@scheduler.scheduled_job("cron", hour=8, minute=0, timezone="Asia/Seoul", id="serenity_scorer")
def job_scorer():
    from backend.discovery.serenity.scorer import refresh_all_scores
    updated = refresh_all_scores()
    logger.info(f"Serenity scorer: {updated} tickers updated")

# 매주 월 00:00 KST · 백테스트
@scheduler.scheduled_job("cron", day_of_week="mon", hour=0, minute=0, timezone="Asia/Seoul", id="serenity_backtest")
def job_backtest():
    from backend.discovery.serenity.backtest import refresh_backtests
    inserted = refresh_backtests()
    logger.info(f"Serenity backtest: {inserted} signals computed")
```

## 8. 환경 변수 (`.env` · chmod 600)

```bash
# ============ Serenity Integration ============
# Serenity 로컬 아카이브 경로 (yan-labs/serenity-aleabitoreddit clone)
SERENITY_TRACKER_DIR=/Users/gonnim/GON-Dev/serenity-tracker

# z.ai GLM-5.2 (추출 · methodology 프롬프트)
# 발급: https://z.ai/manage-apikey/apikey-list
ZAI_API_KEY=
ZAI_MODEL=glm-5.2
ZAI_BASE_URL=https://api.z.ai/api/paas/v4

# Supabase (기존 · 이미 있으면 재사용)
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
```

**주의 (naver §1 가드)**: 실 API 키 본 문서·코드에 하드코드 금지. `.env` (chmod 600) 로만 관리 · `.gitignore` 확인 · 실 세션에서 사용자가 채움.

## 9. FastAPI 라우트 (`backend/api/serenity.py`)

Frontend 가 호출할 read API:

```python
from fastapi import APIRouter, Depends
from typing import Literal
from backend.api.deps import require_auth

router = APIRouter(prefix="/api/serenity", tags=["serenity"])

@router.get("/signals")
async def list_signals(
    limit: int = 50,
    sentiment: Literal["bullish", "bearish", "neutral", "calibration"] | None = None,
    days: int = 14,
    _=Depends(require_auth),
):
    """최근 N일 signal feed."""

@router.get("/tickers")
async def list_tickers(_=Depends(require_auth)):
    """discovery_serenity_scores 전체 (auto_avoid 포함)."""

@router.get("/tickers/{ticker}")
async def ticker_detail(ticker: str, _=Depends(require_auth)):
    """개별 티커 상세 (스코어 + 최근 signals + backtest)."""

@router.get("/backtest/summary")
async def backtest_summary(_=Depends(require_auth)):
    """signal type 별 · sentiment 별 정확도 aggregate."""

@router.get("/methodology")
async def methodology_content(_=Depends(require_auth)):
    """methodology.md 원문 (`SERENITY_TRACKER_DIR`/references/methodology.md 읽기)."""
```

## 10. 미해결 결정 사항 (사용자 확인 필요)

- [ ] Supabase RLS Public vs. Authenticated (§2.2 Option A/B)
- [ ] serenity-tracker 통합 방식 (git submodule vs. 로컬 경로 참조)
- [ ] z.ai 비용 예산 (트윗 6,222 개 초기 배치 + 매일 신규 · 예: 하루 20~100 트윗 × 트윗당 ~$0.005)
- [ ] yfinance vs. Alpha Vantage (backtest 데이터 소스 · SEK/KOSPI 등 non-US 티커 정합성)
- [ ] Ticker 심볼 매핑 (SEK-listed SIVE · Korean 138080.KQ · Taiwan 3231.TWO 등)
- [ ] 초기 backfill · 6,222 트윗 전체 vs. 최근 90일부터 · 비용·시간 트레이드오프
