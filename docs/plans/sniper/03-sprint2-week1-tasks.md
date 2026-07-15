# 🌙 Sprint 2 · Week 1 상세 태스크 (야간 신호 수집 파이프라인)

**목적**: 마감 후 (15:30 KST~) 부터 다음날 08:30 KST 까지 뉴스·소셜·정부·이벤트 소스를 축적, `watchlist_signal` 로 저장한다.

**전제**: `docs/plans/sniper/02-strategic-pivot-as-is-to-be.md` 승인됨.

**진행 방식**: 순차 · 각 태스크 마다 로컬 검증 + 사용자 승인 · 최종 단일 배포 (`feedback_deploy_only_when_complete`).

---

## T58 · watchlist_signal 스키마 (선행)

Week 1 다른 모든 태스크가 이 테이블로 write 하므로 최우선.

### 스키마

```python
class WatchlistSignal(Base):
    """마감 후 야간 축적 신호. 다음날 Watchlist 승격의 원천 데이터."""

    __tablename__ = "watchlist_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)   # KRX 6자리
    source: Mapped[str] = mapped_column(String(20), index=True)
    #   news_yhap · news_edaily · news_fnnews · news_herald · news_sedaily
    #   board_naver · youtube_hantoo · youtube_shuka · youtube_jungpro · youtube_sampro
    #   assembly · motie_rss · msit_rss · moef_rss · molit_rss
    #   prev_day_derivative
    signal_type: Mapped[str] = mapped_column(String(30))
    #   headline · board_post_velocity · video_upload · bill_registered · press_release · gap_up_candidate
    intensity: Mapped[float]                                       # z-score or fraction
    payload_json: Mapped[Optional[str]] = mapped_column(Text)      # 원본 링크·제목·발췌
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    trade_date: Mapped[str] = mapped_column(String(10), index=True)  # 대상 거래일 YYYY-MM-DD
    # trade_date 는 detected_at 기준 다음 거래일 (마감 후 신호이므로)

    __table_args__ = (
        Index("ix_watchlist_signal_ticker_date", "ticker", "trade_date"),
        Index("ix_watchlist_signal_source_time", "source", "detected_at"),
    )
```

### 파일
- `backend/services/models.py` · 새 클래스 추가 (Meme 테이블 다음)
- `backend/discovery/watchlist/` (신규 폴더) · `__init__.py`, `store.py`
- `backend/discovery/watchlist/store.py`
  - `async def upsert_signal(ticker, source, signal_type, intensity, payload, trade_date)` · duplicate 방지 (source + ticker + detected_at 5m window)
  - `async def signals_for_date(trade_date)` · Watchlist 승격 잡용
  - `async def recent_signals(hours=24, limit=100)` · UI/디버그용

### DoD
- SQLite alembic 없이 `Base.metadata.create_all()` 자동 반영 (프로젝트 컨벤션 유지)
- `pytest backend/tests/discovery/test_watchlist_store.py` · insert·조회·중복 방지 · 각 1건

---

## T54 · 뉴스 headline RSS crawler

### 소스 (5개 · 초기)

| 언론 | RSS URL 후보 | 비고 |
|---|---|---|
| 연합인포맥스 | `https://news.einfomax.co.kr/rss/S1N2.xml` (종목/시황) | free |
| 이데일리 | `https://rss.edaily.co.kr/stock_news.xml` | free |
| 파이낸셜뉴스 | `https://www.fnnews.com/rss/fn_realnews_stock.xml` | free |
| 헤럴드경제 | `https://biz.heraldcorp.com/rss/010101000000.xml` | free |
| 서울경제 | `https://www.sedaily.com/RSS/S1N2.xml` | free |

⚠️ URL 실제 유효성은 T54 착수 시 실측 확인 · 폐지된 소스는 대체.

### 종목 매칭 로직

1. Watchlist 유니버스 (KOSDAQ 150) + KOSPI 상위 200 = **matcher universe 350 종목** 로드
2. 각 뉴스 headline + description 에서 회사명 substring 매칭
   - 정확 매칭 (예: `삼성전자` · `LG에너지솔루션`)
   - 축약 매칭 (예: `삼성전자우` · `LG엔솔` · `TIGER 반도체` 등은 별도 alias 테이블 필요 · T54 v1 에서는 skip · v2 에서 alias 추가)
3. 매칭 성공 시 · intensity = 1.0 (기본) · velocity 계산은 T58 store 에서 60일 baseline 대비 z-score

