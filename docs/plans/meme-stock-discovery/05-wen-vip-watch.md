# 05. WEN VIP 특별 감시 채널

**작성일**: 2026-07-07 (P-A 로컬 검증 완료 2026-07-08)
**상태**: 🚧 P-A 로컬 검증 완료 · 사용자 배포 승인 대기
**선행**: 04 [구현 로드맵](04-implementation-roadmap.md) (Phase 1a~2 완료)
**계기**: 사용자님 웬디스(WEN, Nasdaq) 실매수 진행 중 → 개별 종목 심층 감시 요구

> 본 문서는 **세션 인계용 종합 기획서**. 새 Claude Code 세션이 이 파일 하나만 읽으면 컨텍스트가 완성되도록 자체 완결적으로 구성.

---

## 1. 왜 WEN이 특별한가

- **밈주 워치 프로젝트의 상징적 시작 계기** ([README.md](README.md) 최상단): 2026-06 Wendy's +26% + WSB "Save Wendy's" 바이럴 + 공매도 23% squeeze
- **백테스트 5건 중 유일한 미합격 사례**: Phase 2 튜닝 후 max 1.200 @D+0 달성했으나 D-1까지 신호 부재 → "폭등이 D-day 갑작스러운 시작" 특성 확인
- **개선 방향 명시**: 03-backtest-report.md → "Reddit WSB 바이럴이 D-2~D-3 시작 → social 시그널 추가 시 lead time 확장 예상"
- **사용자 실매수**: 개인 P&L이 걸린 상황 → 종목 관점 알림을 넘어 **포지션 인식형** 알림 필요

즉 WEN은 (1) 개선 여지가 남은 유일 사례, (2) 실제 자본이 걸린 종목, (3) 밈주 프로젝트의 원점 — 세 가지가 겹치는 유일한 티커.

---

## 2. 8대 획기적 제안

### 주식동업투자자 관점 (4)

#### A1. Trian Partners(넬슨 펠츠) 액티비스트 트래커 ⭐⭐⭐
- WEN 최대주주급 액티비스트. **13D/13G/13F 필링·Trian 언급 뉴스가 5~15% 급등 최대 catalyst**
- SEC EDGAR RSS 폴링 → "Trian / Nelson Peltz / Wendy's Company" 매치 시 즉시 알림
- **왜 획기적**: Reddit/X 소셜 신호보다 3~6시간 선행. 대부분 밈봇이 놓치는 지점

#### A2. 매수 평균가·수량 인식형 동적 알림 ⭐⭐⭐
- 현행 밈주 워치는 "종목 관점" (누구든 동일 신호). 실제 투자자는 **본인 P&L 기준** 알림이 실용적
- 등록: 평균가, 수량, 목표 수익률, 최대 감내 손실률
- 알림 예:
  - `평균가 +7%`: 부분 익절 검토
  - `평균가 +15%`: Trailing Stop 자동 상향
  - `평균가 -5%`: 손절 라인 접근 (사고 발생 전 선제 알림)
- **재활용**: upbit-tradebot의 Take Profit + Trailing Stop 로직 (검증된 코드)

#### A3. Peer Divergence — 밈 모드 vs 펀더멘털 모드 자동 판별 ⭐⭐
- **동조**(MCD/QSR/YUM/CMG): 외식 매크로 → 홀딩
- **이탈**(WEN만 튀는): 밈/이벤트드리븐 → 익절 검토
- 구현: 3σ 이탈 감지 시 "밈 모드" 태깅
- **왜 획기적**: 이 두 상태 구분 없으면 익절/홀딩 판단이 정반대로 갈 수 있음

#### A4. 이벤트 캘린더 하드코딩 + D-3/D-1 리마인더 ⭐⭐
- 실적 (약 8/1 예상), 배당락, Investor Day, 프랜차이즈 신규 발표
- 이벤트 앞 IV 급등 → 옵션 시장이 미리 아는 신호

### 데이터전문분석가 관점 (4)

