# 03 · Implementation Plan · Serenity Integration

> **의존**: [README.md](./README.md) · [01-ui-spec.md](./01-ui-spec.md) · [02-backend-arch.md](./02-backend-arch.md)
>
> **범위**: Phase L1~L8 실행 순서 · 파일 리스트 · 시간 예산 · 승인 게이트

## Phase 개요 (총 36h · ~4~5일 집중 or 2~3주 저녁·주말)

| Phase | 이름 | 예상 시간 | 산출물 | 승인 게이트 |
|---|---|---|---|---|
| **L1** | serenity-tracker 통합 + 스키마 마이그레이션 | 2h | git submodule · Alembic revision | ✅ 사용자 승인 필요 |
| **L2** | Crawler (`serenity_crawler.py`) | 3h | 트윗 → serenity_tweets · unit test | ✅ 사용자 승인 필요 |
| **L3** | Extractor (`serenity_extractor.py`) + z.ai 프롬프트 | 5h | 트윗 → serenity_signals · 백필 50건 검증 | ✅ 사용자 승인 필요 |
| **L4** | Scorer (`serenity_scorer.py`) + 15원칙 스코어링 | 4h | serenity_signals aggregate → discovery_serenity_scores | ✅ 사용자 승인 필요 |
| **L5** | Backtest (`serenity_backtest.py`) + yfinance | 4h | serenity_backtest 채움 · Track-record 대조 | ✅ 사용자 승인 필요 |
| **L6** | Frontend Nav + `/influencer/serenity` 랜딩 | 8h | Nav 조건부 렌더 · Signal Feed + Ticker Grid | ✅ 사용자 승인 필요 |
| **L7** | Frontend `/influencer/serenity/[ticker]` + methodology + backtest 페이지 | 6h | 상세 페이지 · 15원칙 checklist · Backtest chart | ✅ 사용자 승인 필요 |
| **L8** | Cron 등록 + 통합 테스트 + 문서화 | 4h | scheduler · README · Post-mortem | ✅ 사용자 승인 필요 (배포) |

---

## Phase L1 · 통합 · 스키마 마이그레이션 (2h)

### 파일 (신규 · 수정)

| 유형 | 경로 | 내용 |
|---|---|---|
| 신규 | `backend/alembic/versions/YYYYMMDD_serenity_integration.py` | 4 테이블 · enum · index (02 §2 SQL DDL 반영) |
| 수정 | `.gitmodules` | `serenity-tracker` submodule 추가 (선택 A) |
| 수정 | `.env.example` | `SERENITY_TRACKER_DIR` · `ZAI_API_KEY` 추가 |
| 신규 | `backend/discovery/serenity/__init__.py` | 빈 파일 (Python 패키지) |

### 옵션 A · Git Submodule (권장)

```bash
cd ~/Project-MVP/Source/toss-tradebot-mvp
git submodule add https://github.com/yan-labs/serenity-aleabitoreddit vendor/serenity-tracker
git commit -m "chore: serenity-tracker submodule (Serenity Integration L1)"
```

- `.env` `SERENITY_TRACKER_DIR=./vendor/serenity-tracker` 로 설정
- 사용자가 로컬에서 `update.py` 실행 시 submodule 폴더 갱신

### 옵션 B · 로컬 경로 참조 (단순)

- 사용자 로컬 `~/GON-Dev/serenity-tracker/` 그대로 사용
- `.env` `SERENITY_TRACKER_DIR=/Users/gonnim/GON-Dev/serenity-tracker`
- 다른 기기 이식성 낮음 · 사용자 개인 도구 관점에서 감당

### 검증

```bash
cd backend && alembic upgrade head
python -c "from backend.discovery.serenity import __path__; print(__path__)"
```

