---
name: deploy-optimus8
description: Toss Tradebot MVP를 optimus8.cafe24.com에 배포·마이그레이션·검증하는 표준 절차. 사용 시점 · 새 DB 컬럼 추가 후 마이그레이션, 서버 상태 조사, 배포 후 curl 3중 검증, SNIPER_API_TOKEN 서버 내부 참조 필요할 때.
---

# deploy-optimus8

Toss Tradebot MVP 표준 배포 절차. `.github/workflows/deploy.yml` 자동 배포(push=배포)와 병행.

## 서버·프로젝트 구조

- **서버**: `ssh root@optimus8.cafe24.com`
- **프로젝트 루트**: `/root/toss-tradebot-mvp`
- **Backend**: `/root/toss-tradebot-mvp/backend` · FastAPI · systemd `tradebot-api`, `tradebot-cron`
- **Frontend**: `/root/toss-tradebot-mvp/frontend` · Next.js 14 · pm2 `tradebot-web`
- **DB**: `/root/toss-tradebot-mvp/backend/data/tradebot.db` · SQLite
- **Nginx**: reverse proxy · `https://optimus8.cafe24.com`
- **SOPS**: `backend/.env.sops.yaml` · age key · deploy.yml 자동 동기화 (커밋·push 시 서버 반영)

## 배포 순서 (스키마 변경 있을 때 · 필수 순서)

### 1단계 · 로컬 검증
```
python3 -m py_compile <변경된 .py>
(cd frontend && npm run build)   # 프론트 변경 시
```

### 2단계 · DB 마이그레이션 (스키마 변경 시만 · 코드 배포 전!)
```
ssh root@optimus8.cafe24.com sqlite3 /root/toss-tradebot-mvp/backend/data/tradebot.db <<'SQL'
ALTER TABLE <table> ADD COLUMN <col> <TYPE>;
.schema <table>
SQL
```
- 코드 배포 전에 반드시 마이그레이션. 순서 뒤바꾸면 재평가 시 `OperationalError`.
- 멱등 스크립트는 `backend/scripts/migrations/YYYY-MM-DD-<subject>.py`로 커밋 · 서버에서 재실행 가능.

### 3단계 · 커밋·push (GitHub Actions 자동 배포)
```
git add <파일들>
git commit -m "..."
git push origin main
```

### 4단계 · 배포 감시
```
RUN_ID=$(gh run list --workflow=deploy.yml --limit=1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```

### 5단계 · 배포 후 curl 3중 검증
```
# ① SHA 인라인 (배포 확증 · 3차 리뷰 P0 인프라)
curl -sS https://optimus8.cafe24.com/powderkeg | python3 -c "
import re, sys
m = re.search(r'build[^A-Za-z0-9]*([a-f0-9]{6,12})', sys.stdin.read())
print('build sha:', m.group(1) if m else 'NOT FOUND')
"

# ② 응답 헤더 (Cache-Control · x-nextjs-cache · ETag)
curl -sSI https://optimus8.cafe24.com/powderkeg | grep -iE '^(cache-control|etag|x-nextjs-cache|date):'

# ③ health
curl -sSf https://optimus8.cafe24.com/health
```

## 서버 상태 조사 (read-only)
```
ssh root@optimus8.cafe24.com "
  echo '=== GIT HEAD ==='; git -C /root/toss-tradebot-mvp log --oneline -3
  echo '=== BUILD_ID ==='; cat /root/toss-tradebot-mvp/frontend/.next/BUILD_ID 2>/dev/null || echo 'no BUILD_ID'
  echo '=== SYSTEMD ==='; systemctl is-active tradebot-api tradebot-cron
  echo '=== PM2 ==='; pm2 list | head -12
  echo '=== NGINX PROXY ==='; grep -rE 'proxy_cache|proxy_pass' /etc/nginx/sites-enabled/ | head
"
```

## 인증 토큰 사용 (SNIPER_API_TOKEN · 서버 내부 참조 · 로컬 노출 절대 금지)

`.env` 파일에 홀따옴표 짝 오류 이슈 있으므로 `source` 대신 `grep` + `cut`으로 값만 추출:
```
ssh root@optimus8.cafe24.com bash <<'REMOTE'
TOKEN=$(grep -E '^SNIPER_API_TOKEN=' /root/toss-tradebot-mvp/backend/.env | head -1 | cut -d= -f2- | tr -d "\"'")
curl -sS -X POST http://127.0.0.1:8000/api/v1/powderkeg/screener/run \
  -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tickers":["003240"],"year":2026}'
REMOTE
```
- heredoc `'REMOTE'` (홀따옴표) 로 로컬 셸 확장 차단 · escape 지옥 회피
- 토큰은 서버 셸 변수로만 존재 · 로컬 대화창엔 결과 JSON만 도달

## 흔한 실수 (반복 방지)

- **스키마 변경 후 마이그레이션 없이 push** → 배포 완료 후 재평가 시 `sqlite3.OperationalError: no such column`. 반드시 마이그레이션 먼저.
- **SNIPER_API_TOKEN 을 로컬 명령줄에 노출** → 대화 로그·shell history 오염. 원격 실행이 원칙.
- **Cache-Control s-maxage=31536000 유지** → 배포 후에도 프록시 캐시가 이전 SSR 서빙. `next.config.mjs`에서 `/powderkeg[/*]` `s-maxage=60`으로 하향 완료 (v1.29+).
- **SSR 마커로 배포 확증 시도** → `page.tsx = "use client"` + 탭 조건부 렌더링으로 오탐/누탐. **커밋 해시 SSR 푸터** (`build {SHA}`) 가 유일한 결정적 방법.

## 관련 문서·메모리

- `.github/workflows/deploy.yml` — 자동 배포 실체 (SOPS · git reset · npm build · pm2 reload · verify)
- `docs/plans/powderkeg-screener/3rd-review-response.md` — 배포 갭·캐시·SHA 인라인 근거
- `.claude/lessons-learned.md` 교훈 #1 (workflow 우선), #2 (§6 팔림세스트)
- 메모리: `reference_tossbot_deploy`, `feedback_workflow_first_before_manual_deploy`
