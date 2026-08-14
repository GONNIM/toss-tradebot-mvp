"use client";

/**
 * 보유 작전실 (2026-08-14 · Fable 5).
 * 청산 계획 없이 걸린 사활 = 감정에 넘긴 결정.
 * 각 카드 = 종목당 1장 · 3칸 (가격/사건/시한) · 미기록 시 적색.
 * 트리거 도달 시 카드 border 적색 · Activist 심볼은 배지.
 */
import Link from "next/link";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { api, type PositionCard, type PositionExitPlan } from "@/lib/api";
import type { SessionInfo } from "@/lib/auth";

function isAuthError(err: unknown): boolean {
  const s = (err as { status?: number } | null)?.status;
  return s === 401 || s === 403;
}

function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  if (v > 0) return "text-red-500";
  if (v < 0) return "text-blue-500";
  return "text-muted-foreground";
}

function _krw(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

function _usd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toFixed(digits)}`;
}

function _pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// KRW compact 표기 · US 종목 평가금액 KRW 환산 인라인 병기용
// 1,224,135원 → 122만원 · 8,241,516원 → 824만원 (한 줄 정렬 유지)
function _krwCompact(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 10_000).toFixed(0)}만원`;
  if (abs >= 10_000) return `${(v / 10_000).toFixed(1)}만원`;
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

function _qty(v: number): string {
  return v % 1 === 0 ? String(v) : v.toFixed(3);
}

export default function PositionsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["positions-plan"],
    queryFn: () => api.positions.plan(),
    refetchInterval: 60_000,
    retry: false,
  });
  const authRequired = isAuthError(error);

  const handleSessionChange = (info: SessionInfo) => {
    if (info.role === "admin") {
      queryClient.invalidateQueries({ queryKey: ["positions-plan"] });
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">🎯 보유 작전실</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          청산 계획 없이 걸린 사활 = 감정에 넘긴 결정. 오늘 밤 3줄 (보유 이유 · 청산 조건 · 지금 기분).
        </p>
      </header>

      <AdminSessionBar onSessionChange={handleSessionChange} scope="sniper" />

      {authRequired && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm">
          <span className="font-semibold text-red-500">🔒 인증 필요</span>{" "}
          <span className="text-muted-foreground">· 위 관리자 세션에 토큰 입력</span>
        </div>
      )}

      {!authRequired && isLoading && (
        <div className="text-sm text-muted-foreground">로딩...</div>
      )}

      {!authRequired && data && !data.ok && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs">
          <div className="font-semibold text-red-500">
            🚨 토스 연결 실패 · {data.error_reason ?? "unknown"}
          </div>
        </div>
      )}

      {!authRequired && data && data.ok && (
        <>
          {/* Fable 5 캠페인 카운터 · 미기록 종목 강조 */}
          {data.total_missing_plans > 0 && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <span className="font-semibold text-amber-500">
                ⚠ 청산 계획 미기록 {data.total_missing_plans}종목
              </span>{" "}
              <span className="text-muted-foreground">
                · 오늘 밤 15분 · 3종목 × 3줄 = 이번 주 가능한 유일한 극대화 실행
              </span>
            </div>
          )}

          {data.positions.length === 0 ? (
            <div className="rounded border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              보유 종목 없음
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
              {data.positions.map((p) => (
                <PositionCardView key={p.symbol} card={p} />
              ))}
            </div>
          )}

          <footer className="text-[10px] text-muted-foreground">
            60s 자동 갱신 · {new Date(data.fetched_at).toLocaleTimeString("ko-KR")}
          </footer>
        </>
      )}
    </div>
  );
}

// ─── 종목 카드 ───────────────────────────────────────────────────────

