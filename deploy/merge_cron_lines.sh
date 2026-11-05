#!/bin/bash
# WP96 → 1105-06 · crontab 관리 구역.
# 현재 crontab (파일 1) 에서 봇 구역 (# >>> toss-tradebot … # <<< toss-tradebot) 을 줄 파일 (파일 2) 내용으로 통째 바꿔 출력한다.
#   - 구역 밖 줄 (사용자 줄) 은 순서·내용 그대로 둔다.
#   - 구역 밖에 줄 파일과 정확히 같은 줄이 있으면 (예전 덧붙이기 방식으로 들어간 줄) 지우고 구역으로 옮긴다 (처음 한 번).
#   - 몇 번 실행해도 같은 결과.
# 안전장치 (Fable 1105-04-01 막음 3) · 아래면 아무것도 출력하지 않고 exit 3 (배포는 crontab 을 바꾸지 않음):
#   - 줄 파일에 줄이 없음 · 결과가 비어 있음
#   - 시작 표시만 있고 끝 표시가 없음 (또는 반대) · 표시가 두 번 이상
#   - 구역 밖 줄이 「옮긴 줄」 보다 더 많이 줄어듦
# 사용: bash deploy/merge_cron_lines.sh <현재 crontab 파일> <봇 줄 파일>
set -euo pipefail
CURRENT="$1"
LINES="$2"
BEGIN_MARK="# >>> toss-tradebot (deploy/biotech_cron_lines.txt · 배포가 이 구역을 통째로 바꿈 · 직접 고치지 마십시오) >>>"
END_MARK="# <<< toss-tradebot <<<"

fail() { echo "merge_cron_lines: $1 · crontab 그대로 둠" >&2; exit 3; }

NEW_LINES="$(grep -v '^[[:space:]]*$' "$LINES" || true)"
[ -n "$NEW_LINES" ] || fail "봇 줄 파일이 비어 있음"

n_begin=$(grep -c '^# >>> toss-tradebot' "$CURRENT" || true)
n_end=$(grep -cxF "$END_MARK" "$CURRENT" || true)
[ "$n_begin" -le 1 ] && [ "$n_end" -le 1 ] && [ "$n_begin" -eq "$n_end" ] || fail "구역 표시가 맞지 않음 (시작 ${n_begin} · 끝 ${n_end})"

# 구역 밖 줄 (마지막 줄 줄바꿈 없어도 awk 가 맞춤)
OUTSIDE="$(awk -v e="$END_MARK" '
  /^# >>> toss-tradebot/ {inblk=1; next}
  inblk && $0 == e {inblk=0; next}
  !inblk {print}
' "$CURRENT")"

# 구역 밖에서 봇 줄과 정확히 같은 줄을 뺌 (구역으로 옮김)
KEPT="$(printf '%s\n' "$OUTSIDE" | grep -vxFf <(printf '%s\n' "$NEW_LINES") || true)"

count_entries() { printf '%s\n' "$1" | grep -cv '^[[:space:]]*$' || true; }
before=$(count_entries "$OUTSIDE")
moved=$(printf '%s\n' "$OUTSIDE" | grep -cxFf <(printf '%s\n' "$NEW_LINES") || true)
after=$(count_entries "$KEPT")
[ "$after" -eq $(( before - moved )) ] || fail "구역 밖 줄 수가 맞지 않음 (전 ${before} · 옮김 ${moved} · 후 ${after})"

OUT="$( {
  if [ -n "$KEPT" ]; then printf '%s\n' "$KEPT"; fi
  printf '%s\n' "$BEGIN_MARK"
  printf '%s\n' "$NEW_LINES"
  printf '%s\n' "$END_MARK"
} )"
[ -n "$OUT" ] || fail "결과가 비어 있음"
printf '%s\n' "$OUT"
