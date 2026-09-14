#!/bin/bash
# WP67-2 · 로컬 뷰어 관리 (start/status/stop) · biotech_h55_viewer FastAPI
# 기본 포트 4000 · BIOTECH_VIEWER_PORT 환경변수로 변경 가능
# 서버 (optimus8) 접근 없음 · 로컬 브라우저 전용

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
set -euo pipefail
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp

PORT="${BIOTECH_VIEWER_PORT:-4010}"
PIDFILE="backend/data/biotech/community_daily/viewer.pid"
LOGFILE="backend/data/biotech/community_daily/viewer.log"
VENV=backend/venv/bin/python

case "${1:-status}" in
  start)
    # 포트 점유 확인 (자동 이동 금지 · 사용자 지정 포트 유지)
    if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "🚨 포트 $PORT 이미 사용 중 · 점유 프로세스:"
      lsof -i :"$PORT" -sTCP:LISTEN
      echo ""
      echo "→ 자동 이동 금지 (사용자가 $PORT 지정)"
      echo "→ 해결: 점유 프로세스 종료 후 재시도 또는 BIOTECH_VIEWER_PORT=8080 등으로 변경"
      exit 1
    fi
    if [ -f "$PIDFILE" ]; then
      OLD_PID=$(cat "$PIDFILE")
      if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "이미 실행 중 · PID $OLD_PID (포트 $PORT)"
        exit 0
      fi
      rm -f "$PIDFILE"
    fi
    mkdir -p "$(dirname "$LOGFILE")"
    BIOTECH_VIEWER_PORT="$PORT" nohup $VENV -m backend.scripts.biotech_h55_viewer > "$LOGFILE" 2>&1 &
    NEW_PID=$!
    echo "$NEW_PID" > "$PIDFILE"
    sleep 2
    if kill -0 "$NEW_PID" 2>/dev/null; then
      echo "✅ 뷰어 기동 · PID $NEW_PID · 포트 $PORT"
      echo "브라우저: http://localhost:$PORT/"
    else
      echo "🚨 기동 실패 · 로그: tail -20 $LOGFILE"
      tail -20 "$LOGFILE"
      exit 1
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "✅ 실행 중 · PID $PID · 포트 $PORT · http://localhost:$PORT/"
      else
        echo "⚠️ PID 파일 있으나 프로세스 없음 · rm $PIDFILE"
      fi
    else
      echo "미실행"
    fi
    lsof -i :"$PORT" -sTCP:LISTEN 2>/dev/null || echo "  (포트 $PORT 미점유)"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "종료 신호 · PID $PID"
        sleep 1
      fi
      rm -f "$PIDFILE"
    fi
    # 잔여 프로세스 정리
    pkill -f "biotech_h55_viewer" 2>/dev/null || true
    echo "뷰어 종료 · 포트 $PORT 해제"
    ;;
  *)
    echo "Usage: $0 {start|status|stop}"
    echo "  포트: BIOTECH_VIEWER_PORT (기본 $PORT)"
    exit 1
    ;;
esac
