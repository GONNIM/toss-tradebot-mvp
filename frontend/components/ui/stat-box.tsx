// WP72-2a · 부품 승격 · activist-radar/page.tsx 에서 이동
// 동일 클래스 문자열 (regression 방지)
"use client";

type Props = { label: string; value: string; hint?: string };

export function StatBox({ label, value, hint }: Props) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
