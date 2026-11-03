#!/usr/bin/env bash
# Toss Tradebot MVP · SQLite 백업 스크립트 · Phase D 주 8 · 2026-07-31 · 1103-03 고침 2026-11-03
#
# 목적: backend/data/tradebot.db 를 안전한 시점 스냅샷으로 복사 + 검사 + gzip + 보관 개수 정리.
#      로컬·서버 공통. 서버는 cron 으로 매일 03:30 KST 실행 (deploy/biotech_cron_lines.txt).
#
# 사용:
#     ./scripts/backup.sh                     # 백업 (성공해야 LATEST 갱신 · 보관 정리)
#     BACKUP_KEEP=14 ./scripts/backup.sh      # 남길 성공 스냅샷 개수 override (기본 7)
#     BACKUP_DIR=/mnt/xxx ./scripts/backup.sh # 백업 위치 override (기본 .backup/)
#
# 산출:
#     .backup/YYYYMMDD_HHMMSS/tradebot.db.gz  # VACUUM INTO + quick_check + gzip
#     .backup/YYYYMMDD_HHMMSS/backup-info.txt # 커밋·크기·걸린 시간 메타
#     .backup/YYYYMMDD_HHMMSS/.ok             # 모든 검사를 통과한 스냅샷 표식 (보관 개수는 이것만 셈)
#     .backup/LATEST → YYYYMMDD_HHMMSS (심볼릭 링크)
#     마지막 줄 요약 `backup ok|fail …` (cron 이 /var/log/toss-tradebot/backup.log 에 남김)
#
# 왜 VACUUM INTO 인가 (1103-03): `.backup` 은 복사 중 다른 연결이 쓰면 처음부터 다시 시작한다.
#   운영은 api·cron 두 프로세스가 30초·5분 주기로 계속 써서 11/03 15분 안에 끝나지 않았다.
#   VACUUM INTO 는 읽기 트랜잭션 하나로 복사해 쓰기를 막지 않는다 (11/03 2.7GB 6분).
#   운영 DB 를 읽는 것은 이 단계뿐이고, quick_check·gzip 은 복사본에서 한다.
#
# 참조: upbit-tradebot-mvp/scripts/backup.sh (Boilerplate 백업 · 문서용) —
#      본 스크립트는 DB 스냅샷 전용으로 재설계.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# ─── 설정 (env override) ──────────────────────────────────────────
DB_PATH="${DB_PATH:-backend/data/tradebot.db}"
BACKUP_DIR="${BACKUP_DIR:-.backup}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"   # 남길 성공 스냅샷 개수
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_DIR="${BACKUP_DIR}/${TIMESTAMP}"
LATEST_LINK="${BACKUP_DIR}/LATEST"
TMP_DB="${SNAPSHOT_DIR}/tradebot.db"
START_SEC=$(date +%s)
DB_SIZE_MB=0
GZ_SIZE_MB=0
STEP="준비"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# 실패하면 그 스냅샷 폴더를 지우고 요약 한 줄을 남긴다 (.ok 가 있으면 성공한 것이라 두지 않음).
on_exit() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        if [ -d "$SNAPSHOT_DIR" ] && [ ! -f "${SNAPSHOT_DIR}/.ok" ]; then
            rm -rf "$SNAPSHOT_DIR"
        fi
        log "backup fail step=${STEP} rc=${rc} dir=${SNAPSHOT_DIR} sec=$(( $(date +%s) - START_SEC ))"
    fi
}
trap on_exit EXIT

log "백업 시작 · DB=${DB_PATH} · OUT=${SNAPSHOT_DIR} · KEEP=${BACKUP_KEEP}개"

# ─── 사전 검증 ────────────────────────────────────────────────────
if [ ! -f "$DB_PATH" ]; then
    echo "❌ DB 파일 없음: $DB_PATH" >&2
    exit 1
fi

command -v sqlite3 >/dev/null 2>&1 || {
    echo "❌ sqlite3 미설치 (brew install sqlite / apt-get install sqlite3)" >&2
    exit 2
}

case "$BACKUP_KEEP" in
    ''|*[!0-9]*|0) echo "❌ BACKUP_KEEP 는 1 이상 정수: $BACKUP_KEEP" >&2; exit 2 ;;
esac

mkdir -p "$BACKUP_DIR"

# 겹침 막기 (서버에는 flock 있음 · 맥에는 없어 건너뜀)
STEP="잠금"
if command -v flock >/dev/null 2>&1; then
    exec 9>"${BACKUP_DIR}/.backup.lock"
    if ! flock -n 9; then
        echo "❌ 다른 백업이 실행 중" >&2
        exit 3
    fi
fi

