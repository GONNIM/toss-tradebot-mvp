"use client";

/**
 * Crazy Picks 페이지 — Top 10 테이블.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatMarketCap, formatUSD } from "@/lib/utils";

export default function CrazyPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["crazy", "top"],
    queryFn: () => api.crazy.list(10),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">🎯 Crazy Picks</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          매일 06:30 KST · 시총 ≥ $1B 안전 universe · 정보 전용 (수동 매수)
        </p>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          API 호출 실패.
        </div>
      )}
      {data && data.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
          저장된 Crazy Pick 없음. cron 활성 후 채워집니다.
        </div>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40">
              <tr className="text-left">
                <th className="px-4 py-3">#</th>
                <th className="px-4 py-3">티커</th>
                <th className="px-4 py-3">회사</th>
                <th className="px-4 py-3">섹터</th>
                <th className="px-4 py-3 text-right">현재가</th>
                <th className="px-4 py-3 text-right">시총</th>
                <th className="px-4 py-3 text-right">점수</th>
                <th className="px-4 py-3">Thesis</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className="border-b border-border hover:bg-muted/20">
                  <td className="px-4 py-3 text-muted-foreground">#{p.rank}</td>
                  <td className="px-4 py-3 font-bold">{p.ticker}</td>
                  <td className="px-4 py-3 max-w-[180px] truncate">{p.company_name || "—"}</td>
                  <td className="px-4 py-3 text-muted-foreground">{p.sector || "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {p.close_price != null ? formatUSD(p.close_price) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{formatMarketCap(p.market_cap)}</td>
                  <td className="px-4 py-3 text-right font-bold">
                    {(p.composite_score ?? 0).toFixed(1)}
                  </td>
                  <td className="px-4 py-3 max-w-[300px] truncate text-muted-foreground">
                    {p.thesis || "(미생성)"}
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