### 승인 게이트 L1
- [ ] 4 테이블 생성 확인 (Supabase Studio · psql `\dt+ serenity*`)
- [ ] `.env` 에 `SERENITY_TRACKER_DIR` 설정 확인
- [ ] Git submodule (옵션 A) or 로컬 경로 (옵션 B) 결정 · 커밋
- [ ] **사용자 승인** → L2 진입

---

## Phase L2 · Crawler (3h)

### 파일 (신규)

| 경로 | 내용 |
|---|---|
| `backend/discovery/serenity/crawler.py` | 02 §3.2 스켈레톤 구현 |
| `backend/tests/discovery/test_serenity_crawler.py` | 단위 테스트 (fixtures) |
| `backend/scripts/serenity_crawl.py` | CLI 진입점 (`python -m backend.scripts.serenity_crawl`) |

### 구현 순서
1. 02 §3.2 스켈레톤 복사 · yan-labs JSON 스키마 정확 매핑 (특히 `posted_at` · `metrics`)
2. 첫 실행: `SERENITY_TRACKER_DIR` 지정 · 로컬 6,222 트윗 로드 확인
3. Supabase 접속 · 100건 dry-run · 스키마 매핑 검증
4. 전체 batch upsert · 6,222 건 삽입 확인

### 검증

```bash
python -m backend.scripts.serenity_crawl
# 예상 출력: Serenity 트윗 sync 완료: {'inserted': 6222, 'skipped': 0}

psql $SUPABASE_URL -c "SELECT COUNT(*) FROM serenity_tweets;"
# 6222
```

### 승인 게이트 L2
- [ ] 6,222 트윗 삽입 확인
- [ ] 재실행 시 skipped=6222 (증분 로직 정상)
- [ ] unit test 통과 (5+ 케이스)
- [ ] **사용자 승인** → L3 진입

---

## Phase L3 · Extractor + z.ai 프롬프트 (5h)

### 파일 (신규)

| 경로 | 내용 |
|---|---|
| `backend/discovery/serenity/extractor.py` | 02 §4 스켈레톤 |
| `backend/discovery/serenity/prompts/system.md` | SYSTEM_PROMPT 원문 (버전 관리 · 반복 튜닝) |
| `backend/tests/discovery/test_serenity_extractor.py` | 단위 테스트 (mock openai) |
| `backend/scripts/serenity_extract.py` | CLI batch 진입점 |

### 구현 순서
1. 02 §4.2 SYSTEM_PROMPT 를 `prompts/system.md` 로 관리 (버전 관리)
2. `extractor.py` 는 파일에서 프롬프트 로드
3. z.ai API 호출 · JSON 응답 파싱 · exception handling
4. 소규모 배치 (10건) 로 정확도 확인 · 프롬프트 튜닝
5. 배치 크기 200건씩 실행 · 6,222 전체 processing 시간 측정
6. Rate limit · 재시도 · 실패 signal 로그 별도 저장

### Supabase RPC 함수 (선택 · 성능 최적화)

```sql
CREATE OR REPLACE FUNCTION get_pending_serenity_tweets(limit_n INT)
RETURNS SETOF serenity_tweets
LANGUAGE sql AS $$
  SELECT t.* FROM serenity_tweets t
  LEFT JOIN serenity_signals s ON s.tweet_id = t.tweet_id
  WHERE s.id IS NULL
  ORDER BY t.posted_at DESC
  LIMIT limit_n;
$$;
```

### 검증

```bash
python -m backend.scripts.serenity_extract --batch 50
# 첫 배치 · 통계 출력 · 성공률·평균 confidence 확인

psql $SUPABASE_URL -c "
SELECT sentiment, COUNT(*)
FROM serenity_signals
GROUP BY sentiment
ORDER BY COUNT(*) DESC;
"
# 예상: bullish 다수 · bearish 소수 (IREN·CRWV) · neutral (watchlist) · calibration (AAOI CPO 등)
```

