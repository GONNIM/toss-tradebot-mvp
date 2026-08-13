"use client";

// 👁 관찰 전용 · 지시서 §3 · 가격 피드 없는 고언급 티커 (SIVE 등)
// 별도 접힘 리스트 · 매매 불가 명시

import { useState } from "react";
import type { WatchOnlyItem } from "@/lib/serenity-hunter/types";

export function WatchOnlyList({ items }: { items: WatchOnlyItem[] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <section className="rounded border border-border/40 bg-background/40 px-3 py-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? "▲" : "▼"} 👁 관찰 전용 · 가격 피드 없음 · 거래 불가 · {items.length} 티커
      </button>
      {open && (
        <div className="mt-2 space-y-1">
          {items.map((w) => (
            <div key={w.ticker} className="flex flex-wrap items-baseline gap-2 text-xs">
              <span className="font-mono font-bold">{w.ticker}</span>
              {w.industry && (
                <span className="text-[10px] text-muted-foreground">{w.industry}</span>
              )}
              <span className="text-[10px] text-muted-foreground">
                Bull {w.bull_pct.toFixed(0)}% · 90d {w.mentions_90d} · 7d {w.mentions_7d}
              </span>
              <span className="ml-auto text-[10px] text-red-500">{w.reason}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
