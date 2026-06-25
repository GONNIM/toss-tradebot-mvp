"use client";

/**
 * Sector Leader 분석 패널 (B-2f).
 *
 * 5개 구성:
 *   (a) 메인 차트 — 24M 종가 + 수출 YoY 오버레이 + ReferenceArea 음영
 *   (b) 통계 카드 — r₀ / best_r@lag / 신뢰도 배지
 *   (c) 백테스트 — 수출 YoY 4 구간 × 평균/누적 수익률 (lag=0 + best_lag 둘 다)
 *   (d) 월별 정합 표 — 수출·주가·시그널 컬러
 *   (e) 최근 시그널 카드 — 직전 발표 + lag 기반 윈도우
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  api,
  type BacktestBucket,
  type JoinSignal,
  type LatestSignalHint,
  type MonthlyJoinRow,
  type TickerAnalysis,
} from "@/lib/api";
import {
  confidenceBadgeClass,
  confidenceStars,
  formatKRW,
  formatPct,
  lagDescription,
} from "@/lib/utils";
import { ForecastCard } from "@/components/sector-leaders/ForecastCard";

export function AnalysisPanel({
  ticker,
  item,
}: {
  ticker: string;
  item: string;
}) {
  const analysisQ = useQuery({
    queryKey: ["sector-leaders", "analysis", ticker, item],
    queryFn: () => api.sectorLeaders.tickerAnalysis(ticker, item),
  });
  const forecastQ = useQuery({
    queryKey: ["sector-leaders", "forecast", ticker, item],
    queryFn: () => api.sectorLeaders.tickerForecast(ticker, item),
  });
  if (analysisQ.isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-muted-foreground">
        분석 데이터 로딩 중...
      </div>
    );
  }
  if (analysisQ.error || !analysisQ.data) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
        분석 데이터 호출 실패 ({ticker})
      </div>
    );
  }
  return (
    <PanelBody
      data={analysisQ.data}
      forecast={forecastQ.data ?? null}
      forecastLoading={forecastQ.isLoading}
      forecastError={!!forecastQ.error}
    />
  );
}

function PanelBody({
  data,
  forecast,
  forecastLoading,
  forecastError,
}: {
  data: TickerAnalysis;
  forecast: import("@/lib/api").TickerForecast | null;
  forecastLoading: boolean;
  forecastError: boolean;
}) {
  return (
    <div className="space-y-4">
      {/* 종목 헤더 카드 — 5요소 위 (어느 종목인지 표시) */}
      <div className="rounded-xl border border-cyan-500/30 bg-card p-4">
        <PanelHeader data={data} />
      </div>

      {/* (1) 미래 주가 예측 — 사용자 결정 2026-06-25 최상단 이동 */}
      {forecastLoading && (
        <div className="rounded-xl border border-border bg-card p-4 text-muted-foreground text-sm">
          미래 예측 데이터 로딩 중...
        </div>
      )}
      {forecastError && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          미래 예측 호출 실패
        </div>
      )}
      {forecast && <ForecastCard data={forecast} />}

      {/* (2) 월별 정합표 (디폴트 펼침) */}
      <MonthlyJoinTable rows={data.monthly_join} />

      {/* (3) 메인 차트 */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <AnalysisChart data={data} />
        <p className="text-xs text-muted-foreground">
          *녹색 음영 = 수출 YoY ≥ +30% 호조 구간 · 적색 음영 = YoY &lt; 0% 부진
          구간 · 좌축 = 월말 종가(원) · 우축 = 수출 YoY(%)
        </p>
      </div>

      {/* (4) 통계 카드 */}
      <StatsCards data={data} />

      {/* (5) 최근 시그널 */}
      <LatestSignalCard hint={data.latest_signal} sign={data.correlation_sign} />

      {/* (6) 백테스트 2종 */}
      <BacktestTable
        title="백테스트 — 동시 시점 (lag=0)"
        buckets={data.backtest_lag0}
        correlationSign={data.correlation_sign}
      />
      <BacktestTable
        title={`백테스트 — best_lag = ${
          data.leader.best_lag_months ?? 0
        }M ${lagDescription(data.leader.best_lag_months)}`}
        buckets={data.backtest_best_lag}
        correlationSign={data.correlation_sign}
      />
    </div>
  );
}

// ─── 헤더 ────────────────────────────────────────────────