### 승인 게이트 L3
- [ ] 50건 샘플 signals 사용자 육안 검증 · 프롬프트 조정 반영
- [ ] 6,222 전체 processing 완료 (수 시간 예상)
- [ ] `SELECT COUNT(*) FROM serenity_signals` 확인 (트윗당 평균 signals 수 · 예: 1.5)
- [ ] 도메인 티커 상위 (NBIS·SIVE·AXTI 등) sentiment 분포 spot-check
- [ ] **사용자 승인** → L4 진입

---

## Phase L4 · Scorer + 15원칙 (4h)

### 파일 (신규)

| 경로 | 내용 |
|---|---|
| `backend/discovery/serenity/scorer.py` | 02 §5 스켈레톤 |
| `backend/discovery/serenity/aggregators.py` | signals → aggregate 로직 (mention count · sentiment 분포 · 도메인 태그) |
| `backend/tests/discovery/test_serenity_scorer.py` | 스코어링 공식 unit test (경계값 · avoid 규칙) |

### Supabase RPC (aggregate)

```sql
CREATE OR REPLACE FUNCTION aggregate_serenity_signals(target_ticker TEXT)
RETURNS JSON
LANGUAGE plpgsql AS $$
DECLARE
  result JSON;
BEGIN
  SELECT json_build_object(
    'mention_count_90d', COUNT(*) FILTER (WHERE extracted_at > NOW() - INTERVAL '90 days'),
    'bullish_pct_90d', 100.0 * COUNT(*) FILTER (WHERE sentiment = 'bullish' AND extracted_at > NOW() - INTERVAL '90 days')
      / NULLIF(COUNT(*) FILTER (WHERE extracted_at > NOW() - INTERVAL '90 days'), 0),
    'last_signal_at', MAX(extracted_at),
    'thesis_types', ARRAY_AGG(DISTINCT thesis_type) FILTER (WHERE thesis_type IS NOT NULL)
  ) INTO result
  FROM serenity_signals WHERE ticker = target_ticker;
  RETURN result;
END $$;
```

### 초기 seed (사용자 수동 편집 필요 필드)

일부 15원칙 필드 (`bottleneck_score` · `financing_tier` · `serenity_tier` · `anti_pattern_flags` · `domain_tags`) 는 z.ai 자동 추출 어려움 → **사용자가 theses.md·methodology.md 정독 후 수동 편집** or **별도 seed script**.

**seed script 예시** (`backend/scripts/serenity_seed_tiers.py`):

```python
# theses.md 정독 결과 반영 (관찰 로그 §L 참조)
SEED = [
    {"ticker": "NBIS", "financing_tier": "S", "serenity_tier": "S", "domain_tags": ["neocloud"]},
    {"ticker": "AXTI", "financing_tier": "A", "serenity_tier": "A", "domain_tags": ["inp_substrates"]},
    {"ticker": "SIVE", "financing_tier": "B", "serenity_tier": "S", "domain_tags": ["optical_cpo"]},
    {"ticker": "LITE", "financing_tier": "B", "serenity_tier": "B", "domain_tags": ["optical_cpo"]},
    {"ticker": "AAOI", "financing_tier": "C", "serenity_tier": "B", "domain_tags": ["optical_cpo"], "anti_pattern_flags": ["no_cpo_design_win"]},
    {"ticker": "IREN", "financing_tier": "D", "serenity_tier": "F", "domain_tags": ["neocloud"], "anti_pattern_flags": ["atm_51pct_overhang", "sbc_1p14b"]},
    {"ticker": "CRWV", "financing_tier": "F", "serenity_tier": "F", "domain_tags": ["neocloud"], "anti_pattern_flags": ["heavy_debt_1p3b_yr"]},
    # ... 확장 (관찰 로그 §K 참조)
]
```

### 검증

```bash
python -m backend.scripts.serenity_seed_tiers
python -m backend.scripts.serenity_score

psql $SUPABASE_URL -c "
SELECT ticker, total_score, auto_avoid, financing_tier, serenity_tier
FROM discovery_serenity_scores
ORDER BY total_score DESC
LIMIT 20;
"
# 예상: NBIS 최상위 · AXTI 상위 · IREN·CRWV auto_avoid=TRUE
```

