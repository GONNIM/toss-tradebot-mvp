#!/bin/bash
# PreToolUse(Bash) hook: 위험 명령 차단 + 커밋 전 린트·테스트.
# stdin 으로 도구 입력 JSON 을 받는다. exit 2 = 차단(stderr 가 Claude 에게 전달됨).
# toss-tradebot-mvp: 커밋 전 검사는 스테이징 경로별 조건 (intake 2026-10-21).
#   backend/  → compileall(2초) + biotech 테스트(약 14초) · frontend/ → tsc --noEmit(2초)
#   전체 pytest(211초 · 기존 실패 21건)는 걸지 않는다 — 핸드북 규칙 8.
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')

block() { echo "차단: $1 — 사용자 승인 후 직접 실행하십시오." >&2; exit 2; }

echo "$cmd" | grep -Eq 'rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f?[[:space:]]+(/|~|\$HOME|\*)([[:space:]]|$)' && block "광범위 rm -rf"
echo "$cmd" | grep -Eq 'git[[:space:]]+push.*(--force([[:space:]]|$)|-f([[:space:]]|$))' && block "강제 push"
echo "$cmd" | grep -Eq 'git[[:space:]]+reset[[:space:]]+--hard' && block "git reset --hard"
echo "$cmd" | grep -Eq 'git[[:space:]]+clean[[:space:]]+-[a-zA-Z]*f' && block "git clean -f"
echo "$cmd" | grep -Eiq '\b(DROP[[:space:]]+(TABLE|DATABASE|SCHEMA)|TRUNCATE[[:space:]]+)' && block "DB DROP/TRUNCATE"
echo "$cmd" | grep -Eq 'terraform[[:space:]]+(apply|destroy)' && block "terraform apply/destroy"
# 설정 폴더 쓰기: 쓰기 동작의 "대상"이 설정 폴더일 때만 막는다. (2>/dev/null 같은 읽기 명령의 리다이렉트는 통과)
CFG='["'"'"']?(~|\$HOME|/Users/gonnim)/\.claude(-thetak|-profiles)?(/|["'"'"'[:space:]]|$)'
echo "$cmd" | grep -Eq "(>>?|&>|tee([[:space:]]+-a)?)[[:space:]]*$CFG" && block "설정 폴더 수정 (리다이렉트·tee)"
echo "$cmd" | grep -Eq "(^|[;&|[:space:]])(rm|mv|touch|truncate|chmod|sed[[:space:]]+-i[^[:space:]]*|ln)[[:space:]]+[^;&|]*$CFG" && block "설정 폴더 수정"
echo "$cmd" | grep -Eq "(^|[;&|[:space:]])cp[[:space:]]+[^;&|]*[[:space:]]$CFG[^[:space:];&|]*[[:space:]]*($|[;&|])" && block "설정 폴더로 복사"

if echo "$cmd" | grep -Eq 'git[[:space:]]+commit'; then
  cd "$CLAUDE_PROJECT_DIR" || exit 0
  # 같은 명령 안의 `git add …`도 반영하려고 스테이징 목록과 명령 문자열을 함께 본다.
  changed="$(git diff --cached --name-only 2>/dev/null) $cmd"
  if echo "$cmd" | grep -Eq 'git[[:space:]]+commit[^;&|]*[[:space:]]-[a-zA-Z]*a'; then
    changed="$changed $(git diff --name-only 2>/dev/null)"
  fi
  PY="$CLAUDE_PROJECT_DIR/backend/venv/bin/python"
  if echo "$changed" | grep -q 'backend/'; then
    if [ -x "$PY" ]; then
      (cd backend && "$PY" -m compileall -q -x 'venv' . >/dev/null) >&2 || block "backend 문법 검사 실패"
      out=$(cd backend && "$PY" -m pytest -q -p no:cacheprovider tests/test_biotech_*.py 2>/dev/null) \
        || { echo "$out" | tail -15 >&2; block "biotech 테스트 실패"; }
      echo "$out" | tail -1 >&2
    else
      echo "경고: backend/venv 없음 — backend 검사 건너뜀" >&2
    fi
  fi
  if echo "$changed" | grep -q 'frontend/'; then
    if [ -x frontend/node_modules/.bin/tsc ]; then
      (cd frontend && node_modules/.bin/tsc --noEmit) >&2 || block "frontend 타입 검사 실패"
    else
      echo "경고: frontend/node_modules 없음 — tsc 건너뜀" >&2
    fi
  fi
fi
exit 0
