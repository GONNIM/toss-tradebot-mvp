# DEPLOY-SERVER · biotech 파이프 서버 이식 계획

**대상 서버**: optimus8.cafe24.com (`root@` · GitHub Actions secret 재사용)
**작성**: 2026-09-20 · WP69-3a v2 (실측 반영 + Fable 결함 3건 수정)
**상태**: 실행 승인 대기 (조회 완료 · 코드 수정·배포 필요)

---

## §1 배포 자동화 현황 (기존)

- `.github/workflows/deploy.yml` · main push → validate → deploy → verify (2m 20s)
- SSH → **`git reset --hard`** → build → systemctl/pm2 재시작 → /health 3회 curl
- **소스·프론트 배포만 자동** · 데이터 파이프는 아직 로컬 crontab (사용자 mac)

## §2 로컬 파이프 현황 (§3 이식 대상)

- 실행자: 사용자 개인 mac
- 스케줄: `crontab -e` → `0 22 * * *` (UTC 22 = KST 07 · 사용자 mac 은 UTC 기준으로 등록)
- 절차서: `backend/scripts/biotech_h48v3_daily.sh` · 6 단계 (candidates · confirm · report · radar · Form4 · STATUS)
- 산출 폴더: `backend/data/biotech/...`
- 문제: 사용자 mac 꺼짐 시 미실행 · WP72-3 로 시작한 `docs/plans/biotech/data/` 는 수동 커밋

---

## §3 서버 파이프 이식 계획 (WP69-3 · 실행 승인 대기)

### §3.0 서버 조회 결과 (2026-09-20 · 읽기 전용 · 변경 0)

| 항목 | 실측값 |
|---|---|
| OS · 커널 | Ubuntu · Linux 5.15.0-52 x86_64 |
| 시스템 python | 3.10.12 (`/usr/bin/python3`) |
| 프로젝트 경로 | **`/root/toss-tradebot-mvp`** (계획서 v1 의 `/opt/...` 는 오추정) |
| venv python | **3.12.13** (`backend/.venv/bin/python → python3.12`) |
| **시간대** | **Asia/Seoul (KST +0900) · NTP 동기 · System clock synchronized: yes** |
| 디스크 / | 36GB · **21GB 여유** (39% 사용) |
| crontab -l | **비어 있음** (root user · `no crontab for root`) |
| systemd timers | 시스템 기본만 (ua-timer · certbot · dpkg-db-backup · logrotate · fstrim · apt-daily) · **커스텀 없음** |

**외부 HEAD** (biotech_sec_common.SEC_UA / SEC_FROM / SEC_ACCEPT_ENCODING · 서버 IP):

| 소스 | 결과 | 비고 |
|---|---|---|
| SEC EDGAR (data.sec.gov) | ✅ **HTTP 200** | 서버 IP 정상 접근 · UA 준수 |
| CT.gov v2 | ⚠️ **HTTP 403 (HEAD)** | **즉시 중단** · HEAD 미지원 가능성 (원래 GET 만 · Phase A 실 파이프는 GET 이라 별개) — 실행 승인 전 GET 로 재확인 필요 |
| StockTwits · apewisdom · Reddit RSS | ⏸ 미시험 (403 감지로 중단) | CT.gov GET 재확인 후 순차 시도 |

### §3.1 실행 환경

| 항목 | 계획 (실측 반영) |
|---|---|
| Python | **3.12.13** (기존 venv 재사용) |
| venv | **`/root/toss-tradebot-mvp/backend/.venv/`** |
| pip | `.venv/bin/pip install -e "backend[dev]"` · 이미 자동 배포에서 설치 완료 (import backend.api.main 성공) |
| **시간대** | **KST** (서버 로컬) — cron 표기는 **KST 기준** (§3.2) |

### §3.2 cron 라인 (KST · 서버 로컬)

**서버 crontab -e**:
```cron
0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
```
> 「매일 KST 07:00 실행 · 서버 시간대 KST 확정 (§3.0) 이라 UTC 22 표기 불필요」

