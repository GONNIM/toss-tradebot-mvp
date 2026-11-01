"use client";


// 1022-10 5b (2026-11-01) · 긴 목록 「더 보기」
// 휴대폰에서 화면 길이를 줄인다 (/powderkeg 30,015px · /activist-radar 24,810 · /serenity 23,317 · 10/30 측정).
// 처음에는 앞부분만 보여 주고, 누르면 나머지를 모두 편다.

export function ShowMoreButton({
  total,
  shown,
  onShowAll,
}: {
  total: number;
  shown: number;
  onShowAll: () => void;
}) {
  if (total <= shown) return null;
  return (
    <button
      type="button"
      onClick={onShowAll}
      className="mt-2 min-h-[44px] w-full rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground"
    >
      더 보기 · 남은 {total - shown}개
    </button>
  );
}
