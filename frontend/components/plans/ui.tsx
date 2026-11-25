"use client";

// 계획 실행기 화면 공용 조각 · 색은 DESIGN 토큰(primary · up · down · warn · muted)만 쓴다.

import type { ReactNode } from "react";

export const BTN =
  "inline-flex min-h-[44px] items-center justify-center rounded-lg px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_PRIMARY = `${BTN} bg-primary text-primary-foreground`;
export const BTN_LINE = `${BTN} border border-border bg-card text-foreground`;
export const BTN_WARN = `${BTN} border border-warn bg-card text-warn`;
export const INPUT =
  "min-h-[44px] w-full rounded-lg border border-input bg-background px-3 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-ring";

export function Chip({ children, tone = "plain", testid }: { children: ReactNode; tone?: "plain" | "on" | "warn"; testid?: string }) {
  const cls =
    tone === "on"
      ? "border-primary/40 bg-primary/10 text-primary"
      : tone === "warn"
        ? "border-warn/40 bg-warn/10 text-warn"
        : "border-border bg-card text-muted-foreground";
  return (
    <span data-testid={testid} className={`inline-flex min-h-[32px] items-center rounded-full border px-3 text-sm ${cls}`}>
      {children}
    </span>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-semibold">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function Notice({ tone = "plain", children, testid }: { tone?: "plain" | "warn"; children: ReactNode; testid?: string }) {
  return (
    <p
      data-testid={testid}
      role={tone === "warn" ? "alert" : undefined}
      className={`rounded-lg border px-3 py-2 text-sm ${
        tone === "warn" ? "border-warn/40 bg-warn/5 text-warn" : "border-border bg-card text-muted-foreground"
      }`}
    >
      {children}
    </p>
  );
}

export function Row({ k, v, testid, tone }: { k: string; v: ReactNode; testid?: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-2 last:border-0">
      <dt className="text-sm text-muted-foreground">{k}</dt>
      <dd data-testid={testid} className={`text-right text-sm font-semibold tabular-nums ${tone ?? ""}`}>
        {v}
      </dd>
    </div>
  );
}

export const NEED_API = "서버가 아직 주지 않는 값";

// 1125-01 · 목록 카드용 공용 조각 (상세 화면도 나중에 쓸 수 있게 여기에 둔다)
/** 카드 하나 · 테두리와 틈으로 나눈다 (그림자 없음) */
export const CARD = "block rounded-[14px] border border-border bg-card p-4 hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 이름표 + 큰 숫자 칸 · lines 는 [작은 이름, 값] 쌍을 여러 줄 쌓는다 */
export function StatCell({ label, lines, note, testid }: { label: string; lines: { k?: string; v: ReactNode }[]; note?: ReactNode; testid?: string }) {
  return (
    <div data-testid={testid} className="min-w-0 rounded-lg bg-muted/50 px-3 py-2">
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <div className="mt-1 space-y-0.5">
        {lines.map((l, i) => (
          <p key={i} className="flex flex-wrap items-baseline gap-x-1.5 tabular-nums">
            {l.k && <span className="text-xs text-muted-foreground">{l.k}</span>}
            <span className="text-base font-bold">{l.v}</span>
          </p>
        ))}
      </div>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

/** 휴대폰 2열 · 넓은 화면 4열 */
export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">{children}</div>;
}