**신규 스크립트** `biotech_h48v3_daily_server.sh`:
- shebang: `#!/bin/bash`
- 상단 `set -euo pipefail`
- `cd /root/toss-tradebot-mvp`
- **VENV=`backend/.venv/bin/python`** (스크립트 내부에서 venv python 지정 · cron 라인은 `/bin/bash` 만)
- `export BIOTECH_RUNTIME_DIR=/root/toss-tradebot-mvp/var/biotech` (§3.3)
- 나머지는 기존 `biotech_h48v3_daily.sh` 6 단계 그대로 (candidates · confirm · report · radar · Form4 · STATUS)

### §3.3 런타임 폴더 (git 추적 밖 · 배포 reset --hard 영향 없음)

**결함 1 해결**: 계획서 v1 은 산출물을 `docs/plans/biotech/data/` (git 추적) 에 쓰려고 함 → 다음 자동 배포의 `git reset --hard` 로 소실 위험.

**해결**: 산출물 전부 **`/root/toss-tradebot-mvp/var/biotech/`** (git 추적 밖 · `.gitignore` 로 확인).

```
/root/toss-tradebot-mvp/var/biotech/
├── candidates/    ← biotech_candidates_v3_YYYYMMDD.csv
├── community_daily/ ← community_confirm_YYYYMMDD.csv
├── rumor-daily/   ← YYYY-MM-DD.md
├── watchlist/     ← radar-v1.X-YYYYMMDD.md
├── STATUS.md · GLOSSARY.md · PHASE-A-FINAL.md
├── logs/          ← daily.log (90일 logrotate)
└── ...
```

**API 조회 순서 (`backend/api/routes/biotech.py`)**:
```python
BIOTECH_RUNTIME_DIR = Path(os.environ.get("BIOTECH_RUNTIME_DIR", ""))  # 서버 · systemd env
DATA_DIR_DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech" / "data"  # 기존 · 저장소 스냅샷
DATA_DIR = PROJECT_ROOT / "backend" / "data"                          # 기존 · 로컬 파이프

# 조회 순서: 런타임 > docs > backend/data (환경변수 미설정 시 기존 동작 그대로)
def _search_dirs(sub: str) -> list[Path]:
    dirs = []
    if BIOTECH_RUNTIME_DIR:
        dirs.append(BIOTECH_RUNTIME_DIR / sub)
    dirs.append(DATA_DIR_DOCS)
    dirs.append(DATA_DIR / "biotech" / sub)
    return [d for d in dirs if d.exists()]
```

### §3.4 외부 접근 · UA 규칙 (코드 상수 참조 · 결함 2 해결)

**결함 2 해결**: 계획서 v1 은 curl `-A "..."` 하드코딩 예시 → **삭제**. 반드시 `backend.scripts.biotech_sec_common` 상수 참조:

```python
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING
HEADERS = {"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}
```

**외부 소스** (모두 무인증 · GET · 최소 간격 0.5s):

| 소스 | Base URL | 상태 (§3.0 조회) |
|---|---|---|
| SEC EDGAR | `https://data.sec.gov/*` · `https://www.sec.gov/cgi-bin/browse-edgar` | ✅ HEAD 200 확증 |
| CT.gov v2 | `https://clinicaltrials.gov/api/v2/studies` | ⚠️ HEAD 403 · GET 재확인 필요 |
| StockTwits | `https://api.stocktwits.com/api/2/streams/symbol/*.json` | ⏸ 미시험 · rate 429 주의 |
| apewisdom | `https://apewisdom.io/api/v1.0/filter/all-stocks` | ⏸ 미시험 |
| Reddit RSS | `https://www.reddit.com/r/*/new/.rss` | ⏸ 미시험 |

**확장 파이프 (Phase C 이후)** API 키 사용 (TIINGO · SIMFIN · DART · EODHD) → §3 기본 포함 안 함.

### §3.5 파이프 입력 파일

- 런타임 우선 (`BIOTECH_RUNTIME_DIR`) → 저장소 스냅샷 (`docs/plans/biotech/data/`) → 기존 로컬 (`backend/data/biotech/`)
- 서버 daily 실행은 런타임 폴더에만 씀 · 저장소 커밋·push 안 함 (결함 3 해결)

### §3.6 로그 · 실패 알림

