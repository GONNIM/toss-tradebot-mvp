# 04. 구현 로드맵

**작성일**: 2026-06-25
**선행**: 03 백테스트 (Q16=A/Q17=A/Q18=A/Q19=A 추천안 채택)
**상태**: 작성 — Q20~Q23 결정 후 즉시 코드 작업 착수

> 본 문서는 **기획 마지막 문서**. 결정 완료 후 Phase 1a 부터
> 코드 작업으로 진행.

---

## 1. 전체 일정

```
2026-06-25 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2026-07-15
            │
            ▼
   ┌─ Phase 1a (DB + Universe) ────  D+0 ~ D+3
   │
   ├─ Phase 1b (Volume + Oversold) ─  D+3 ~ D+5
   │
   ├─ Phase 1c (Reddit) ────────────  D+5 ~ D+7
   │
   ├─ Phase 1d (Stocktwits + Trends)  D+7 ~ D+8
   │
   ├─ Phase 1e (Confluence + API) ──  D+8 ~ D+9
   │
   ├─ Phase 1f (UI /meme-watch) ────  D+9 ~ D+12
   │
   └─ Phase 1g (백테스트 + 보고) ───  D+12 ~ D+15
            │
            ▼
       2026-07-10 경 출시 (3주 가량)
```

각 Phase 종료 시 작은 commit + 자동 배포 (메모리
[[feedback_deploy_only_when_complete]] 의 "한 Phase 내 일괄 완료" 원칙).

---

## 2. Phase 1a — DB + Universe (D+0 ~ D+3)

### 산출물
- 4개 SQLAlchemy 모델 (`backend/services/models.py` 확장)
  - `MemeUniverse`, `MemeSocialSignal`, `MemeShortInterest`, `MemeVolumeSnapshot`
- `init_db()` 갱신 — 새 테이블 자동 생성
- `backend/discovery/meme_watch/universe.py` — Universe 빌드 잡
- 첫 시드 데이터 (US Russell 2000 시총 ≤ 5B + KOSDAQ 시총 ≤ 1조원)
- APScheduler `meme_universe_weekly` 잡 등록

### 의존성
- 기존 `init_db()` 패턴 (sector_leaders 와 동일)
- pykrx (시총 fetch — 이미 의존성)
- yfinance (US 시총 fetch — 이미 의존성)

### 검증
- `sqlite3 backend/data/tradebot.db ".schema meme_universe"` — 테이블 생성 확인
- `meme_universe` row 수 ≈ 1,500
- universe build 잡 수동 1회 실행 → DB 적재 확인

---

## 3. Phase 1b — Volume + Oversold (D+3 ~ D+5)

### 산출물
- `backend/discovery/meme_watch/quote_client.py` — yfinance + pykrx 통합
- `backend/discovery/meme_watch/oversold.py` — RSI(14) + 1D return 계산
- APScheduler `meme_volume_5min` 잡 (장중)
- DB `meme_volume_snapshot` 적재

### 검증
- 5분 batch 후 `meme_volume_snapshot` 1,500 × 60/5 = 18,000 row/일 (장중)
- RSI / volume z-score 정상 분포

---

## 4. Phase 1c — Reddit (D+5 ~ D+7)

