# 배포 절차서 · 1페이지 (2026-09-14 · 세션 21 3회차 · Phase A 종결 승인)

> 📖 [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 상태 · 가설 뜻

## 배포 대상 (biotech 이름공간 · 3탭 로컬 완결 · md 리포트 형태)

| # | 탭 이름 (기능 뜻) | 파일 경로 (스크린샷 대체) | 갱신 |
|---|---|---|---|
| 1 | **레이더 순위표** (탐색 대상 우선 순위표) | `docs/plans/biotech/watchlist/radar-v1.3-YYYYMMDD.md` | 매일 (cron) |
| 2 | **소문 확인** (커뮤니티 급증 여부 · 후보 중심) | `docs/plans/biotech/rumor-daily/YYYY-MM-DD.md` | 매일 (cron) |
| 3 | **가능성 지도** (밝은 자리 · 죽은 자리 · 다음 자리) | `docs/plans/biotech/STATUS.md · PHASE-A-FINAL.md` | 수동 갱신 |

**열람 페이지 (WP55)**: 최소 md 뷰어 FastAPI 로 3탭 + 용어집 + Phase A 최종 라우트 신설 (`backend/scripts/biotech_h55_viewer.py`).

**로컬 실행 방법 (1줄)**:
```
backend/venv/bin/python -m backend.scripts.biotech_h55_viewer
```
→ 브라우저에서 `http://127.0.0.1:8765` · 5개 라우트 (`/radar` · `/rumor?date=YYYY-MM-DD` · `/map` · `/glossary` · `/phase-a-final`) · 상단 nav · 하단 고정 문구 (알파 미확정 · 소액 전향용 · 자동매매 없음).

---

## 운영 구조 (2026-09-14 확정 · 배포 조건 2)

### (a) 매일 파이프 실행 위치: **로컬 cron → git push → 뷰어가 파일 읽기**

**선택 근거**: 별도 서버 미보유 · Phase B 는 로컬 FastAPI 뷰어 (`biotech_h55_viewer.py`) · GitHub 원격은 백업/이력 용도.

```
[로컬 macOS cron 22:00 UTC (KST 07:00)]
    ↓ 실행: backend/scripts/biotech_h48v3_daily.sh
    ├─ biotech_h48v3_candidates → biotech_candidates_v3_YYYYMMDD.csv
    ├─ biotech_h48v3_confirm    → community_confirm_YYYYMMDD.csv
    ├─ biotech_h48v3_report     → rumor-daily/YYYY-MM-DD.md
    └─ biotech_h46v3_radar      → watchlist/radar-v1.3-YYYYMMDD.md
    ↓ 사용자 수동 git commit + push (또는 별도 push-only cron)
[GitHub 백업]
    ↓
[로컬 뷰어 biotech_h55_viewer.py] → 브라우저 :8765 · 최신 md 파일 읽어 렌더
```

**대안 (서버 cron)** = 미채택. 배포 대상 서버 없음. 서버 도입 시 이 절 갱신.

### (b) 필요한 .env 키 목록과 위치

**저장 위치**: `backend/.env` (`.gitignore` 등재 · 평문 커밋 금지 · 글로벌 §1 가드레일 준수)
**템플릿**: `backend/.env.example` (값 비운 placeholder)
**암호화 백업**: `backend/.env.sops.yaml` (SOPS · 팀 공유용)

**biotech 파이프 실사용 키**:

| 키 | 용도 | daily.sh 필요 여부 | Phase |
|---|---|---|---|
| **(없음)** | 무인증 API (SEC · CT.gov · StockTwits · apewisdom · Reddit RSS) | ❌ | Phase A/B daily.sh 는 키 불필요 |
| `TIINGO_API_KEY` | 주가·기업 정보 (h6 membership · h41 가격 보충) | 확장 파이프 실행 시 | Phase C |
| `SIMFIN_API_KEY` | 재무·시총 (h1a mcap · b60 파산) | 확장 파이프 실행 시 | Phase C |
| `DART_API_KEY` | 한국 전자공시 (H5 재개 시) | H5 재개 시만 | Phase D |
| `EODHD_API_KEY` | 주가 (파산 종목 회수) | 파산 회수 재시도 시만 | Phase C 6 |

**daily.sh 파이프 = 무인증 API 만 사용** → 배포 즉시 cron 실행 가능 (키 미설정 상태에서도 3탭 파이프 정상 동작).

### (c) 서버 변경 절차 (사용자 승인 후 단일 배포 · 롤백)

- **원칙**: 사용자 명시 승인 없이 서버 변경 금지 (Issue #16 교훈 · 프로젝트 CLAUDE.md §CRITICAL)
- **단일 배포**: 멀티 Phase 작업은 모든 Phase 로컬 완료 후 단일 배포 (Phase별 부분 배포 금지)
- **롤백**: `git revert HEAD` → 재검토 후 재푸시 (destructive 명령 (`git reset --hard`) 사용 금지)

---

## 배포 사전 확인 (사용자 · 승인 전)

- [x] pytest 전체 통과: **154 passed · 2 skipped · 0 failed** (2026-09-14 확인)
- [x] STATUS.md 상단 5줄 쉬운 말 (배포 조건 1)
- [x] DEPLOY.md 운영 구조 확정 (배포 조건 2 · a/b/c)
- [x] 오늘 보고서 존재: `rumor-daily/2026-09-14.md` · `watchlist/radar-v1.3-20260914.md`
- [x] Fable 최종 검수 통과 (완주 풀 재검 · Phase A 종결 승인)
- [ ] cron 등록: `crontab -l | grep biotech_h48v3_daily` (사용자 액션)

## 배포 명령 (사용자 승인 후 단일 배포)

```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp

# 1. pytest 확인
backend/venv/bin/python -m pytest backend/tests/ -q

# 2. git 스테이지 (biotech 이름공간만 · 자격증명 파일 제외)
git status
git add docs/plans/biotech/ \
        backend/scripts/biotech_*.py backend/scripts/biotech_*.sh backend/scripts/_biotech_bootstrap.py \
        backend/scripts/SCRIPTS.md \
        backend/data/biotech/ backend/data/MANIFEST.csv \
        backend/data/h_radar_params.json backend/data/h3_params.json \
        backend/data/h5_params.json backend/data/h6_params.json \
        backend/tests/test_biotech_*.py backend/requirements.txt

# 3. 커밋
git commit -m "$(cat <<'EOF'
feat(biotech): Phase A 종결 · WP39 완주 · 3탭 로컬 뷰어 · 배포 승인

- WP39 완주 340/340 · 7351 events · H1b +1.62% (CI [+0.73%, +2.61%])
- H8 검정 3 (뉴스에 팔기) 지지 유지 (post -0.74% · CI 상한 < 0)
- WP54 신호 유무 검정 사전 등록 (채널 3/5 · CI 하한 < 0 방향만)
- WP55 최소 FastAPI 뷰어 (5 라우트 · md 렌더)
- WP52 용어집 · 인라인 뜻 · WP46-4/5 레이더 v1.3 · WP53 검정 1 재계산
EOF
)"

# 4. 원격 push
git push origin main
```

## 롤백 방법

```bash
git log --oneline | head -5
git revert HEAD
git push origin main
```

**destructive 명령 (`git reset --hard`) 사용 금지**. 항상 revert 로 새 커밋 생성.

## cron 등록 (사용자 액션 · 필수)

```bash
crontab -e
# 다음 라인 추가 (KST 07:00 = UTC 22:00 전날)
0 22 * * * /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily.sh >> /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/data/biotech/community_daily/cron.log 2>&1
```

**확인**: `crontab -l | grep biotech`
**첫 실행 로그**: `tail -f backend/data/biotech/community_daily/cron.log`

## 실전 기록 임시 사용법 (Phase C UI 배포 전)

1. `backend/data/biotech/trades/trades_manual.csv` 열기
2. 매수 결정 시 새 행 추가 (CSV 헤더 참조)
3. `radar-v1.3-*.md` · `rumor-daily/*.md` 참조 링크 필수
4. status = PLANNED / OPEN / CLOSED
5. exit_target 3개 (3배 · 10배 · 뉴스 발표 날짜)

## Phase C 우선순위 (배포 후 첫 작업 = 1)

1. **소문 채널 완비** · 회사별 PubMed·bioRxiv 게재 증가율 · CT.gov 상태 변경 (AACT 스냅샷) → WP54-2 신호 유무 재검 (규칙 동일 · +1.0%p AND CI 하한 > 0)
2. **H6 소속 확장** (CT.gov 스폰서 전체 재매핑) → 재검
3. **반자동 티켓 탭** (실전 기록 화면화 · trades_manual.csv 편집기)
4. **H3b 전향 검정** (2026-09-14 이후 신규 13D · 소형~중형)
5. **파산 종목 가격 복구** (원장 v6 · B60 파산 8건 완결)

---

- 문서 링크: [PHASE-A-FINAL](PHASE-A-FINAL.md) · [STATUS](STATUS.md) · [GLOSSARY](GLOSSARY.md) · [INDEX](INDEX.md) · [PENDING](PENDING.md)