### 승인 게이트 L4
- [ ] Seed 반영 확인 (NBIS S · IREN F 등)
- [ ] Score 순위 spot-check · 관찰 로그 §L 매칭
- [ ] `auto_avoid` 로직 검증 (IREN·CRWV = TRUE)
- [ ] **사용자 승인** → L5 진입

---

## Phase L5 · Backtest + yfinance (4h)

### 파일 (신규)

| 경로 | 내용 |
|---|---|
| `backend/discovery/serenity/backtest.py` | 02 §6 스켈레톤 |
| `backend/services/ticker_map.py` | Ticker 심볼 매핑 (SEK-listed SIVE → SIVE.ST · KQ → KRX 등) |
| `backend/tests/discovery/test_serenity_backtest.py` | mock yfinance |

### Ticker 매핑 예시

```python
YFINANCE_SYMBOL = {
    "SIVE": "SIVE.ST",        # Stockholm
    "138080.KQ": "138080.KS",  # Korea KOSDAQ
    "3231.TWO": "3231.TWO",   # Taiwan
    "SKHYV": "SKHYV",         # US ADR
    "SKHY": "000660.KS",      # Korea local
    # NBIS · SIVE · LITE · AAOI · AXTI 등 US 은 그대로
}
```

### 초기 backfill

```bash
python -m backend.scripts.serenity_backtest --all --dry-run
# 예상: 총 signals 수 · backtest 대상 · yfinance API call 수 추정

python -m backend.scripts.serenity_backtest --all
# 실 실행 (rate limit 유의 · 배치 지연)
```

### 검증

```bash
psql $SUPABASE_URL -c "
SELECT ticker, AVG(return_30d), AVG(return_60d), COUNT(*)
FROM serenity_backtest
GROUP BY ticker
ORDER BY AVG(return_60d) DESC
LIMIT 20;
"
# NBIS·AXTI·SIVE 상위 예상 · IREN·CRWV 하위
```

### 승인 게이트 L5
- [ ] Backtest table 채움 확인
- [ ] Ticker 심볼 매핑 정확성 (SIVE·SKHY·138080 등)
- [ ] 결과 관찰 로그 §K 검증 데이터와 비교 (AAOI +483% · AXTI +1057% 등)
- [ ] **사용자 승인** → L6 진입

---

## Phase L6 · Frontend Nav + `/influencer/serenity` 랜딩 (8h)

### 파일 (신규 · 수정)

| 유형 | 경로 | 내용 |
|---|---|---|
| 신규 | `frontend/components/layout/AppNav.tsx` | 01 §3.2 스켈레톤 |
| 수정 | `frontend/app/layout.tsx` | 01 §3.3 diff 적용 |
| 신규 | `frontend/app/influencer/page.tsx` | `/influencer/serenity` 리다이렉트 |
| 신규 | `frontend/app/influencer/serenity/page.tsx` | Signal Feed + Ticker Grid 랜딩 |
| 신규 | `frontend/components/serenity/SignalFeedCard.tsx` | 개별 signal 카드 |
| 신규 | `frontend/components/serenity/TickerCard.tsx` | 개별 티커 카드 (01 §5.2) |
| 신규 | `frontend/lib/serenity/api.ts` | API 클라이언트 (`/api/serenity/*`) |
| 신규 | `frontend/lib/serenity/types.ts` | TypeScript 타입 (Signal · Score) |

