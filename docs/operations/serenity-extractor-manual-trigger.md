# Serenity Extractor · 수동 트리거 안전 매뉴얼

> ⚠ **`while True` one-liner 절대 금지** (2026-08-13 사고 이력) · 반드시 `scripts/serenity_extract_batch.py` 사용.

---

## 사고 이력 (2026-08-13)

- **증상**: 서버에서 `while True: process_pending_tweets(...)` 실행 · 25 라운드 · 1,250 트윗 API 호출 · signals 겨우 35건 (2.8%)
- **원인**: `load_pending_tweets` 가 `SerenitySignal` 존재 여부로 필터링 → z.ai 가 `signals=[]` 반환 시 마커 없음 → 같은 트윗 무한 재선택
- **fix**: `SerenityTweet.processed_at` 컬럼 신설 · signals 유무 무관 마킹 · migration `a1f7c9b3d2e4`
- **후속**: `process_pending_tweets` 반환값에 `pending_before/after` 추가 · `pending_after >= pending_before` 감지 시 `RuntimeError` (회귀 게이트)

---

## 정상 크론 (자동 · 손 대지 말 것)

`backend/discovery/serenity/scheduler.py`

| 크론 | 시각 (KST) | 조건 |
|---|---|---|
| `serenity_crawler_daily` | 매일 06:00 | `SERENITY_CRON_ENABLED=true` |
| `serenity_extractor_daily` | 매일 07:00 | `SERENITY_EXTRACTOR_CRON=true` (비용 스위치) |
| `serenity_scorer_daily` | 매일 08:00 | `SERENITY_CRON_ENABLED=true` |
| `serenity_backtest_daily` | 매일 01:00 | 배치 500 |
| `serenity_benchmark_daily` | 매일 00:30 | IWM/SPY 캐시 |

크론 정상 시 수동 트리거 불필요. 다음 경우에만 수동 트리거:
- **크론 정지 감지** — `/api/v1/serenity/health` warn (stale_signals or stale_crawler)
- **긴급 배치** — 신규 트윗 다량 · 오늘 안 처리 필요
- **디버그** — dry-run 으로 pending count 확인

---

## 수동 트리거 절차 (안전)

### 1. Health 확인

```bash
curl -sSf https://optimus8.cafe24.com/api/v1/serenity/health | python -m json.tool
```

`warn: true` + `reasons` 배열의 `code` 확인:
- `stale_crawler` → crawler 정지 · SSH 로 crawler 수동 실행
- `stale_signals` → extractor 정지 · 아래 §2 실행

### 2. Dry-run (반드시 실 실행 전에)

```bash
ssh root@optimus8.cafe24.com 'cd /root/toss-tradebot-mvp && \
  backend/.venv/bin/python scripts/serenity_extract_batch.py --dry-run'
```

출력:
```
pending tweets: 47
[dry-run] max_rounds=5 · batch_size=50 · 예상 라운드=1 · 예상 z.ai 호출=47
```

**pending 이 예상보다 훨씬 크면** (예 500+) 크론 장기 정지 or 크롤러 버그 의심 · 실 실행 전 조사.

### 3. 실 실행 (dry-run 결과 확인 후)

```bash
ssh root@optimus8.cafe24.com 'cd /root/toss-tradebot-mvp && \
  backend/.venv/bin/python scripts/serenity_extract_batch.py --max-rounds 3'
```

라운드별 진행 표시:
```
round 1: tweets=50 signals=126 failed=0 pending 200→150 (Δ-50) · running_total={...}
round 2: tweets=50 signals=98 failed=0 pending 150→100 (Δ-50) · running_total={...}
...
✅ pending 0 · 정상 종료.
FINAL: {'tweets': 200, 'signals_inserted': 412, 'failed': 0} · remaining_pending=0
```

### 4. Health 재확인

```bash
curl -sSf https://optimus8.cafe24.com/api/v1/serenity/health | python -m json.tool
```

`stale_signals` 해소되면 성공. Action Cards 도 재확인:

```bash
curl -sSf https://optimus8.cafe24.com/api/v1/serenity/action-cards | python -c \
  "import json,sys; d=json.load(sys.stdin); print('cards:', len(d['cards']))"
```

---

## 스크립트 가드레일 (자동 중단 조건)

`scripts/serenity_extract_batch.py` default 값:

| 옵션 | Default | 의미 |
|---|---|---|
| `--max-rounds` | 5 | 라운드 상한 · 초과 시 강제 중단 |
| `--max-total-tweets` | 500 | 총 z.ai 호출 상한 (비용 캡) |
| `--max-zero-rounds` | 2 | 연속 `signals_inserted=0` 라운드 상한 (효율 저하 감지) |
| `--batch-size` | 50 | 라운드당 배치 크기 |
| `--concurrency` | 2 | 동시 z.ai 호출 (rate limit 안전) |

**대량 처리가 명확히 필요할 때만** default 상향:
```bash
--max-rounds 15 --max-total-tweets 1500
```

---

## 절대 금지 (사고 재발 방지)