### 사용자 작업 (D-1 까지 필요)
- **Reddit 앱 등록**: https://www.reddit.com/prefs/apps
- `script` 타입 — name "toss-tradebot-meme-watch"
- 받은 `client_id` + `client_secret` 을 GitHub Actions secrets 에 추가:
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`

### 산출물
- `backend/discovery/data_sources/reddit/client.py` — praw 비동기 wrapper
- ticker regex 매칭 (`\$([A-Z]{1,5})`) + 종목명 NER (선택)
- 모니터 subreddit: WSB, stocks, pennystocks, Shortsqueeze
- 24h 윈도우 mention count + upvote 가중 score
- APScheduler `meme_social_5min` 잡

### 검증
- 5분 batch 후 `meme_social_signal` source="reddit" 누적
- Top 10 mention ticker 출력 (수동 확인)
- 가용 ticker 의 30일 평균 mention 분포 → z-score 산출 가능

---

## 5. Phase 1d — Stocktwits + Google Trends (D+7 ~ D+8)

### 산출물
- `backend/discovery/data_sources/stocktwits/client.py` — httpx wrapper
- `backend/discovery/data_sources/google_trends/client.py` — pytrends wrapper
- 5분 batch 통합 — `meme_social_5min` 잡에 추가
- DB `meme_social_signal` source="stocktwits" / "google_trends" 적재

### 검증
- API rate limit 이내 동작 확인
- 실패 시 가용 가중치 재정규화 정상 작동 (메모리
  [[feedback_partner_accountability]])

---

## 6. Phase 1e — Confluence + API (D+8 ~ D+9)

### 산출물
- `backend/discovery/meme_watch/confluence.py` — 02 문서 공식 구현
  - `compute_meme_score(ticker) → MemeScoreResponse`
  - 동적 가중치 재정규화
- `backend/discovery/meme_watch/top10.py` — Top N 매력도 정렬
- `backend/api/routes/meme_watch.py` — FastAPI 라우터
  - `GET /api/v1/meme-watch/` — 전체 score 분포 요약
  - `GET /api/v1/meme-watch/top10?limit=10` — Top 워치리스트
  - `GET /api/v1/meme-watch/tickers/{ticker}` — 단일 상세 (5축 분해)
- `backend/api/schemas.py` 응답 모델
- `backend/api/main.py` 라우터 등록

### 검증
- `curl /api/v1/meme-watch/top10?limit=10` → 200 OK
- 응답에 5개 시그널 contributions + label + emoji

---

## 7. Phase 1f — UI (D+9 ~ D+12)

### 산출물
- `frontend/app/meme-watch/page.tsx` — Top 워치리스트 페이지
- `frontend/components/meme-watch/MemeWatchTable.tsx`
  - 컬럼: rank · 🔥/⚠️/👀 · ticker · name · market · score · top signal · 24h chg
- `frontend/components/meme-watch/MemeRadarChart.tsx` — Recharts RadarChart 5축
- `frontend/components/meme-watch/SignalBreakdown.tsx` — 종목별 5요소 분해
- `frontend/lib/api.ts` 타입 확장
- 네비 메뉴에 "🔥 Meme Watch" 추가

### 검증
- 브라우저에서 `/meme-watch` 페이지 로딩 + 데이터 표시
- 종목 클릭 → 레이더 차트 + 분해
- light/dark 가독성 (메모리 logs 페이지 사례 교훈 적용)

---

## 8. Phase 1g — 백테스트 + 보고 (D+12 ~ D+15)

### 사전 작업
- **Reddit 과거 데이터 입수** — Kaggle 검색 (Q17=A)
  - 후보 dataset: "GME WSB sentiment", "AMC Reddit mentions"
  - 다운로드 → `data/backtest/reddit_*.csv` 로 적재
- pushshift.io 백업 fetch (Kaggle 미흡 시)

### 산출물
- `backend/discovery/meme_watch/backtest.py`
  - `BacktestCase`, `BacktestResult` dataclass
  - `run_backtest()` — 사례별 D-30 ~ D+5 시그널 재구성
  - `report_summary()` — 합격률 + lead time 분포
- CLI: `python -m backend.discovery.meme_watch.backtest --output ...`
- `docs/plans/meme-stock-discovery/03-backtest-report.md` 자동 생성

### 검증 (Q14 합격 기준)
- 10 사례 중 ≥ 6건 D-3 ~ D-1 사이 score ≥ 0.75 진입
- False positive 6,000 random ticker·month 중 < 5% HOT 진입

미달 시 가중치 튜닝 → 재실행. 동결 후 운영 가중치 commit.

---

## 9. Phase 2 (출시 후 — 1~3 개월 단위)

| 항목 | 우선순위 | 예상 |
|---|---|---|
| ⑤ catalyst event (Yahoo halt + KRX VI + DART) | ⭐⭐⭐ | 3~5d |
| Twitter/X API ($100/월) | ⭐⭐ | 2d |
| 네이버 종토방 · 디시인사이드 크롤 | ⭐⭐ | 3d |
| Push 알림 (사용자 임계값 설정) | ⭐⭐ | 3d |
| 한국 트랙 강화 (정치테마 NER, 작전주 패턴) | ⭐ | 5~7d |
| 백테스트 분기별 재실행 + 가중치 재튜닝 | ⭐⭐⭐ | 매분기 1d |

---

## 10. 리스크 매트릭스

| 리스크 | 영향 | 완화책 |
|---|---|---|
| Reddit API 변경/차단 | 핵심 시그널 손실 | Stocktwits + Google Trends 가중치 재정규화 자동 |
| pytrends Captcha | Google Trends 결손 | 1시간 backoff + 운영 ERROR 로그 |
| pushshift.io 차단 | 백테스트 불완전 | Kaggle 우선, 그것도 안 되면 백테스트 사례 7~8건으로 축소 |
| KOSDAQ 시총 ≤ 1조 universe 너무 큼 (~2,000) | 5분 batch timeout | concurrency 제한 (10) + chunking |
| yfinance rate limit (분당 50req) | volume batch 실패 | universe 분할 + sleep 도입 |
| 5분 batch 누적 부하 | DB 비대 | 30일 이전 데이터 weekly 정리 잡 |
| Meme score false positive 5% 초과 | 사용자 신뢰 손실 | 가중치 튜닝 + 임계값 ↑ 후 재배포 |
| 운영 서버 outbound 차단 | 시그널 fetch 실패 | optimus8 에서 사전 connectivity 검증 |

---

## 11. 작업 의존성 그래프

```
Phase 1a (DB)
    ├─ Phase 1b (Volume) ─┐
    ├─ Phase 1c (Reddit) ─┤
    └─ Phase 1d (Stocktwits/Trends) ─┤
                                     ├─ Phase 1e (Confluence) ─┐
                                                                ├─ Phase 1f (UI)
                                                                │
                                                                └─ Phase 1g (백테스트)
