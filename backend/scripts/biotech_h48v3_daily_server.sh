#!/bin/bash
# WP69-3b · biotech daily · 서버 실행 절차서 (optimus8.cafe24.com · KST 07:00)
#
# crontab -e (root):
#   0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
#
# 산출·로그 전부 런타임 폴더 (git 추적 밖 · 배포 reset --hard 영향 없음):
#   /root/toss-tradebot-mvp/var/biotech/{candidates,community_daily,rumor-daily,watchlist,logs}
#
# 각 단계 실패 시 exit≠0 + 텔레그램 알림 (backend.services.notifier 재사용).
# Form 4 단계는 SEC 403 시 skip 기록 (기존 정책 유지).

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

STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== $STARTED biotech daily start (server · KST $(date +%H:%M)) ==="

# ── 실패 시 텔레그램 통보 (notifier 재사용) ─────────────
_notify_failure() {
  local step="$1"
  local msg="$2"
  $VENV - <<PY 2>&1 || echo "notifier 실패: $msg"
import asyncio
from backend.services.notifier import TelegramNotifier
async def _send():
    n = TelegramNotifier()
    await n.send_critical(
        title="biotech daily 실패 · $step",
        body="""서버 파이프 단계 실패
step: $step
detail: $msg
서버: optimus8.cafe24.com
로그: /root/toss-tradebot-mvp/var/biotech/logs/daily.log""",
    )
asyncio.run(_send())
PY
}

# 1. 후보 우주 갱신
echo "[1/6] candidates"
$VENV -m backend.scripts.biotech_h48v3_candidates || { _notify_failure "candidates" "exit $?"; exit 11; }

# 2. 커뮤니티 확인
echo "[2/6] confirm"
$VENV -m backend.scripts.biotech_h48v3_confirm || { _notify_failure "confirm" "exit $?"; exit 12; }

# 3. 소문 확인 일일 리포트
echo "[3/6] rumor report"
$VENV -m backend.scripts.biotech_h48v3_report || { _notify_failure "report" "exit $?"; exit 13; }

# 4. 레이더 리스트 v1.3/v1.4
echo "[4/6] radar"
$VENV -m backend.scripts.biotech_h46v3_radar || { _notify_failure "radar" "exit $?"; exit 14; }

# 5. Form 4 증분 · 표 4 CSV (403 시 skip 정책 유지 · 기존 daily.sh 동일)
echo "[5/6] form4 (skip 허용)"
$VENV -m backend.scripts.biotech_h65_form4_daily || echo "  WP65 skip (SEC 403 등 · 다음 실행 재시도)"

# 6. STATUS.md 자동 생성
echo "[6/6] status_gen"
$VENV -m backend.scripts.biotech_h57b_status_gen || { _notify_failure "status_gen" "exit $?"; exit 16; }

# 90일 넘은 로그 정리 (스크립트 자체 logrotate · 서버 logrotate 미의존)
find "$BIOTECH_RUNTIME_DIR/logs" -name '*.log' -mtime +90 -delete 2>/dev/null || true
# 365일 넘은 산출 CSV 정리
find "$BIOTECH_RUNTIME_DIR" -maxdepth 3 -name '*.csv' -mtime +365 -delete 2>/dev/null || true

FINISHED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== $FINISHED biotech daily done ==="