#### B1. 옵션 시장 서베일런스 ⭐⭐⭐ 밈주 감시 게임체인저
현물만 보면 반쪽. 밈주는 **옵션이 현물을 밀어올리는 구조** (2021 GME 재확인):
| 지표 | 의미 |
|------|------|
| Gamma Exposure (GEX) | 딜러 헷지 자기증폭 예측 |
| Put/Call ratio 급변 | 방향성 베팅 쏠림 |
| UOA (평시 5배+) | 특정 strike 집중 |
| Max Pain | 옵션 만기 수렴 가격 |

**데이터 소스 검증 필요**:
- CBOE 무료 API (지연 데이터 15분)
- Yahoo Options 페이지 스크래핑 (rate limit 확인)
- Unusual Whales (유료 대안)

#### B2. 다중 소스 Meme Heat Score (Fusion) ⭐⭐
현행 confluence 5요소 위에 별도 **0~100 스코어**:

| 소스 | 상태 | 가중치 |
|------|------|--------|
| apewisdom (Reddit 대체) | ✅ 가용 | 0.35 |
| 네이버 뉴스 (WEN 언급) | ✅ 가용 | 0.20 |
| YouTube 조회수·업로드 | 미검증 | 0.15 |
| SEC 필링 velocity | ✅ 가용 (EDGAR RSS) | 0.15 |
| 옵션 UOA 강도 | B1 결과 재사용 | 0.15 |
| ~~Stocktwits~~ | ❌ 403 (코드 보존만) | 0 |
| ~~Google Trends~~ | ❌ 429 (코드 보존만) | 0 |
| ~~X/Twitter~~ | 미검증 (API 유료화) | 0 |

**정규화**: z-score → 가중 합성 → 0~100. **획기성**: pump-and-dump 조작 저항 (단일 소스 조작으로는 스코어 안 오름)

#### B3. Regime Detection (HMM 기반) ⭐⭐
- 상태: {펀더멘털, 밈-냉각, 밈-가열, 이벤트드리븐}
- Features: 변동성, 거래량, 옵션 volume, sentiment score, peer 상관도
- **왜 획기적**: 상태별로 손절·익절 룰이 달라야 함. 현행은 단일 룰

#### B4. Monte Carlo P&L 시나리오 시뮬레이터 ⭐⭐
- 입력: 매수가·수량
- 과거 WEN drawdown 이벤트 재현 (2021 밈, 2022 인플레, 2023 activist)
- 10,000회 시뮬 → 30일 P&L 분포·손절 확률·최적 사이즈
- Kelly criterion으로 부분 청산/추가 매수 근거

---

## 3. 킬러 통합 제안 — "WEN VIP 채널"

기존 밈주 워치에 **VIP 티어** 추가:

| 항목 | 일반 밈주 | **WEN VIP** |
|------|-----------|-------------|
| 폴링 간격 | 5분 (apewisdom batch) | **30초** (US 장중), 5분 (AH/PM) |
| 시그널 | 5요소 confluence | **5요소 + 옵션 GEX + Trian tracker + Peer divergence** |
| 임계값 | 정적 | **매수가 기반 동적** |
| 알림 | Telegram 일반 | **Telegram 우선순위 3단계** (긴급/일반/참고) |
| 운영 시간 | 09:00~24:00 (KST) | **24시간** (AH·프리마켓 포함) |
| 액션 | 텍스트만 | **텍스트 + 대시보드 원클릭 링크** |

---

## 4. 실질 제약 (반드시 반영)

