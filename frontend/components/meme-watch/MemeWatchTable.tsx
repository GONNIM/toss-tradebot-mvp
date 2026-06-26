"use client";

import { useState } from "react";

import type { MemeScoreItem } from "@/lib/api";
import { cn } from "@/lib/utils";

import { MemeDetailModal } from "./MemeDetailModal";

const LABEL_COLORS: Record<string, string> = {
  BLAZING: "text-rose-600 dark:text-rose-400",
  HOT: "text-orange-600 dark:text-orange-400",
  WATCH: "text-amber-600 dark:text-amber-400",
  OBSERVE: "text-cyan-600 dark:text-cyan-400",
  SLEEP: "text-zinc-500 dark:text-zinc-400",
};

const STRONGEST_LABELS: Record<string, string> = {
  social: "소셜",
  volume: "거래량",
  oversold: "Oversold",
  short: "공매도",
  catalyst: "Catalyst",
};

export function MemeWatchTable({ items }: { items: MemeScoreItem[] }) {
  const [selected, setSelected] = useState<MemeScoreItem | null>(null);

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
        가용 시그널 데이터 없음. 5분 batch 누적 후 다시 확인.
      </div>
    );
  }

  return (
    <>
      <div className="rounded-xl border border-border overflow-hidden bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted/60 text-foreground font-semibold">
            <tr className="text-left">
              <th className="px-3 py-3 w-12 text-center">#</th>
              <th className="px-3 py-3">종목</th>
              <th className="px-3 py-3 text-right">Score</th>
              <th className="px-3 py-3 text-center">라벨</th>
              <th className="px-3 py-3 text-center">활성</th>
              <th className="px-3 py-3">최강 시그널</th>
              <th className="px-3 py-3">시장</th>
              <th className="px-3 py-3 text-right">시총</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const labelClass = LABEL_COLORS[it.label] || "";
              const strongestLabel =
                STRONGEST_LABELS[it.strongest_signal] || it.strongest_signal;
              return (
                <tr
                  key={`${it.ticker}-${i}`}
                  className="border-b border-border/40 last:border-0 hover:bg-muted/30 cursor-pointer"
                  onClick={() => setSelected(it)}
                >
                  <td className="px-3 py-2.5 text-center font-mono text-muted-foreground">
                    {i + 1}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono font-semibold text-foreground">
                      {it.ticker}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {it.name || "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono font-bold text-foreground">
                    {it.score.toFixed(3)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-center font-semibold",
                      labelClass,
                    )}
                  >
                    <span className="mr-1">{it.emoji}</span>
                    {it.label}
                  </td>
                  <td className="px-3 py-2.5 text-center font-mono text-muted-foreground">
                    {it.active_signals}/5
                  </td>
                  <td className="px-3 py-2.5 text-foreground">
                    {strongestLabel}
                    {it.sample_warning && (
                      <span
                        className="ml-1 text-amber-600 dark:text-amber-400"
                        title="시그널 부족 — 신뢰도 weak"
                      >
                        ⚠️
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">
                    {it.market || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-muted-foreground">
                    {it.market_cap
                      ? `$${(it.market_cap / 1e9).toFixed(1)}B`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <MemeDetailModal item={selected} onClose={() => setSelected(null)} />
    </>
  );
}
