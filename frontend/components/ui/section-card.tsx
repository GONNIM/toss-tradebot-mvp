// WP72-2a · SectionCard 부품 · activist-radar BucketCard 색띠 헤더 패턴 정합
// 사용 팔레트: sky (정보) · emerald (성공/매수) · amber (주의/통과) · rose (위험) · slate (중성)
"use client";

import { ReactNode } from "react";

export type SectionTone = "sky" | "emerald" | "amber" | "rose" | "slate";

const TONE: Record<SectionTone, { border: string; badge: string; count: string }> = {
  sky: {
    border: "border-2 border-sky-300 bg-sky-50 dark:border-sky-800 dark:bg-sky-950/40",
    badge: "bg-sky-600 text-white",
    count: "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-100",
  },
  emerald: {
    border: "border-2 border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40",
    badge: "bg-emerald-600 text-white",
    count: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
  },
  amber: {
    border: "border-2 border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
    badge: "bg-amber-500 text-slate-900",
    count: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
  },
  rose: {
    border: "border-2 border-rose-300 bg-rose-50 dark:border-rose-800 dark:bg-rose-950/40",
    badge: "bg-rose-600 text-white",
    count: "bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100",
  },
  slate: {
    border: "border-2 border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40",
    badge: "bg-slate-500 text-white",
    count: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100",
  },
};

type Props = {
  tone: SectionTone;
  icon?: string;
  label: string;
  hint?: string;
  count?: number;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function SectionCard({
  tone,
  icon,
  label,
  hint,
  count,
  collapsible,
  defaultOpen = true,
  children,
}: Props) {
  const t = TONE[tone];
  const Header = (
    <div className="flex items-center gap-2 flex-wrap bg-white/60 px-4 py-2.5 border-b border-slate-200 dark:bg-slate-900/60 dark:border-slate-700">
      <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-bold ${t.badge}`}>
        {icon && <span className="text-base">{icon}</span>}
        {label}
      </span>
      {typeof count === "number" && (
        <span className={`inline-flex min-w-[24px] items-center justify-center rounded-full px-2 py-0.5 text-xs font-black ${t.count}`}>
          {count}
        </span>
      )}
      {hint && (
        <span className="text-sm text-slate-700 dark:text-slate-100 font-medium">{hint}</span>
      )}
    </div>
  );

  if (collapsible) {
    return (
      <details className={`overflow-hidden rounded-lg ${t.border}`} open={defaultOpen}>
        <summary className="cursor-pointer list-none">{Header}</summary>
        <div className="space-y-2 p-3">{children}</div>
      </details>
    );
  }
  return (
    <div className={`overflow-hidden rounded-lg ${t.border}`}>
      {Header}
      <div className="space-y-2 p-3">{children}</div>
    </div>
  );
}