### 구현 순서
1. AppNav.tsx 분리 · layout.tsx 수정 · 기존 6개 페이지 pathname 활성 표시 정상 확인 (regression 방지)
2. `/influencer/serenity` 페이지 · Loading skeleton · Empty state
3. FastAPI `/api/serenity/signals` · `/api/serenity/tickers` 호출
4. Signal Feed · sentiment 색상 (bullish 녹색·bearish 빨강·neutral 회색·calibration 노랑)
5. Ticker Grid · financing_tier 별 섹션 (S/A/B/C/Avoid)
6. shadcn/ui `Card` · `Badge` · `Skeleton` 재사용

### 검증
- 로컬 dev (`npm run dev`) · 브라우저:
  - Journal → 하단 nav = 기존 5개
  - Influencer 클릭 → 하단 nav = Serenity 만
  - Signal Feed · Ticker Grid 실 데이터 렌더
- 반응형 · 다크모드 · 모바일 확인

### 승인 게이트 L6
- [ ] Nav 조건부 렌더 정상 (기존 페이지 regression 없음)
- [ ] 랜딩 페이지 실 데이터 표시
- [ ] 반응형·다크모드 통과
- [ ] **사용자 승인** → L7 진입

---

## Phase L7 · Frontend 상세 · methodology · backtest 페이지 (6h)

### 파일 (신규)

| 경로 | 내용 |
|---|---|
| `frontend/app/influencer/serenity/[ticker]/page.tsx` | 개별 티커 상세 (01 §6) |
| `frontend/app/influencer/serenity/methodology/page.tsx` | 15원칙 markdown 열람 |
| `frontend/app/influencer/serenity/backtest/page.tsx` | 백테스트 리포트 · 차트 |
| `frontend/components/serenity/ChecklistCard.tsx` | 14점 체크리스트 UI |
| `frontend/components/serenity/BacktestChart.tsx` | 5·10·30·60·180일 차트 |
| `frontend/lib/serenity/markdown.ts` | methodology.md fetch + markdown 렌더 |

### 차트 라이브러리 결정 (사용자 확인 필요)

- **shadcn/ui chart** (recharts wrapper) — 권장 · 기존 프로젝트 정합
- recharts 직접
- chart.js

### 검증
- Ticker 상세 · 15원칙 checklist · Backtest chart 실 데이터
- Methodology 페이지 · 15원칙 앵커 링크 정상

### 승인 게이트 L7
- [ ] 상세 페이지 렌더 · 데이터 정합성
- [ ] Methodology 페이지 · markdown 정상 렌더
- [ ] Backtest 차트 · 실 수익률 시각화
- [ ] **사용자 승인** → L8 진입

---

## Phase L8 · Cron 등록 + 통합 테스트 + 문서화 (4h)

### 파일 (신규 · 수정)

| 유형 | 경로 | 내용 |
|---|---|---|
| 신규 | `backend/scheduler/serenity_jobs.py` | 02 §7 스켈레톤 |
| 수정 | `backend/scheduler/__init__.py` | serenity_jobs import |
| 수정 | `docs/plans/serenity-integration/README.md` | 상태 → **완료** |
| 신규 | `docs/plans/serenity-integration/POST-MORTEM.md` | 구현 후 배운 점 · 예상 vs 실제 시간 · 튜닝 포인트 |

### 통합 테스트 시나리오

1. **매일 시나리오** — 오전 06:00 crawler → 07:00 extractor → 08:00 scorer 순차 실행 · 결과 UI 반영
2. **주간 시나리오** — 월요일 00:00 backtest 실행 · 새 return 값 UI 반영
3. **자동 복구** — 개별 job 실패 시 로그 · 다음 실행에서 recovery
4. **비용 모니터링** — z.ai 사용량 · 하루 예산 초과 시 alert

### 승인 게이트 L8 (배포)

- [ ] 4 cron job 등록 확인 (`scheduler --list`)
- [ ] 통합 테스트 4 시나리오 통과
- [ ] Post-mortem 문서 작성
- [ ] **사용자 최종 승인** → 프로덕션 배포

---

