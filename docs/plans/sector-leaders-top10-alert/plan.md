# Sector Leaders Top 10 매력도 알림 기획안

**작성일**: 2026-06-26
**상태**: 초안 — D1~D5 사용자 확정 완료, 본 문서 사용자 검토 후 로컬 구현 진입
**배포 정책**: 단일 Phase 작업 — 로컬 완료 후 1회 배포 (메모리 규칙 `feedback_deploy_only_when_complete`)

관련:
- 기존 자산 — `backend/discovery/sector_leaders/top10.py` (Top 10 산출 함수)
- 기존 자산 — `backend/services/notifier.py` (Telegram 발송 + dedupe)
- 기존 자산 — `backend/scheduler/cron.py` (APScheduler 데몬, 기존 cron 등록)
- 자매 패턴 — `upbit-tradebot-mvp/docs/plans/strategy-sync-hardening/plan.md` (동일 SP/Phase 표기 규약)

---

## 1. WHY (목적)

### 1-1. 사용자 요청 원문

> Toss Tradebot > 투자 종목 Top 10 정보 중 매력도 0.6 이상 종목 관련 데이터를 09시, 05시에 한번씩 텔레그램 알림으로 보내라.
> 매력도 0.6 이상 종목이 5개 이하면 0.5 이상 종목까지 포함.
> 정보 내용은 종목 / 품목 / 현재가 / 진입가 / 예측수익가 / 매력도.

### 1-2. 해결할 본질 문제

현재 `compute_top10()`은 산출 함수만 존재하고 알림 통로가 없어, 사용자가 매번 대시보드를 직접 열어야 매력도 높은 종목을 확인할 수 있다. 알림 통로를 추가하면:

- **개장 직후 안정화된 현재가 기반 매수 후보 검토** (09:05 — 시초가 변동 흡수 후)
- **정규장 마감 후 종가 기반 익일 매수 후보 검토** (17:05 — 정규장 15:30 마감 + 시간외 단일가 1차 마감 직후)

→ 사용자의 매수 의사결정을 **하루 2회 분기점**에 맞춰 능동적으로 제시.

---

## 2. WHAT (요구사항)

| ID | 요구 | 우선순위 |
|---|---|---|
| R1 | 매력도 임계 통과 종목을 산출해 Telegram 으로 발송 | MUST |
| R2 | 임계 1차 = ≥ 0.6 (6개 이상이면 그대로) / 5개 이하면 임계 2차 = ≥ 0.5 까지 후보 확장 | MUST |
| R3 | 후보군 매력도 정렬 후 **상위 3개만** 발송 (메시지 분량·가독성) | MUST |
| R4 | 메시지 필드 = 종목 / 품목 / 현재가 / 진입가 / 예측수익가 / 매력도 + `entry_status` | MUST |
| R5 | 일 2회 발송 — 09:05 / 17:05 KST | MUST |
| R6 | 후보 0개 시에도 "오늘 매수 후보 없음" 안내 발송 (운영 가시성) | SHOULD |
| R7 | 1회 수동 실행 옵션 추가 (`--once sector_leaders`) — 로컬·서버 검증 | SHOULD |

---

## 3. AS-IS (현재 흐름)

### 3-1. Top 10 산출 — 이미 완성됨

`backend/discovery/sector_leaders/top10.py:114~336`

```
compute_top10(session, top_n=10) → list[Top10Item]
  ├── SectorLeader 전체 로드
  ├── KrxStockMeta 로드 (last_close)
  ├── Naver Quote 실시간 fetch (60s cache, fallback last_close)
  ├── KrxDailyCandle → 월말 종가/수익률
  ├── MotirItemExport / RegionExport / History → confluence 입력
  ├── customs_interim YoY → 매크로 입력
  └── per leader:
      ├── compute_confluence(...)         # -1 ~ +1
      ├── multi_horizon_forecast(...)     # point_estimate_pct
      ├── historical_quantiles(...)       # band
      ├── compute_rr_ratio(...)           # R/R
      ├── recommend_stop_take(...)        # stop/take 가격
      └── compute_attractiveness(conf, |r|, R/R) → 0~1
      → Top10Item (entry_price, point_price, attractiveness, ...)
```

`Top10Item` 필드 매핑 (사용자 요청 6개 필드 + 보조):

