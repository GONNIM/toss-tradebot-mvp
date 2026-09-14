# Toss Tradebot 사이트 지도 + Biotech Radar 통합 설계안 (WP68 · 2026-09-14)

> 📖 [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 상태 · 가설 뜻
> 🚫 **본 문서는 조사·설계 전용 · 코드 수정 0건** · 실 통합은 사용자 승인 후 별도 세션

---

## §1 · 기존 사이트 현황 (읽기 전용 조사)

### 프론트엔드 (frontend/)

| 항목 | 내용 |
|---|---|
| **프레임워크** | Next.js 14.2.18 · React 18.3.1 · next-auth 4.24.10 |
| **실행 명령** | `npm run dev` (개발 · 포트 4000) · `npm run build` · `npm run start` (프로덕션 · 포트 4000) |
| **포트** | **4000** (dev · prod 동일) |
| **라우팅 방식** | **App Router** (`frontend/app/`) |
| **API 호출** | Fetch API + react-query · base URL `/api/v1` (next.config.mjs rewrites 프록시 · env `NEXT_PUBLIC_API_BASE_URL`) |

**메뉴 (내비게이션)**:
- 파일: `frontend/components/layout/AppNav.tsx`
- 구조: **L1 (매일 여정) + L2 (심층) 2단계** · 조건부 L2 (경로 감지)
- L1: Journal · Watchlist · Sniper · Positions · Influencer · Dashboard · Logs
- L2 기본: Principles · Screener · Rulebook · Powderkeg · Activist · VIP · Sector

**주요 페이지 폴더 구조** (`frontend/app/`):
```
/ (홈) · /journal · /watchlist · /sniper · /positions · /dashboard · /logs
/influencer · /influencer/serenity · /influencer/serenity-hunter
/powderkeg · /sector-leaders · /activist-radar · /vip
/principles · /principles/screener · /principles/verification · /principles/gate-history
/rulebook · /lab (+ 하위 실험장) · /admin/settings
```

**인증**:
- next-auth 4 + **httpOnly 쿠키** (Phase D 주 7 · 2026-07-31 마이그레이션)
- 파일: `frontend/lib/auth.ts`
- 세션 API: POST/DELETE/GET `/api/v1/admin/session`

### 백엔드 (backend/)

| 항목 | 내용 |
|---|---|
| **프레임워크** | FastAPI ≥ 0.115.0 · uvicorn ≥ 0.32.0 |
| **진입 파일** | `backend/api/main.py` (FastAPI 인스턴스) |
| **DB** | SQLAlchemy 2.0.36 · aiosqlite (SQLite) · Alembic 1.14.0 |
| **정적 파일** | (StaticFiles 미사용 · SPA 프론트가 자체 렌더) |
| **인증** | `Depends()` + httpOnly 쿠키 · admin/subscriber/anon 3역할 |
| **CORS** | `CORSMiddleware` · `config.cors_origins()` (env `CORS_ORIGINS`) |

**라우터 등록 (`backend/api/main.py`)**:
```python
app.include_router(judgments.router,   prefix="/api/v1/judgments")
app.include_router(positions.router,   prefix="/api/v1/positions")
app.include_router(dashboard.router,   prefix="/api/v1/dashboard")
app.include_router(logs.router,        prefix="/api/v1/logs")
app.include_router(sniper.router,      prefix="/api/v1/sniper")
app.include_router(watchlist.router,   prefix="/api/v1/watchlist")
app.include_router(powderkeg.router,   prefix="/api/v1/powderkeg")
app.include_router(sector_leaders.router, prefix="/api/v1/sector-leaders")
app.include_router(serenity.router,    prefix="/api/v1/serenity")
app.include_router(serenity_hunter.router, prefix="/api/v1/serenity")   # 서브
app.include_router(rulebook.router,    prefix="/api/v1/rulebook")
app.include_router(principles.router,  prefix="/api/v1/principles")
app.include_router(insights.router,    prefix="/api/v1/insights")
app.include_router(meme_watch.router,  prefix="/api/v1/meme-watch")
app.include_router(settings.router,    prefix="/api/v1/settings")
app.include_router(session.router,     prefix="/api/v1/admin/session")
app.include_router(webhooks.router,    prefix="/api/v1/webhooks")
```

### 기존 메뉴 · 라우터 매핑

| 메뉴 | 프론트 경로 | 백엔드 라우터 파일 | API prefix |
|---|---|---|---|
| Journal | /journal | judgments.py | /api/v1/judgments |
| Watchlist | /watchlist | watchlist.py | /api/v1/watchlist |
| Sniper | /sniper | sniper.py | /api/v1/sniper |
| Positions | /positions | positions.py | /api/v1/positions |
| Influencer | /influencer | serenity.py | /api/v1/serenity |
| Dashboard | /dashboard | dashboard.py | /api/v1/dashboard |
| Logs | /logs | logs.py | /api/v1/logs |
| Principles | /principles | principles.py | /api/v1/principles |
| Rulebook | /rulebook | rulebook.py | /api/v1/rulebook |
| Powderkeg | /powderkeg | powderkeg.py | /api/v1/powderkeg |
| Activist | /activist-radar | meme_watch.py | /api/v1/meme-watch |
| VIP | /vip | meme_watch.py | /api/v1/meme-watch |
| Sector | /sector-leaders | sector_leaders.py | /api/v1/sector-leaders |
| Serenity Hunter | /influencer/serenity-hunter | serenity_hunter.py | /api/v1/serenity/* |

### 배포 형태

| 항목 | 내용 |
|---|---|
| 배포 호스트 | **optimus8.cafe24.com** (결정 42) |
| CI/CD | **GitHub Actions** (`.github/workflows/deploy.yml`) |
| 방식 | git pull → pip install → alembic upgrade → npm build → systemd (backend) · PM2 (frontend) |
| 헬스체크 | GET /health · 3회 재시도 · 20초 대기 |
| 환경 관리 | SOPS (age) 우선 · fallback GitHub Secrets inject |
| **로컬 dev** | 프론트 `npm run dev` (:4000) · 백엔드 별도 (uvicorn :8000 예상 · env `NEXT_PUBLIC_API_BASE_URL`) |
| **프로덕션 (서버)** | systemd + PM2 · 프론트 `npm run start` :4000 · 백엔드 uvicorn :8000 |

**차이**: 로컬 dev 는 별도 프로세스 2개 (npm dev · uvicorn) · 프로덕션은 동일하지만 systemd/PM2 관리 · 배포 자동화.

---

## §2 · Biotech Radar 통합 설계안 (구현 금지 · 사용자 승인 후 별도 세션)

### 통합 원칙 (README.md §1 기존 · 재확인)

- **격리 강제**: 신규 응용 코드는 biotech 이름공간 안에서만 · 기존 응용 무접촉
- **인프라 재사용 허용**: `logging_setup` · `data_sources` · SEC/CT.gov 어댑터 등
- **DB 테이블 접두어**: `biotech_` (현 프로젝트는 파일 CSV/JSON 위주 · DB 미도입)
- **스케줄 접두어**: `biotech_*` (이미 준수 · crontab 등록 완료)

### 통합 접점 3곳 (기존 코드 수정 = 각 1줄)

**1. 프론트 메뉴 (`frontend/components/layout/AppNav.tsx`)**:
```tsx
// L1 매일 여정 배열에 1줄 추가
{ label: "Biotech", href: "/biotech", icon: "🧬" },
```

**2. 프론트 페이지 (`frontend/app/biotech/page.tsx`)**:
```tsx
// 신규 파일 · 기존 페이지 무접촉
// 하위 라우트: /biotech (통합 대시보드) → 5개 화면 탭 or 서브 라우트
```

**3. 백엔드 라우터 (`backend/api/main.py`)**:
```python
# 다른 include_router 옆에 1줄 추가
from backend.api.routes import biotech
app.include_router(biotech.router, prefix="/api/v1/biotech", tags=["biotech"])
```

### 신규 파일 (모두 biotech 이름공간 격리)

**백엔드**:
- `backend/api/routes/biotech.py` — 신규 라우터 (읽기 전용 · md → JSON/HTML 반환)
- `backend/biotech_radar/` — 응용 로직 별도 (현재 `backend/scripts/biotech_*.py` 는 유지 · 새 서비스 계층만 신설 시)

**프론트**:
- `frontend/app/biotech/page.tsx` — 통합 대시보드 (5 화면 탭)
- `frontend/app/biotech/radar/page.tsx` — 순위표
- `frontend/app/biotech/rumor/page.tsx` — 소문 확인 (날짜 선택)
- `frontend/app/biotech/status/page.tsx` — 상태판
- `frontend/app/biotech/glossary/page.tsx` — 용어집
- `frontend/app/biotech/final/page.tsx` — 최종 리포트

### 백엔드 API (읽기 전용 · biotech.py 안)

```python
GET /api/v1/biotech/radar          # 최신 radar-v1.X md → HTML/JSON
GET /api/v1/biotech/rumor?date=... # rumor-daily/YYYY-MM-DD.md → HTML/JSON
GET /api/v1/biotech/status         # STATUS.md → HTML/JSON
GET /api/v1/biotech/glossary       # GLOSSARY.md → HTML/JSON
GET /api/v1/biotech/final          # PHASE-A-FINAL.md → HTML/JSON
```

- 파일 참조: `docs/plans/biotech/**` (읽기 전용 · git pull 산물)
- 렌더링: `python-markdown` (이미 requirements.txt · WP55)
- 인증: 기존 미들웨어 재사용 (`Depends(get_current_user)` · admin/subscriber 판정)

### 인증

- **기존 로그인 뒤 배치** (기존 미들웨어 재사용)
- basic auth 별도 계정 신설 **불필요** · 기존 admin 세션 활용
- **사용자 결정**: 접근 권한 (admin 만 / subscriber 포함 / anon 허용)

### 롤백 (접점 3줄 제거)

```bash
# 롤백 순서 (각 파일 1줄 제거)
git revert <commit>
# 또는 수동:
# 1. AppNav.tsx 에서 "Biotech" 항목 1줄 삭제
# 2. main.py 에서 include_router(biotech.router) 1줄 삭제
# 3. frontend/app/biotech/ · backend/api/routes/biotech.py 폴더 유지 or 삭제
```

**원상복구 시간**: 재시작 1회 (backend systemctl restart tradebot-api · frontend PM2 reload)

### 로컬 확인 방법 (통합 후)

```bash
# 1. 백엔드 (별도 터미널)
backend/venv/bin/uvicorn backend.api.main:app --reload --port 8000

# 2. 프론트
cd frontend && npm run dev
# → http://localhost:4000/ (기존 사이트) · http://localhost:4000/biotech (신규)
```

### 서버 배포 (통합 후 · 별도 서비스 불필요)

- **라우터는 동일 앱** → 새 systemd 서비스 불필요
- 서버 반영: **git pull + systemctl restart tradebot-api + PM2 reload tradebot-frontend** (1회)
- CI/CD (deploy.yml) 자동 진행 · 별도 설정 없음

### 예상 작업량 · 위험 · 사용자 결정 항목

**예상 작업량 (통합 시 · 이번 지시 아님)**:
- 백엔드 `biotech.py` 라우터 신설: 100~200줄 (md 5개 반환 + 인증)
- 프론트 페이지 6개: 400~600줄 (통합 대시보드 + 5 화면)
- AppNav 1줄 + main.py 1줄: 2줄
- 배포 커밋 1회
- **예상 시간**: 4~8시간 (설계 · 구현 · 로컬 검증 · 배포)

**위험**:
- 저 · 격리 원칙 준수 · 롤백 3줄
- 중 · CORS/인증 미묘한 케이스 (기존 admin 세션 재사용 확인 필요)
- 저 · md 파싱 · 이미 python-markdown 사용 (WP55)

**사용자 결정 항목 (2건 · 승인 필요)**:
1. **통합 승인**: 로컬 뷰어 (4010) 유지 vs 기존 사이트 통합 진행 · 통합 시 예상 4~8h 세션
2. **인증 방식 · 메뉴 위치**:
   - (a) admin 만 접근 (기존 admin 세션 재사용) / (b) subscriber 포함 / (c) anon 허용
   - 메뉴 위치: L1 (Journal 옆) / L2 (Powderkeg 옆) / 별도 L1 그룹

### 진행 순서 (사용자 승인 후)

1. 승인 확인 (본 문서 §2 사용자 결정 2건)
2. 로컬 확인 뷰어 (localhost:4010) 유지 (통합 완료까지 병행)
3. 백엔드 `biotech.py` 라우터 + md 반환 구현 · 로컬 curl 검증
4. 프론트 페이지 6개 + AppNav 1줄 · 로컬 브라우저 검증
5. `main.py` include_router 1줄 추가
6. 로컬 전체 동선 검증 (기존 메뉴 무영향 확인)
7. git commit + push → optimus8 자동 배포
8. 서버 검증 (5 라우트 200 · 기존 페이지 무회귀)
9. 로컬 뷰어 (4010) 종료 · 통합 완료

---

## 결론

- **기존 사이트 4000 복구 완료** (`npm run dev` · GET / 200 · 1초 준비)
- **바이오 뷰어 4010 으로 이동** (기본 포트 변경 · 4000 침해 방지)
- **본 문서는 조사·설계 · 코드 수정 0건**
- **통합 진행 여부는 사용자 결정** · 승인 시 위 순서 · 예상 4~8h
