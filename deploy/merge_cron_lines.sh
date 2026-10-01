#!/bin/bash
# WP96 · 현재 crontab 내용 (파일 1) 에 줄 파일 (파일 2) 의 줄 중 정확히 같은 줄이 없는 것만 덧붙여 출력한다.
# 기존 줄은 순서·내용 그대로 두고, 이미 있는 줄은 다시 넣지 않는다 (몇 번 실행해도 같은 결과).
# 사용: bash deploy/merge_cron_lines.sh <현재 crontab 파일> <추가할 줄 파일>
set -euo pipefail
CURRENT="$1"
LINES="$2"
awk 1 "$CURRENT"   # 마지막 줄에 줄바꿈이 없어도 덧붙인 줄과 붙지 않게
grep -v '^[[:space:]]*$' "$LINES" | grep -vxFf "$CURRENT" || true
