# DEPLOY-SERVER · biotech 파이프 서버 이식 계획

**대상 서버**: optimus8.cafe24.com
**작성**: 2026-09-20 · WP69-3a
**상태**: 조회 승인 대기 (SSH 실측 아직 없음 · 로컬 파이프 이해 기반)

---

## §1 배포 자동화 현황 (기존)

- `.github/workflows/deploy.yml` · main 브랜치 push → validate → deploy → verify (2m 20s)
- SSH → git reset --hard → build → systemctl/pm2 재시작 → /health 3회 curl
- **소스 코드·프론트 배포만 자동** · 데이터 생성 파이프는 아직 로컬 crontab (macOS 단말)

## §2 로컬 파이프 현황 (§3 이식 대상)

- 실행자: 사용자 개인 mac
- 스케줄: crontab `0 22 * * * biotech_h48v3_daily.sh` (UTC 22:00 = KST 07:00)
- 절차서: `backend/scripts/biotech_h48v3_daily.sh` · 6 단계 (candidates · confirm · report · radar · Form4 · STATUS)
- 산출 폴더: `backend/data/biotech/candidates/` · `.../community_daily/` · `.../rumor-daily/` · `.../watchlist/`
- **문제**: 사용자 단말 꺼짐 시 실행 안 됨 · docs/plans/biotech/data/ 반영은 수동 커밋 (WP72-3 로 시작)

---

## §3 서버 파이프 이식 계획 (WP69-3 · 승인 대기)

### §3.1 실행 환경

| 항목 | 계획 | 검증 필요 |
|---|---|---|
| OS | Ubuntu (cafe24 VPS · 자동 배포에서 systemctl 사용 관측) | `uname -a` |
| Python | 3.12 (로컬 `backend/venv` 와 동일) | `python3 --version` |
| venv 위치 | `/opt/toss-tradebot-mvp/backend/.venv/` (자동 배포 스텝 2.5 pre-smoke 이 사용) | `ls .venv/bin/python` |
| pip 방식 | `.venv/bin/pip install -e "backend[dev]"` 또는 pyproject.toml requirements | `.venv/bin/pip list` |
| 시간대 | 서버 UTC · KST 07:00 = **UTC 22:00 전날** | `timedatectl` |

### §3.2 스케줄 (cron)

**cron 라인** (사용자 계정 crontab · `crontab -e`):
```cron
0 22 * * * cd /opt/toss-tradebot-mvp && backend/.venv/bin/bash backend/scripts/biotech_h48v3_daily_server.sh >> /opt/toss-tradebot-mvp/logs/biotech_daily.log 2>&1
```

**신규 스크립트** `biotech_h48v3_daily_server.sh` (기존 로컬 sh 서버 이식본):
- 절대 경로를 `/opt/toss-tradebot-mvp` 로 교체
- VENV = `backend/.venv/bin/python`
- 산출 대상 폴더 = **`docs/plans/biotech/data/`** (git 추적 · WP72-3 정합) + 기존 `backend/data/biotech/` 병행

**대체안** (systemd timer): cron 대신 `biotech-daily.timer` + `biotech-daily.service` · 실패 통보 이메일 자동 연동 가능. **기본안 = crontab** (기존 방식 이어감).

### §3.3 디스크

| 항목 | 예상 |
|---|---|
| 산출 CSV/MD | 하루 **<200KB** (candidates ~22KB + confirm ~32KB + radar ~10KB + Form4 <1KB + rumor md ~5KB + STATUS md ~10KB) |
| 로그 | 하루 <100KB · 90일 보관 = <10MB |
| 이력 (365일) | <100MB · git 추적 CSV 는 최신 30일만 유지 (오래된 것은 .gitignored 아카이브) |

### §3.4 외부 접근 (모두 무인증)

**HEAD 요청으로 접근 가능 여부 사전 확인**:

| 소스 | Base URL | API 키 | HEAD 검증 |
|---|---|---|---|
| SEC EDGAR | `https://data.sec.gov/` · `https://www.sec.gov/cgi-bin/browse-edgar` | ❌ 불필요 (User-Agent 만 필수) | `curl -I -A "toss-tradebot admin@example" https://data.sec.gov/` |
| CT.gov (v2) | `https://clinicaltrials.gov/api/v2/studies` | ❌ 불필요 | `curl -I https://clinicaltrials.gov/api/v2/studies?pageSize=1` |
| StockTwits | `https://api.stocktwits.com/api/2/streams/symbol/*.json` | ❌ 불필요 (rate 429 주의) | `curl -I https://api.stocktwits.com/api/2/streams/symbol/AAPL.json` |
| apewisdom | `https://apewisdom.io/api/v1.0/filter/all-stocks` | ❌ 불필요 | `curl -I https://apewisdom.io/api/v1.0/filter/all-stocks` |
| Reddit RSS | `https://www.reddit.com/r/*/new/.rss` | ❌ 불필요 | `curl -I -A "toss-tradebot admin@example" https://www.reddit.com/r/biotech_stocks/new/.rss` |

