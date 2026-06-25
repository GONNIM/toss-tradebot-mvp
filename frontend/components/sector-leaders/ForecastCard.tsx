"use client";

/**
 * 미래 주가 예측 카드 — v4 종합 판정 (2026-06-25).
 *
 * 사용자 중심 재설계:
 *   ① VerdictBanner — 🟢🟡🔴 결론 한 줄 + 컨텍스트 + 액션 힌트
 *   ② PositionBar — 약세 P10 ━ 현재 ━ 점추정 ━ 강세 P90 가로 막대 한눈에
 *   ③ KPI 3카드 — 기대 수익률 · R/R · 신호 강도
 *   ④ 가격대별 의미 — 4 가격 + 자연어 한 줄씩
 *   ⑤ Stop / Take Profit 권장가
 *   ⑥ Fan Chart (보조)
 *   ⑦ 해석 가이드
 *   ⑧ 전문가 모드 (회귀계수·OOS·disclaimer)
 */
import { useMemo, useState } from "react";

import type {
  ForecastDisclaimer as TForecastDisclaimer,
  HistoricalBand,
  HorizonAdvice,
  HorizonForecast,
  OOSMetrics,
  TickerForecast,
  Verdict,
} from "@/lib/api";
import { formatPct } from "@/lib/utils";

// ─── 유틸 ──────────────────────────────────────────────

function formatKRWPrice(amount: number): string {
  return amount.toLocaleString("ko-KR") + "원";
}

function formatKRWDelta(amount: number): string {
  const sign = amount >= 0 ? "+" : "";
  return sign + amount.toLocaleString("ko-KR") + "원";
}

// ─── 메인 ─────────────────────────────────────────────