# 지난번에 끝나지 못한 스냅샷 (.ok 없음) 을 지운다 — 잠금을 잡은 뒤라 지금 도는 백업은 없다.
for d in "$BACKUP_DIR"/[0-9]*_[0-9]*; do
    [ -d "$d" ] || continue
    if [ ! -f "$d/.ok" ]; then
        log "끝나지 못한 스냅샷 지움: $d"
        rm -rf "$d"
    fi
done

# 남은 디스크가 DB 크기 × 2 보다 작으면 시작하지 않는다 (복사본 + 압축본이 잠깐 같이 있음).
STEP="디스크"
DB_BYTES=$(wc -c < "$DB_PATH" | tr -d ' ')
AVAIL_KB=$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')
NEED_KB=$(( DB_BYTES * 2 / 1024 ))
if [ "$AVAIL_KB" -lt "$NEED_KB" ]; then
    echo "❌ 디스크 부족: 남음 $(( AVAIL_KB / 1024 )) MB < 필요 $(( NEED_KB / 1024 )) MB" >&2
    exit 4
fi

mkdir -p "$SNAPSHOT_DIR"

# ─── 1) VACUUM INTO (쓰기 중에도 끝나는 스냅샷) ──────────────────
STEP="복사"
log "[1/5] VACUUM INTO..."
sqlite3 -cmd ".timeout 30000" "$DB_PATH" "VACUUM INTO '${TMP_DB}'"
DB_SIZE_MB=$(du -m "$TMP_DB" | awk '{print $1}')
log "  ✓ ${DB_SIZE_MB} MB"

# ─── 2) 복사본 검사 (운영 DB 와 무관) ────────────────────────────
STEP="검사"
log "[2/5] quick_check (복사본)..."
CHECK="$(nice -n 19 sqlite3 "$TMP_DB" "PRAGMA quick_check;")"
if [ "$CHECK" != "ok" ]; then
    echo "❌ quick_check 실패: $(echo "$CHECK" | head -3)" >&2
    exit 5
fi
log "  ✓ ok"

# ─── 3) gzip 압축 + 압축 검사 ────────────────────────────────────
STEP="압축"
log "[3/5] gzip 압축..."
nice -n 19 gzip "$TMP_DB"
gzip -t "${TMP_DB}.gz"
GZ_SIZE_MB=$(du -m "${TMP_DB}.gz" | awk '{print $1}')
log "  ✓ ${GZ_SIZE_MB} MB · gzip -t ok"

# ─── 4) 메타데이터 + 성공 표식 ────────────────────────────────────
STEP="메타"
log "[4/5] 메타 기록..."
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'nogit')"
GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'nobranch')"
cat > "${SNAPSHOT_DIR}/backup-info.txt" <<EOF
Toss Tradebot MVP · DB 백업 정보
================================
timestamp:  ${TIMESTAMP}
db_source:  ${DB_PATH}
db_size_mb: ${DB_SIZE_MB}
gz_size_mb: ${GZ_SIZE_MB}
seconds:    $(( $(date +%s) - START_SEC ))
method:     VACUUM INTO + quick_check + gzip -t
git_sha:    ${GIT_SHA}
git_branch: ${GIT_BRANCH}
hostname:   $(hostname)
==================================
복원 명령 (서비스를 멈춘 뒤):
    gunzip -k ${SNAPSHOT_DIR}/tradebot.db.gz
    cp ${SNAPSHOT_DIR}/tradebot.db ${DB_PATH}
    rm -f ${DB_PATH}-wal ${DB_PATH}-shm
EOF
touch "${SNAPSHOT_DIR}/.ok"

# ─── 5) LATEST 링크 갱신 + 보관 개수 정리 ─────────────────────────
STEP="정리"
log "[5/5] LATEST 갱신 · 성공 스냅샷 ${BACKUP_KEEP}개만 남김..."
ln -sfn "$TIMESTAMP" "$LATEST_LINK"

# 이름 (YYYYMMDD_HHMMSS) 이 시각 순이라 거꾸로 정렬해 앞의 KEEP 개를 뺀 나머지를 지운다.
REMOVED=0
for d in $(ls -1d "$BACKUP_DIR"/[0-9]*_[0-9]*/ 2>/dev/null | sort -r | tail -n +$(( BACKUP_KEEP + 1 ))); do
    [ -f "${d}.ok" ] || continue
    rm -rf "$d"
    REMOVED=$(( REMOVED + 1 ))
done
REMAINING=$(ls -1d "$BACKUP_DIR"/[0-9]*_[0-9]*/ 2>/dev/null | wc -l | tr -d ' ')

STEP="끝"
log "backup ok dir=${SNAPSHOT_DIR} db_mb=${DB_SIZE_MB} gz_mb=${GZ_SIZE_MB} sec=$(( $(date +%s) - START_SEC )) kept=${REMAINING} removed=${REMOVED} disk=$(df -P "$BACKUP_DIR" | awk 'NR==2 {print $5}')"
