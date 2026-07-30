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

function parseJsonArray(s: string | null): string[] {
  if (!s) return [];
  try {
    const v = JSON.parse(s);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export default function MoonshotPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["moonshot", "top"],
    queryFn: () => api.moonshot.list(3),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="flex items-center gap-2 text-3xl font-bold">
          🚀 Moonshot Picks
          <span className="rounded bg-gray-500/20 px-2 py-0.5 text-[10px] font-semibold text-gray-400">
            LAGGING
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          매일 16:50 KST (미국 장 시작 10분 전) · 정보 전용 (수동 매수)
        </p>
        <p className="mt-1 text-[11px] text-amber-400/80">
          ⚠️ 모든 pick 의 outcome (T+1·T+3·T+5) 을 카드에 표시합니다. cherry-pick 금지 (리뷰 A 권고 2).
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
          저장된 Moonshot Pick 없음. cron 16:50 KST 활성 후 채워집니다.
        </div>
      )}

      {data && data.map((pick) => <PickCard key={pick.id} pick={pick} />)}
    </div>
  );
}

function PickCard({ pick }: { pick: MoonshotPick }) {
  const catalysts = parseJsonArray(pick.catalysts);
  const risks = parseJsonArray(pick.risks);
  const risk_level = pick.risk_level || "MED";
  const manipulation_risk = pick.manipulation_risk ?? 3;

  return (
    <article className="rounded-xl border border-border bg-card p-6 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-muted-foreground">#{pick.rank}</div>
          <h2 className="text-2xl font-bold">{pick.ticker}</h2>
          <p className="text-sm text-muted-foreground">
            {pick.company_name || "—"} · {pick.sector || "—"}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold">
            {pick.current_price != null ? formatUSD(pick.current_price, 4) : "—"}
          </div>
          <div className="text-xs text-muted-foreground">{formatMarketCap(pick.market_cap)}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className={cn("rounded-full border px-2 py-1", riskBadgeClass(risk_level))}>
          위험 {risk_level}
        </span>
        <span className={cn("rounded-full border px-2 py-1", manipulationBadgeClass(manipulation_risk))}>
          조작 {manipulation_risk}/5
        </span>
        <span className="rounded-full border border-border bg-muted px-2 py-1">
          총점 {(pick.composite_score ?? 0).toFixed(1)}/100
        </span>
      </div>

      <div className="text-sm">
        <div className="font-semibold">📊 Thesis</div>
        <p className="mt-1 text-muted-foreground whitespace-pre-line">
          {pick.thesis || "(thesis 없음)"}
        </p>
      </div>

      {catalysts.length > 0 && (
        <div className="text-sm">
          <div className="font-semibold text-green-400">🎯 카탈리스트</div>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {catalysts.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      {risks.length > 0 && (
        <div className="text-sm">
          <div className="font-semibold text-red-400">⚠️ 위험</div>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
        <div className="font-semibold">💰 매수 가격대 (Decision 33)</div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <div className="text-muted-foreground">A 시장가</div>
            <div className="font-mono font-bold">
              {pick.buy_price_a != null ? formatUSD(pick.buy_price_a, 4) : "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">B -5% drop</div>
            <div className="font-mono font-bold text-cyan-400">
              {pick.buy_price_b != null ? formatUSD(pick.buy_price_b, 4) : "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">C +8% 돌파</div>
            <div className="font-mono font-bold text-cyan-400">
              {pick.buy_price_c != null ? formatUSD(pick.buy_price_c, 4) : "—"}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
        <div className="font-semibold">🎯 매도 정책 (Decision 34)</div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <div className="text-muted-foreground">목표 (×{pick.target_sell_multiplier ?? 2})</div>
            <div className="font-mono font-bold text-green-400">
              {pick.current_price != null && pick.target_sell_multiplier != null
                ? formatUSD(pick.current_price * pick.target_sell_multiplier, 2)
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">스탑 (×{pick.stop_loss_multiplier ?? 0.5})</div>
            <div className="font-mono font-bold text-red-400">
              {pick.current_price != null && pick.stop_loss_multiplier != null
                ? formatUSD(pick.current_price * pick.stop_loss_multiplier, 2)
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">타임</div>
            <div className="font-mono font-bold">{pick.time_stop_days ?? 5}일</div>
          </div>
        </div>
      </div>

      {/* Phase B 주 4-1 · outcome (cherry-pick 방지 · 무조건 표시) */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
        <div className="font-semibold">📊 Outcome (실현 수익률 · 계산 대기 시 —)</div>
        <div className="mt-2 grid grid-cols-4 gap-2 text-center text-xs">
          <PerfBox label="T+1" value={pick.perf_1d} />
          <PerfBox label="T+3" value={pick.perf_3d} />
          <PerfBox label="T+5" value={pick.perf_5d} />
          <div>
            <div className="text-muted-foreground">최고가 이후</div>
            <div className="font-mono font-bold">
              {pick.max_price_after != null ? formatUSD(pick.max_price_after, 4) : "—"}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

function PerfBox({ label, value }: { label: string; value: number | null }) {
  const pct = value !== null && value !== undefined ? value * 100 : null;
  const color =
    pct === null ? "text-muted-foreground/60" : pct > 0 ? "text-green-400" : pct < 0 ? "text-red-400" : "text-muted-foreground";
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className={`font-mono font-bold ${color}`}>
        {pct === null ? "—" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
      </div>
    </div>
  );
}