| 사용자 요청 필드 | `Top10Item` 필드 | 비고 |
|---|---|---|
| 종목 | `name` + `ticker` | 회사명 + KRX 코드 |
| 품목 | `item` | MOTIR 분류 |
| 현재가 | `current_price` | 실시간(Naver) 우선 / fallback last_close |
| 진입가 | `entry_price` | `min(현재가, 점추정 × 0.9)` |
| 예측수익가 | `point_price` | `현재가 × (1 + point_pct/100)` |
| 매력도 | `attractiveness` | 0 ~ 1 |
| (보조) 진입 상태 | `entry_status` | "🟢 지금 매수 가능" / "🟡 X.X% 조정 대기" |
| (보조) 현재가 출처 | `price_source` | "live" / "fallback" |

### 3-2. Telegram 알림 — 이미 완성됨

`backend/services/notifier.py:56~129`

```
TelegramNotifier
  ├── from_env() — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  ├── dedupe (60s, hash key = md5(title|body[:200]))
  ├── send_info(title, body) — INFO 레벨, ℹ️ 아이콘
  ├── send_warning / send_critical
  └── HTML parse_mode

format_moonshot_alert(picks) → (title, body)
format_crazy_alert(picks)    → (title, body)
```

→ 동일 패턴으로 `format_sector_leaders_alert(items, bucket_label)` 추가만 하면 됨.

### 3-3. Scheduler — 이미 완성됨

`backend/scheduler/cron.py:468~476`

```
build_scheduler() → AsyncIOScheduler (tz=Asia/Seoul)
  ├── 06:00 — universe_refresh
  ├── 06:30 — crazy_picks
  └── 16:50 — moonshot_picks
```

→ 동일 패턴으로 cron 3개 추가만 하면 됨.

### 3-4. 운영 인프라

메모리 `reference_tossbot_deploy`: optimus8.cafe24.com — `tradebot-cron` systemd 서비스. 배포는 git pull + `systemctl restart tradebot-cron`.

---

## 4. TO-BE (Phase 설계)

**단일 Phase — SA1 (Sector-leaders Alert 1)**

설계가 단순하고 변경 범위 작아 Phase 분리 불필요.

### 4-1. 새 모듈 — `format_sector_leaders_alert`

`backend/services/notifier.py` 끝부분에 추가:

```python
def format_sector_leaders_alert(
    items: list,             # list[Top10Item]
    bucket_label: str,       # "0.6" / "0.5" / "empty"
    expanded: bool = False,  # 0.5로 확장됐는지
) -> tuple[str, str]:
    """Sector Leaders Top 매력도 알림 — (title, body)."""

    if not items:
        # R6 — 빈 결과도 안내 발송
        title = "📊 Sector Leaders — 오늘 매수 후보 없음"
        body = (
            "매력도 0.5 이상 종목이 없습니다.\n"
            "<i>모든 시그널이 약하거나 음의 영역에 있는 상황입니다.</i>"
        )
        return title, body

    title = f"📊 Sector Leaders Top {len(items)} — 매력도 {bucket_label}+"

    lines = []
    if expanded:
        lines.append(
            "<i>※ 0.6 이상이 5개 이하라 0.5 이상까지 확장한 결과입니다.</i>\n"
        )

    for it in items:
        # 진입 상태 (entry_status 가 그대로 "🟢 ..." / "🟡 ..." 문자열 형태)
        # 현재가 출처 표기 — fallback 이면 "(전일종가)" 부가
        price_tag = "" if it.price_source == "live" else " <i>(전일종가)</i>"

        lines.append(
            f"\n<b>#{it.rank} {it.name} ({it.ticker})</b>"
            f"  매력도 <b>{it.attractiveness:.2f}</b>\n"
            f"품목: {it.item}\n"
            f"현재가: {it.current_price:,.0f}원{price_tag}\n"
            f"진입가: {it.entry_price:,.0f}원  ({it.entry_status})\n"
            f"예측수익가: {it.point_price:,.0f}원  (+{it.point_pct:.1f}%)\n"
        )

    return title, "".join(lines)
```

### 4-2. 새 job — `run_sector_leaders_alert_job`

`backend/scheduler/cron.py` 에 추가:

```python
SECTOR_LEADERS_TOP_N = int(os.environ.get("SECTOR_LEADERS_TOP_N", "3"))


async def run_sector_leaders_alert_job(slot: str = "default") -> int:
    """Sector Leaders Top 매력도 알림 — Top N 발송.

    Args:
        slot: 알림 시점 라벨 ("09:05" / "17:05") — 로깅용

    Logic:
        1) compute_top10(session, top_n=10) — 매력도 정렬된 Top 10
        2) ≥0.6 인 항목 추출
           - 6개 이상이면 그대로 사용
           - 5개 이하면 ≥0.5 까지 확장
        3) 후보 매력도 상위 SECTOR_LEADERS_TOP_N (=3) 컷
        4) format_sector_leaders_alert → Telegram send_info
    """
    from backend.discovery.sector_leaders.top10 import compute_top10
    from backend.services.db import get_session
    from backend.services.notifier import (
        TelegramNotifier,
        format_sector_leaders_alert,
    )

    logger.info(f"[sector_leaders_alert] start slot={slot}")

    async with get_session() as session:
        items = await compute_top10(session, top_n=10)

    high = [i for i in items if i.attractiveness >= 0.6]
    if len(high) >= 6:
        candidates = high
        bucket = "0.6"
        expanded = False
    else:
        candidates = [i for i in items if i.attractiveness >= 0.5]
        bucket = "0.5"
        expanded = True

    # 매력도 상위 N 컷 (compute_top10 이 이미 정렬된 상태로 반환하므로 단순 슬라이스)
    picks = candidates[:SECTOR_LEADERS_TOP_N]

    # rank 재계산 (1~N)
    from dataclasses import replace as _replace
    picks = [_replace(p, rank=i + 1) for i, p in enumerate(picks)]

    if not picks:
        bucket = "empty"

    title, body = format_sector_leaders_alert(picks, bucket, expanded=expanded)
    notifier = TelegramNotifier()
    await notifier.send_info(title, body)

    logger.info(
        f"[sector_leaders_alert] slot={slot} sent={len(picks)} bucket={bucket}"
    )
    return len(picks)


async def job_sector_leaders_alert_0905():
    try:
        await run_sector_leaders_alert_job(slot="09:05")
    except Exception as e:
        logger.error(f"[cron] sector_leaders 09:05 failed: {e}", exc_info=True)


async def job_sector_leaders_alert_1705():
    try:
        await run_sector_leaders_alert_job(slot="17:05")
    except Exception as e:
        logger.error(f"[cron] sector_leaders 17:05 failed: {e}", exc_info=True)
```

### 4-3. `build_scheduler` 에 cron 2개 등록

```python
scheduler.add_job(
    job_sector_leaders_alert_0905,
    CronTrigger(hour=9, minute=5),
    id="sector_leaders_alert_0905",
    name="Sector Leaders Top — 09:05 KST (개장 안정)",
    replace_existing=True,
)
scheduler.add_job(
    job_sector_leaders_alert_1705,
    CronTrigger(hour=17, minute=5),
    id="sector_leaders_alert_1705",
    name="Sector Leaders Top — 17:05 KST (정규장 마감 후)",
    replace_existing=True,
)
```

### 4-4. `--once sector_leaders` 옵션 추가

```python
parser.add_argument(
    "--once",
    choices=["universe", "crazy", "moonshot", "sector_leaders"],
    help="1회 즉시 실행 (수동 검증). 미지정 시 데몬 모드.",
)
...
elif target == "sector_leaders":
    n = await run_sector_leaders_alert_job(slot="manual")
    print(f"✅ Sector Leaders Alert: Top {n} 발송")
```

---

## 5. 영향 받는 파일

| 파일 | 변경 종류 | 상세 |
|---|---|---|
| `backend/services/notifier.py` | 추가 | `format_sector_leaders_alert(items, bucket_label, expanded)` 함수 1개 |
| `backend/scheduler/cron.py` | 추가 | (1) 모듈 상수 `SECTOR_LEADERS_TOP_N` (2) `run_sector_leaders_alert_job` + 2개 wrapper (3) `build_scheduler` cron 2개 등록 (4) `--once sector_leaders` 옵션 |
| 신규 파일 | — | 없음 |
| 환경 변수 | (선택) | `SECTOR_LEADERS_TOP_N` (기본 3) — 운영 중 조정 가능 |

→ **변경 매우 작음**. 기존 패턴과 완벽 일치.

---

## 6. Phase 순서

```
P0 — 기획안 사용자 검토 (현재 단계 — 본 문서)
   ↓
SA1 — 구현 (notifier.py + cron.py)
   ↓
로컬 검증
  ├── --once sector_leaders 1회 실행 → Telegram 수신 확인
  ├── 0.6 이상 충분 / 부족 / 0개 시나리오 데이터로 시뮬레이션
  └── HTML 렌더링 검증 (가독성)
   ↓
사용자 최종 승인
   ↓
커밋 + push
   ↓
서버 배포 (사용자 명시 승인 후) — optimus8 git pull + systemctl restart tradebot-cron
   ↓
서버 검증 (첫 cron 발사 — 다음 09:05 또는 17:05 중 가장 빠른 시점)
```

---

## 7. 결정 항목 (확정)

