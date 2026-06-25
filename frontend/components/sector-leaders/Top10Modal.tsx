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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[1200px] max-h-[90vh] overflow-auto rounded-xl border border-cyan-500/50 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-5 py-3">
          <div>
            <h2 className="text-xl font-bold">🏆 투자 종목 Top 10</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              매력도 점수 = Confluence 0.5 + 신뢰도 0.3 + R/R 0.2 · horizon은 종목별 best_lag
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/30"
            aria-label="Close"
          >
            ✕ 닫기 (Esc)
          </button>
        </div>

        {/* 본문 */}
        <div className="p-5">
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

function Top10Table({ items, computedAt }: { items: Top10Item[]; computedAt: string }) {
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground font-mono">
        산출 시점: {computedAt} · {items.length} 종목
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="border-b border-border bg-muted/40">
            <tr className="text-left whitespace-nowrap">
              <th className="px-3 py-2.5">#</th>
              <th className="px-3 py-2.5">종목</th>
              <th className="px-3 py-2.5">품목</th>
              <th className="px-3 py-2.5 text-right">현재가</th>
              <th className="px-3 py-2.5 text-right">진입가</th>
              <th className="px-3 py-2.5">진입 상태</th>
              <th className="px-3 py-2.5 text-right">예측수익가 (수익률)</th>
              <th className="px-3 py-2.5 text-right">Stop Loss</th>
              <th className="px-3 py-2.5 text-right">Take Profit</th>
              <th className="px-3 py-2.5 text-right">Confluence</th>
              <th className="px-3 py-2.5">신뢰도</th>
              <th className="px-3 py-2.5 text-right">매력도</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <Row key={`${it.ticker}-${it.item}`} it={it} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-1 text-xs text-muted-foreground rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3">
        <div className="font-semibold text-cyan-300 mb-1">💡 사용 가이드</div>
        <ul className="list-disc list-inside space-y-0.5">
          <li><strong>매력도 점수</strong>: 종합 점수 (0~1). 0.6 이상이면 강한 시그널</li>
          <li><strong>진입가</strong>: 현재가가 점추정 90% 이하면 지금 매수 가능. 초과면 조정 대기 권장</li>
          <li><strong>예측수익가</strong>: 종목별 best_lag horizon (수출 → 주가 선행 개월) 적용한 단변량 회귀 점추정</li>
          <li><strong>Stop Loss / Take Profit</strong>: 24M P10 또는 -30% 보수적 / 점추정 80%</li>
          <li><strong>Confluence</strong>: 4종 시그널(수출·지역·모멘텀·갱신) 통합. 0.7 이상이면 매우 강한 동의</li>
          <li>⚠️ 본 모델은 보조 신호 — 투자 권유 아님, 사용자 자체 판단 필요</li>
        </ul>
      </div>
    </div>
  );
}

function Row({ it }: { it: Top10Item }) {
  const isOk = it.entry_status.startsWith("🟢");
  const formatKRW = (n: number) => Math.round(n).toLocaleString("ko-KR");
  return (
    <tr className="border-b border-border/40 hover:bg-muted/20 whitespace-nowrap">
      <td className="px-3 py-2 font-bold text-cyan-400">#{it.rank}</td>
      <td className="px-3 py-2">
        <div className="font-semibold">{it.name}</div>
        <div className="text-[10px] text-muted-foreground font-mono">{it.ticker}</div>
      </td>
      <td className="px-3 py-2">{it.item}</td>
      <td className="px-3 py-2 text-right font-mono">{formatKRW(it.current_price)}</td>
      <td className="px-3 py-2 text-right font-mono font-semibold">{formatKRW(it.entry_price)}</td>
      <td className={`px-3 py-2 ${isOk ? "text-emerald-400" : "text-amber-400"}`}>
        {it.entry_status}
      </td>
      <td className="px-3 py-2 text-right font-mono">
        <div className="text-emerald-400 font-semibold">{formatKRW(it.point_price)}</div>
        <div className="text-[10px] text-muted-foreground">
          ({formatPct(it.point_pct, 1)}, +{it.horizon_months}M)
        </div>
      </td>
      <td className="px-3 py-2 text-right font-mono text-rose-400">
        {it.stop_price !== null ? formatKRW(it.stop_price) : "—"}
        {it.stop_pct !== null && (
          <div className="text-[10px] text-muted-foreground">{formatPct(it.stop_pct, 1)}</div>
        )}
      </td>
      <td className="px-3 py-2 text-right font-mono text-emerald-400">
        {it.take_price !== null ? formatKRW(it.take_price) : "—"}
        {it.take_pct !== null && (
          <div className="text-[10px] text-muted-foreground">{formatPct(it.take_pct, 1)}</div>
        )}
      </td>
      <td className={`px-3 py-2 text-right font-mono ${
        it.confluence_score > 0.4 ? "text-emerald-400" :
        it.confluence_score > -0.4 ? "text-amber-400" : "text-rose-400"
      }`}>
        {it.confluence_score >= 0 ? "+" : ""}
        {it.confluence_score.toFixed(2)}
      </td>
      <td className="px-3 py-2">
        <span className={
          it.confidence_label === "strong" ? "text-emerald-400" :
          it.confidence_label === "medium" ? "text-cyan-400" : "text-muted-foreground"
        }>
          {it.confidence_stars}
        </span>
      </td>
      <td className="px-3 py-2 text-right font-bold font-mono text-cyan-400">
        {it.attractiveness.toFixed(3)}
      </td>
    </tr>
  );
}