function PositionCardView({ card }: { card: PositionCard }) {
  const { exit_plan: plan } = card;
  const missingPlan = !plan.has_plan;
  const triggerHit = plan.trigger_hit;

  // 카드 border: 트리거 도달 > 미기록 > 정상
  const borderClass = triggerHit
    ? "border-red-500/60 bg-red-500/5"
    : missingPlan
      ? "border-amber-500/40 bg-amber-500/5"
      : "border-border bg-card";

  const fmt = card.currency === "KRW" ? _krw : (v: number | null) => _usd(v, 4);

  return (
    <article className={"rounded-xl border p-4 " + borderClass}>
      <header className="mb-3 border-b border-border/40 pb-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-mono text-lg font-bold">{card.symbol}</span>
          {card.name && (
            <span className="text-sm text-muted-foreground">{card.name}</span>
          )}
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
            {card.currency}
          </span>
          {card.activist_symbol && (
            <span
              className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-purple-400"
              title="Activist Radar universe 소속 · SEC 13D/A 추적"
            >
              🕵️ Activist
            </span>
          )}
          {triggerHit && (
            <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-red-500">
              🚨 트리거 도달 ({plan.trigger_reason})
            </span>
          )}
        </div>
      </header>

      {/* 실황: 수량·평균·현재·손익 */}
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">평균 단가</div>
          <div className="font-mono">{fmt(card.avg_price)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">현재가</div>
          <div className="font-mono font-bold">{fmt(card.current_price)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">수량</div>
          <div className="font-mono">{_qty(card.qty)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">평가금액</div>
          <div className="font-mono">
            {fmt(card.market_value)}
            {card.currency === "USD" && card.market_value_krw !== null && (
              <span className="ml-1 whitespace-nowrap text-[10px] text-muted-foreground">
                ≈{_krw(card.market_value_krw)}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className={"mb-3 rounded bg-background/40 px-2 py-1 text-sm font-semibold " + pnlClass(card.unrealized_pnl)}>
        수익 {card.unrealized_pnl !== null && card.unrealized_pnl > 0 ? "+" : ""}
        {fmt(card.unrealized_pnl)} ({_pct(card.unrealized_pnl_pct)})
      </div>

      {/* 트랑셰 분해 (task #38a · 2026-08-14) */}
      <TrancheBlock card={card} />

      {/* 청산 계획 3칸 (Fable 5 핵심) */}
      <ExitPlanBlock plan={plan} symbol={card.symbol} currency={card.currency} />

      {/* Serenity 최근 signal 인라인 (task #23 · 2026-08-14) */}
      <SerenityBlock
        signals={card.serenity_recent_signals}
        bearishAlert={card.serenity_bearish_alert}
      />
    </article>
  );
}

// ─── 트랑셰 분해 (Fable 5 · 2026-08-14) ────────────────────────────────
// "005930 100주 = 🏛70 core + 🌊30 swing" 표시.
// 트랑셰 (활성 판정) qty 합계 vs 실 토스 보유 수량 정합 검증.

function TrancheBlock({ card }: { card: PositionCard }) {
  if (!card.tranches || card.tranches.length === 0) return null;
  const iconOf: Record<string, string> = { core: "🏛", swing: "🌊", event: "⚡" };
  const parts = card.tranches.map((t) => {
    const icon = iconOf[t.strategy] ?? "?";
    const qtyText = t.qty !== null ? `${t.qty}` : "?";
    return `${icon}${qtyText} ${t.strategy}`;
  });
  return (
    <div className="mt-3 rounded border border-border/40 bg-background/40 p-2 text-[11px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-muted-foreground">🎚 트랑셰 분해</span>
        <span className="font-mono text-[10px] text-muted-foreground">
          실보유 {card.qty} · 판정 합계 {card.qty_sum_declared ?? "?"}
        </span>
      </div>
      <div className="mt-1 font-mono">
        {card.symbol} {card.qty}{card.currency === "KRW" ? "주" : ""} = {parts.join(" + ")}
      </div>
      {card.qty_mismatch && (
        <div className="mt-1 text-[10px] text-amber-500">
          ⚠ 트랑셰 합계 ≠ 실 보유 수량 · 편집으로 정합 맞추기
        </div>
      )}
    </div>
  );
}

function SerenityBlock({
  signals,
  bearishAlert,
}: {
  signals: import("@/lib/api").SerenitySignalPreview[];
  bearishAlert: boolean;
}) {
  if (!signals || signals.length === 0) return null;
  const sentimentColor: Record<string, string> = {
    bullish: "text-emerald-500",
    bearish: "text-red-500",
    neutral: "text-slate-400",
    calibration: "text-amber-500",
  };
  const sentimentIcon: Record<string, string> = {
    bullish: "▲", bearish: "▼", neutral: "●", calibration: "◆",
  };
  return (
    <div className="mt-3 rounded border border-border/40 bg-background/40 p-2 text-[11px]">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-semibold text-muted-foreground">
          🕵️ Serenity 최근 signal ({signals.length})
        </span>
        {bearishAlert && (
          <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-red-500">
            ⚠ bearish 감지
          </span>
        )}
      </div>
      <div className="space-y-1">
        {signals.map((s, i) => (
          <div key={i} className="flex items-baseline gap-2 border-b border-border/20 pb-1 last:border-0">
            <span className={"font-semibold " + (sentimentColor[s.sentiment] ?? "text-muted-foreground")}>
              {sentimentIcon[s.sentiment] ?? "?"} {s.sentiment}
            </span>
            {s.thesis_type && (
              <span className="rounded bg-slate-500/20 px-1 py-0.5 text-[10px] text-slate-400">
                {s.thesis_type}
              </span>
            )}
            <span className="ml-auto text-[10px] text-muted-foreground">
              {new Date(s.ts).toLocaleDateString("ko-KR")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 청산 계획 3칸 ────────────────────────────────────────────────────

function ExitPlanBlock({
  plan,
  symbol,
  currency,
}: {
  plan: PositionExitPlan;
  symbol: string;
  currency: "KRW" | "USD";
}) {
  if (!plan.has_plan) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/5 p-3">
        <div className="text-sm font-semibold text-red-500">⚠ 청산 계획 없음</div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          보유 이유 · 청산 조건 · 지금 기분 3줄. 오늘 밤 15분.
        </p>
        <Link
          href={`/journal?ticker=${symbol}`}
          className="mt-2 inline-block rounded bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/80"
        >
          📓 지금 판정 기록
        </Link>
      </div>
    );
  }

  // 통화별 fmt (2026-08-14 · 국내 60000.0000 → 60,000 요구)
  const fmtPrice = (v: number | null): string => {
    if (v === null) return "—";
    if (currency === "KRW") return _krw(v);
    return _usd(v, v < 100 ? 2 : 2);
  };

  const priceParts: string[] = [];
  if (plan.invalidation_price !== null) priceParts.push(`손절 ${fmtPrice(plan.invalidation_price)}`);
  if (plan.target_price !== null) priceParts.push(`목표 ${fmtPrice(plan.target_price)}`);

  return (
    <div className="space-y-2 rounded bg-background/40 p-2 text-[11px]">
      <div>
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">가격 조건</div>
        <div className="font-mono">
          {priceParts.length > 0 ? priceParts.join(" · ") : <span className="text-muted-foreground">—</span>}
        </div>
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">사건 조건 / thesis</div>
        <div className="whitespace-pre-wrap text-muted-foreground">
          {plan.thesis_full ?? "—"}
        </div>
      </div>
      <div className="flex justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">시한</div>
          <div className="font-mono">
            {plan.deadline
              ? `${new Date(plan.deadline).toLocaleDateString("ko-KR")}${plan.horizon_days ? ` · T+${plan.horizon_days}d` : ""}`
              : "—"}
          </div>
        </div>
        {plan.judgment_id !== null && (
          <Link
            href={`/journal?ticker=${symbol}`}
            className="self-end text-[10px] text-sky-500 hover:underline"
          >
            저널 열기 →
          </Link>
        )}
      </div>
    </div>
  );
}