## 전체 흐름 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│ L1 · 스키마 · 통합         (2h)                          │
│  ┌────────────────────────────┐                          │
│  │ Alembic migration · submodule │                       │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L2 · Crawler              (3h)                          │
│  ┌────────────────────────────┐                          │
│  │ serenity_crawler.py        │  → serenity_tweets       │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L3 · Extractor + z.ai      (5h) ★ 프롬프트 튜닝 지점    │
│  ┌────────────────────────────┐                          │
│  │ serenity_extractor.py      │  → serenity_signals      │
│  │  system.md 프롬프트         │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L4 · Scorer + 15원칙       (4h) ★ Seed script 수동      │
│  ┌────────────────────────────┐                          │
│  │ serenity_scorer.py         │  → discovery_serenity_scores │
│  │  seed_tiers.py             │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L5 · Backtest + yfinance   (4h) ★ Ticker 심볼 매핑      │
│  ┌────────────────────────────┐                          │
│  │ serenity_backtest.py       │  → serenity_backtest     │
│  │  ticker_map.py             │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L6 · Frontend Nav + 랜딩    (8h) ★ 사용자 UX 확인       │
│  ┌────────────────────────────┐                          │
│  │ AppNav.tsx · /influencer   │                          │
│  │ /serenity 랜딩 · Feed·Grid │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L7 · Frontend 상세 페이지    (6h)                        │
│  ┌────────────────────────────┐                          │
│  │ [ticker] · methodology     │                          │
│  │ backtest 차트              │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│ L8 · Cron + 통합 테스트     (4h)                        │
│  ┌────────────────────────────┐                          │
│  │ scheduler · post-mortem    │                          │
│  └────────────────────────────┘                          │
│                    ↓                                      │
│           프로덕션 배포                                    │
└─────────────────────────────────────────────────────────┘
```

## 리스크 · 완화

| 리스크 | 확률 | 영향 | 완화 |
|---|---|---|---|
| z.ai 프롬프트 정확도 낮음 | 중 | 중 | L3 샘플 검증 · 프롬프트 반복 튜닝 · confidence < 0.5 필터 |
| 트윗당 z.ai 비용 예상 초과 | 중 | 저 | 초기 90일만 backfill · 이후 증분 · z.ai 무료·저가 티어 확인 |
| yfinance rate limit · non-US 티커 실패 | 중 | 중 | Ticker 매핑 · 재시도 · 실패 로그 · Alpha Vantage fallback |
| Frontend Nav regression | 저 | 중 | L6 승인 게이트 · 기존 5개 페이지 spot-check |
| serenity-tracker 저장소 폐쇄·이름 변경 | 저 | 상 | 로컬 아카이브 백업 · fork 준비 |
| 사용자 시간 예산 소진 (재직 병행) | 상 | 중 | 각 Phase 승인 게이트 · 중단·재개 가능 · Path B (최소 통합 L1~L4) 로 전환 옵션 |
| Toss API Phase K 미완 시 자동매매 결합 리스크 | 상 | 상 | **본 통합은 signal 표시만** · 자동 매수 결합은 별도 Phase (K 완료 후) |

## 중단·재개 시나리오

각 Phase L1~L8 은 독립적으로 완료 가능 · 중단 후 재개 시:

1. 마지막 완료 Phase 의 승인 게이트 재확인
2. 다음 Phase 산출물 목록 참조
3. 시간 예산 재산정 · 저녁·주말 단위로 배분
4. **완전 중단 시** — 관찰 로그 §M Path B (최소 통합 L1~L4 · 14h) 로 축소 가능

## 완료 정의 (Definition of Done)

- 8 Phase 모두 승인 게이트 통과
- 통합 테스트 4 시나리오 통과
- Post-mortem 작성 (실 시간 vs. 예상 · 튜닝 포인트 · 다음 개선 항목)
- gonnim-landing 스타일 배포 자동화 (선택 · 개인 사용이면 로컬 dev 유지도 가능)
- 관찰 로그 §L 최신화 (실 구현 반영)
