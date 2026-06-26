"use client";

import { useEffect } from "react";

import type { MemeScoreItem } from "@/lib/api";
import { cn } from "@/lib/utils";

import { MemeRadarChart } from "./MemeRadarChart";

const LABEL_COLORS: Record<string, string> = {
  BLAZING: "text-rose-600 dark:text-rose-400 border-rose-500/40 bg-rose-500/10",
  HOT: "text-orange-600 dark:text-orange-400 border-orange-500/40 bg-orange-500/10",
  WATCH:
    "text-amber-600 dark:text-amber-400 border-amber-500/40 bg-amber-500/10",
  OBSERVE:
    "text-cyan-600 dark:text-cyan-400 border-cyan-500/40 bg-cyan-500/10",
  SLEEP:
    "text-zinc-500 dark:text-zinc-400 border-zinc-500/40 bg-zinc-500/10",
};

export function MemeDetailModal({
  item,
  onClose,
}: {
  item: MemeScoreItem | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!item) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [item, onClose]);

  if (!item) return null;

  const labelClass = LABEL_COLORS[item.label] || LABEL_COLORS.SLEEP;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between border-b border-border bg-card px-5 py-3">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{item.emoji}</span>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-foreground">
                  {item.ticker}
                </span>
                <span className="text-foreground">{item.name || "—"}</span>
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs font-semibold",
                    labelClass,
                  )}
                >
                  {item.label}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                {item.market || "—"}
                {item.sector ? ` · ${item.sector}` : ""}
                {item.market_cap
                  ? ` · 시총 $${(item.market_cap / 1e9).toFixed(2)}B`
                  : ""}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm text-foreground hover:bg-muted/50"
          >
            ✕ 닫기 (Esc)
          </button>
        </div>

        {/* 본문 */}
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {/* Score 요약 */}
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="text-xs text-muted-foreground">Meme Score</div>
              <div className="font-mono text-2xl font-bold text-foreground mt-1">
                {item.score.toFixed(3)}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                / 1.5 (이론 최대)
              </div>
            </div>
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="text-xs text-muted-foreground">활성 시그널</div>
              <div className="font-mono text-2xl font-bold text-foreground mt-1">
                {item.active_signals}/5
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                normalized ≥ 0.5
              </div>
            </div>
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="text-xs text-muted-foreground">신뢰도</div>
              <div className="font-mono text-2xl font-bold text-foreground mt-1">
                {item.confidence_label}
              </div>
              {item.sample_warning && (
                <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                  ⚠️ 시그널 부족
                </div>
              )}
            </div>
          </div>

          {/* 5축 레이더 */}
          <div className="rounded-xl border border-border p-4">
            <div className="text-sm font-semibold text-foreground mb-2">
              📊 5요소 시그널 분해
            </div>
            <MemeRadarChart contributions={item.contributions} />
          </div>

          {/* 시그널 detail */}
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-muted/60 text-foreground font-semibold">
                <tr>
                  <th className="px-3 py-2 text-left">시그널</th>
                  <th className="px-3 py-2 text-left">값</th>
                  <th className="px-3 py-2 text-right">정규화</th>
                  <th className="px-3 py-2 text-right">가중치</th>
                  <th className="px-3 py-2 text-right">기여도</th>
                </tr>
              </thead>
              <tbody>
                {item.contributions.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-3 py-4 text-center text-muted-foreground"
                    >
                      가용 시그널 없음
                    </td>
                  </tr>
                )}
                {item.contributions.map((c) => (
                  <tr
                    key={c.name}
                    className="border-b border-border/40 last:border-0"
                  >
                    <td className="px-3 py-2 text-foreground">{c.label}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {c.raw_label}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-foreground">
                      {c.normalized.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {(c.weight * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-semibold text-cyan-700 dark:text-cyan-300">
                      {c.contribution.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 안내 */}
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
            ⚠️ Meme Score 는 보조 시그널입니다. 투자 권유 아님 — 본 점수는
            과거 패턴 통계이며 미래 수익을 보장하지 않습니다.
          </div>
        </div>
      </div>
    </div>
  );
}
