"use client";

// 개별 티커 카드 · Phase L6 · 2026-08-02

import Link from "next/link";
import type { TickerCardItem } from "@/lib/serenity/types";

const TIER_STYLE: Record<string, string> = {
  S: "bg-purple-500/20 text-purple-400 border-purple-500/40",
  A: "bg-blue-500/20 text-blue-400 border-blue-500/40",
  B: "bg-emerald-500/20 text-emerald-500 border-emerald-500/40",
  C: "bg-amber-500/20 text-amber-500 border-amber-500/40",
  D: "bg-orange-500/20 text-orange-500 border-orange-500/40",
  F: "bg-red-500/20 text-red-500 border-red-500/40",
};

export function TickerCard({ item }: { item: TickerCardItem }) {
  const financing = item.financing_tier ?? "-";
  const serenity = item.serenity_tier ?? "-";
  const financingCls = TIER_STYLE[financing] ?? "bg-slate-500/20 text-slate-400 border-slate-500/40";
  const serenityCls = TIER_STYLE[serenity] ?? "bg-slate-500/20 text-slate-400 border-slate-500/40";

  return (
    <Link
      href={`/influencer/serenity/${item.ticker}`}
      className={`block rounded-lg border p-3 transition hover:border-primary/60 ${
        item.auto_avoid ? "border-red-500/40 bg-red-500/5" : "border-border bg-card"
      }`}
    >
      <div className="flex items-baseline justify-between">
        <div>
          <div className="font-mono text-lg font-bold">${item.ticker}</div>
          {item.domain_tags.length > 0 && (
            <div className="mt-0.5 text-[10px] text-muted-foreground">
              {item.domain_tags.join(" · ")}
            </div>
          )}
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-primary">{item.total_score}</div>
          {item.auto_avoid && (
            <span className="text-[10px] font-semibold text-red-500">AVOID</span>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
        <span className={`rounded border px-1.5 py-0.5 font-semibold ${financingCls}`}>
          Financing {financing}
        </span>
        <span className={`rounded border px-1.5 py-0.5 font-semibold ${serenityCls}`}>
          Serenity {serenity}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>90d {item.mention_count_90d} mentions</span>
        <span>bullish {item.bullish_pct_90d.toFixed(0)}%</span>
      </div>

      {item.anti_pattern_flags.length > 0 && (
        <div className="mt-1 text-[10px] text-red-400">
          ⚠ {item.anti_pattern_flags.join(", ")}
        </div>
      )}

      {item.latest_reasoning && (
        <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">
          {item.latest_reasoning}
        </p>
      )}
    </Link>
  );
}