| # | 항목 | 결정 |
|---|---|---|
| **D1** | 알림 시각 | **09:05 + 17:05 KST — 일 2회**. 09:05 = 개장 후 안정 시점, 17:05 = 정규장(15:30) + 시간외 단일가 1차(16:00) 마감 후 익일 매수 검토. 사용자 결정 (2026-06-26 갱신) |
| **D2** | 데이터 신선도 | **(a) 알림 job 안에서 매번 `compute_top10()` 재계산**. 별도 사전 갱신 job 불필요 |
| **D3** | 메시지 포맷 | **(b) 6개 필드 + `entry_status`** (🟢 지금 매수 가능 / 🟡 X.X% 조정 대기). 현재가 출처는 fallback 시 "(전일종가)" 부가 |
| **D4** | 발송 분량·후보 0개 처리 | **최종 매력도 상위 3개만 발송**. 후보 0개 시 "오늘 매수 후보 없음" 안내 발송 (R6) |
| **D5** | 동일 결과 dedupe | **(a) 시각 무관 매번 발송**. 시간 간격이 길고 본문에 종목·가격 변동 반영되어 자연스럽게 hash 달라짐 → dedupe 자동 통과 |

---

## 8. 리스크 & 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| **09:05 시초가 변동성** | 개장 직후 5분간 호가 흔들림 가능 — 표시 현재가가 매우 단기적 가격일 수 있음 | "현재가" 표기에 메시지 부가 설명 불요 — 사용자가 시간 의미 인지. 17:05 알림으로 종가 기준 재확인 가능 |
| **17:05 정규장 마감 후 — live quote 의미 변화** | Naver 호가가 정규장 종가 또는 시간외 가격 중 어느 값을 반환할지 시기 의존 | `price_source = "live"` 라도 메시지에 "(정규장 종가 / 시간외 가격)" 같은 부가 표기 검토 — 구현 단계에서 Naver 응답 확인 후 결정 |
| **휴장일(주말·공휴일) live quote 부재** | `current_price` 가 `last_close` fallback — 메시지에 "(전일종가)" 표기됨 | 기 설계된 fallback 표기로 사용자 혼동 방지 — `4-1` 포맷에 반영 |
| **`compute_top10()` 실행 시간** | DB 풀스캔 — 수 초~수십 초 가능, 다른 cron job 블로킹 위험 | APScheduler async job — fire-and-forget, 다른 job 영향 없음 (기존 crazy/moonshot 동일) |
| **휴장일 알림 발송** | 토·일·공휴일에도 알림 → 사용자 피로 | 일단 매일 발송 — 추후 캘린더(pykrx 또는 pandas-market-calendars) 도입 결정 (별도 작업) |
| **Telegram 발송 실패 (네트워크/API)** | 알림 누락 | `notifier.py:send` 가 이미 try/except + logger.error — 다음 슬롯에서 자동 회복 |
| **`get_session()` 미존재** | 임포트 실패 | `backend/services/db.py` 의 기존 헬퍼 확인 후 구현 (이미 crazy/moonshot 에서 사용 중) |
| **`SECTOR_LEADERS_TOP_N` 환경변수 미설정** | 기본 3 적용 (코드에 명시) | 영향 없음 — 의도된 기본값 |
| **dedupe 60초 — 09:05 와 17:05 동일 본문 차단?** | 두 시점 간격 8시간 — dedupe TTL(60s) 와 무관하게 자동 통과 | 추가 대응 불필요 |

---

## 9. 진행 흐름

1. 본 기획안 사용자 검토 → 승인
2. 로컬 구현 (notifier.py + cron.py)
3. 로컬 1회 검증 (`python -m backend.scheduler.cron --once sector_leaders`)
4. 사용자 완료 보고 + 승인
5. 커밋 (단일 커밋) → push
6. 사용자 배포 승인 요청
7. optimus8 서버 — `git pull && systemctl restart tradebot-cron`
8. 서버 검증 — 첫 cron 슬롯 알림 수신 확인
9. 완료 보고

---

## 10. 진행 이력

| 일시 | 단계 | 비고 |
|---|---|---|
| 2026-06-26 14:00 | 초안 작성 | 사용자 요청 "09/05시 매력도 0.6+ 알림" → D1~D5 결정 수신 → 본 기획안 작성. 변경 범위 매우 작음 (notifier +1 함수, cron +3 job + `--once` 옵션) |
| 2026-06-26 14:30 | D1 스케줄 갱신 | 사용자 결정 "09:05 / 17:05 KST 하루 2번" → §1-2 분기점·§2 R5·§4-2~4-3 job/스케줄·§7 D1·§8 리스크(09:05 시초가 변동, 17:05 마감 후 quote 의미, dedupe 행)·§5 wrapper 수·§6 검증 슬롯 일괄 갱신. 05:00 + 08:55 슬롯 제거, 17:05 신설 |
