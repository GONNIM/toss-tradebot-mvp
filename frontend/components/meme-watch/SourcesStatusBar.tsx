"use client";

import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<string, string> = {
  apewisdom: "ApeWisdom",
  stocktwits: "Stocktwits",
  google_trends: "Google Trends",
  reddit: "Reddit (PRAW)",
};

export function SourcesStatusBar({
  status,
}: {
  status: Record<string, string>;
}) {
  const entries = Object.entries(status);
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="text-muted-foreground">데이터 소스:</span>
      {entries.map(([src, st]) => {
        const ok = st === "ok";
        return (
          <span
            key={src}
            className={cn(
              "rounded-full border px-2 py-0.5",
              ok
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
            )}
            title={
              ok
                ? "최근 12시간 내 데이터 적재 확인"
                : "운영 IP 차단 또는 미설치 — 동적 가중치 재정규화로 자동 보정"
            }
          >
            {ok ? "🟢" : "⚠️"} {SOURCE_LABELS[src] || src}
          </span>
        );
      })}
    </div>
  );
}
