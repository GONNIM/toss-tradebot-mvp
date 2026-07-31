#!/usr/bin/env bash
# Toss Tradebot MVP · SQLite 백업 스크립트 · Phase D 주 8 · 2026-07-31
#
# 목적: backend/data/tradebot.db 를 안전한 시점 스냅샷으로 dump + gzip + rotate.
#      로컬·서버 공통. cron 으로 매일 03:00 KST 실행 권장.
#
# 사용:
#     ./scripts/backup.sh                     # 백업 (LATEST 링크 갱신 · rotate)
#     BACKUP_KEEP=14 ./scripts/backup.sh      # 보관 일 수 override (기본 7)
#     BACKUP_DIR=/mnt/xxx ./scripts/backup.sh # 백업 위치 override (기본 .backup/)
#
# 산출:
#     .backup/YYYYMMDD_HHMMSS/tradebot.db.gz  # sqlite3 .backup + gzip
#     .backup/YYYYMMDD_HHMMSS/backup-info.txt # 커밋·크기·개수 메타
#     .backup/LATEST → YYYYMMDD_HHMMSS (심볼릭 링크)
#
# 참조: upbit-tradebot-mvp/scripts/backup.sh (Boilerplate 백업 · 문서용) —
#      본 스크립트는 DB 스냅샷 전용으로 재설계.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# ─── 설정 (env override) ──────────────────────────────────────────
DB_PATH="${DB_PATH:-backend/data/tradebot.db}"
BACKUP_DIR="${BACKUP_DIR:-.backup}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"   # 최근 N일 보관
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_DIR="${BACKUP_DIR}/${TIMESTAMP}"
LATEST_LINK="${BACKUP_DIR}/LATEST"

echo "======================================"
echo " Toss Tradebot MVP · DB 백업"
echo "======================================"
echo " DB: $DB_PATH"
echo " OUT: $SNAPSHOT_DIR"
echo " KEEP: $BACKUP_KEEP 일"
echo ""

# ─── 사전 검증 ────────────────────────────────────────────────────
if [ ! -f "$DB_PATH" ]; then
    echo "❌ DB 파일 없음: $DB_PATH" >&2
    exit 1
fi

command -v sqlite3 >/dev/null 2>&1 || {
    echo "❌ sqlite3 미설치 (brew install sqlite / apt-get install sqlite3)" >&2
    exit 2
}

mkdir -p "$SNAPSHOT_DIR"

# ─── 1) sqlite3 .backup (안전 스냅샷) ────────────────────────────
echo "[1/4] sqlite3 .backup 실행..."
TMP_DB="${SNAPSHOT_DIR}/tradebot.db"
sqlite3 "$DB_PATH" ".backup '$TMP_DB'"
DB_SIZE_MB=$(du -m "$TMP_DB" | awk '{print $1}')
echo "  ✓ ${DB_SIZE_MB} MB"

# ─── 2) gzip 압축 ────────────────────────────────────────────────
echo "[2/4] gzip 압축..."
gzip -9 "$TMP_DB"
GZ_SIZE_MB=$(du -m "${TMP_DB}.gz" | awk '{print $1}')
echo "  ✓ ${GZ_SIZE_MB} MB (압축률 $((100 - GZ_SIZE_MB * 100 / (DB_SIZE_MB > 0 ? DB_SIZE_MB : 1)))%)"

# ─── 3) 메타데이터 ────────────────────────────────────────────────
echo "[3/4] 메타 기록..."
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'nogit')"
GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'nobranch')"
cat > "${SNAPSHOT_DIR}/backup-info.txt" <<EOF
Toss Tradebot MVP · DB 백업 정보
================================
timestamp:  ${TIMESTAMP}
db_source:  ${DB_PATH}
db_size_mb: ${DB_SIZE_MB}
gz_size_mb: ${GZ_SIZE_MB}
git_sha:    ${GIT_SHA}
git_branch: ${GIT_BRANCH}
hostname:   $(hostname)
==================================
복원 명령:
    gunzip -k ${SNAPSHOT_DIR}/tradebot.db.gz
    cp ${SNAPSHOT_DIR}/tradebot.db ${DB_PATH}
EOF
echo "  ✓ backup-info.txt"

# ─── 4) LATEST 링크 갱신 + rotate ────────────────────────────────
echo "[4/4] LATEST 갱신 · ${BACKUP_KEEP}일 초과 rotate..."
rm -f "$LATEST_LINK"
ln -s "$TIMESTAMP" "$LATEST_LINK"

# rotate: BACKUP_KEEP 일 이전 스냅샷 삭제 (LATEST 링크 제외)
# find 는 스냅샷 디렉토리(YYYYMMDD_HHMMSS) 만 대상.
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+${BACKUP_KEEP}" \
    -exec rm -rf {} \; 2>/dev/null || true

REMAINING=$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
echo "  ✓ 남은 스냅샷: ${REMAINING} 개"

echo ""
echo "======================================"
echo " ✅ 백업 완료 → $SNAPSHOT_DIR"
echo "======================================"