**운영 IP 차단 매트릭스** ([README.md#운영-차단-매트릭스](README.md) 참조):
| 소스 | 상태 |
|------|------|
| 네이버 금융 (US+KRX 일봉, 뉴스, marketValue) | ✅ |
| apewisdom (Reddit 사실상 대체) | ✅ |
| yfinance, Reddit 공개 JSON, Stocktwits, Google Trends, pykrx | ❌ |
| SEC EDGAR RSS | 🟡 미검증 (P-A에서 검증 필요) |
| CBOE/Yahoo Options | 🟡 미검증 (P-B에서 검증 필요) |
| X/Twitter API | ❌ 유료화 (제외) |

**첫 세션에서 반드시 검증할 것**:
1. SEC EDGAR RSS로 Trian 필링 실시간 감지 가능 여부
2. CBOE 무료 옵션 데이터 가용성 (지연 데이터 허용)
3. 30초 폴링 시 네이버 금융 rate limit

---

## 5. Phase 로드맵

| Phase | 기간 | 내용 | 완료 기준 |
|-------|------|------|-----------|
| **P-A 필수** | 1~2일 | Trian tracker, 매수가 기반 알림, 30초 폴링, WEN 별도 VIP 티어 | Trian 필링 실시간 감지 성공 + WEN 개별 알림 채널 활성 |
| **P-B 시장 데이터** | 2~3일 | 옵션 GEX/UOA, Peer Divergence (MCD/QSR/YUM/CMG), 이벤트 캘린더 | GEX 스코어 대시보드 노출 + peer 3σ 이탈 감지 |
| **P-C 센티먼트 확장** | 3~5일 | Meme Heat Score fusion (apewisdom + 네이버 뉴스 + SEC velocity + UOA) | 0~100 스코어 노출 + 백테스트 재검증 |
| **P-D 고도화** | 1주+ | Regime Detection (HMM), Monte Carlo 시뮬레이터 | 상태 자동 판별 + P&L 분포 UI |

**배포 원칙** ([[feedback_deploy_only_when_complete]]): P-A 완결 후 단일 배포, 이후 각 Phase 완결 시 개별 배포. Phase 부분 배포 금지.

---

## 6. 관련 파일 위치 (다음 세션 진입점)

### 기존 코드 (수정·확장 대상)
- `backend/discovery/moonshot_picks.py` — 밈주 discovery 메인
- `backend/discovery/crazy_picks.py` — Crazy 로직
- `backend/discovery/universe.py` — 티커 universe 관리
- `backend/discovery/backtest.py` — 백테스트 프레임워크
- `backend/api/main.py` — `/api/v1/meme-watch/*` 엔드포인트
- `backend/api/schemas.py` — Pydantic 스키마
- `backend/services/models.py` — DB 모델
- `backend/scheduler/cron.py` — 스케줄러 (5분 → 30초 VIP 별도 트랙 추가 지점)
- `frontend/app/meme-watch/` — 대시보드 페이지

### 재활용 대상 (upbit-tradebot-mvp)
- `core/filters/sell_filters.py` — Take Profit, Trailing Stop, Stale Position (매수가 기반 알림 로직 이식용)

### 참조 문서
- `docs/plans/meme-stock-discovery/README.md` — 전체 프로젝트 상태
- `docs/plans/meme-stock-discovery/01-signal-sources.md` — 시그널 소스 설계
- `docs/plans/meme-stock-discovery/02-confluence-design.md` — 5요소 confluence 로직
- `docs/plans/meme-stock-discovery/03-backtest-report.md` — WEN 미합격 원인 상세

---

## 7. 다음 세션 진입 첫 스텝

새 세션에서 이 문서를 읽은 뒤 아래 순서로 시작:

### Step 0 — 사용자 결정 수집 (필수, 코드 착수 전)
- 우선순위 선택: `P-A만` / `P-A+P-B` / `P-A~P-C` / `전체`
- 알림 채널: 기존 Telegram 재활용? 또는 별도 채널?
- 매수가 정보 등록 방식: DB 직접 / 환경변수 / 대시보드 UI

### Step 1 — 데이터 소스 실측 검증 (P-A 착수 전 1~2시간)
```bash
# SEC EDGAR RSS 접근성
curl -sS "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000030697&type=SC+13&dateb=&owner=include&count=40&output=atom"

# CBOE 옵션 데이터 페이지 접근성
curl -sS "https://www.cboe.com/us/options/market_statistics/daily/?dt=<YYYY-MM-DD>"

# 네이버 US WEN 일봉 rate limit
# → 기존 backend/services/naver_client.py 재활용
```

### Step 2 — P-A 착수 (사용자 승인 후)
1. `backend/discovery/vip/` 서브패키지 신설 (기존 코드 영향 최소화)
2. `wen_watch.py` — 30초 폴링 + Trian tracker + 매수가 기반 알림
3. `/api/v1/meme-watch/vip/wen` 신규 엔드포인트
4. `frontend/app/meme-watch/vip/` 서브 대시보드 (선택)
5. 로컬 검증 → dashboard.py 버전 갱신 → 커밋 → 사용자 승인 → 배포

### Step 3 — 인수인계 문서 갱신
- 본 문서 상태를 "기획 완료 → P-A 진행" 등으로 갱신
- README.md 진행 현황에 VIP 트랙 추가

---

## 8. 이전 세션 상태 스냅샷 (2026-07-07 세션 종료 시점)

### 로컬 서비스 상태
- **backend**: `127.0.0.1:10001` — uvicorn 실행 중 (PID 18701) — 9001 MinIO 충돌 회피로 8001→10001 이동
- **frontend**: `127.0.0.1:3001` — 종료됨 (Docker가 3001 재점유). 새 세션에서 다른 포트로 재실행 필요
- **THETAK MinIO**: 9001 유지 (건드리지 않음)

### 이전 세션에서 수정된 파일
- `frontend/.env.local` — `NEXT_PUBLIC_API_BASE_URL=http://localhost:10001`
- `frontend/app/sector-leaders/page.tsx:379` — "포트 8001" → "포트 10001"

### 이전 세션에서 논의된 자격증명 이슈 (미결)
- `frontend/.env.local:6` — `CUSTOMS_API_KEY` 평문 상주 (data.go.kr 공공API 키)
- git 추적 안 됨 (`.gitignore` 등재 확인) → 저장소 노출 위험 없음
- 로컬 파일 노출은 존재 → 향후 Keychain/direnv 이전 검토 (사용자 결정 대기)

---

## 9. 위험·제약 (계속 유효)

- **밈주 = 본질적 도박**: 과거 패턴 ≠ 미래. 모델은 보조 신호. **투자 권유 아님**.
- **개별 종목 감시의 함정**: WEN 편애로 인한 확증편향 위험. Regime Detection (P-D) 필수 이유.
- **옵션 데이터 유료 벽**: 무료 15분 지연 데이터로는 gamma squeeze의 실시간 감지 한계.
- **사용자 실매수 종목**: 손실 알림이 심리적 반응을 유발할 수 있음. 알림 문구·타이밍 신중 설계.

---

**마지막 업데이트**: 2026-07-07 (세션 인계 목적 초안 작성)
**다음 갱신 시점**: P-A 완료 후 상태 필드 및 진행 현황 갱신

---

## 10. P-A 구현 결과 (2026-07-08 로컬 검증 완료)

### 사용자 결정 (Step 0)
| 항목 | 채택 |
|------|------|
| 범위 | **P-A 만** (배포 완결 원칙 준수) |
| 알림 채널 | 기존 밈주 봇 재활용 + `[VIP-WEN · <이벤트>]` 태그 |
| 매수가 등록 | 환경변수 `.env` |

### Step 1 실측 결과
| 대상 | 결과 |
|------|------|
| SEC EDGAR data.sec.gov | ✅ 200 (정식 UA "회사명 + 이메일" 형식 필수) — Wendy's Co CIK `0000030697` 필링 수신 |
| Trian Fund Management CIK | ✅ **`0001345471`** 확정 (EDGAR full-text search 로 검증) |
| 네이버 US 실시간 | ✅ `api.stock.naver.com/stock/WEN.O/basic` (`delayTime:0`, 정규장·AH 등락률 동시 제공) |
| 30초 폴링 부하 | ✅ 5초 간격에서도 안정 (30초는 여유) |

### 신규 파일
- `backend/discovery/vip/__init__.py`
- `backend/discovery/vip/config.py` — `.env` 로딩·활성 판정
- `backend/discovery/vip/price_client.py` — 네이버 US basic 래퍼
- `backend/discovery/vip/state.py` — 파일 기반 상태 (`data/vip_wen_state.json`, 24h cooldown, Trian accession dedup, trail peak 추적)
- `backend/discovery/vip/position.py` — TP1 / TP2 / STOP_APPROACH / TRAIL_ARMED / TRAIL_GIVEBACK 판정
- `backend/discovery/vip/trian_tracker.py` — data.sec.gov 폴러, SC 13D/G 계열 + WEN 문자열 매치
- `backend/discovery/vip/notifier.py` — `[VIP-WEN · <이벤트>]` 포맷
- `backend/discovery/vip/wen_watch.py` — 오케스트레이터 (`run_price_tick` / `run_trian_tick` / `get_status`)

### 수정 파일
- `backend/scheduler/cron.py` — `IntervalTrigger` 30s(정규장) / 300s(AH) / 300s(Trian) 3개 job 추가 · `--once wen_vip_price|wen_vip_trian|wen_vip_status`
- `backend/api/routes/meme_watch.py` — `GET /api/v1/meme-watch/vip/wen/status`
- `backend/.env.example` — `WEN_VIP_*` + `SEC_EDGAR_UA` 12개 키 템플릿

### 로컬 검증 로그
- 문법 검증 (`python -m py_compile`) ✅
- Import smoke test ✅ · `is_us_regular_hours()` 정상 (KST 21시 → False)
- **비활성 상태**: `active: False`, quote 없이 thresholds 만 반환 ✅
- **활성 상태 mock** (`WEN_VIP_ENABLED=true`, `AVG_PRICE=7.0`): quote 정상 (7.78 USD, `overMarketRatio=-0.64`), `pnl=+11.14%`, TP1 + TRAIL_ARMED 2건 판정 ✅
- **STOP** (avg 8.5): -8.47%, STOP_APPROACH + TRAIL_GIVEBACK 2건 ✅
- **TP2** (avg 6.5): +19.7%, TP1 + TP2 2건 ✅
- **Trian tick**: SEC 200, WEN 매치 `SC 13D/A · 2023-08-23 · 0001345471-23-000134` 감지 ✅
- **API 엔드포인트**: `/api/v1/meme-watch/vip/wen/status` 200, JSON 응답 완성 ✅
- **스케줄러**: 기존 5 + VIP 3 = 8개 job 등록 확인 ✅

### 운영 활성화 절차 (배포 후)
1. 서버 `.env` 에 `WEN_VIP_ENABLED=true`, `WEN_VIP_AVG_PRICE=<실 평균가>`, `WEN_VIP_QTY=<수량>` 설정
2. `systemctl restart tradebot-cron` (스케줄러가 신규 3개 job 로드)
3. `curl http://127.0.0.1:10001/api/v1/meme-watch/vip/wen/status` 로 활성 확인
4. `WEN_VIP_ENABLED=false` 로 즉시 비활성 가능 (실매수 청산 후)

### 잔여 위험·주의
- Telegram 미설정 상태에서는 Trian dedup 이 걸리지 않아 5분마다 재감지 (배포 시 `TELEGRAM_*` 반드시 설정)
- `data/vip_wen_state.json` 은 프로세스 재시작에도 살아남지만 `data/` 는 `.gitignore` 등재됨
- 30s / 300s job 은 `WEN_VIP_ENABLED=false` 라도 tick 진입 후 첫 줄에서 조기 return — 상시 등록해도 부하 미미 (config load + skip 만)

---

## 11. P-A+ 리팩터 — 종목 파라미터화 + UI 편집기 (2026-07-08 오후)

**계기**: 사용자 요청 — "VIP 종목은 추후 바뀔 수 있다. 고려하여 구현" + "activist 내용을 화면에서 보기·수정".

### 사용자 결정 (Step 0-b)
| 항목 | 채택 |
|------|------|
| 접두어 | **전면 리네임 (A)** — `WEN_VIP_*` 완전 삭제, `VIP_*` 통일 |
| Activist | env 기반 선택적 활성 (`VIP_ACTIVIST_ENABLED`) |
| UI 범위 | **백엔드 override + 프론트 `/vip` 페이지 (조회+편집) 전체** |

### 스키마 변경 (요약)
- env 접두어: `WEN_VIP_*` → `VIP_*` (기존 하위 호환 없음 — 서버에 실 값 아직 없음)
- 신규 env: `VIP_COMPANY_NAME`, `VIP_TAG` (미지정 시 티커에서 자동), `VIP_ACTIVIST_ENABLED`, `VIP_ACTIVIST_CIK`, `VIP_ACTIVIST_NAME`, `VIP_ACTIVIST_KEYWORDS`
- 파일 리네임: `wen_watch.py` → `vip_watch.py`, `trian_tracker.py` → `activist_tracker.py`
- state 파일: `data/vip_{ticker_slug}_state.json` (예: `vip_WEN_O_state.json`) — 티커별 격리
- 이벤트: `TRIAN_FILING` → `ACTIVIST_FILING`
- 태그: `[VIP-WEN · …]` → `[VIP-{TAG} · …]` (env·티커에서 파생)
- 스케줄러 job id: `wen_vip_*` → `vip_*`
- API: `/vip/wen/status` → `/vip/status` + `/vip/config` (GET·PATCH)
- `--once` 인자: `wen_vip_*` → `vip_*` (`vip_config` 추가)

### JSON override 시스템
- 파일: `data/vip_overrides.json`
- 허용 키: `activist_enabled`, `activist_cik`, `activist_name`, `activist_keywords`
- 로드 순서: `.env` (기본) → `data/vip_overrides.json` (런타임 override, tick 마다 재로드)
- 프로세스 재시작 없이 UI 편집 반영 → 사용자가 activist CIK·키워드를 즉시 바꿔서 실험 가능
- 빈 문자열/빈 리스트 저장 → 해당 키 override 삭제(env 기본값 복귀)

### API 확장
- `GET /api/v1/meme-watch/vip/status` — 실시간 quote·P&L·최근 이벤트·activist 최신 대상 필링·최근 10건 이력
- `GET /api/v1/meme-watch/vip/config` — 편집 폼용 스냅샷 (env + overrides merged)
- `PATCH /api/v1/meme-watch/vip/config` — `activist.{enabled,cik,name,keywords}` override 저장

### Frontend `/vip` (신규)
- `frontend/app/vip/page.tsx` — App Router 페이지, TanStack Query 30s refetch
- 네비 진입: layout `NAV` 배열에 `🕵️ VIP 감시` 링크 추가
- 카드 구성:
  - **Quote Card**: 현재가·정규장/AH 등락률·매수가 대비 P&L·손익 USD
  - **Thresholds Card**: TP1/TP2/STOP/TRAIL 임계값 (읽기 전용, 편집은 서버 .env)
  - **Activist Card**: enabled·CIK·name·keywords + 최신 대상 필링 + 최근 10건 이력(펼침)
  - **Sent Events Log**: 24h cooldown 상태 (event: last_sent_at)
- **Activist Editor Modal**: enabled 토글, CIK·name·keywords 편집 → PATCH → 즉시 반영
- override 초기화 버튼 (env 기본값 복귀)

### 로컬 재검증 (오후)
- `py_compile` ✅ 9개 파일
- import smoke ✅ · `--once vip_status` 정상 (`active/activist_active/quote/pnl/activist.recent_forms` 완비)
- `--once vip_activist` — Trian 최신 SC 13D/A `2023-08-23` 감지 유지 ✅ (오래된 desc 매치 · 최근 SCHEDULE 13D/A 는 desc 비어 매치 실패 → 별건 개선 사항)
- `--once vip_config` — env + overrides merge 응답 ✅
- Frontend `npx tsc --noEmit` ✅ 0 오류

### 종목 전환 절차 (다른 종목으로 바꿀 때)
1. 서버 `.env` 편집:
   - `VIP_TICKER=<새 티커>` (네이버 reuters code, 예: `AAPL`)
   - `VIP_COMPANY_NAME=<회사명>`
   - `VIP_AVG_PRICE=<새 평균가>`, `VIP_QTY=<수량>`
2. Activist 감시 필요/불필요에 따라:
   - 필요: `VIP_ACTIVIST_*` env 또는 UI `/vip` 편집기에서 CIK·키워드 설정
   - 불필요: `VIP_ACTIVIST_ENABLED=false` (또는 UI 에서 토글)
3. `systemctl restart tradebot-cron` — state 파일이 티커별로 분리돼 이전 종목 상태와 섞이지 않음
4. `/vip` 페이지에서 활성 확인

### 알려진 개선 여지 (P-A+β)
- Trian 최근 SCHEDULE 13D/A 필링이 `primaryDocDescription` 비어있어 keyword 매치 실패. 해결안: filing 상세 페이지에서 subject company 재추출, 또는 관심 폼 확대 후 사용자에게 "확인 필요" 태그로 발송. 별건 스코프.
- `data/vip_overrides.json` 편집 UI 는 activist 만 지원. TP·STOP 등 임계값 UI 편집도 원하면 스키마 확장 (지금은 env 편집 + 재시작).
