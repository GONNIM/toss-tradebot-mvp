"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { MemeWatchTable } from "@/components/meme-watch/MemeWatchTable";
import { SourcesStatusBar } from "@/components/meme-watch/SourcesStatusBar";
import { UsageGuide } from "@/components/meme-watch/UsageGuide";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type MarketFilter = "all" | "US" | "KRX";

function formatKstTime(iso: string): string {
  if (!iso) return "—";
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${kst.getUTCFullYear()}-${pad(kst.getUTCMonth() + 1)}-${pad(kst.getUTCDate())} ` +
    `${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())} KST`
  );
}

export default function MemeWatchPage() {
  const [limit, setLimit] = useState(20);
  const [market, setMarket] = useState<MarketFilter>("all");

  const marketParam = market === "all" ? undefined : market;
  const { data, isLoading } = useQuery({
    queryKey: ["meme-watch", "top", limit, market],
    queryFn: () => api.memeWatch.top(limit, marketParam),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold">🔥 화끈한 밈주 찾기</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            5요소 confluence — 공매도 · 소셜 · 거래량 · Momentum · Catalyst.
            매 5분 갱신.
          </p>
        </div>
        <select
          className="rounded-lg border border-border bg-card px-3 py-2 text-sm"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
        >
          <option value={10}>Top 10</option>
          <option value={20}>Top 20</option>
          <option value={50}>Top 50</option>
          <option value={100}>Top 100</option>
        </select>
      </header>

      <UsageGuide />

      {/* 시장 탭 */}
      <div className="flex gap-2 border-b border-border">
        <MarketTab active={market === "all"} onClick={() => setMarket("all")}>
          🌐 전체
        </MarketTab>
        <MarketTab active={market === "US"} onClick={() => setMarket("US")}>
          🇺🇸 미국
        </MarketTab>
        <MarketTab active={market === "KRX"} onClick={() => setMarket("KRX")}>
          🇰🇷 한국
        </MarketTab>
      </div>

      {data && (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <SourcesStatusBar status={data.sources_status} />
          <div className="text-xs text-muted-foreground font-mono">
            산출 시각: {formatKstTime(data.computed_at)} · {data.total} 종목
          </div>
        </div>
      )}

      {isLoading && (
        <div className="text-muted-foreground">로딩 중...</div>
      )}
      {data && <MemeWatchTable items={data.items} />}

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
        ⚠️ Meme Score 는 보조 시그널입니다. 투자 권유 아님 — 본 점수는 과거
        패턴 통계이며 미래 수익을 보장하지 않습니다. 밈주는 단시간 -50% 이상
        손실 가능 — Moonshot 모듈과 동일하게 "카지노 머니" 로만 운영 권장.
      </div>
    </div>
  );
}

function MarketTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
        active
          ? "border-cyan-500 text-cyan-700 dark:text-cyan-300"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