### 파일
- `backend/discovery/watchlist/news_rss.py`
  ```python
  RSS_SOURCES = {
      "news_yhap": "https://news.einfomax.co.kr/rss/S1N2.xml",
      # ...
  }

  async def poll_news_rss() -> dict:
      """모든 소스 병렬 폴링 · matcher 유니버스 매칭 · watchlist_signal 저장.
      Returns: {"fetched": ..., "matched": ..., "inserted": ..., "errors": {...}}
      """
  ```
- `backend/discovery/watchlist/matcher.py` · `build_matcher()` + `match_text(text) -> list[ticker]`

### 의존성
- `feedparser` (이미 pyproject 에 있음 · 확인 필요)
- `httpx` (기존)

### DoD
- 5개 소스 각각 최소 1건 fetch 성공 로그
- matcher 를 통해 최근 30분 헤드라인에서 최소 5개 종목 매칭
- watchlist_signal 에 저장 확인 (source=news_*)
- 단위 테스트 · 뉴스 mock XML 로 파싱·매칭·저장 검증

---

## T55 · 네이버 종토방 velocity crawler

### 소스
- URL 패턴: `https://finance.naver.com/item/board_list.naver?code={ticker}&page=1`
- HTML 파싱 (BeautifulSoup) · 최근 30분 게시글수 카운트
- 60일 동일 시간대 baseline 대비 z-score 계산

### 로직
1. 야간 활성창 (15:30~다음 08:00) · 30분 주기 실행
2. Watchlist 유니버스 150 종목 순회 · 종목별 1 페이지 (약 20 게시글)
3. 게시글 timestamp parsing · 최근 30분 내 게시글수 = N
4. 60일 rolling baseline (동일 시간대 30분 슬롯) mean·std
5. z = (N - mean) / std · z >= 2.0 → signal 저장 (intensity=z)

### 파일
- `backend/discovery/watchlist/naver_board.py`
  ```python
  async def fetch_board_posts(ticker: str, session: httpx.AsyncClient) -> list[datetime]:
      """최근 30분 게시글 timestamp 리스트."""

  async def compute_baseline(ticker: str, slot_start: datetime) -> tuple[float, float]:
      """60일 동일 시간대 mean·std."""

  async def poll_naver_boards() -> dict:
      """유니버스 순회 · z >= 2.0 저장."""
  ```
- 60일 baseline 저장용 테이블 신규 vs 매번 계산 · v1 은 매번 계산 (단순화)

### 부하 관리
- 150 종목 × 30분 주기 = 300 호출/시간 · Naver 서버 부담
- httpx AsyncClient · concurrency 5 · sleep 200ms between requests
- User-Agent 정상 설정 (`Mozilla/5.0 ...`)
- 실패 시 exponential backoff · 3회 재시도

### DoD
- 5개 임의 종목 · 게시글 timestamp 파싱 정확도 100%
- 30분 잡 완료 시간 < 2분 (성능)
- watchlist_signal 저장 확인 (source=board_naver)

---

## T56 · YouTube Data API v3 채널 감시

### 소스 (4개 초기)

| 채널 | Channel ID | 지표 |
|---|---|---|
| 한투군 | (검색 필요 · T56 착수 시 확정) | 신규 upload 시 종목명 extract |
| 슈카월드 | (검색 필요) | |
| 정프로가 소개하는 주식 | (검색 필요) | |
| 삼프로TV | (검색 필요) | |

### API
- `https://www.googleapis.com/youtube/v3/search?channelId={ID}&part=snippet&order=date&maxResults=5`
- API Key 필요 · Google Cloud Console 무료 발급 · quota 10000 units/day
- 1회 호출 = 100 units · 4채널 × 1시간 = 96 units/day → 여유 충분

### 로직
1. 1시간 주기 · 4채널 순회
2. 최근 upload 5건 · title + description 추출
3. matcher 로 종목 매칭
4. 업로드 시각 < 12시간 이내 신규만 저장

### 파일
- `backend/discovery/watchlist/youtube.py`
- 환경변수: `YOUTUBE_API_KEY` · SOPS 저장

### DoD
- API 호출 성공 로그 · 4채널
- 최소 1건 종목 매칭
- 중복 저장 방지 (video_id 기준)

---

## T57 · 국회 의안·정부 RSS

### 소스

**국회 의안정보 시스템**
- API: `https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn` (신규 발의 법안)
- 무료 발급 · 인증키 필요
- 1일 주기 (아침 시간대)
- 산업별 keyword 매칭 (반도체 · 배터리 · 신재생 · 방산 · 바이오 등)
- 산업 → KOSDAQ 대표 종목 매핑 테이블 관리 (`backend/discovery/watchlist/industry_map.py`)

