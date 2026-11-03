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
        if (st === "off") {
          // 1102-06: 수집을 끈 소스 (접근 거부) · 경고색 대신 회색
          return (
            <span
              key={src}
              className="rounded-full border border-border px-2 py-0.5 text-muted-foreground"
              title="접근 거부 (HTTP 403 · 로그 첫 기록 2026-08-22~) 로 수집을 껐습니다 · 점수에는 쓰지 않습니다"
            >
              {SOURCE_LABELS[src] || src} · 수집 안 함 (접근 거부)
            </span>
          );
        }
        return (
          <span
            key={src}
            className={cn(
              "rounded-full border px-2 py-0.5",
              ok
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-warn/40 bg-warn/10 text-warn",
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
