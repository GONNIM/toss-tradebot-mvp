"use client";

/**
 * 자동매매 대시보드 — Phase K (Toss API) 활성 후 실 데이터.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatPct, formatUSD } from "@/lib/utils";

export default function DashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.dashboard.summary(),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">📊 자동매매 대시보드</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          1,500만원 시드 · Mode A 단타 · +20% 익절 (Phase K 활성 후 실 데이터)
        </p>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          API 호출 실패.
        </div>
      )}

      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="총 자산 (USD)" value={formatUSD(data.total_value_usd)} />
            <StatCard label="총 매수 비용" value={formatUSD(data.total_cost_usd)} />
            <StatCard
              label="실현 손익"
              value={formatUSD(data.realized_pnl_usd)}
              accent={data.realized_pnl_usd >= 0 ? "positive" : "negative"}
            />
            <StatCard
              label="평가 손익"
              value={formatUSD(data.unrealized_pnl_usd)}
              accent={data.unrealized_pnl_usd >= 0 ? "positive" : "negative"}
            />
          </div>

          <div className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">운영 상태</h2>
            <dl className="mt-4 space-y-2 text-sm">
              <Row label="엔진 상태" value={data.engine_status} />
              <Row label="보유 종목 수" value={`${data.open_positions} 개`} />
              <Row
                label="마지막 거래"
                value={data.last_trade_at ? new Date(data.last_trade_at).toLocaleString("ko-KR") : "—"}
              />
            </dl>
          </div>

          {data.engine_status === "not_initialized" && (
            <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4 text-sm">
              <p className="font-semibold text-yellow-400">⚠️ Phase K 미활성</p>
              <p className="mt-1 text-muted-foreground">
                Toss API 개방 후 자동매매 코어가 시작되면 실 데이터로 채워집니다.
                현재는 Crazy / Moonshot 정보 전용 모드로 운영 중입니다.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "positive" | "negative";
}) {
  const color =
    accent === "positive"
      ? "text-green-400"
      : accent === "negative"
        ? "text-red-400"
        : "";
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border pb-2 last:border-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}
