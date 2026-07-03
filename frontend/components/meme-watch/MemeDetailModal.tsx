"use client";

import { useEffect } from "react";

import type { MemeScoreItem } from "@/lib/api";
import { cn } from "@/lib/utils";

import { MemeRadarChart } from "./MemeRadarChart";

const LABEL_COLORS: Record<string, string> = {
  BLAZING:
    "text-rose-700 dark:text-rose-300 border-rose-500/50 bg-rose-500/15",
  HOT:
    "text-orange-700 dark:text-orange-300 border-orange-500/50 bg-orange-500/15",
  WATCH:
    "text-amber-700 dark:text-amber-300 border-amber-500/50 bg-amber-500/15",
  OBSERVE:
    "text-cyan-700 dark:text-cyan-300 border-cyan-500/50 bg-cyan-500/15",
  SLEEP:
    "text-zinc-600 dark:text-zinc-400 border-zinc-500/40 bg-zinc-500/10",
};

function MetricCell({
  label,
  value,
  format,
}: {
  label: string;
  value: number | null | undefined;
  format: "pct" | "x";
}) {
  const valStr =
    value == null
      ? "—"
      : format === "pct"
        ? `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
        : `${value.toFixed(2)}×`;
  const cls =
    value == null
      ? "text-zinc-500 dark:text-zinc-500"
      : format === "pct" && value < 0
        ? "text-rose-700 dark:text-rose-300"
        : value == null || value <= 0
          ? "text-zinc-600 dark:text-zinc-400"
          : "text-emerald-700 dark:text-emerald-300 font-semibold";
  return (
    <div className="rounded bg-muted/40 border border-border px-2 py-1.5 text-center">
      <div className="text-zinc-600 dark:text-zinc-400 text-[10px]">{label}</div>
      <div className={cn("font-mono text-sm mt-0.5", cls)}>{valStr}</div>
    </div>
  );
}

function formatPrice(price: number | null | undefined, market: string | null | undefined): string {
  if (price == null) return "—";
  if (market === "KRX") return `${Math.round(price).toLocaleString("ko-KR")}원`;
  return `$${price.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function formatMarketCap(cap: number | null | undefined, market: string | null | undefined): string {
  if (cap == null) return "—";
  if (market === "KRX") return `${(cap / 1e12).toFixed(2)}조원`;
  return `$${(cap / 1e9).toFixed(2)}B`;
}

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
  const r1d = item.return_1d_pct;
  const r1dClass =
    r1d == null
      ? "text-zinc-500 dark:text-zinc-400"
      : r1d >= 0
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-rose-700 dark:text-rose-300";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden rounded-xl border border-cyan-500/40 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between border-b border-border bg-card px-5 py-3">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{item.emoji}</span>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono font-bold text-zinc-900 dark:text-zinc-50 text-base">
                  {item.ticker}
                </span>
                <span className="text-zinc-800 dark:text-zinc-100 font-semibold">
                  {item.name || "—"}
                </span>
                <span
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-bold",
                    labelClass,
                  )}
                >
                  {item.label}
                </span>
              </div>
              <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-1">
                {item.market || "—"}
                {item.sector ? ` · ${item.sector}` : ""}
                {item.market_cap
                  ? ` · 시총 ${formatMarketCap(item.market_cap, item.market)}`
                  : ""}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm text-zinc-900 dark:text-zinc-100 hover:bg-muted/60"
          >
            ✕ 닫기 (Esc)
          </button>
        </div>

        {/* 본문 */}
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {/* 가격 요약 (신규) */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <div className="text-xs text-zinc-600 dark:text-zinc-400">
                현재가
              </div>
              <div className="font-mono text-xl font-bold text-zinc-900 dark:text-zinc-50 mt-1">
                {formatPrice(item.current_price, item.market)}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <div className="text-xs text-zinc-600 dark:text-zinc-400">
                1D 변화
              </div>
              <div className={cn("font-mono text-xl font-bold mt-1", r1dClass)}>
                {r1d == null
                  ? "—"
                  : `${r1d >= 0 ? "+" : ""}${r1d.toFixed(2)}%`}
              </div>
            </div>
          </div>

          {/* Intensity Index (Phase 3-E) */}
          {item.intensity && (
            <div className="rounded-xl border border-cyan-500/40 bg-cyan-500/10 p-4">
              <div className="flex items-baseline justify-between mb-2">
                <div className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
                  🌡️ 현재 폭등 강도 (Intensity Index)
                </div>
                <div className="text-3xl">{item.intensity.emoji}</div>
              </div>
              <div className="flex items-baseline gap-3">
                <div className="font-mono text-4xl font-bold text-zinc-900 dark:text-zinc-50">
                  {item.intensity.intensity.toFixed(1)}
                </div>
                <div className="text-sm text-zinc-600 dark:text-zinc-400">/ 10</div>
                <div className="text-lg font-bold text-cyan-700 dark:text-cyan-300 ml-2">
                  {item.intensity.label}
                </div>
              </div>
              <div className="grid grid-cols-4 gap-2 mt-3 text-xs">
                <MetricCell
                  label="1D"
                  value={item.intensity.return_1d}
                  format="pct"
                />
                <MetricCell
                  label="5D 누적"
                  value={item.intensity.return_5d}
                  format="pct"
                />
                <MetricCell
                  label="가속도"
                  value={item.intensity.acceleration}
                  format="pct"
                />
                <MetricCell
                  label="거래량 배수"
                  value={item.intensity.volume_ratio}
                  format="x"
                />
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-500 mt-2">
                샘플 {item.intensity.sample_days}일. 이력 누적 시 정확도 ↑.
              </div>
            </div>
          )}

          {/* Score 요약 3-grid */}
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <div className="text-xs text-zinc-600 dark:text-zinc-400">
                Meme Score
              </div>
              <div className="font-mono text-2xl font-bold text-cyan-700 dark:text-cyan-300 mt-1">
                {item.score.toFixed(3)}
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-500 mt-1">
                / 1.5 (이론 최대)
              </div>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <div className="text-xs text-zinc-600 dark:text-zinc-400">
                활성 시그널
              </div>
              <div className="font-mono text-2xl font-bold text-zinc-900 dark:text-zinc-50 mt-1">
                {item.active_signals}/5
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-500 mt-1">
                normalized ≥ 0.5
              </div>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 p-3">
              <div className="text-xs text-zinc-600 dark:text-zinc-400">
                신뢰도
              </div>
              <div className="font-mono text-2xl font-bold text-zinc-900 dark:text-zinc-50 mt-1">
                {item.confidence_label}
              </div>
              {item.sample_warning && (
                <div className="text-xs text-amber-700 dark:text-amber-300 font-semibold mt-1">
                  ⚠️ 시그널 부족
                </div>
              )}
            </div>
          </div>

          {/* 5축 레이더 */}
          <div className="rounded-xl border border-border p-4 bg-card">
            <div className="text-sm font-bold text-zinc-900 dark:text-zinc-50 mb-2">
              📊 5요소 시그널 분해
            </div>
            <MemeRadarChart contributions={item.contributions} />
          </div>

          {/* 시그널 detail 표 */}
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-cyan-500/40 bg-cyan-500/15 text-cyan-700 dark:text-cyan-200 font-bold">
                <tr>
                  <th className="px-3 py-2.5 text-left">시그널</th>
                  <th className="px-3 py-2.5 text-left">값</th>
                  <th className="px-3 py-2.5 text-right">정규화</th>
                  <th className="px-3 py-2.5 text-right">가중치</th>
                  <th className="px-3 py-2.5 text-right">기여도</th>
                </tr>
              </thead>
              <tbody className="text-zinc-800 dark:text-zinc-100">
                {item.contributions.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-3 py-4 text-center text-zinc-500 dark:text-zinc-400"
                    >
                      가용 시그널 없음
                    </td>
                  </tr>
                )}
                {item.contributions.map((c) => (
                  <tr
                    key={c.name}
                    className="border-b border-border/40 last:border-0 hover:bg-muted/30"
                  >
                    <td className="px-3 py-2.5 text-zinc-900 dark:text-zinc-50 font-semibold">
                      {c.label}
                    </td>
                    <td className="px-3 py-2.5 text-zinc-600 dark:text-zinc-300 font-mono text-xs">
                      {c.raw_label}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-zinc-800 dark:text-zinc-100">
                      {c.normalized.toFixed(2)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-zinc-600 dark:text-zinc-400">
                      {(c.weight * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono font-bold text-cyan-700 dark:text-cyan-300">
                      {c.contribution.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 안내 */}
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200 font-semibold">
            ⚠️ Meme Score 는 보조 시그널입니다. 투자 권유 아님 — 본 점수는
            과거 패턴 통계이며 미래 수익을 보장하지 않습니다.
          </div>
        </div>
      </div>
    </div>
  );
}
