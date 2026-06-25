#!/usr/bin/env bash
# toss-tradebot-mvp 운영 서버 배포 스크립트
#
# 배치 위치: optimus8.cafe24.com:/root/deploy-tossbot.sh   (chmod +x)
# 호출 (로컬): `deploy-tossbot` alias
#   alias deploy-tossbot='ssh root@optimus8.cafe24.com "/root/deploy-tossbot.sh"'
#
# 자매 프로젝트 upbit-tradebot-mvp 의 /root/deploy.sh (= deploy-tradebot) 패턴 차용.
# 본 스크립트는 서버 환경 가정에 따라 작성됨 — 실제 systemd 서비스명·프론트 serve
# 방식이 다르면 아래 변수 / 단계를 조정.

set -euo pipefail

# ─────────────────────────────────────────────────────────────────
# 환경 설정 — 서버 실 환경에 맞춰 수정 가능
# ─────────────────────────────────────────────────────────────────
REPO=/root/toss-tradebot-mvp
BACKEND_SVC=tossbot-backend
FRONTEND_SVC=tossbot-frontend
LOG_TAIL_LINES=15

# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────
step() {
    printf '\n\033[1;36m▶ %s\033[0m\n' "$1"
}
warn() {
    printf '\033[1;33m⚠️  %s\033[0m\n' "$1" >&2
}
ok() {
    printf '\033[1;32m✓ %s\033[0m\n' "$1"
}

# ─────────────────────────────────────────────────────────────────
# 사전 점검
# ─────────────────────────────────────────────────────────────────
step "0/5 사전 점검"
if [ ! -d "$REPO" ]; then
    warn "$REPO 가 존재하지 않습니다. 최초 배포는 git clone 부터 수행하세요:"
    echo "    git clone <repo-url> $REPO"
    exit 1
fi
ok "repo: $REPO"

# ─────────────────────────────────────────────────────────────────
# 1/5 git pull
# ─────────────────────────────────────────────────────────────────
step "1/5 git pull (origin/main rebase)"
cd "$REPO"
BEFORE=$(git rev-parse --short HEAD)
git pull --rebase --quiet
AFTER=$(git rev-parse --short HEAD)
if [ "$BEFORE" = "$AFTER" ]; then
    ok "이미 최신 ($AFTER)"
else
    ok "$BEFORE → $AFTER"
    git log --oneline "$BEFORE..$AFTER" | head -10
fi

# ─────────────────────────────────────────────────────────────────
# 2/5 backend 의존성 (변경 시에만)
# ─────────────────────────────────────────────────────────────────
step "2/5 backend dependencies"
cd "$REPO/backend"
if [ ! -d venv ]; then
    warn "backend/venv 가 없습니다. python3.12 -m venv venv 로 초기 셋업 필요."
    exit 1
fi
venv/bin/pip install -r requirements.txt \
    --quiet --upgrade-strategy only-if-needed
ok "pip install 완료"

# ─────────────────────────────────────────────────────────────────
# 3/5 frontend 빌드
# ─────────────────────────────────────────────────────────────────
step "3/5 frontend build"
cd "$REPO/frontend"
if [ ! -d node_modules ]; then
    warn "frontend/node_modules 가 없어 최초 install 수행"
fi
npm install --legacy-peer-deps --no-audit --no-fund --silent
npm run build
ok "next build 완료"

# ─────────────────────────────────────────────────────────────────
# 4/5 systemctl restart
# ─────────────────────────────────────────────────────────────────
step "4/5 systemctl restart"
if systemctl list-unit-files | grep -q "^$BACKEND_SVC"; then
    systemctl restart "$BACKEND_SVC"
    ok "$BACKEND_SVC restart"
else
    warn "$BACKEND_SVC 서비스가 등록되어 있지 않습니다 — systemd unit 파일 작성 필요"
fi
if systemctl list-unit-files | grep -q "^$FRONTEND_SVC"; then
    systemctl restart "$FRONTEND_SVC"
    ok "$FRONTEND_SVC restart"
else
    warn "$FRONTEND_SVC 서비스가 등록되어 있지 않습니다 — systemd unit 파일 작성 필요"
fi

# 짧은 대기 후 상태 확인
sleep 3

# ─────────────────────────────────────────────────────────────────
# 5/5 상태 확인
# ─────────────────────────────────────────────────────────────────
step "5/5 상태 확인"
for svc in "$BACKEND_SVC" "$FRONTEND_SVC"; do
    if systemctl list-unit-files | grep -q "^$svc"; then
        echo ""
        echo "── $svc ──"
        systemctl status "$svc" --no-pager | head -8
        echo ""
        echo "  최근 로그:"
        journalctl -u "$svc" -n "$LOG_TAIL_LINES" --no-pager
    fi
done

echo ""
ok "deploy-tossbot 완료"