**확장 파이프 (Phase C·H1a/H6/H41)** API 키 사용: TIINGO · SIMFIN · DART · EODHD → **§3 기본 파이프에는 미포함** (필요 시 별도 §3.10 추가).

### §3.5 파이프 입력 파일 (있어야 함)

- `docs/plans/biotech/data/` (git 추적) · 최신 CSV 4개 (radar v1.3 · candidates v3 · community_confirm · h65_form4)
- `backend/data/biotech/candidates/` (git 미추적 · 서버가 새로 생성)
- 서버가 daily 실행 시 두 폴더 모두에 산출 (docs/ 는 커밋용 스냅샷 · backend/ 는 정식 아카이브)

### §3.6 로그 · 실패 알림

- **로그**: `/opt/toss-tradebot-mvp/logs/biotech_daily.log` (append · 90일 logrotate)
- **cron 실행 확인**: `tail -20 logs/biotech_daily.log` · `grep "daily done" logs/biotech_daily.log`
- **실패 알림**: 텔레그램 (기존 `backend/services/notifier.py` 재사용) · daily 스크립트 마지막에 `send_telegram()` · 실패 시 exit ≠ 0 → cron 이 stderr 캡처 → 별도 알림 훅

### §3.7 첫 실행 절차 (승인 후)

1. SSH: `ssh optimus8` (기존 자동 배포 SSH key 활용)
2. `cd /opt/toss-tradebot-mvp && git pull` (배포 정합 확인)
3. `backend/.venv/bin/pip install -e "backend[dev]"` (신규 스크립트 의존성)
4. `mkdir -p logs`
5. **dry-run** (crontab 등록 전): `backend/scripts/biotech_h48v3_daily_server.sh` 수동 1회 실행 → 산출 CSV/MD 확인 + `git status` 로 docs/plans/biotech/data/ 변경 확인
6. dry-run 성공 시 `crontab -e` → 위 §3.2 라인 등록
7. **24시간 관측**: 첫 UTC 22:00 실행 결과 `tail -f logs/biotech_daily.log`
8. rows 수 확인: `curl -H "X-API-Token: ..." https://optimus8.cafe24.com/api/v1/biotech/kpi.json` → 값 갱신 감지

### §3.8 로컬 crontab 제거 시점

- 서버 파이프 **3일 연속 성공** 확인 후 (로그 3건 + KPI 갱신 3일)
- 사용자 mac 에서 `crontab -e` · `biotech_h48v3_daily.sh` 라인 삭제
- 로컬 산출 폴더 `backend/data/biotech/` 는 유지 (백업)

### §3.9 롤백

- **롤백 조건**: 서버 파이프 실패 · 데이터 오류 · KPI 잘못된 값 · 백엔드 예외 로그 지속
- **롤백 절차**:
  1. `crontab -e` → §3.2 라인 주석 처리 (`#` prefix) · 서버 파이프 즉시 중단
  2. `git revert` 서버 파이프 커밋 (docs/plans/biotech/data/ 최신본 → 이전 상태)
  3. 로컬 crontab 다시 활성 (§3.8 절차 역순)
  4. `/api/v1/biotech/kpi.json` 이 이전 값 (2026-09-14 자) 로 복귀 확인
- **부작용 없음**: 백엔드 라우터는 CSV 부재 시 rows=[] fallback (WP71-2 hotfix) · 프론트 렌더 안정

### §3.10 리스크 · 미정 사항

| 항목 | 리스크 | 완화 |
|---|---|---|
| Playwright 서버 미탑재 | 데이터 파이프는 Playwright 불필요 (SEC/CT.gov/StockTwits/RSS 만) | ❌ 문제 없음 |
| Form4 SEC 403 | 하루 실패 허용 (daily.sh 안 `|| echo skip`) · 다음 날 재시도 | ⚠️ 3일 연속 실패 시 알림 |
| Git 자동 커밋·push | 서버가 CSV 를 커밋·push 하려면 write 권한 SSH key 필요 | ⚠️ 대안: 커밋 대신 nginx 로 CSV 직접 서빙 (docs/plans/biotech/data/ 를 정적 노출) · 이 경우 프론트는 서버 로컬 CSV 만 읽으면 됨 |
| 시간대 오해 | UTC 22:00 은 KST 07:00 (전날 22일 UTC → 23일 07 KST 아님 · 22일 UTC 22:00 = 23일 07:00 KST) | 확인: `date -u` + `TZ=Asia/Seoul date` |

---

## 승인 요청

> **위 계획 (§3.1~§3.10) 대로 서버 SSH 접속 후 §3.1 조회 항목 (uname, python 버전, venv 존재, timedatectl, 외부 접근 HEAD 5개) 만 실행해서 실측·이 문서 §3 을 확정하겠습니다. 변경 0 (readonly). 조회 승인?**
