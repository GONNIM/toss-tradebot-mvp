# Implementation Roadmap — Toss Tradebot MVP

**작성일**: 2026-06-19
**상태**: v2 — Phase A~I 완료 (Toss API 미의존 영역 전체 구현)
**선행 문서**: `docs/plans/PRD/03-PRD-v1.md` (v0.1-7) + `docs/plans/PRD/02-strategy-decision.md` (44 결정)

## 진행 상태 (2026-06-19)

| Phase | 상태 | 산출물 |
|---|---|---|
| A 골격 | ✅ | backend/frontend/.gitignore/.env.example/CLAUDE.md |
| B DB 인프라 | ✅ | services/db.py·models.py(10테이블)·init_db.py·test_db.py(5케이스) |
| C 데이터 소스 | ✅ 7/7 | base·stooq·finnhub·sec_edgar·finra·reddit·rss + services/llm |
| D Discovery 코어 | ✅ | scoring(9인자)·universe·crazy_picks·moonshot_picks·backtest |
| E /moonshot CLI | ✅ | cli/moonshot.py (7 명령) + console_scripts |
| F Telegram | ✅ | services/notifier.py (dedupe·HTML·3 레벨) |
| G FastAPI | ✅ | api/main.py + 6 라우트 + schemas.py |
| H Next.js | ✅ | 6 페이지 + lib/api.ts·utils.ts·providers.tsx |
| I 인프라 | ✅ | scheduler/cron.py + docs/deployment/INFRA.md |
| J dry-run | ⏳ | 1주 데이터 누적 (cron 실행 후) |
| **K Toss API** | 🔒 | **사용자 결정: Toss API 오픈 대기** |

**총 코드**: ~5,400 줄 (Python+TypeScript, __init__·테스트·문서 포함)

---

## 0. 본 문서의 위치

PRD v0.1 (`03-PRD-v1.md`) 의 모든 결정 사항을 **실 코드로 구현하기 위한 단계별 로드맵**.

**전략**:
- 사용자 결정 2026-06-19: **Toss API 사용 이외 모든 영역 우선 진행**
- 자동매매 코어 (Phase K) 는 Toss API 오픈 후 별도 진입
- 메모리 [feedback-deploy-only-when-complete] 준수: Phase A~J 로컬 완성 후 단일 배포
- 메모리 [feedback-plan-doc-protocol] 준수: 본 문서 = 구현계획서 영구 기록

---

## 1. 전체 Phase (11단계)

| # | Phase | 영역 | 예상 일정 | 우선순위 | Toss API |
|---|---|---|---|---|---|
| **A** | 프로젝트 골격 | backend/ + frontend/ + .env.example | 1~2일 | ⭐⭐⭐ | ❌ |
| **B** | DB 인프라 | SQLAlchemy 2.0 + SQLite + 스키마 | 2~3일 | ⭐⭐⭐ | ❌ |
| **C** | 데이터 소스 클라이언트 | Stooq + Finnhub + SEC EDGAR + FINRA + Reddit + RSS + Anthropic | 3~5일 | ⭐⭐⭐ | ❌ |
| **D** | Discovery 코어 | scoring + crazy_picks + moonshot_picks + backtest | 5~7일 | ⭐⭐⭐ | ❌ |
| **E** | /moonshot CLI | click + rich + 7 명령어 | 2~3일 | ⭐⭐ | ❌ |
| **F** | Telegram 알림 | notifier + error_messages (upbit 차용) | 1일 | ⭐⭐ | ❌ |
| **G** | FastAPI Backend | api/main.py + 라우트 6종 + API Key | 3~5일 | ⭐⭐ | ❌ |
| **H** | Frontend (Next.js) | 6 페이지 + NextAuth + 차트 + shadcn/ui | 5~10일 | ⭐⭐ | ❌ |
| **I** | 인프라 셋업 가이드 | Nginx + PM2 + systemd + Let's Encrypt + GitHub Actions yml | 1~2일 | ⭐⭐ | ❌ |
| **J** | 통합 테스트 + 1주 dry-run | Discovery 데이터 누적 + 작동 확인 | 7일 (대기 포함) | ⭐⭐⭐ | ❌ |
| **K** | **자동매매 코어 (보류)** | toss_api + live_loop + 결정 1~13·23·24·25 | 5~7일 | ⭐ | ✅ **필수** |

**총 예상 (A~J)**: 25~35일
**Phase K (자동매매)**: 별도 Toss API 오픈 후

---

## 2. Phase 의존성

```
A (골격)
  ↓
B (DB)
  ↓
C (데이터 소스)
  ↓
D (Discovery 코어)
  ↓
┌─────────┬─────────┬─────────┐
│         │         │         │
E (CLI)  F (알림)  G (API)
                    ↓
                  H (Frontend)
                    ↓
                  I (인프라)
                    ↓
                  J (통합 테스트 + dry-run)
                    ↓
              [Phase A~J 1회 단일 배포]
                    ↓
              [Toss API 오픈 대기]
                    ↓
              K (자동매매 코어, 별도 배포)
```

