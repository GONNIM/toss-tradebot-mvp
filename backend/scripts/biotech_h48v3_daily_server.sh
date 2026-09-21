#!/bin/bash
# WP69-3h · biotech daily · 서버 실행 절차서 (optimus8.cafe24.com · KST 07:00)
#
# crontab -e (root):
#   0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
#   0 6 * * 1 /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh --aact-weekly-only >> /root/toss-tradebot-mvp/var/biotech/logs/aact-weekly.log 2>&1
#
# 산출·로그 전부 런타임 폴더 (git 추적 밖 · 배포 reset --hard 영향 없음):
#   /root/toss-tradebot-mvp/var/biotech/{candidates,community_daily,rumor-daily,watchlist,logs}
#
# WP69-3h 변경 (2026-09-21):
# - 7단계 (h50 time_state 편입 · candidates → time_state → confirm → report → radar → form4 → status)
# - shell source (`. backend/.env`) 제거 · notifier 는 python -m backend.scripts.biotech_notify 로 호출
#   (config 로더가 python-dotenv 로 파싱 · 홑따옴표·특수문자 안전)
# - Form 4 단계는 SEC 403 시 skip 기록 (기존 정책 유지)

set -uo pipefail

ROOT=/root/toss-tradebot-mvp
VENV=$ROOT/backend/.venv/bin/python
export BIOTECH_RUNTIME_DIR=$ROOT/var/biotech
export PYTHONPATH=$ROOT

# 런타임 폴더 생성 (idempotent)
mkdir -p \
  "$BIOTECH_RUNTIME_DIR/candidates" \
  "$BIOTECH_RUNTIME_DIR/community_daily" \
  "$BIOTECH_RUNTIME_DIR/rumor-daily" \
  "$BIOTECH_RUNTIME_DIR/watchlist" \
  "$BIOTECH_RUNTIME_DIR/logs"

cd "$ROOT"

# ── 실패 시 텔레그램 통보 (biotech_notify · config 로더로 .env 로드 · 셸 source 안 함) ─────
_notify_failure() {
  local step="$1"
  local msg="$2"
  $VENV -m backend.scripts.biotech_notify critical "biotech daily 실패 · $step" "step: $step
detail: $msg
서버: optimus8.cafe24.com
로그: $BIOTECH_RUNTIME_DIR/logs/daily.log" || echo "notifier 호출 자체 실패 · step=$step"
}

# 옵션: --aact-weekly-only (월요일 06:00 cron 용 · 주간 스냅샷만 실행 후 종료)
if [ "${1:-}" = "--aact-weekly-only" ]; then
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) AACT weekly only ==="
    $VENV -m backend.scripts.biotech_h69_aact_weekly || { _notify_failure "aact_weekly" "exit $?"; exit 20; }
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) AACT weekly done ==="
    exit 0
fi

STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== $STARTED biotech daily start (server · KST $(date +%H:%M)) ==="

# 1. 후보 우주 갱신 (biotech_candidates_YYYYMMDD.csv · v1)
echo "[1/7] candidates"
$VENV -m backend.scripts.biotech_h48v3_candidates || { _notify_failure "candidates" "exit $?"; exit 11; }

# 2. 시간 상태 판정 (h50 · AACT ctgov_snapshot.json 참조 · A/B/C · candidates_v3 산출)
echo "[2/7] time_state (h50 · AACT JSON)"
$VENV -m backend.scripts.biotech_h50_ct_upcoming || { _notify_failure "time_state" "exit $?"; exit 12; }

# 3. 커뮤니티 확인 (community_confirm_YYYYMMDD.csv · apewisdom+Reddit · WP69-3d γ)
echo "[3/7] confirm"
$VENV -m backend.scripts.biotech_h48v3_confirm || { _notify_failure "confirm" "exit $?"; exit 13; }

# 4. 소문 확인 일일 리포트
echo "[4/7] rumor report"
$VENV -m backend.scripts.biotech_h48v3_report || { _notify_failure "report" "exit $?"; exit 14; }

# 5. 레이더 리스트 v1.4
echo "[5/7] radar"
$VENV -m backend.scripts.biotech_h46v3_radar || { _notify_failure "radar" "exit $?"; exit 15; }

# 6. Form 4 증분 (403 시 skip 정책 유지)
echo "[6/7] form4 (skip 허용)"
$VENV -m backend.scripts.biotech_h65_form4_daily || echo "  WP65 skip (SEC 403 등 · 다음 실행 재시도)"

# 7. STATUS.md 자동 생성
echo "[7/7] status_gen"
$VENV -m backend.scripts.biotech_h57b_status_gen || { _notify_failure "status_gen" "exit $?"; exit 17; }

# 90일 넘은 로그 정리
find "$BIOTECH_RUNTIME_DIR/logs" -name '*.log' -mtime +90 -delete 2>/dev/null || true
# 365일 넘은 산출 CSV 정리
find "$BIOTECH_RUNTIME_DIR" -maxdepth 3 -name '*.csv' -mtime +365 -delete 2>/dev/null || true

FINISHED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== $FINISHED biotech daily done ==="
