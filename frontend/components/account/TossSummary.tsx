"use client";

/**
 * 토스 계좌 요약 (옛 /dashboard · 2026-08-13 Fable 5 → 1022-10 2단계 2026-10-29 /account 로 합침).
 * 총자산 · 주문 가능 · 내 투자 · 국내/미국 소계. 종목 표는 /account 보유 표 하나로 합쳐 여기서 뺐다.
 * 색상: 이익 red · 손실 blue (한국 관례). 원장 = 토스 API · 이 화면 = 사본 (broker-api-source-of-truth).
 */
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TossAccountSnapshot } from "@/lib/api";

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

/** 「토스증권」 칸의 요약 · 로그인 전에는 안내만 · 60초 다시 읽기 (옛 /dashboard 와 같음). */
export function TossSummary({ isAdmin }: { isAdmin: boolean }) {
  const q = useQuery({
    queryKey: ["account", "toss"],
    queryFn: () => api.dashboard.tossAccount(),
    enabled: isAdmin,
    refetchInterval: 60_000,
    retry: false,
  });
  if (!isAdmin) {
    return <p className="text-sm text-muted-foreground">로그인하면 이 사이트가 읽은 토스 실계좌 요약이 보입니다.</p>;
  }
  return <TossAccountView data={q.data} isLoading={q.isLoading} error={q.error} />;
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

          {/* 층 3 · 국내 / 해외 소계 (종목은 아래 보유 표) */}
          <div className="space-y-1 rounded-lg border border-border bg-card/60 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">국내주식 {data.kr_holdings.length}종목</span>
              <SectionSubtotal subtotal={data.kr_market_value} pnl={data.kr_pnl} pnlPct={data.kr_pnl_pct} />
            </div>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">
                해외주식 {data.us_holdings.length}종목
                {data.price_source === "prior_close" && (
                  <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">전일 종가</span>
                )}
              </span>
              <SectionSubtotal subtotal={data.us_market_value_krw} pnl={data.us_pnl_krw} pnlPct={data.us_pnl_pct} />
            </div>
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
              {/* 1029-01 · 고정 1330 → 이 응답의 토스 참고 환율 (없으면 환산 안 함) */}
              {data.cash_usd !== null && data.fx_rate != null && (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  (≈{_krw(data.cash_usd * data.fx_rate)} · 환율 {data.fx_rate.toLocaleString("ko-KR")}원 추정)
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

// ─── 섹션 소계 · 컬럼 정렬 (2026-08-13 · KR/US 일치감 통일) ────────────
// tabular-nums (숫자 등폭) + inline-block + min-w + text-right 로
// 자릿수·부호 차이가 있어도 두 섹션이 동일 컬럼 정렬 유지.

function SectionSubtotal({
  subtotal,
  pnl,
  pnlPct,
}: {
  subtotal: number | null;
  pnl: number | null;
  pnlPct: number | null;
}) {
  return (
    <div className="flex items-baseline gap-3 text-sm tabular-nums">
      <span className="inline-block min-w-[7rem] text-right font-bold">
        {_krw(subtotal)}
      </span>
      <span className={"inline-block min-w-[7rem] text-right " + pnlClass(pnl)}>
        {pnl !== null ? (pnl > 0 ? "+" : "") + _krw(pnl) : "—"}
      </span>
      <span className={"inline-block min-w-[5rem] text-right text-xs " + pnlClass(pnlPct)}>
        {pnlPct !== null ? `(${_pct(pnlPct)})` : ""}
      </span>
    </div>
  );
}