```

→ 1b/1c/1d 는 1a 후 **병행 가능** 이론적이나 1인 작업이라 순차.

---

## 12. 미해결 사항 — 사용자 결정 대기 (마지막)

### Q20. 백테스트 시점
- A. **1g (Phase 1 끝)** — 모델 구현 완료 후 검증 ← **추천**
- B. 1g 를 1e 후 즉시 — 가중치 동결 후 1f UI
- C. 1g 를 1a 직후 — 가중치 동결 후 모든 단계

→ A 추천: 코드 구현이 끝나야 시그널 시계열 재구성 함수도 같이 쓸 수 있음.

### Q21. Universe 1차 크기
- A. **US 시총 ≤ 5B USD + KOSDAQ 시총 ≤ 1조원 (~1,500)** ← **추천**
- B. US Russell 2000 + KOSDAQ 전체 (~4,500)
- C. US Reddit 언급 + KOSDAQ 거래량 상위 200 (~500)

### Q22. 자동 배포 cadence
- A. **각 Phase 종료 시 commit + auto deploy** ← **추천**
- B. Phase 1f 완료 후 한 번에
- C. Phase 1e (API) 시점에 한 번, 1f UI 후 한 번 (2회)

### Q23. Reddit 인증 등록 타이밍
- A. **Phase 1a~1b 진행 중 사용자 등록** — 1c 도착 시 준비됨 ← **추천**
- B. 1c 시작 직전 즉시
- C. 이미 등록되어 있음 (사용자 보유 키)

---

## 13. 빠른 답변 예시

> "Q20=A, Q21=A, Q22=A, Q23=A, 진행"

이렇게 답주시면 Phase 1a 코드 작업 시작합니다.

---

## 14. Phase 1a 첫 작업 명세 (사전 보기)

승인 직후 시작할 첫 작업:

1. `backend/services/models.py` — 4개 신규 모델 추가
2. `init_db()` 갱신 검증 — 로컬 sqlite 새 테이블 생성
3. `backend/discovery/meme_watch/__init__.py` + `universe.py` 신규
4. universe 빌드 함수 — US 시총 ≤ 5B + KOSDAQ ≤ 1조 fetch
5. APScheduler 잡 등록 (`meme_universe_weekly`)
6. 수동 1회 실행 → DB 1,500 row 적재 검증
7. 로컬 commit + push → 자동 배포

소요 2~3일. Phase 1a 완료 보고 시 1b 시작 의사 확인.