❌ **one-liner while true 루프** — 2026-08-13 원인
```bash
# 금지 · 무한 루프 · z.ai 비용 폭발 위험
python -c "
async def loop_all():
    while True:
        r = await process_pending_tweets(...)
        if r['tweets'] == 0: break
"
```

❌ **`process_pending_tweets` 직접 호출 반복** — 가드레일 우회
❌ **`concurrency` 5+** — z.ai rate limit hit · 대량 실패
❌ **`batch_size` 200+** — 단일 트랜잭션 크기 · 실패 시 롤백 비용

✅ **반드시** `scripts/serenity_extract_batch.py` 사용 · 상한 옵션 명시.

---

## 회귀 방지 게이트

`process_pending_tweets` 반환 시 다음 assertion:
```python
if stats["tweets"] > 0 and pending_after >= pending_before:
    raise RuntimeError("무한 루프 감지 · processed_at 마킹 실패")
```

즉 사고 재현 시 **즉시 예외** 로 실행이 중단됨. 회귀 감지 후 `_mark_processed` 로직 조사 필수.

테스트 커버리지 (`backend/tests/serenity/test_extractor_idempotent.py`):
- `test_empty_signals_marks_processed` — 오늘 사고 정확히 재현 검증
- `test_load_pending_shrinks_after_process` — pending 감소 assertion
- `test_extractor_failure_does_not_mark` — 실패 시 재시도 대상 유지
- `test_pending_before_after_reported` — 반환값 정합
- `test_infinite_loop_detection` — RuntimeError 게이트 동작

---

## 비용 감사

수동 트리거 실행 시 대략 비용:
- z.ai `glm-5.2` · 트윗당 ~1,500 tokens (system prompt 대부분 · reasoning off)
- 배치 500 트윗 = 750K tokens · $0.5~1 (모델·요금표 확인)

일일 자동 크론 (매일 07:00 KST) 은 신규 트윗만 · 20~50건 · $0.05~0.1 예상.

**비상 신호** — 24h 내 300+ signals 삽입 시 Telegram alert (구현 중 · 축 5).

---

## Backfill 감사 (A-3 정책 · 2026-08-13)

Migration `a1f7c9b3d2e4` 는 기존 트윗 전질을 `processed_at=CURRENT_TIMESTAMP` 로 skip 마킹했다.
**감사 가능성**: backfill 로 스킵된 트윗과 정상 처리 후 signal=[] 트윗을 DB만으로 구분 불가.

식별 SQL (backfill 실 시각 = 서버 `alembic upgrade` 실행 시각 · deploy 로그에서 확인):

```sql
-- 1) backfill 실 시각 파악 (트윗 대량 · 초 단위 클러스터)
SELECT DATE_TRUNC('second', processed_at) AS ts,
       COUNT(*) AS cnt
FROM serenity_tweets
WHERE processed_at IS NOT NULL
GROUP BY DATE_TRUNC('second', processed_at)
ORDER BY cnt DESC
LIMIT 5;
-- 최상위 결과가 backfill 시각 · cnt ≈ 전체 트윗 수

-- 2) backfill skip 트윗 식별 (예: 배포 시각 = '2026-08-13 05:XX:XX')
SELECT tweet_id, posted_at, processed_at
FROM serenity_tweets
WHERE processed_at BETWEEN '<backfill_ts - 2s>' AND '<backfill_ts + 2s>'
ORDER BY posted_at DESC;

-- 3) 필요 시 재처리 (backfill skip 트윗의 processed_at 을 NULL 로 되돌림)
UPDATE serenity_tweets
SET processed_at = NULL
WHERE processed_at BETWEEN '<backfill_ts - 2s>' AND '<backfill_ts + 2s>';
```

**후속 개선**: `SerenityTweet.processed_source` enum ('backfill', 'crawler_processed', 'manual_retry') 컬럼 추가로 명시적 구분 가능. 태스크 #10 (독약 트윗 처리) 와 함께 후속 처리 예정.

---

## 정규 크론 경로 상한 (사전 차단)

`_job_extractor` (매일 07:00 KST):
- `batch_size=200 · concurrency=2` (한 번 실행 · **라운드 반복 없음**)
- 즉 하루 최대 z.ai 호출 = **200회** 사전 차단
- 크롤러가 대량 유입 (예 500 트윗) 시 → 200 씩 여러 날에 걸쳐 처리 (매일 7시)
- 사전 차단 (`batch_size=200`) + 사후 탐지 (`_job_zai_cost_audit` >300 alert) **이중 방어**

---

## 참고

- 스크립트: `scripts/serenity_extract_batch.py`
- 모델: `backend/services/models.py` `SerenityTweet.processed_at`
- Migration: `backend/alembic/versions/a1f7c9b3d2e4_add_serenity_tweet_processed_at.py`
- 스케줄러: `backend/discovery/serenity/scheduler.py` (`_job_extractor` · `_job_zai_cost_audit`)
- 테스트: `backend/tests/serenity/test_extractor_idempotent.py`
- 후속 티켓: 태스크 #10 (독약 트윗 · failure_count 컬럼) · 감사 컬럼 (processed_source)