**정부 부처 보도자료 RSS**
- 산업부: `https://www.motie.go.kr/rss/press.xml` (2026 명칭 변경 · motir 으로 확인 필요 · `project_motir_rebrand`)
- 과기부: `https://www.msit.go.kr/rss/press.xml`
- 기재부: `https://www.moef.go.kr/rss/press.xml`
- 국토부: `https://www.molit.go.kr/rss/press.xml`
- 각 URL 실측 필요 (T57 착수 시)

### 로직
1. 4개 RSS 1시간 주기 폴링
2. 국회 의안 1일 주기 (아침 06:00)
3. 산업 keyword 추출 · industry_map 으로 종목 확장
4. intensity = 0.5 (뉴스보다 낮은 즉시 반응) · v2 에서 튜닝

### 파일
- `backend/discovery/watchlist/assembly.py`
- `backend/discovery/watchlist/gov_press.py`
- `backend/discovery/watchlist/industry_map.py`

### DoD
- 4개 부처 RSS fetch 성공
- 국회 API 인증 키 발급 · 성공
- 최소 1건 저장 (source=assembly · motie_rss 등)

---

## T59 · APScheduler 야간 잡 등록

### 잡 스펙

| 잡 ID | 함수 | 주기 | 활성창 | 비고 |
|---|---|---|---|---|
| `watchlist_news` | `poll_news_rss` | 5m | 항상 | 15:30~08:00 도 실행 |
| `watchlist_boards` | `poll_naver_boards` | 30m | 15:30~08:00 | 정규장 중 skip |
| `watchlist_youtube` | `poll_youtube_channels` | 1h | 항상 | |
| `watchlist_assembly` | `poll_assembly_bills` | 1d (06:00) | 항상 | cron |
| `watchlist_gov_press` | `poll_gov_press` | 1h | 항상 | |
| `watchlist_finalize` | `finalize_watchlist` | 1d (08:30) | 항상 | Week 2 · placeholder 만 등록 |

### 파일
- `backend/discovery/watchlist/scheduler.py`
  ```python
  def register_watchlist_jobs(scheduler) -> None:
      """main.py lifespan 에서 호출."""
  ```
- `backend/main.py` (lifespan) · `register_watchlist_jobs(scheduler)` 추가

### DoD
- 서버 재시작 후 `/api/scheduler/jobs` (있으면) 또는 로그에서 6 잡 등록 확인
- 각 잡 최소 1회 실행 완료 (로그 확인)

---

## Week 1 완료 판정

- [ ] T58 스키마 · store 완성 · 단위 테스트 통과
- [ ] T54 뉴스 5개 소스 · 30분 관찰 · 매칭 5+ 종목 저장
- [ ] T55 종토방 · 유니버스 순회 · z-score 계산 · 저장
- [ ] T56 YouTube · API 성공 · 4채널 최근 upload 저장
- [ ] T57 국회·정부 · RSS 성공 · 산업 매핑 저장
- [ ] T59 6 잡 등록 · lifespan 통합 · 실행 로그 확인
- [ ] UI 미노출 (Week 2 에서 `/watchlist` 페이지 신설)
- [ ] `SNIPER_LIVE_ENABLED=false` 유지 · 실주문 트리거 없음
- [ ] 로컬 완료 후 사용자 승인 → 단일 커밋 · 단일 배포 (`feedback_deploy_only_when_complete`)

## Week 2 예고

- T60 composite_score = 0.35·news_z + 0.25·board_z + 0.15·youtube + 0.15·event + 0.10·prev_day
- T61 finalize_watchlist 잡 실체 (08:30 KST)
- T62 `/watchlist` 페이지 (Top 30 · breakdown)
- T63 사용자 수동 편집 (add/remove/lock)

---

## 리스크 · 개방 이슈

1. **RSS URL 유효성** · 5개 언론 URL 실측 결과에 따라 대체 필요
2. **naver 종토방 파싱** · HTML 구조 변경 감시 필요 · 실패 시 alerting
3. **YouTube API 키** · Google Cloud 프로젝트 준비 · quota 모니터링
4. **국회 API 인증키** · open.assembly.go.kr 발급 절차 진행 필요
5. **60일 baseline 없음 · v1** · 초기 며칠은 baseline 부족 · z-score 부정확
   - 완화: Sprint 2 forward test 는 5거래일 · 6일차 이후 실 시뮬 시작
6. **회사명 축약·별칭** · v1 은 정확 매칭만 · 재현율 손실 인지

## 참조

- `docs/plans/sniper/02-strategic-pivot-as-is-to-be.md`
- `[[project_strategic_pivot_pre_market]]`
- `[[feedback_deploy_only_when_complete]]`
- `[[project_motir_rebrand]]` (산업부 명칭·도메인 확인 필요)