function PanelHeader({ data }: { data: TickerAnalysis }) {
  const l = data.leader;
  return (
    <div className="flex items-baseline justify-between gap-3 flex-wrap">
      <div>
        <h3 className="text-lg font-bold">
          📊 {l.name}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            ({l.ticker}) · {l.item} rank #{l.rank}
          </span>
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          시총 {formatKRW(l.market_cap_krw)}원 · 수출비중*{" "}
          {l.export_ratio_hint !== null
            ? `${(l.export_ratio_hint * 100).toFixed(0)}%`
            : "—"}{" "}
          · 표본 {l.sample_n ?? 0}M{" "}
          {data.correlation_sign < 0 && (
            <span className="text-amber-400">· ⚠️ 음의 상관 (수출↑ 시 주가↓)</span>
          )}
        </p>
      </div>
      <span
        className={`text-xs ${confidenceBadgeClass(
          l.confidence,
        )} rounded-full border px-2 py-0.5`}
      >
        {confidenceStars(l.confidence)} {l.confidence}
      </span>
    </div>
  );
}

// ─── (a) 메인 차트 ────────────────────────────────────────

function AnalysisChart({ data }: { data: TickerAnalysis }) {
  const merged = useMemo(() => {
    const yoyMap: Record<string, number> = {};
    const valMap: Record<string, number> = {};
    for (const e of data.export_series) {
      if (e.yoy_pct !== null) yoyMap[e.month] = e.yoy_pct;
      valMap[e.month] = e.value_musd;
    }
    return data.monthly_close
      .map((p) => ({
        month: p.date,
        close: p.close,
        yoy: yoyMap[p.date] ?? null,
      }))
      .sort((a, b) => (a.month < b.month ? -1 : 1));
  }, [data]);

  // ReferenceArea 구간 산출 (연속된 동일 regime 묶음)
  const shadeRegions = useMemo(() => {
    const out: { from: string; to: string; kind: "green" | "red" }[] = [];
    let currentKind: "green" | "red" | null = null;
    let start: string | null = null;
    for (const r of merged) {
      let k: "green" | "red" | null = null;
      if (r.yoy !== null && r.yoy >= 30) k = "green";
      else if (r.yoy !== null && r.yoy < 0) k = "red";
      if (k !== currentKind) {
        if (currentKind && start) {
          const lastMonth = merged[merged.indexOf(r) - 1]?.month;
          if (lastMonth) {
            out.push({ from: start, to: lastMonth, kind: currentKind });
          }
        }
        currentKind = k;
        start = r.month;
      }
    }
    if (currentKind && start) {
      out.push({
        from: start,
        to: merged[merged.length - 1].month,
        kind: currentKind,
      });
    }
    return out;
  }, [merged]);

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={merged}
          margin={{ top: 5, right: 20, bottom: 5, left: 10 }}
        >
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
          {shadeRegions.map((r, i) => (
            <ReferenceArea
              key={i}
              x1={r.from}
              x2={r.to}
              yAxisId="close"
              strokeOpacity={0}
              fill={r.kind === "green" ? "#10b981" : "#ef4444"}
              fillOpacity={0.08}
            />
          ))}
          <XAxis
            dataKey="month"
            stroke="hsl(var(--muted-foreground))"
            fontSize={10}
            tickFormatter={(v) => v.slice(2)}
          />
          <YAxis
            yAxisId="close"
            orientation="left"
            stroke="hsl(var(--muted-foreground))"
            fontSize={10}
            tickFormatter={(v) => `${(v / 10000).toFixed(0)}만`}
          />
          <YAxis
            yAxisId="yoy"
            orientation="right"
            stroke="hsl(var(--muted-foreground))"
            fontSize={10}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              fontSize: "12px",
            }}
            formatter={(value: number | string, name: string) => {
              if (name === "월말 종가") return [`${Number(value).toLocaleString()}원`, name];
              if (name === "수출 YoY") return [`${Number(value).toFixed(1)}%`, name];
              return [value, name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: "12px" }} />
          <Line
            yAxisId="close"
            type="monotone"
            dataKey="close"
            name="월말 종가"
            stroke="#06b6d4"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="yoy"
            type="monotone"
            dataKey="yoy"
            name="수출 YoY"
            stroke="#f97316"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── (b) 통계 카드 ────────────────────────────────────────

function StatsCards({ data }: { data: TickerAnalysis }) {
  const l = data.leader;
  return (
    <div className="grid grid-cols-3 gap-3">
      <StatCell
        label="r₀ (동시 시점)"
        value={l.pearson_r0 !== null ? formatR(l.pearson_r0) : "—"}
      />
      <StatCell
        label={`best_r @ lag=${l.best_lag_months}M`}
        value={l.best_r !== null ? formatR(l.best_r) : "—"}
        sub={lagDescription(l.best_lag_months)}
      />
      <StatCell
        label="신뢰도 (24M 표본)"
        value={confidenceStars(l.confidence)}
        sub={l.confidence}
      />
    </div>
  );
}

function StatCell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-bold font-mono">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function formatR(r: number): string {
  return `${r >= 0 ? "+" : ""}${r.toFixed(3)}`;
}

