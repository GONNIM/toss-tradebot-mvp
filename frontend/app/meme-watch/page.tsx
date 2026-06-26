"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { MemeWatchTable } from "@/components/meme-watch/MemeWatchTable";
import { SourcesStatusBar } from "@/components/meme-watch/SourcesStatusBar";
import { api } from "@/lib/api";

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
  const { data, isLoading } = useQuery({
    queryKey: ["meme-watch", "top", limit],
    queryFn: () => api.memeWatch.top(limit),
    refetchInterval: 60_000, // 1분마다 자동 갱신
  });

  return (
    <div className="space-y-5">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold">🔥 화끈한 밈주 찾기</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            5요소 confluence — 공매도 · 소셜 · 거래량 · Oversold · Catalyst.
            매 5분 갱신 (apewisdom + 일봉 + …).
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

      {data && (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <SourcesStatusBar status={data.sources_status} />
          <div className="text-xs text-muted-foreground font-mono">
            산출 시각: {formatKstTime(data.computed_at)} · 총 {data.total} 종목
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
