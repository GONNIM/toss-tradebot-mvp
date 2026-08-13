"use client";

/**
 * 자동매매 대시보드 — Phase K (Toss API) 활성 후 실 데이터.
 * 2026-08-13 · Fable 5 지시 · 토스 실계좌 섹션 + 저널 대조 컬럼 추가.
 * 인증 필수 (실 계좌 노출 방지 · 401 시 로그인 유도).
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type TossAccountSnapshot, type TossHolding } from "@/lib/api";
import { formatUSD } from "@/lib/utils";

function isAuthError(err: unknown): boolean {
  const s = (err as { status?: number } | null)?.status;
  return s === 401 || s === 403;
}

export default function DashboardPage() {
  const summaryQ = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api.dashboard.summary(),
    retry: false,
  });

  const tossQ = useQuery({
    queryKey: ["dashboard-toss-account"],
    queryFn: () => api.dashboard.tossAccount(),
    refetchInterval: 60_000, // 60s · Fable 5 유지
    retry: false,
  });

  const authRequired = isAuthError(summaryQ.error) || isAuthError(tossQ.error);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">📊 자동매매 대시보드</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          토스증권 실 계좌 · 실시간 잔고·보유종목·저널 대조
        </p>
      </header>

      {authRequired && <AuthGate />}

      {!authRequired && (
        <>
          <TossAccountSection
            data={tossQ.data}
            isLoading={tossQ.isLoading}
            error={tossQ.error}
          />

          {summaryQ.data && <AutoBotSummary data={summaryQ.data} />}
        </>
      )}
    </div>
  );
}

// ─── 로그인 필요 배너 ────────────────────────────────────────────────

function AuthGate() {
  return (
    <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-6">
      <h2 className="text-lg font-semibold text-red-400">🔒 관리자 인증 필요</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        이 대시보드는 실 계좌 잔고와 보유종목을 표시하므로 인증 없이 접근할 수 없습니다.
      </p>
      <div className="mt-4">
        <Link
          href="/admin/settings"
          className="inline-block rounded bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/80"
        >
          로그인 페이지로 이동
        </Link>
      </div>
    </div>
  );
}

// ─── 토스증권 실 계좌 섹션 ────────────────────────────────────────────

function TossAccountSection({
  data,
  isLoading,
  error,
}: {
  data: TossAccountSnapshot | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  if (isLoading && !data) {
    return (
      <section className="rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold">💼 토스증권 계좌 · 로딩...</h2>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="rounded-xl border border-red-500/40 bg-red-500/10 p-6">
        <h2 className="text-lg font-semibold text-red-400">💼 토스증권 · API 호출 실패</h2>
        <p className="mt-2 text-xs text-muted-foreground">
          {String((error as Error | null)?.message ?? "unknown")}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">💼 토스증권 계좌</h2>
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span
            className={
              data.market_open
                ? "rounded bg-emerald-500/20 px-2 py-0.5 font-semibold text-emerald-400"
                : "rounded bg-muted px-2 py-0.5 font-semibold"
            }
          >
            {data.market_open ? "🟢 US 장중 · 실시간" : "⚪ 장 마감 · 가격 기준: 전일 종가"}
          </span>
          <span>60s 자동 갱신 · {new Date(data.fetched_at).toLocaleTimeString("ko-KR")}</span>
        </div>
      </header>

      {/* Fable 5 정직 UX: 실패 시 정직 표시 · 빈 테이블 X */}
      {!data.ok && (
        <div className="mb-4 rounded border border-red-500/40 bg-red-500/10 p-3 text-xs">
          <div className="font-semibold text-red-400">
            🚨 토스 연결 실패 · {data.error_reason ?? "unknown"}
          </div>
          <div className="mt-1 text-muted-foreground">
            {data.last_success_at
              ? `마지막 성공 ${new Date(data.last_success_at).toLocaleString("ko-KR")}`
              : "마지막 성공 기록 없음 (프로세스 재시작 후 첫 요청 가능성)"}
          </div>
        </div>
      )}

      {data.ok && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="총 자산 (USD)"
            value={data.total_value_usd !== null ? formatUSD(data.total_value_usd) : "—"}
          />
          <StatCard
            label="총 매수 비용"
            value={data.total_cost_usd !== null ? formatUSD(data.total_cost_usd) : "—"}
          />
          <StatCard
            label="평가 손익"
            value={data.total_pnl_usd !== null ? formatUSD(data.total_pnl_usd) : "—"}
            accent={
              data.total_pnl_usd !== null
                ? data.total_pnl_usd >= 0
                  ? "positive"
                  : "negative"
                : undefined
            }
          />
          <StatCard
            label="손익률"
            value={data.total_pnl_pct !== null ? `${data.total_pnl_pct.toFixed(2)}%` : "—"}
            accent={
              data.total_pnl_pct !== null
                ? data.total_pnl_pct >= 0
                  ? "positive"
                  : "negative"
                : undefined
            }
          />
        </div>
      )}

      {data.ok && (data.balance_krw !== null || data.balance_usd !== null) && (
        <div className="mt-3 flex flex-wrap gap-4 rounded border border-border/40 bg-background/40 px-3 py-2 text-xs">
          {data.balance_krw !== null && (
            <span>
              KRW 잔고 <span className="font-mono font-bold">₩{Math.round(data.balance_krw).toLocaleString("ko-KR")}</span>
            </span>
          )}
          {data.balance_usd !== null && (
            <span>
              USD 잔고 <span className="font-mono font-bold">{formatUSD(data.balance_usd)}</span>
            </span>
          )}
        </div>
      )}

      {/*
        보유종목 테이블 · 저널 대조 컬럼 포함 (Fable 5 30건 캠페인)
        Fable 5 3차 지적 (2026-08-13): react-query 는 200 + ok=false 를 성공으로 캐시.
        실패 시 이전 성공 데이터 잔상 방지 · data.ok 시에만 렌더 · fetched_at 을 테이블 상단에도 명시.
      */}
      {data.ok && (
        <HoldingsTable
          holdings={data.holdings}
          priceSource={data.price_source}
          fetchedAt={data.fetched_at}
        />
      )}
    </section>
  );
}