// ─── (c) 백테스트 표 ─────────────────────────────────────

function BacktestTable({
  title,
  buckets,
  correlationSign,
}: {
  title: string;
  buckets: BacktestBucket[];
  correlationSign: number;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h4 className="text-sm font-semibold mb-2">{title}</h4>
      <p className="text-xs text-muted-foreground mb-3">
        {correlationSign >= 0
          ? "수출 호조 시 주가 상승 기대 (정방향)"
          : "음의 상관 — 수출 호조 시 주가 부진 기대 (역방향)"}
      </p>
      <table className="w-full text-xs">
        <thead className="text-muted-foreground border-b border-border">
          <tr className="text-left">
            <th className="py-1.5 pr-2">수출 YoY 구간</th>
            <th className="py-1.5 px-2 text-right">표본 개월</th>
            <th className="py-1.5 px-2 text-right">평균 월 수익률</th>
            <th className="py-1.5 pl-2 text-right">누적 수익률</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => {
            const upBias = correlationSign >= 0 ? b.mean_return_pct > 0 : b.mean_return_pct < 0;
            const meanClass =
              b.n_months === 0
                ? "text-muted-foreground"
                : upBias && Math.abs(b.mean_return_pct) > 1
                  ? "text-emerald-400"
                  : !upBias && Math.abs(b.mean_return_pct) > 1
                    ? "text-rose-400"
                    : "text-foreground";
            return (
              <tr key={b.label} className="border-b border-border/40">
                <td className="py-1.5 pr-2 font-medium">{b.label}</td>
                <td className="py-1.5 px-2 text-right font-mono">{b.n_months}</td>
                <td className={`py-1.5 px-2 text-right font-mono ${meanClass}`}>
                  {b.n_months === 0 ? "—" : formatPct(b.mean_return_pct, 2)}
                </td>
                <td className={`py-1.5 pl-2 text-right font-mono ${meanClass}`}>
                  {b.n_months === 0 ? "—" : formatPct(b.cumulative_return_pct, 1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── (d) 월별 정합 표 ─────────────────────────────────────

function MonthlyJoinTable({ rows }: { rows: MonthlyJoinRow[] }) {
  const [open, setOpen] = useState(true); // 디폴트 펼침 (사용자 결정 2026-06-25)
  const [sortDesc, setSortDesc] = useState(true);
  const sorted = useMemo(
    () => [...rows].sort((a, b) => (sortDesc ? b.month.localeCompare(a.month) : a.month.localeCompare(b.month))),
    [rows, sortDesc],
  );
  const filledCount = rows.filter(
    (r) => r.export_yoy_pct !== null && r.return_pct !== null,
  ).length;
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/20 transition"
        aria-expanded={open}
      >
        <div className="flex items-baseline gap-2 flex-wrap">
          <h4 className="text-sm font-semibold">📋 월별 정합표</h4>
          <span className="text-xs text-muted-foreground">
            {rows.length}개월 · 수출 + 주가 + 시그널 ({filledCount}개월 동행성 평가 가능)
          </span>
        </div>
        <span className="text-xs text-muted-foreground shrink-0">
          {open ? "▴ 접기" : "▾ 펼치기"}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-2 border-t border-border">
          <div className="flex items-center justify-end pt-2">
            <button
              onClick={() => setSortDesc((v) => !v)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              {sortDesc ? "↓ 최신순" : "↑ 오래된순"}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground border-b border-border">
                <tr className="text-left">
                  <th className="py-1.5 pr-2">월</th>
                  <th className="py-1.5 px-2 text-right">수출(M$)</th>
                  <th className="py-1.5 px-2 text-right">수출 YoY</th>
                  <th className="py-1.5 px-2 text-right">월말 종가</th>
                  <th className="py-1.5 px-2 text-right">월 수익률</th>
                  <th className="py-1.5 pl-2">시그널</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.month} className="border-b border-border/40">
                    <td className="py-1 pr-2 font-mono">{r.month}</td>
                    <td className="py-1 px-2 text-right font-mono">
                      {r.export_value_musd !== null
                        ? r.export_value_musd.toLocaleString()
                        : "—"}
                    </td>
                    <td
                      className={`py-1 px-2 text-right font-mono ${yoyClass(r.export_yoy_pct)}`}
                    >
                      {r.export_yoy_pct !== null ? formatPct(r.export_yoy_pct, 1) : "—"}
                    </td>
                    <td className="py-1 px-2 text-right font-mono">
                      {r.price_close !== null
                        ? r.price_close.toLocaleString()
                        : "—"}
                    </td>
                    <td className={`py-1 px-2 text-right font-mono ${retClass(r.return_pct)}`}>
                      {r.return_pct !== null ? formatPct(r.return_pct, 2) : "—"}
                    </td>
                    <td className="py-1 pl-2">{signalBadge(r.signal)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function yoyClass(yoy: number | null): string {
  if (yoy === null) return "text-muted-foreground";
  if (yoy >= 30) return "text-emerald-400";
  if (yoy > 0) return "text-emerald-300";
  if (yoy >= -10) return "text-muted-foreground";
  return "text-rose-400";
}

function retClass(r: number | null): string {
  if (r === null) return "text-muted-foreground";
  if (r > 1) return "text-emerald-400";
  if (r < -1) return "text-rose-400";
  return "text-muted-foreground";
}

function signalBadge(sig: JoinSignal): React.ReactNode {
  const map: Record<JoinSignal, { label: string; cls: string }> = {
    agree_up: { label: "🟢 동행↑", cls: "text-emerald-400" },
    agree_down: { label: "🔴 동행↓", cls: "text-rose-400" },
    disagree: { label: "⚪ 엇박자", cls: "text-amber-400" },
    neutral: { label: "— 횡보", cls: "text-muted-foreground" },
    no_data: { label: "—", cls: "text-muted-foreground" },
  };
  const v = map[sig];
  return <span className={`text-xs ${v.cls}`}>{v.label}</span>;
}

// ─── (e) 최근 시그널 ───────────────────────────────────────

function LatestSignalCard({
  hint,
  sign,
}: {
  hint: LatestSignalHint | null;
  sign: number;
}) {
  if (!hint) return null;
  const regimeText: Record<string, string> = {
    strong_growth: "강한 상승 시그널",
    mild_growth: "완만한 상승 시그널",
    flat: "횡보 시그널",
    decline: "하락 시그널",
    inverse: "역방향 시그널 (수출↑ 시 주가↓)",
    low_signal: "신호 약함",
  };
  const arrow = hint.direction === "up" ? "📈" : "📉";
  return (
    <div className="rounded-xl border border-cyan-500/40 bg-cyan-500/5 p-4">
      <div className="flex items-baseline justify-between gap-2 mb-2 flex-wrap">
        <h4 className="text-sm font-semibold">
          📍 최근 시그널 ({hint.month} 발표)
        </h4>
        <span className="text-xs text-muted-foreground">
          based_on_lag = {hint.based_on_lag}M
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">수출 YoY</div>
          <div className="text-xl font-bold font-mono">
            {hint.export_yoy_pct !== null
              ? formatPct(hint.export_yoy_pct, 1)
              : "—"}{" "}
            <span className="text-xs text-muted-foreground">{hint.bucket_label}</span>
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">예상 영향 윈도우</div>
          <div className="text-sm font-mono mt-1">{hint.expected_window}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">평가</div>
          <div className="text-sm mt-1">
            {arrow} {regimeText[hint.regime] ?? hint.regime}
          </div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-3">
        ⚠️ 본 추정은 24개월 표본의 통계적 패턴에 기반 ·{" "}
        {sign < 0 && "음의 상관 종목으로 방향 반전 적용 · "}
        투자 권유 아님
      </p>
    </div>
  );
}