export function ForecastCard({ data }: { data: TickerForecast }) {
  const [hIdx, setHIdx] = useState(() => {
    const best = data.leader.best_lag_months ?? 0;
    let idx = 0;
    let minDiff = Infinity;
    data.horizons.forEach((h, i) => {
      const diff = Math.abs(h.horizon_months - best);
      if (diff < minDiff) {
        minDiff = diff;
        idx = i;
      }
    });
    return idx;
  });
  const selected = data.horizons[hIdx];
  const advice = data.advice_by_horizon[hIdx];
  const band = data.historical_bands.find(
    (b) => b.horizon_months === selected?.horizon_months,
  );
  const targetMonth =
    data.fan_chart.find((f) => f.month_offset === selected?.horizon_months)
      ?.target_month ?? "—";
  const sign = data.correlation_sign;
  const cp = data.latest_close_krw;

  return (
    <div className="rounded-xl border border-purple-500/30 bg-card p-4 space-y-4">
      <Header data={data} />

      {sign < 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          ⚠️ 이 종목은 <strong>음의 상관 종목</strong>입니다 — 수출이 늘면 주가가
          오히려 부진하는 경향. 시그널 방향은 회귀가 이미 반영했으나 해석에 주의.
        </div>
      )}

      {/* Horizon 토글 */}
      <div className="flex gap-2">
        {data.horizons.map((h, i) => {
          const active = i === hIdx;
          return (
            <button
              key={h.horizon_months}
              onClick={() => setHIdx(i)}
              className={`rounded-lg border px-3 py-1.5 text-sm transition ${
                active
                  ? "border-purple-500/60 bg-purple-500/10 text-purple-300"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {h.horizon_months}개월 후
            </button>
          );
        })}
      </div>

      {advice && <VerdictBanner v={advice.verdict} targetMonth={targetMonth} />}

      {selected && cp !== null && band && (
        <PositionBar
          currentPrice={cp}
          pointPct={selected.point_estimate_pct}
          band={band}
        />
      )}

      {advice && selected && (
        <KpiCards
          horizon={selected}
          advice={advice}
          currentPrice={cp}
        />
      )}

      {selected && cp !== null && band && (
        <PriceTagsBox
          horizon={selected}
          band={band}
          currentPrice={cp}
          targetMonth={targetMonth}
          advice={advice}
        />
      )}

      {advice?.stop_take && cp !== null && (
        <StopTakeBox st={advice.stop_take} currentPrice={cp} />
      )}

      {cp !== null && (
        <PriceFanChart
          points={data.fan_chart}
          bands={data.historical_bands}
          currentPrice={cp}
        />
      )}

      <InterpretationGuide
        verdict={advice?.verdict}
        oosHit={data.oos_metrics?.hit_rate ?? null}
      />

      <ExpertMode
        horizon={selected}
        oos={data.oos_metrics}
        disclaimer={data.disclaimer}
      />
    </div>
  );
}

// ─── 헤더 ─────────────────────────────────────────────

function Header({ data }: { data: TickerForecast }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h4 className="text-base font-semibold">
          🔮 {data.leader.name} 주가 예측
        </h4>
        {data.latest_close_krw !== null && (
          <span className="text-sm">
            <span className="text-muted-foreground">현재가</span>{" "}
            <span className="font-mono font-semibold">
              {formatKRWPrice(data.latest_close_krw)}
            </span>{" "}
            {data.latest_close_date && (
              <span className="text-xs text-muted-foreground">
                ({data.latest_close_date} 종가)
              </span>
            )}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">
        입력 시그널: {data.latest_data_month} {data.leader.item} 수출 YoY{" "}
        <span
          className={
            data.latest_input_yoy >= 0 ? "text-emerald-400" : "text-rose-400"
          }
        >
          {formatPct(data.latest_input_yoy, 1)}
        </span>
      </p>
    </div>
  );
}

// ─── ① VerdictBanner ─────────────────────────────────

function VerdictBanner({
  v,
  targetMonth,
}: {
  v: Verdict;
  targetMonth: string;
}) {
  const colorMap = {
    green:
      "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
    amber: "border-amber-500/50 bg-amber-500/10 text-amber-200",
    red: "border-rose-500/50 bg-rose-500/10 text-rose-300",
  } as const;
  const iconMap = { green: "🟢", amber: "🟡", red: "🔴" } as const;
  return (
    <div className={`rounded-lg border ${colorMap[v.color]} p-3`}>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <span className="text-base font-bold">
          {iconMap[v.color]} {v.label}
        </span>
        <span className="text-xs opacity-80">
          {targetMonth} 시점 종합 판정
        </span>
      </div>
      <p className="text-sm mt-1 opacity-95">{v.context}</p>
      <div className="text-xs mt-2 font-semibold">
        👉 액션 힌트: {v.action_hint}
      </div>
    </div>
  );
}

// ─── ② PositionBar — 가로 막대 시각화 ─────────────────

function PositionBar({
  currentPrice,
  pointPct,
  band,
}: {
  currentPrice: number;
  pointPct: number;
  band: HistoricalBand;
}) {
  const p10Price = currentPrice * (1 + band.p10_pct / 100);
  const p90Price = currentPrice * (1 + band.p90_pct / 100);
  const pointPrice = currentPrice * (1 + pointPct / 100);

  // 막대 범위 = min(p10, point) ~ max(p90, point) — 점추정이 밖이면 함께 포함
  const lo = Math.min(p10Price, pointPrice) * 0.95;
  const hi = Math.max(p90Price, pointPrice) * 1.05;
  const range = hi - lo;

  const xCurrent = ((currentPrice - lo) / range) * 100;
  const xPoint = ((pointPrice - lo) / range) * 100;
  const xP10 = ((p10Price - lo) / range) * 100;
  const xP90 = ((p90Price - lo) / range) * 100;

  return (
    <div className="rounded-lg border border-border bg-background p-4 space-y-2">
      <div className="text-sm font-semibold">📊 가격 위치 시각화</div>

      <div className="relative h-16">
        {/* 막대 배경 */}
        <div className="absolute top-7 left-0 right-0 h-2 rounded-full bg-gradient-to-r from-rose-500/30 via-zinc-500/30 to-emerald-500/30" />

        {/* P10 마커 */}
        <Marker x={xP10} color="rose" label={`P10\n${formatPct(band.p10_pct, 1)}`} priceLabel={formatKRWPrice(Math.round(p10Price))} position="bottom" />

        {/* 현재가 */}
        <Marker x={xCurrent} color="cyan" label="현재" priceLabel={formatKRWPrice(currentPrice)} position="top" highlight />

        {/* 점추정 */}
        <Marker x={xPoint} color="purple" label={`점추정\n${formatPct(pointPct, 1)}`} priceLabel={formatKRWPrice(Math.round(pointPrice))} position="bottom" highlight />

        {/* P90 마커 */}
        <Marker x={xP90} color="emerald" label={`P90\n${formatPct(band.p90_pct, 1)}`} priceLabel={formatKRWPrice(Math.round(p90Price))} position="top" />
      </div>

      <div className="text-xs text-muted-foreground pt-1 border-t border-border">
        ━━ 막대 색: 좌(약세 영역) ━ 중(중립) ━ 우(강세 영역) · ● 마커 = 가격대
      </div>
    </div>
  );
}

function Marker({
  x,
  color,
  label,
  priceLabel,
  position,
  highlight,
}: {
  x: number;
  color: "rose" | "cyan" | "purple" | "emerald";
  label: string;
  priceLabel: string;
  position: "top" | "bottom";
  highlight?: boolean;
}) {
  const xClamped = Math.max(0, Math.min(100, x));
  const colorMap = {
    rose: "bg-rose-500",
    cyan: "bg-cyan-400",
    purple: "bg-purple-500",
    emerald: "bg-emerald-500",
  };
  const textColor = {
    rose: "text-rose-400",
    cyan: "text-cyan-300",
    purple: "text-purple-300",
    emerald: "text-emerald-400",
  };
  return (
    <div
      className="absolute"
      style={{ left: `${xClamped}%`, transform: "translateX(-50%)" }}
    >
      {position === "top" && (
        <div className={`absolute -translate-x-1/2 left-1/2 text-center whitespace-pre text-[10px] ${textColor[color]} ${highlight ? "font-bold" : ""}`} style={{ top: "-2px" }}>
          {label}
          <br />
          <span className="font-mono">{priceLabel}</span>
        </div>
      )}
      <div
        className={`absolute top-7 ${colorMap[color]} ${highlight ? "h-3 w-3 -mt-0.5" : "h-2 w-2"} rounded-full border-2 border-background`}
        style={{ left: "-50%" }}
      />
      {position === "bottom" && (
        <div className={`absolute -translate-x-1/2 left-1/2 text-center whitespace-pre text-[10px] ${textColor[color]} ${highlight ? "font-bold" : ""}`} style={{ top: "36px" }}>
          {label}
          <br />
          <span className="font-mono">{priceLabel}</span>
        </div>
      )}
    </div>
  );
}

// ─── ③ KPI 3카드 ──────────────────────────────────────

function KpiCards({
  horizon,
  advice,
  currentPrice,
}: {
  horizon: HorizonForecast;
  advice: HorizonAdvice;
  currentPrice: number | null;
}) {
  const rr = advice.risk_reward;
  const expectedDelta = currentPrice !== null
    ? Math.round(currentPrice * horizon.point_estimate_pct / 100)
    : null;

  let strengthStars = "★";
  let strengthLabel = "약함";
  let strengthTone = "text-rose-400";
  if (horizon.r_squared >= 0.3) {
    strengthStars = "★★★";
    strengthLabel = "강함";
    strengthTone = "text-emerald-400";
  } else if (horizon.r_squared >= 0.1) {
    strengthStars = "★★";
    strengthLabel = "중간";
    strengthTone = "text-cyan-400";
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <KpiCell
        label="기대 수익률"
        primary={formatPct(horizon.point_estimate_pct, 1)}
        secondary={
          expectedDelta !== null ? formatKRWDelta(expectedDelta) : "—"
        }
        tone={
          horizon.point_estimate_pct > 0
            ? "text-emerald-400"
            : "text-rose-400"
        }
      />
      <KpiCell
        label="수익 / 리스크"
        primary={rr ? `${rr.ratio.toFixed(1)} : 1` : "—"}
        secondary={rr ? rr.grade_label : "산출 불가"}
        tone={
          rr?.grade === "excellent" || rr?.grade === "good"
            ? "text-emerald-400"
            : rr?.grade === "too_high"
              ? "text-amber-400"
              : "text-muted-foreground"
        }
      />
      <KpiCell
        label="신호 강도"
        primary={`${strengthStars} ${strengthLabel}`}
        secondary={`R² ${horizon.r_squared.toFixed(2)} · 적중 ${(horizon.hit_rate * 100).toFixed(0)}%`}
        tone={strengthTone}
      />
    </div>
  );
}

function KpiCell({
  label,
  primary,
  secondary,
  tone,
}: {
  label: string;
  primary: string;
  secondary: string;
  tone: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-xl font-bold font-mono mt-0.5 ${tone}`}>
        {primary}
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">{secondary}</div>
    </div>
  );
}

// ─── ④ 가격대별 의미 ─────────────────────────────────

function PriceTagsBox({
  horizon,
  band,
  currentPrice,
  targetMonth,
  advice,
}: {
  horizon: HorizonForecast;
  band: HistoricalBand;
  currentPrice: number;
  targetMonth: string;
  advice: HorizonAdvice | undefined;
}) {
  const p10Price = currentPrice * (1 + band.p10_pct / 100);
  const p90Price = currentPrice * (1 + band.p90_pct / 100);
  const pointPrice = currentPrice * (1 + horizon.point_estimate_pct / 100);

  const isOutlierHigh = horizon.point_estimate_pct > band.p90_pct;
  const isOutlierLow = horizon.point_estimate_pct < band.p10_pct;

  const rows: { icon: string; label: string; price: number; meaning: string; tone: string }[] = [
    {
      icon: "📈",
      label: `${targetMonth} 강세 상단 (24M P90)`,
      price: p90Price,
      meaning: "이 가격대 도달 시 — 24개월 중 상위 10% 강세 시나리오",
      tone: "text-emerald-400",
    },
    {
      icon: "📊",
      label: `${targetMonth} 점추정 (수출 시그널 기반)`,
      price: pointPrice,
      meaning: isOutlierHigh
        ? "⬆️ 통계적 이례 — 시그널이 강세 범위 초과 (외삽)"
        : isOutlierLow
          ? "⬇️ 통계적 이례 — 시그널이 약세 범위 미달 (외삽)"
          : "가장 가능성이 높은 가격대 — 수출 데이터가 가리키는 방향",
      tone: "text-cyan-400",
    },
    {
      icon: "━━",
      label: "현재가",
      price: currentPrice,
      meaning: "지금 시점 (의사결정 기준점)",
      tone: "text-muted-foreground",
    },
    {
      icon: "📉",
      label: `${targetMonth} 약세 하단 (24M P10)`,
      price: p10Price,
      meaning: "이 가격대 도달 시 — 24개월 중 하위 10% 약세 시나리오, 손절 검토",
      tone: "text-rose-400",
    },
  ];

  // 가격 내림차순 정렬
  rows.sort((a, b) => b.price - a.price);

  return (
    <div className="rounded-lg border border-border bg-background p-4 space-y-2">
      <div className="text-sm font-semibold">💰 가격대별 의미</div>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div
            key={i}
            className="flex items-baseline justify-between gap-3 py-1 border-b border-border/40 last:border-0"
          >
            <div className="flex items-baseline gap-2 min-w-0">
              <span>{r.icon}</span>
              <span className={`font-mono font-semibold ${r.tone} shrink-0`}>
                {formatKRWPrice(Math.round(r.price))}
              </span>
              <span className="text-xs text-muted-foreground truncate">
                {r.label}
              </span>
            </div>
            <span className="text-xs text-muted-foreground text-right max-w-[50%]">
              {r.meaning}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── ⑤ Stop / Take Profit ─────────────────────────────

function StopTakeBox({
  st,
  currentPrice,
}: {
  st: NonNullable<HorizonAdvice["stop_take"]>;
  currentPrice: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-4 space-y-2">
      <div className="text-sm font-semibold">
        🎯 권장 손절가 · 익절가{" "}
        <span className="text-xs text-muted-foreground font-normal">
          (보조 신호 — 절대 기준 아님)
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3">
          <div className="text-xs text-rose-300/80 mb-0.5">📉 Stop Loss (손절가)</div>
          <div className="text-lg font-bold font-mono text-rose-400">
            {formatKRWPrice(Math.round(st.stop_price))}
          </div>
          <div className="text-xs text-muted-foreground">
            현재가 대비 {formatPct(st.stop_pct, 1)} · {formatKRWDelta(Math.round(st.stop_price - currentPrice))}
          </div>
          <div className="text-xs text-rose-300/70 mt-1.5">{st.stop_basis}</div>
        </div>
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
          <div className="text-xs text-emerald-300/80 mb-0.5">📈 Take Profit (익절가)</div>
          <div className="text-lg font-bold font-mono text-emerald-400">
            {formatKRWPrice(Math.round(st.take_price))}
          </div>
          <div className="text-xs text-muted-foreground">
            현재가 대비 {formatPct(st.take_pct, 1)} · {formatKRWDelta(Math.round(st.take_price - currentPrice))}
          </div>
          <div className="text-xs text-emerald-300/70 mt-1.5">{st.take_basis}</div>
        </div>
      </div>
    </div>
  );
}

// ─── ⑥ Fan Chart (그대로 유지) ────────────────────────

function PriceFanChart({
  points,
  bands,
  currentPrice,
}: {
  points: TickerForecast["fan_chart"];
  bands: HistoricalBand[];
  currentPrice: number;
}) {
  const series = useMemo(() => {
    const bandByH = new Map(bands.map((b) => [b.horizon_months, b]));
    const base = [{ label: "현재", price: currentPrice, lo: currentPrice, hi: currentPrice }];
    const future = points.map((p) => {
      const b = bandByH.get(p.month_offset);
      const lo = b
        ? currentPrice * (1 + b.p10_pct / 100)
        : currentPrice * (1 + p.point_estimate_pct / 100);
      const hi = b
        ? currentPrice * (1 + b.p90_pct / 100)
        : currentPrice * (1 + p.point_estimate_pct / 100);
      return {
        label: p.target_month.slice(2),
        price: Math.max(0, currentPrice * (1 + p.point_estimate_pct / 100)),
        lo: Math.max(0, lo),
        hi: Math.max(0, hi),
      };
    });
    return [...base, ...future];
  }, [points, bands, currentPrice]);

  const all = series.flatMap((s) => [s.lo, s.hi, s.price]);
  const minY = Math.min(...all);
  const maxY = Math.max(...all);
  const range = Math.max(maxY - minY, 1);
  const W = 360;
  const H = 110;
  const pad = 6;
  const sx = (i: number) => pad + (i / Math.max(series.length - 1, 1)) * (W - 2 * pad);
  const sy = (v: number) => H - pad - ((v - minY) / range) * (H - 2 * pad);

  const upperPath = series.map((s, i) => `${sx(i)},${sy(s.hi)}`).join(" ");
  const lowerPath = series
    .slice()
    .reverse()
    .map((s, i) => `${sx(series.length - 1 - i)},${sy(s.lo)}`)
    .join(" ");
  const polygonPoints = `${upperPath} ${lowerPath}`;
  const linePoints = series.map((s, i) => `${sx(i)},${sy(s.price)}`).join(" ");

  return (
    <div className="rounded-lg border border-border bg-background p-3 space-y-1">
      <div className="flex items-baseline justify-between flex-wrap gap-1">
        <span className="text-sm font-semibold">📈 향후 {points.length}개월 가격 경로</span>
        <span className="text-xs text-muted-foreground">
          ━━ 점추정 ▒ 24M 실측 P10~P90 범위
        </span>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line
          x1={pad}
          x2={W - pad}
          y1={sy(currentPrice)}
          y2={sy(currentPrice)}
          stroke="hsl(var(--muted-foreground))"
          strokeOpacity={0.4}
          strokeDasharray="2 3"
        />
        <line
          x1={sx(0)}
          x2={sx(0)}
          y1={pad}
          y2={H - pad}
          stroke="#a855f7"
          strokeOpacity={0.5}
          strokeDasharray="3 3"
        />
        <polygon points={polygonPoints} fill="#a855f7" fillOpacity={0.18} />
        <polyline
          points={linePoints}
          fill="none"
          stroke="#a855f7"
          strokeWidth={2}
          strokeDasharray="4 2"
        />
        {series.map((s, i) => (
          <circle
            key={i}
            cx={sx(i)}
            cy={sy(s.price)}
            r={i === 0 ? 4 : 2.5}
            fill={i === 0 ? "#06b6d4" : "#a855f7"}
          />
        ))}
      </svg>
      <div className="text-xs text-muted-foreground flex justify-between font-mono">
        <span>{formatKRWPrice(Math.round(minY))}</span>
        <span className="text-cyan-400">● 현재 {formatKRWPrice(currentPrice)}</span>
        <span>{formatKRWPrice(Math.round(maxY))}</span>
      </div>
    </div>
  );
}

// ─── ⑦ 해석 가이드 ───────────────────────────────────

function InterpretationGuide({
  verdict,
  oosHit,
}: {
  verdict: Verdict | undefined;
  oosHit: number | null;
}) {
  if (!verdict) return null;
  const points: string[] = [
    "**기대 수익률**은 산업통상부 수출 데이터로만 추정한 회귀 점추정입니다.",
    "**P10/P90**은 본 종목이 지난 24개월 동안 실제로 보였던 변동 범위입니다.",
    "**점추정이 P10~P90 사이**에 있으면 ‘합리적 시그널’, 벗어나면 ‘통계적 이례’입니다.",
    "**수익/리스크 비율(R/R)**은 (점추정 가격 - 현재가) / (현재가 - 약세 가격). 1.5 이상이면 양호.",
    "**Stop/Take Profit**은 약세 P10/점추정 80%에 기반한 보조 신호 — 절대 기준 아님.",
  ];
  if (oosHit !== null && oosHit < 0.5) {
    points.push(
      `**OOS 부호 적중 ${(oosHit * 100).toFixed(0)}%** — 본 모델 단독 매수/매도 결정은 위험합니다.`,
    );
  }
  return (
    <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 text-xs space-y-1">
      <div className="font-semibold text-cyan-300 mb-1">💡 어떻게 읽어야 하나요?</div>
      <ul className="list-disc list-inside space-y-1 text-cyan-100/80">
        {points.map((p, i) => (
          <li key={i} dangerouslySetInnerHTML={{ __html: p.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>") }} />
        ))}
      </ul>
    </div>
  );
}

// ─── ⑧ 전문가 모드 ───────────────────────────────────

function ExpertMode({
  horizon,
  oos,
  disclaimer,
}: {
  horizon: HorizonForecast | undefined;
  oos: OOSMetrics | null;
  disclaimer: TForecastDisclaimer;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-background overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-muted/20 transition"
        aria-expanded={open}
      >
        <span className="text-xs font-semibold text-muted-foreground">
          ▾ 전문가 모드 — 회귀식·OOS 검증·디스클레이머 전문
        </span>
        <span className="text-xs text-muted-foreground">
          {open ? "▴ 접기" : "▾ 펼치기"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-2 border-t border-border space-y-3 text-xs">
          {horizon && (
            <div className="space-y-1">
              <div className="font-semibold">회귀식 (단변량 OLS)</div>
              <div className="font-mono text-foreground">
                월수익률(t+{horizon.horizon_months}M) ={" "}
                {horizon.alpha >= 0 ? "+" : ""}
                {horizon.alpha.toFixed(3)} +{" "}
                {horizon.beta >= 0 ? "+" : ""}
                {horizon.beta.toFixed(3)} × 수출YoY(t)
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
                <Kv k="n (표본)" v={`${horizon.n_samples}M`} />
                <Kv k="R²" v={horizon.r_squared.toFixed(3)} />
                <Kv k="p-value (z)" v={horizon.p_value_approx.toFixed(3)} />
                <Kv k="RMSE" v={horizon.rmse.toFixed(2)} />
              </div>
            </div>
          )}
          {oos && (
            <div className="space-y-1 pt-2 border-t border-border">
              <div className="font-semibold">OOS 검증 (70/30 split)</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
                <Kv k="train" v={`${oos.train_n}M`} />
                <Kv k="test" v={`${oos.test_n}M`} />
                <Kv k="MAE" v={`${oos.mae.toFixed(2)}%`} />
                <Kv k="부호 적중" v={`${(oos.hit_rate * 100).toFixed(0)}%`} />
              </div>
            </div>
          )}
          <div className="pt-2 border-t border-border space-y-1 text-amber-200/80">
            <div className="font-semibold">⚠️ 모델 한계</div>
            <div className="font-mono text-amber-200/60">
              {disclaimer.method} · {disclaimer.ci_method} ·{" "}
              {disclaimer.sample_window}
            </div>
            <ul className="list-disc list-inside space-y-0.5">
              {disclaimer.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-muted-foreground">{k}</div>
      <div className="text-foreground">{v}</div>
    </div>
  );
}
