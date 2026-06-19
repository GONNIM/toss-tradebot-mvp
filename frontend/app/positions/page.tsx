"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn, formatPct, formatUSD, riskBadgeClass } from "@/lib/utils";

export default function PositionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["positions"],
    queryFn: () => api.positions.list(),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">💼 보유 포지션</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Phase K (Toss API) 활성 후 실 데이터.
        </p>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {data && data.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
          보유 포지션 없음. (Phase K 활성 후 자동매매 결과 채워짐)
        </div>
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 text-left">
              <tr>
                <th className="px-4 py-3">티커</th>
                <th className="px-4 py-3">위험</th>
                <th className="px-4 py-3 text-right">수량</th>
                <th className="px-4 py-3 text-right">평균 단가</th>
                <th className="px-4 py-3 text-right">현재가</th>
                <th className="px-4 py-3 text-right">평가 손익</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.ticker} className="border-b border-border hover:bg-muted/20">
                  <td className="px-4 py-3 font-bold">{p.ticker}</td>
                  <td className="px-4 py-3">
                    <span className={cn("rounded-full border px-2 py-1 text-xs", riskBadgeClass(p.risk_level))}>
                      {p.risk_level}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{p.shares}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatUSD(p.avg_cost)}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {p.current_price ? formatUSD(p.current_price) : "—"}
                  </td>
                  <td className={cn(
                    "px-4 py-3 text-right font-mono",
                    (p.unrealized_pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400",
                  )}>
                    {p.unrealized_pnl_pct != null ? formatPct(p.unrealized_pnl_pct) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
