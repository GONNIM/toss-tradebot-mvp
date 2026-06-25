"use client";

/**
 * Confluence 카드 (B-2i-a) — 4종 시그널 통합 강도 시각화.
 *
 * 단변량 회귀의 R² 한계를 다중 시그널 일치로 보강.
 * 시그널: 수출 YoY · 지역 일관성 · 종목 3M 모멘텀 · 잠정→확정 갱신.
 */
import type { Confluence, SignalContribution } from "@/lib/api";

export function ConfluenceCard({ data }: { data: Confluence }) {
  const colorMap = {
    green: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
    amber: "border-amber-500/50 bg-amber-500/10 text-amber-200",
    red: "border-rose-500/50 bg-rose-500/10 text-rose-300",
  } as const;
  const iconMap = { green: "🟢", amber: "🟡", red: "🔴" } as const;

  return (
    <div className="rounded-xl border border-fuchsia-500/30 bg-card p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h4 className="text-base font-semibold">🔬 Confluence — 다중 시그널 통합</h4>
        <span className="text-xs text-muted-foreground">
          {data.agreement_count}/{data.total_signals} 시그널 {data.direction === "bullish" ? "강세" : data.direction === "bearish" ? "약세" : "혼재"} 동의
        </span>
      </div>

      {/* 종합 결론 + 게이지 */}
      <div className={`rounded-lg border ${colorMap[data.grade_color]} p-3 space-y-2`}>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <span className="text-base font-bold">
            {iconMap[data.grade_color]} {data.grade_label}
          </span>
          <span className="font-mono text-xl font-bold">
            {data.score >= 0 ? "+" : ""}
            {data.score.toFixed(2)}{" "}
            <span className="text-xs opacity-70">/ ±1.0</span>
          </span>
        </div>

        {/* 가로 게이지 — score 위치 시각화 */}
        <ScoreGauge score={data.score} color={data.grade_color} />

        <p className="text-sm opacity-95">{data.interpretation}</p>
      </div>

      {/* 시그널별 기여도 */}
      <div className="rounded-lg border border-border bg-background p-3 space-y-2">
        <div className="text-sm font-semibold mb-1">시그널별 기여도</div>
        <div className="space-y-2">
          {data.contributions.map((s) => (
            <SignalRow key={s.name} s={s} />
          ))}
        </div>
        <p className="text-xs text-muted-foreground pt-2 border-t border-border">
          * 각 시그널은 -1 ~ +1 로 정규화 후 가중치 곱해 합산. 4종 모두 동의(±0.7+) 시 강한 시그널.
        </p>
      </div>

      <div className="text-xs text-muted-foreground">
        💡 단변량 회귀(수출 YoY 1개)의 R² 한계를 4종 독립 시그널 일치로 보강.
        모든 시그널 일치 시 신뢰도 대폭 증가.
      </div>
    </div>
  );
}

// ─── ScoreGauge ────────────────────────────────────────

function ScoreGauge({
  score,
  color,
}: {
  score: number;
  color: "green" | "amber" | "red";
}) {
  // -1 ~ +1 → 0 ~ 100% (50%가 중립)
  const x = ((score + 1) / 2) * 100;
  const colorFill = {
    green: "#10b981",
    amber: "#f59e0b",
    red: "#f43f5e",
  }[color];

  return (
    <div className="relative h-6">
      {/* 배경 그라데이션: 빨강 ━ 회색 ━ 초록 */}
      <div className="absolute inset-x-0 top-2 h-2 rounded-full bg-gradient-to-r from-rose-500/40 via-zinc-500/30 to-emerald-500/40" />
      {/* 0 (중앙) 표시 */}
      <div className="absolute top-1 h-4 w-px bg-zinc-400/60" style={{ left: "50%" }} />
      {/* score 마커 */}
      <div
        className="absolute top-1 h-4 w-4 rounded-full border-2 border-background -translate-x-1/2"
        style={{ left: `${x}%`, backgroundColor: colorFill }}
      />
      <div
        className="absolute top-5 text-[10px] font-mono -translate-x-1/2 opacity-70"
        style={{ left: `${x}%`, color: colorFill }}
      >
        {score >= 0 ? "+" : ""}
        {score.toFixed(2)}
      </div>
    </div>
  );
}

// ─── SignalRow ─────────────────────────────────────────

function SignalRow({ s }: { s: SignalContribution }) {
  const dirColor =
    s.direction === "bullish"
      ? "text-emerald-400"
      : s.direction === "bearish"
        ? "text-rose-400"
        : "text-muted-foreground";
  const flag =
    s.direction === "bullish" ? "✓" : s.direction === "bearish" ? "✗" : "─";
  // 기여도 막대: contribution 의 절대값 / weight = normalized 절대값 (0~1)
  const fillPct = Math.abs(s.normalized) * 100;
  const fillColor =
    s.direction === "bullish"
      ? "bg-emerald-500/70"
      : s.direction === "bearish"
        ? "bg-rose-500/70"
        : "bg-zinc-500/40";
  const isRtl = s.normalized < 0;

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold flex items-center gap-1.5">
          <span className={dirColor}>{flag}</span>
          {s.label}
        </span>
        <span className="font-mono">
          {s.raw_label} · 가중 {s.weight.toFixed(2)} ={" "}
          <span className={dirColor}>
            {s.contribution >= 0 ? "+" : ""}
            {s.contribution.toFixed(3)}
          </span>
        </span>
      </div>
      {/* 막대 — 중앙 기준 좌(약세) / 우(강세) */}
      <div className="relative h-2 rounded-full bg-zinc-700/30">
        <div className="absolute top-0 bottom-0 w-px bg-zinc-400/60" style={{ left: "50%" }} />
        <div
          className={`absolute top-0 bottom-0 ${fillColor} rounded-full`}
          style={{
            left: isRtl ? `${50 - fillPct / 2}%` : "50%",
            width: `${fillPct / 2}%`,
          }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{s.detail}</p>
    </div>
  );
}