function HoldingsTable({
  holdings,
  priceSource,
  fetchedAt,
}: {
  holdings: TossHolding[];
  priceSource: "realtime" | "prior_close";
  fetchedAt: string;
}) {
  if (holdings.length === 0) {
    return (
      <div className="mt-4 rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
        보유종목 없음.
      </div>
    );
  }

  return (
    <div className="mt-4 overflow-x-auto">
      <div className="mb-1 text-[10px] text-muted-foreground">
        📸 가격 스냅샷 · {new Date(fetchedAt).toLocaleString("ko-KR")} ·{" "}
        {priceSource === "prior_close" ? "전일 종가 기준" : "실시간"}
      </div>
      <table className="w-full text-xs">
        <thead className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="pb-2">Ticker</th>
            <th className="pb-2 text-right">Qty</th>
            <th className="pb-2 text-right">Avg</th>
            <th className="pb-2 text-right">Current{priceSource === "prior_close" && " (전일)"}</th>
            <th className="pb-2 text-right">Value</th>
            <th className="pb-2 text-right">P/L</th>
            <th className="pb-2 text-right">%</th>
            <th className="pb-2 text-center">📓</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr key={h.symbol} className="border-b border-border/40 last:border-0">
              <td className="py-2 font-mono font-bold">{h.symbol}</td>
              <td className="py-2 text-right font-mono">
                {h.qty < 1 ? h.qty.toFixed(3) : h.qty.toString()}
              </td>
              <td className="py-2 text-right font-mono text-muted-foreground">
                {formatUSD(h.avg_price)}
              </td>
              <td className="py-2 text-right font-mono">
                {h.current_price !== null ? formatUSD(h.current_price) : "—"}
              </td>
              <td className="py-2 text-right font-mono">
                {h.market_value_usd !== null ? formatUSD(h.market_value_usd) : "—"}
              </td>
              <td
                className={
                  "py-2 text-right font-mono " +
                  (h.unrealized_pnl_usd === null
                    ? "text-muted-foreground"
                    : h.unrealized_pnl_usd >= 0
                      ? "text-emerald-400"
                      : "text-red-400")
                }
              >
                {h.unrealized_pnl_usd !== null ? formatUSD(h.unrealized_pnl_usd) : "—"}
              </td>
              <td
                className={
                  "py-2 text-right font-mono " +
                  (h.unrealized_pnl_pct === null
                    ? "text-muted-foreground"
                    : h.unrealized_pnl_pct >= 0
                      ? "text-emerald-400"
                      : "text-red-400")
                }
              >
                {h.unrealized_pnl_pct !== null ? `${h.unrealized_pnl_pct.toFixed(1)}%` : "—"}
              </td>
              <td className="py-2 text-center">
                {h.journal_recorded ? (
                  <span
                    className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400"
                    title="저널에 판정 기록 있음"
                  >
                    ✓
                  </span>
                ) : (
                  <span
                    className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400"
                    title="저널 판정 미기록 · 실 보유 종목의 근거 없음"
                  >
                    ⚠ 미기록
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-muted-foreground">
        📓 미기록 = 저널 판정 없이 보유 중. Rulebook: 매수 전에 판정 기록.
      </p>
    </div>
  );
}

// ─── 자동매매 봇 요약 (기존 · 유지) ─────────────────────────────────

function AutoBotSummary({ data }: { data: import("@/lib/api").DashboardSummary }) {
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold">🤖 자동매매 봇 (Phase K)</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        1,500만원 시드 · Mode A 단타 · Phase K 활성 후 실 데이터
      </p>
      <dl className="mt-4 space-y-2 text-sm">
        <Row label="엔진 상태" value={data.engine_status} />
        <Row label="보유 종목 수" value={`${data.open_positions} 개`} />
        <Row
          label="마지막 거래"
          value={data.last_trade_at ? new Date(data.last_trade_at).toLocaleString("ko-KR") : "—"}
        />
      </dl>
      {data.engine_status === "not_initialized" && (
        <div className="mt-4 rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3 text-xs">
          <p className="font-semibold text-yellow-400">⚠️ Phase K 미활성</p>
          <p className="mt-1 text-muted-foreground">
            Toss API 자동매매 코어가 시작되면 실 데이터로 채워집니다.
          </p>
        </div>
      )}
    </section>
  );
}

// ─── 공통 부품 ───────────────────────────────────────────────────────

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
      ? "text-emerald-400"
      : accent === "negative"
        ? "text-red-400"
        : "";
  return (
    <div className="rounded-xl border border-border bg-background/30 p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-xl font-bold ${color}`}>{value}</div>
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
