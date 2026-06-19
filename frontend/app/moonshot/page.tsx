"use client";

/**
 * Moonshot Picks 페이지 — Top 3 카드.
 */
import { useQuery } from "@tanstack/react-query";
import { api, type MoonshotPick } from "@/lib/api";
import {
  cn,
  formatMarketCap,
  formatUSD,
  manipulationBadgeClass,
  riskBadgeClass,
} from "@/lib/utils";

export default function MoonshotPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["moonshot", "top"],
    queryFn: () => api.moonshot.list(3),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">🚀 Moonshot Picks</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          매일 16:50 KST (미국 장 시작 10분 전). 100만원 카지노 자금 · 수동 매수.
        </p>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          API 호출 실패. 백엔드(uvicorn) 가동 확인 필요.
        </div>
      )}
      {data && data.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
          저장된 Moonshot Pick 없음. CLI <code className="rounded bg-muted px-1">moonshot live</code> 또는 cron 활성 후 채워집니다.
        </div>
      )}

      {data && data.map((pick) => <PickCard key={pick.id} pick={pick} />)}
    </div>
  );
}

function PickCard({ pick }: { pick: MoonshotPick }) {
  return (
    <article className="rounded-xl border border-border bg-card p-6 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-muted-foreground">#{pick.rank}</div>
          <h2 className="text-2xl font-bold">{pick.ticker}</h2>
          <p className="text-sm text-muted-foreground">
            {pick.company_name} · {pick.sector || "—"}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold">{formatUSD(pick.current_price, 4)}</div>
          <div className="text-xs text-muted-foreground">{formatMarketCap(pick.market_cap_usd)}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className={cn("rounded-full border px-2 py-1", riskBadgeClass(pick.risk_level))}>
          위험 {pick.risk_level}
        </span>
        <span className={cn("rounded-full border px-2 py-1", manipulationBadgeClass(pick.manipulation_risk))}>
          조작 {pick.manipulation_risk}/5
        </span>
        <span className="rounded-full border border-border bg-muted px-2 py-1">
          총점 {pick.total_score.toFixed(1)}/100
        </span>
      </div>

      <div className="text-sm">
        <div className="font-semibold">📊 Thesis</div>
        <p className="mt-1 text-muted-foreground">{pick.thesis || "(thesis 없음)"}</p>
      </div>

      {pick.catalysts.length > 0 && (
        <div className="text-sm">
          <div className="font-semibold text-green-400">🎯 카탈리스트</div>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {pick.catalysts.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      {pick.risks.length > 0 && (
        <div className="text-sm">
          <div className="font-semibold text-red-400">⚠️ 위험</div>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {pick.risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
        <div className="font-semibold">💰 매수 가격대 (3 가격대)</div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <div className="text-muted-foreground">시장가</div>
            <div className="font-mono font-bold">{formatUSD(pick.buy_price_market, 4)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">-3% 지정가</div>
            <div className="font-mono font-bold text-cyan-400">{formatUSD(pick.buy_price_limit_3pct, 4)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">-7% 지정가</div>
            <div className="font-mono font-bold text-cyan-400">{formatUSD(pick.buy_price_limit_7pct, 4)}</div>
          </div>
        </div>
      </div>

      {pick.risk_warning && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {pick.risk_warning}
        </div>
      )}
    </article>
  );
}
