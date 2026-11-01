// 1022-10 5c (2026-11-01) · 등락 색 하나로 · 한국식: 상승 빨강 (up) · 하락 파랑 (down)
// 색 값은 globals.css --up · --down (docs/design-rules.md 1절). 화면마다 따로 고르지 않는다.

/** 값의 부호로 등락 글자 색을 고른다. 값이 없으면 흐림, 0 이면 `zero`. */
export function upDownText(
  v: number | null | undefined,
  zero: string = "text-muted-foreground",
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "text-muted-foreground";
  if (v > 0) return "text-up";
  if (v < 0) return "text-down";
  return zero;
}
