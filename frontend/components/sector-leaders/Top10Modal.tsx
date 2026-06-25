"use client";

/**
 * 🏆 투자 종목 Top 10 모달 (B-2j).
 *
 * 매력도 점수(Confluence 0.5 + 신뢰도 0.3 + R/R 0.2) 상위 10 종목.
 * 진입가 = min(현재가, 점추정 × 0.9).
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Top10Item } from "@/lib/api";
import { formatPct } from "@/lib/utils";

export function Top10Modal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["sector-leaders", "top10", 10],
    queryFn: () => api.sectorLeaders.top10(10),
    enabled: open,
  });

  // ESC 키로 닫기
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-2"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[96vw] max-h-[96vh] flex flex-col overflow-hidden rounded-xl border border-cyan-500/50 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 (고정) */}
        <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2.5">
          <div>
            <h2 className="text-xl font-bold text-foreground">🏆 투자 종목 Top 10</h2>
            <p className="text-xs text-zinc-300 mt-1">
              매력도 = Confluence 0.5 + 신뢰도 0.3 + R/R 0.2 · horizon = 종목별 best_lag
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm text-foreground hover:bg-muted/50"
            aria-label="Close"
          >
            ✕ 닫기 (Esc)
          </button>
        </div>

        {/* 본문 (남은 영역 채움, 내부 표 자체는 가로 스크롤 가능) */}
        <div className="flex-1 overflow-auto p-3">
          {q.isLoading && (
            <div className="rounded-lg border border-border bg-background p-6 text-muted-foreground">
              Top 10 산출 중... (51 종목 매력도 계산)
            </div>
          )}
          {q.error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
              Top 10 호출 실패
            </div>
          )}
          {q.data && <Top10Table items={q.data.items} computedAt={q.data.computed_at} />}
        </div>
      </div>
    </div>
  );
}

function PriceSourceBadge({
  source,
  marketStatus,
  priceAt,
}: {
  source: "live" | "fallback";
  marketStatus: string | null;
  priceAt: string | null;
}) {
  if (source === "fallback") {
    return (
      <div
        className="text-xs text-amber-400 leading-tight mt-0.5"
        title="네이버 실시간 가격 fetch 실패 — 최근 종가 표시"
      >
        ⚠️ 종가 (fallback)
      </div>
    );
  }
  const isOpen = marketStatus === "OPEN";
  const label = isOpen ? "🟢 LIVE" : "⚪ 종가";
  const kstTime = priceAt ? formatKstTime(priceAt) : null;
  return (
    <div className="text-xs text-emerald-300 leading-tight mt-0.5">
      {label}
      {kstTime && <span className="text-zinc-400 ml-1">{kstTime}</span>}
    </div>
  );
}