- **로그**: `/root/toss-tradebot-mvp/var/biotech/logs/daily.log` (append)
- **보존**: **로그 90일** · **산출 CSV/MD 365일** (logrotate 또는 스크립트 마지막 stage 에서 `find ... -mtime +N -delete`)
- **실행 확인**: `tail -50 var/biotech/logs/daily.log` · `grep "daily done" var/biotech/logs/daily.log`
- **실패 알림**: 스크립트 마지막 exit-trap 에서 `send_telegram()` (기존 `backend/services/notifier.py`)

### §3.7 실행 순서 (사용자 지시 (a)~(e) 정리 · 결함 3 해결)

**(a) 코드 변경 PR·배포**
1. `backend/api/routes/biotech.py` · `BIOTECH_RUNTIME_DIR` 환경변수 우선 조회 (§3.3 코드)
2. `backend/scripts/biotech_h48v3_daily_server.sh` 신규 (§3.2)
3. 시스템d unit 에 `Environment="BIOTECH_RUNTIME_DIR=/root/toss-tradebot-mvp/var/biotech"` 추가 (or /etc/systemd/system/*.service.d/)
4. pytest 갱신 (RUNTIME_DIR 조회 순서 계약)
5. PR → main 병합 → 자동 배포 (validate · deploy · verify) · **/health 200 + 기존 API 무회귀 확인**

**(b) 서버 dry-run 1회 (수동)**
```
ssh optimus8
cd /root/toss-tradebot-mvp
mkdir -p var/biotech/{candidates,community_daily,rumor-daily,watchlist,logs}
export BIOTECH_RUNTIME_DIR=/root/toss-tradebot-mvp/var/biotech
bash backend/scripts/biotech_h48v3_daily_server.sh
```
→ 종료 코드 0 + 신규 CSV/MD 생성 + `daily.log` 정상 · `/api/v1/biotech/kpi.json` 값 갱신 확인

**(c) crontab 등록**
```
crontab -e   # 서버 root
# 아래 1줄 추가:
0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
```

**(d) 24h 관측**
- 첫 실행 (다음 KST 07:00) `tail -f var/biotech/logs/daily.log`
- KPI 값 변경 감지 · 텔레그램 알림 없음 (성공) 확인

**(e) 3일 연속 성공 후 로컬 crontab 제거**
- 사용자 mac `crontab -e` · `biotech_h48v3_daily.sh` 라인 삭제
- 서버 파이프 단일화 · 이중 실행 회피

### §3.8 롤백

- **조건**: 서버 파이프 실패 · KPI 오류 · 백엔드 예외 로그 지속
- **절차**:
  1. `crontab -e` · §3.2 라인 앞에 `#` 주석 처리 · 즉시 중단
  2. **런타임 폴더 `/root/toss-tradebot-mvp/var/biotech/` 는 보존** (로그·이력 유지)
  3. 로컬 crontab 재활성 (§3.7 (e) 역순)
  4. `/api/v1/biotech/kpi.json` 이전 값 (docs 스냅샷) 로 복귀 확인
- **부작용 없음**: 백엔드는 CSV 부재 시 rows=[] fallback (WP71-2 hotfix) · BIOTECH_RUNTIME_DIR 미설정 시 기존 동작 유지 (docs → backend/data)

### §3.9 리스크 · 미정

| 항목 | 리스크 | 완화 |
|---|---|---|
| CT.gov HEAD 403 | 실 GET 에서도 차단이면 상태 변경 채널 (H5 AACT) 만 사용 · 나머지 우회 | (b) dry-run 첫 실행이 실 확인 |
| Form 4 SEC 403 | 하루 실패 허용 (기존 daily.sh `\|\| skip`) · 3일 연속 실패 시 텔레그램 | 유지 |
| logrotate 미설정 | 로그 무한 증가 · 디스크 압박 | 스크립트 자체에서 `find var/biotech/logs -mtime +90 -delete` 마지막 실행 |
| 배포 시 `.venv` 삭제 위험 | git reset --hard 는 `.venv/` 를 건드리지 않음 (gitignored) | ✅ 안전 |

---

## 승인 요청 (실행 승인 · 문구 1줄)

> **위 §3 (v2) · 실행 순서 (a) 코드 PR·배포 (`BIOTECH_RUNTIME_DIR` 우선 조회 + 서버 daily.sh + systemd env) 부터 진행하겠습니다. (b) dry-run 은 별도 승인. 실행 승인?**
