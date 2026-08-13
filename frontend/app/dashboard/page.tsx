"use client";

/**
 * 대시보드 · 토스 '내 계좌' 미러링 (2026-08-13 · Fable 5).
 * 정보 배치·위계는 복제 · 디자인 자산은 자체 (상표·저작권 방어).
 * 색상: 이익 red · 손실 blue (한국 관례).
 * 원장 = 토스 API · 대시보드 = 사본 (broker-api-source-of-truth).
 */
import { useState, type ReactNode } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { api, type TossAccountSnapshot, type TossHolding } from "@/lib/api";
import type { SessionInfo } from "@/lib/auth";

function isAuthError(err: unknown): boolean {
  const s = (err as { status?: number } | null)?.status;
  return s === 401 || s === 403;
}

// 한국 관례: 이익 red · 손실 blue
function pnlClass(v: number | null): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  if (v > 0) return "text-red-500";
  if (v < 0) return "text-blue-500";
  return "text-muted-foreground";
}

function _krw(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

function _pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function _usd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toFixed(digits)}`;
}

function _qty(v: number): string {
  return v % 1 === 0 ? String(v) : v.toFixed(3);
}

export default function DashboardPage() {
  const queryClient = useQueryClient();

  const tossQ = useQuery({
    queryKey: ["dashboard-toss-account"],
    queryFn: () => api.dashboard.tossAccount(),
    refetchInterval: 60_000,
    retry: false,
  });

  const authRequired = isAuthError(tossQ.error);

  const handleSessionChange = (info: SessionInfo) => {
    if (info.role === "admin") {
      queryClient.invalidateQueries({ queryKey: ["dashboard-toss-account"] });
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">📊 내 계좌</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          토스증권 · 실시간 · 원본 = 토스 앱 · 대시보드는 사본
        </p>
      </header>

      <AdminSessionBar onSessionChange={handleSessionChange} scope="sniper" />

      {authRequired && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm">
          <span className="font-semibold text-red-500">🔒 인증 필요</span>{" "}
          <span className="text-muted-foreground">
            · 위 관리자 세션에 SNIPER_API_TOKEN 입력 후 자동 갱신됩니다.
          </span>
        </div>
      )}

      {!authRequired && (
        <TossAccountView
          data={tossQ.data}
          isLoading={tossQ.isLoading}
          error={tossQ.error}
        />
      )}
    </div>
  );
}

// ─── 토스 '내 계좌' 미러링 ────────────────────────────────────────────

function TossAccountView({
  data,
  isLoading,
  error,
}: {
  data: TossAccountSnapshot | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  if (isLoading && !data) {
    return <div className="text-muted-foreground text-sm">로딩...</div>;
  }
  if (!data) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-sm">
        <div className="font-semibold text-red-500">API 호출 실패</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {String((error as Error | null)?.message ?? "unknown")}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Fable 5 정직 UX · 실패 시 배너만 · 데이터 잔상 방지 */}
      {!data.ok && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs">
          <div className="font-semibold text-red-500">
            🚨 토스 연결 실패 · {data.error_reason ?? "unknown"}
          </div>
          <div className="mt-1 text-muted-foreground">
            {data.last_success_at
              ? `마지막 성공 ${new Date(data.last_success_at).toLocaleString("ko-KR")}`
              : "마지막 성공 기록 없음"}
          </div>
        </div>
      )}

      {data.ok && (
        <>
          {/* 회계 항등식 위반 배지 (Fable 5 ±1원 · 근사 X) */}
          {(!data.identity_asset_ok || !data.identity_investment_ok) && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
              <div className="font-semibold text-amber-500">⚠ 회계 항등식 위반</div>
              {!data.identity_asset_ok && (
                <div className="mt-1 font-mono text-muted-foreground">
                  주문가능 + 내투자 ≠ 총자산 · 차액 {_krw(data.identity_asset_diff)}
                </div>
              )}
              {!data.identity_investment_ok && (
                <div className="mt-1 font-mono text-muted-foreground">
                  국내 + 해외 ≠ 내투자 · 차액 {_krw(data.identity_investment_diff)}
                </div>
              )}
              <div className="mt-1 text-[10px] text-muted-foreground">
                → 원본 응답 로그 확인 필요 (API 필드 miss or 환율 계산 miss)
              </div>
            </div>
          )}

          {/* 층 1 · 총 자산 (배지 부착 금지 · Fable 5) */}
          <TotalAssetHeader data={data} />

          {/* 층 2 · 주문 가능 + 내 투자 나란히 */}
          <div className="grid gap-4 lg:grid-cols-2">
            <OrderAvailableCard data={data} />
            <InvestmentCard data={data} />
          </div>

          {/* 층 3 · 국내 + 해외 (내 투자 하위 · 시각 종속 · 좌측 들여쓰기) */}
          <div className="ml-4 space-y-4 border-l-2 border-border/40 pl-4">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
              내 투자 · 종목 상세
            </div>
            <KrSection holdings={data.kr_holdings} subtotal={data.kr_market_value} pnl={data.kr_pnl} pnlPct={data.kr_pnl_pct} />
            <UsSection holdings={data.us_holdings} subtotalKrw={data.us_market_value_krw} pnlKrw={data.us_pnl_krw} pnlPct={data.us_pnl_pct} priceSource={data.price_source} />
          </div>

          <footer className="mt-2 text-[10px] text-muted-foreground">
            <span
              className={
                data.market_open
                  ? "rounded bg-emerald-500/20 px-2 py-0.5 font-semibold text-emerald-500"
                  : "rounded bg-muted px-2 py-0.5 font-semibold"
              }
            >
              {data.market_open ? "🟢 US 장중 · 실시간" : "⚪ US 장 마감 · 전일 종가"}
            </span>
            <span className="ml-3">
              60s 자동 갱신 · {new Date(data.fetched_at).toLocaleTimeString("ko-KR")}
            </span>
          </footer>
        </>
      )}
    </div>
  );
}

// ─── 접힘 가능 카드 공통 헤더 ────────────────────────────────────────

function CardHeader({
  label,
  amount,
  open,
  onToggle,
  extra,
}: {
  label: ReactNode;
  amount: string;
  open: boolean;
  onToggle: () => void;
  extra?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between text-left"
    >
      <span className="flex-1">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1 flex flex-wrap items-baseline gap-2">
          <span className="text-xl font-bold">{amount}</span>
          {extra}
        </div>
      </span>
      <span className="ml-2 text-xs text-muted-foreground">{open ? "▲" : "▼"}</span>
    </button>
  );
}

// ─── 층 1 · 총 자산 헤더 (배지 부착 금지 · 접힘 default) ──────────────

function TotalAssetHeader({ data }: { data: TossAccountSnapshot }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <CardHeader
        label="총 자산"
        amount={_krw(data.total_asset_krw)}
        open={open}
        onToggle={() => setOpen(!open)}
      />
      {open && (
        <div className="mt-3 border-t border-border/40 pt-3 text-[10px] text-muted-foreground">
          = 주문 가능 + 내 투자 · 총자산에는 수익률을 붙이지 않습니다 (수익률은 아래 '내 투자' 참조)
        </div>
      )}
    </section>
  );
}

// ─── 층 2A · 주문 가능 (손익 없음 · 접힘 default) ─────────────────────

function OrderAvailableCard({ data }: { data: TossAccountSnapshot }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <CardHeader
        label="💰 주문 가능"
        amount={_krw(data.order_available_krw)}
        open={open}
        onToggle={() => setOpen(!open)}
      />
      {open && (
        <div className="mt-3 grid gap-2 border-t border-border/40 pt-3 text-xs sm:grid-cols-2">
          <div>
            <div className="text-muted-foreground">원화</div>
            <div className="font-mono font-bold">{_krw(data.cash_krw)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">달러</div>
            <div className="font-mono font-bold">
              {_usd(data.cash_usd)}
              {data.cash_usd !== null && (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  (≈{_krw((data.cash_usd ?? 0) * 1330)})
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ─── 층 2B · 내 투자 (손익 배지 · 접힘 default) ───────────────────────

function InvestmentCard({ data }: { data: TossAccountSnapshot }) {
  const [open, setOpen] = useState(false);
  const pnl = data.investment_pnl_krw;
  const pct = data.investment_pnl_pct;
  const cost = data.investment_cost_krw;
  // 헤더 우측에 항상 손익 배지 노출 (접힘 시에도 보이도록 · 요구 위계)
  const badge =
    pnl !== null ? (
      <>
        <span className={"text-sm font-semibold " + pnlClass(pnl)}>
          {pnl > 0 ? "+" : ""}{_krw(pnl)}
        </span>
        <span
          className={"text-xs " + pnlClass(pct)}
          title={cost !== null ? `투자 원금 ${_krw(cost)} 기준 (총자산 아님)` : undefined}
        >
          ({_pct(pct)})
        </span>
        {data.investment_pnl_source === "computed" && (
          <span
            className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="API 원본 없음 · KR+US 자체 합산 · 오차 가능"
          >
            computed
          </span>
        )}
      </>
    ) : null;
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <CardHeader
        label="📈 내 투자"
        amount={_krw(data.investment_market_value_krw)}
        open={open}
        onToggle={() => setOpen(!open)}
        extra={badge}
      />
      {open && cost !== null && (
        <div className="mt-3 border-t border-border/40 pt-3 text-[10px] text-muted-foreground">
          투자 원금 {_krw(cost)} · 수익률은 원금 대비 (총자산 아님)
        </div>
      )}
    </section>
  );
}

// ─── 층 3A · 국내주식 (내 투자 하위) ──────────────────────────────────

function KrSection({
  holdings,
  subtotal,
  pnl,
  pnlPct,
}: {
  holdings: TossHolding[];
  subtotal: number | null;
  pnl: number | null;
  pnlPct: number | null;
}) {
  return (
    <section className="rounded-lg border border-border bg-card/60 p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2 border-b border-border/40 pb-2">
        <h2 className="text-sm font-semibold">🇰🇷 국내주식</h2>
        <div className="text-sm">
          <span className="font-bold">{_krw(subtotal)}</span>
          {pnl !== null && (
            <span className={"ml-2 " + pnlClass(pnl)}>
              {pnl > 0 ? "+" : ""}{_krw(pnl)} ({_pct(pnlPct)})
            </span>
          )}
        </div>
      </header>
      {holdings.length === 0 ? (
        <div className="text-xs text-muted-foreground">보유 없음</div>
      ) : (
        <HoldingsTable holdings={holdings} />
      )}
    </section>
  );
}

// ─── 층 3B · 해외주식 (내 투자 하위) ──────────────────────────────────

function UsSection({
  holdings,
  subtotalKrw,
  pnlKrw,
  pnlPct,
  priceSource,
}: {
  holdings: TossHolding[];
  subtotalKrw: number | null;
  pnlKrw: number | null;
  pnlPct: number | null;
  priceSource: "realtime" | "prior_close";
}) {
  return (
    <section className="rounded-lg border border-border bg-card/60 p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2 border-b border-border/40 pb-2">
        <h2 className="text-sm font-semibold">
          🇺🇸 해외주식
          {priceSource === "prior_close" && (
            <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              전일 종가
            </span>
          )}
        </h2>
        <div className="text-sm">
          <span className="font-bold">{_krw(subtotalKrw)}</span>
          {pnlKrw !== null && (
            <span className={"ml-2 " + pnlClass(pnlKrw)}>
              {pnlKrw > 0 ? "+" : ""}{_krw(pnlKrw)} ({_pct(pnlPct)})
            </span>
          )}
        </div>
      </header>
      {holdings.length === 0 ? (
        <div className="text-xs text-muted-foreground">보유 없음</div>
      ) : (
        <HoldingsTable holdings={holdings} />
      )}
    </section>
  );
}

// ─── 공통 보유종목 테이블 (통화 자동 감지) ────────────────────────────

function HoldingsTable({ holdings }: { holdings: TossHolding[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed text-xs">
        {/* KR/US 섹션 컬럼 너비 통일 (요구: 2026-08-13) */}
        <colgroup>
          <col className="w-[18%]" />   {/* 종목 */}
          <col className="w-[9%]" />    {/* 수량 */}
          <col className="w-[13%]" />   {/* 평균단가 */}
          <col className="w-[13%]" />   {/* 현재가 */}
          <col className="w-[16%]" />   {/* 평가금액 (KRW 환산 2줄 감안) */}
          <col className="w-[13%]" />   {/* 손익 */}
          <col className="w-[9%]" />    {/* % */}
          <col className="w-[9%]" />    {/* 📓 */}
        </colgroup>
        <thead className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="pb-2">종목</th>
            <th className="pb-2 text-right">수량</th>
            <th className="pb-2 text-right">평균단가</th>
            <th className="pb-2 text-right">현재가</th>
            <th className="pb-2 text-right">평가금액</th>
            <th className="pb-2 text-right">손익</th>
            <th className="pb-2 text-right">%</th>
            <th className="pb-2 text-center">📓</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => {
            const fmt = h.currency === "KRW" ? _krw : (v: number | null) => _usd(v, 2);
            return (
              <tr key={h.symbol} className="border-b border-border/40 last:border-0">
                <td className="py-2 pr-2">
                  <div className="truncate font-bold" title={h.name || h.symbol}>
                    {h.name || h.symbol}
                  </div>
                  {h.name && (
                    <div className="truncate text-[10px] font-mono text-muted-foreground">
                      {h.symbol}
                    </div>
                  )}
                </td>
                <td className="py-2 text-right font-mono">{_qty(h.qty)}</td>
                <td className="py-2 text-right font-mono text-muted-foreground">{fmt(h.avg_price)}</td>
                <td className="py-2 text-right font-mono">{fmt(h.current_price)}</td>
                <td className="py-2 text-right font-mono">
                  <div>{fmt(h.market_value)}</div>
                  {h.currency === "USD" && h.market_value_krw !== null && (
                    <div className="text-[10px] text-muted-foreground">≈{_krw(h.market_value_krw)}</div>
                  )}
                </td>
                <td className={"py-2 text-right font-mono " + pnlClass(h.unrealized_pnl)}>
                  {h.unrealized_pnl !== null
                    ? `${h.unrealized_pnl > 0 ? "+" : ""}${fmt(h.unrealized_pnl)}`
                    : "—"}
                </td>
                <td className={"py-2 text-right font-mono " + pnlClass(h.unrealized_pnl_pct)}>
                  {_pct(h.unrealized_pnl_pct)}
                </td>
                <td className="py-2 text-center">
                  {h.journal_recorded ? (
                    <span
                      className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-500"
                      title="저널 판정 기록 있음"
                    >
                      ✓
                    </span>
                  ) : (
                    <span
                      className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-500"
                      title="저널 판정 미기록 · 30건 캠페인 대상"
                    >
                      ⚠ 미기록
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