→ A·B·C·D 순차, E·F·G는 D 완료 후 병렬 가능. H는 G 완료 후. I·J는 H 후.

---

## 3. 진행 방식 (사용자 결정 2026-06-19)

- **Option 1 단계별 신중 진행** ✅ 채택
- 각 Phase 완료 후 사용자 검토 → 다음 Phase 진행
- 단일 세션: 1~2 Phase 권고
- Phase J 완료 후 **단일 배포** (메모리 [deploy-only-when-complete])

---

## 4. Phase 별 세부 작업

### Phase A — 프로젝트 골격 (현 작업)

```
backend/
├── pyproject.toml                  # console_scripts: moonshot
├── requirements.txt
├── .env.example                    # placeholder만
├── __init__.py
├── core/                           # 자동매매 코어 (Phase K)
├── engine/                         # Phase K
├── discovery/                      # Phase D
│   ├── __init__.py
│   └── data_sources/               # Phase C
│       └── __init__.py
├── services/                       # Phase C, F
│   └── __init__.py
├── api/                            # Phase G
│   └── __init__.py
├── cli/                            # Phase E
│   └── __init__.py
├── tests/
│   └── __init__.py
└── data/                           # SQLite + 캐시
    └── .gitkeep

frontend/
├── package.json
├── tsconfig.json
├── next.config.ts
├── tailwind.config.ts
├── postcss.config.mjs
├── .env.example                    # placeholder만
├── app/
│   ├── layout.tsx
│   ├── page.tsx                    # Landing (placeholder)
│   └── globals.css
├── components/
├── lib/
└── public/

.github/
└── workflows/
    └── deploy.yml                  # Phase I (placeholder)
```

### Phase B — DB 인프라
- `backend/services/db.py` — SQLAlchemy 2.0 setup + 세션 관리
- `backend/services/models.py` — 테이블 정의 (crazy_picks·moonshot_picks·daily_candles·logs·ticker_universe)
- Alembic 또는 `create_all` 마이그
- SQLite 파일: `backend/data/tradebot.db`

### Phase C — 데이터 소스 클라이언트  ✅ **완료 (7/7)**
- ✅ `backend/discovery/data_sources/base.py` — httpx 비동기 + tenacity 재시도
- ✅ `backend/discovery/data_sources/stooq.py` — 가격·52w·거래량
- ✅ `backend/discovery/data_sources/finnhub.py` — 어닝 캘린더·애널리스트
- ✅ `backend/discovery/data_sources/sec_edgar.py` — Form 4 (인사이더 cluster)
- ✅ `backend/discovery/data_sources/finra.py` — 단기매도 일일 거래량 (RegSHO)
- ✅ `backend/discovery/data_sources/reddit.py` — PRAW (WSB 멘션 카운트)
- ✅ `backend/discovery/data_sources/rss.py` — feedparser (PRNewswire / GlobeNewswire)
- ✅ `backend/services/llm.py` — Anthropic Claude Haiku 4.5 (thesis 생성)

각 클라이언트:
- HTTP 클라이언트 (httpx) + 캐싱 (60초~1일)
- Rate limit handling
- 에러 핸들링 (지수 백오프)
- 단위 테스트 (`tests/data_sources/test_*.py`)

### Phase D — Discovery 코어
- `backend/discovery/scoring.py` — 9 인자 가중 계산
- `backend/discovery/crazy_picks.py` — Crazy 모듈 (06:30 KST cron)
- `backend/discovery/moonshot_picks.py` — Moonshot 모듈 (16:50 KST cron)
- `backend/discovery/backtest.py` — 과거 데이터 점수 검증
- 각 모듈 단위 테스트 + 통합 테스트

### Phase E — /moonshot CLI
- `backend/cli/moonshot.py` — click + rich
- 7 명령어 구현 (`moonshot`, `top`, `detail`, `history`, `perf`, `live`, `positions`)
- 출력 포맷 (rich 박스·테이블)
- `pyproject.toml` console_scripts entry
- `pip install -e ./backend` 후 `moonshot` 명령 작동

### Phase F — Telegram 알림
- `backend/services/notifier.py` — upbit 패턴 차용
  - dedupe (메모리 dict)
  - LEVEL_CRITICAL / WARNING / INFO
  - HTML 포맷
- `backend/services/error_messages.py` — 한국어 매핑

### Phase G — FastAPI Backend
- `backend/api/main.py` — FastAPI app
- `backend/api/routes/`:
  - `dashboard.py` — 자동매매 요약 (Phase K 후 활성)
  - `crazy.py` — Crazy Picks Top 10
  - `moonshot.py` — Moonshot Picks Top 3
  - `positions.py` — 보유 종목
  - `settings.py` — 파라미터
  - `logs.py` — 감사 로그