function formatKstTime(iso: string): string {
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  if (isNaN(d.getTime())) return "";
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())} KST`;
}

function formatComputedAt(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function Top10Table({ items, computedAt }: { items: Top10Item[]; computedAt: string }) {
  return (
    <div className="space-y-2">
      <div className="text-xs text-zinc-300 font-mono">
        산출 시점: {formatComputedAt(computedAt)} · {items.length} 종목
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="border-b border-cyan-500/40 bg-cyan-500/10 sticky top-0">
            <tr className="text-left whitespace-nowrap text-cyan-200 font-semibold">
              <th className="px-2.5 py-2 w-10">#</th>
              <th className="px-2.5 py-2">종목 / 품목</th>
              <th className="px-2.5 py-2 text-right">현재가</th>
              <th className="px-2.5 py-2 text-right">진입가</th>
              <th className="px-2.5 py-2 text-right">예측수익가</th>
              <th className="px-2.5 py-2 text-right">Stop</th>
              <th className="px-2.5 py-2 text-right">Take</th>
              <th className="px-2.5 py-2 text-right">Conf · ★</th>
              <th className="px-2.5 py-2 text-right">매력도</th>
            </tr>
          </thead>
          <tbody className="text-zinc-100">
            {items.map((it) => (
              <Row key={`${it.ticker}-${it.item}`} it={it} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-zinc-200 rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3">
        <div className="font-semibold text-cyan-200 mb-1.5 text-sm">💡 사용 가이드</div>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 list-disc list-inside">
          <li><strong className="text-cyan-200">매력도</strong>: 0~1, 0.6 이상이면 강한 시그널</li>
          <li><strong className="text-cyan-200">진입가</strong>: 현재가가 점추정 90% 이하면 지금 매수 가능</li>
          <li><strong className="text-cyan-200">예측수익가</strong>: 종목별 best_lag horizon 회귀 점추정</li>
          <li><strong className="text-cyan-200">Stop / Take</strong>: 24M P10 또는 -30% / 점추정 80%</li>
          <li><strong className="text-cyan-200">Conf · ★</strong>: 5종 시그널 통합 점수 + 신뢰도 별</li>
          <li className="text-amber-300">⚠️ 보조 신호 — 투자 권유 아님</li>
        </ul>
      </div>
    </div>
  );
}

function Row({ it }: { it: Top10Item }) {
  const isOk = it.entry_status.startsWith("🟢");
  const formatKRW = (n: number) => Math.round(n).toLocaleString("ko-KR");
  // 간결 entry 상태 — "🟢 지금" / "🟡 -3.5%"
  const entryShort = isOk
    ? "🟢 지금"
    : `🟡 ${it.entry_gap_pct.toFixed(1)}%`;
  const confColor =
    it.confluence_score > 0.4 ? "text-emerald-400" :
    it.confluence_score > -0.4 ? "text-amber-400" : "text-rose-400";
  const starColor =
    it.confidence_label === "strong" ? "text-emerald-400" :
    it.confidence_label === "medium" ? "text-cyan-400" : "text-muted-foreground";
  return (
    <tr className="border-b border-border/40 hover:bg-muted/30 whitespace-nowrap">
      <td className="px-2.5 py-2 font-bold text-cyan-300 text-base">#{it.rank}</td>
      <td className="px-2.5 py-2">
        <div className="font-semibold text-zinc-50 leading-tight">{it.name}</div>
        <div className="text-xs text-zinc-400 font-mono leading-tight mt-0.5">
          {it.ticker} · {it.item}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right whitespace-nowrap">
        <div className="font-mono text-zinc-100 font-semibold leading-tight">
          {formatKRW(it.current_price)}
        </div>
        <PriceSourceBadge
          source={it.price_source}
          marketStatus={it.price_market_status}
          priceAt={it.price_at}
        />
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono font-semibold text-zinc-50 leading-tight">
          {formatKRW(it.entry_price)}
        </div>
        <div className={`text-xs leading-tight mt-0.5 ${isOk ? "text-emerald-300" : "text-amber-300"}`}>
          {entryShort}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono text-emerald-300 font-semibold leading-tight">
          {formatKRW(it.point_price)}
        </div>
        <div className="text-xs text-zinc-400 leading-tight mt-0.5">
          {formatPct(it.point_pct, 1)} · +{it.horizon_months}M
        </div>
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono text-rose-300 leading-tight">
          {it.stop_price !== null ? formatKRW(it.stop_price) : "—"}
        </div>
        {it.stop_pct !== null && (
          <div className="text-xs text-zinc-400 leading-tight mt-0.5">
            {formatPct(it.stop_pct, 1)}
          </div>
        )}
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono text-emerald-300 leading-tight">
          {it.take_price !== null ? formatKRW(it.take_price) : "—"}
        </div>
        {it.take_pct !== null && (
          <div className="text-xs text-zinc-400 leading-tight mt-0.5">
            {formatPct(it.take_pct, 1)}
          </div>
        )}
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className={`font-mono font-semibold leading-tight ${confColor}`}>
          {it.confluence_score >= 0 ? "+" : ""}
          {it.confluence_score.toFixed(2)}
        </div>
        <div className={`text-xs leading-tight mt-0.5 ${starColor}`}>
          {it.confidence_stars}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right font-bold font-mono text-cyan-300 text-base">
        {it.attractiveness.toFixed(3)}
      </td>
    </tr>
  );
}