- `backend/api/auth.py` — API Key 미들웨어
- `backend/api/schemas.py` — Pydantic

### Phase H — Frontend (Next.js)
- `frontend/app/`:
  - `layout.tsx` — 공통 레이아웃
  - `page.tsx` — 랜딩
  - `dashboard/page.tsx` — 자동매매 대시보드 (Phase K 후 활성)
  - `crazy/page.tsx` — Crazy Picks
  - `moonshot/page.tsx` — Moonshot Picks
  - `positions/page.tsx` — 보유 종목
  - `settings/page.tsx` — 파라미터
  - `logs/page.tsx` — 감사 로그
- `frontend/app/api/auth/[...nextauth]/route.ts` — Google OAuth + ALLOWED_EMAIL 화이트리스트
- `frontend/components/ui/` — shadcn/ui 컴포넌트
- `frontend/components/charts/` — TradingView Lightweight + Recharts
- `frontend/lib/api.ts` — Backend FastAPI 호출 (TanStack Query)

### Phase I — 인프라 셋업 가이드
- `scripts/server-setup.md` — 사용자 가이드 (SSH 키 셋업·Nginx·PM2·SSL)
- `nginx/tradebot.conf` — reverse proxy 설정
- `pm2.config.js` — Frontend 프로세스 정의
- `systemd/tradebot-backend.service` — Backend 데몬
- `.github/workflows/deploy.yml` — CI/CD (Phase A에서 placeholder, 여기서 완성)
- Let's Encrypt 가이드

### Phase J — 통합 테스트 + 1주 dry-run
- Discovery 모듈 1주 매일 cron 실 운영
- 추천 종목·thesis·perf_1d 자동 누적
- /moonshot CLI 호출 검증
- Frontend 6 페이지 작동 확인
- Telegram 알림 작동 확인
- → 통합 검증 완료 후 단일 배포

### Phase K — 자동매매 코어 (Toss API 오픈 후 별도)
- `backend/services/toss_api.py` — OAuth + REST 래퍼
- `backend/engine/live_loop.py` — 60초 polling 메인 루프
- `backend/core/strategy_engine.py` — 봉 처리 + 매수/매도 판단
- `backend/core/filters/` — 매수/매도 필터
- `backend/core/reconciler.py` — Toss 주문 reconcile
- 결정 1~13·23·24·25 모두 구현
- 콘솔 검증 6항목 완료 후 진입

---

## 5. 가드레일 준수 사항

### 자격증명 (글로벌 CLAUDE.md §1)
- `.env.example`은 placeholder만 (`TOSS_CLIENT_ID=`, `ANTHROPIC_API_KEY=` 등)
- 실 `.env`는 chmod 600, git 추적 X (.gitignore 13행)
- GitHub Secrets에 SSH private key 등록 (workflow yml에 평문 금지)
- SSH 키 기반 인증만 (비밀번호 인증 비활성화)

### 코드 품질
- `bash -n` 모든 셸 스크립트 문법 검증
- `python3 -m py_compile` Python 파일 검증
- TypeScript strict mode
- Pre-commit hook (선택): gitleaks·trufflehog

### Phase 진행 규칙
- 각 Phase 완료 후 사용자 보고 → 다음 Phase 진입
- 메모리 [feedback-deploy-only-when-complete]: A~J 완성 후 단일 배포
- Phase K는 별도 배포 (Toss API 오픈 + 콘솔 검증 후)

---

## 6. 진행 추적

각 Phase 시작·완료 시 본 문서 §변경 이력 갱신.

| Phase | 시작일 | 완료일 | 비고 |
|---|---|---|---|
| **A** 골격 | 2026-06-19 | 2026-06-19 | ✅ 완료 — 15 파일 + 14 디렉터리 + .env.example (placeholder만) |
| **B** 인프라 | 2026-06-19 | 2026-06-19 | ✅ 완료 — db.py + models.py (10 테이블) + init_db.py + test_db.py (5 test cases) |
| **C** 데이터 소스 | 2026-06-19 | (진행 중) | 🚧 2/7 클라이언트 완료 — Stooq + Finnhub (base.py + tests). 잔여 5: SEC EDGAR, FINRA, Reddit PRAW, RSS, Anthropic LLM |
| D Discovery | | | |
| E CLI | | | |
| F 알림 | | | |
| G API | | | |
| H Frontend | | | |
| I 인프라 셋업 | | | |
| J 통합 + dry-run | | | |
| **K** 자동매매 | (Toss 오픈 후) | | |

---

## 7. 변경 이력

| 날짜 | 변경 | 비고 |
|---|---|---|
| 2026-06-19 | v1 초안 — 11 Phase 로드맵 + 의존성 그래프 + 진행 방식 (Option 1) | Phase A 시작 |
