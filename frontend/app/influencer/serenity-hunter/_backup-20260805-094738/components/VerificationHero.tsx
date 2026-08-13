"use client";

// 검증 Hero 카드 · Serenity 알파 검증 요약
// Fable 5 6차 GO · v6 §2.6 API 계약 · IWM 단독 primary · SPY 참고

import type { VerificationHero } from "@/lib/serenity-hunter/types";

function _fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function _cls(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-500" : "text-red-500";
}

export function VerificationHero({ hero }: { hero: VerificationHero }) {
  const gateOpen = hero.gate_open;
  const deprecated = hero.deprecation_triggered;
  const midWarn = hero.mid_gate_excess_warning;

  let statusBadge: React.ReactNode;
  if (deprecated) {
    statusBadge = (
      <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs font-semibold text-red-500">
        🚨 폐기 발동 · 알파 부재 · 매수 금지
      </span>
    );
  } else if (midWarn) {
    statusBadge = (
      <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs font-semibold text-amber-500">
        ⚠ 중간 경고 · 초과수익 음수 (표본 축적 중)
      </span>
    );
  } else if (!gateOpen) {
    statusBadge = (
      <span className="rounded bg-slate-500/20 px-2 py-0.5 text-xs font-semibold text-slate-400">
        ⏸ 게이트 닫힘 · 데이터 축적 중
      </span>
    );
  } else {
    statusBadge = (
      <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-xs font-semibold text-emerald-500">
        ✓ 게이트 오픈 · 매매 후보 노출
      </span>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">🔬 알파 검증 · Serenity first-mention 사후 성과</h2>
          <p className="mt-1 text-[10px] text-muted-foreground">
            각 티커의 첫 트윗 언급 후 실제 주가 변화율 · IWM 벤치마크 대비 초과수익 판정 ·
            비용 (슬리피지 +1% + 왕복 수수료 1%) 차감.
          </p>
        </div>
        {statusBadge}
      </div>

      {/* 이벤트 수 · 게이트 상태 */}
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricBox label="유효 이벤트" value={`${hero.valid_events} / ${hero.gate_events_needed}+`} />
        <MetricBox label="IWM 벤치마크 rows" value={String(hero.benchmark_rows_iwm)} />
        <MetricBox label="히트율 +10% 3d" value={_fmtPct(hero.hit_rate_10pct_3d, 2)} />
        <MetricBox label="평균 gap next open" value={_fmtPct(hero.avg_gap_next_open_pct, 2)} />
      </div>

      {/* 초과수익 · IWM primary · SPY reference */}
      <div className="mt-4">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
          IWM 대비 초과수익 (v6 판정 기준)
        </div>
        <div className="mt-1 grid grid-cols-3 gap-3">
          <ExcessBox
            label="1d"
            raw={hero.excess_return_primary_raw["1"]}
            adjusted={hero.excess_return_primary_adjusted["1"]}
          />
          <ExcessBox
            label="3d"
            raw={hero.excess_return_primary_raw["3"]}
            adjusted={hero.excess_return_primary_adjusted["3"]}
          />
          <ExcessBox
            label="5d"
            raw={hero.excess_return_primary_raw["5"]}
            adjusted={hero.excess_return_primary_adjusted["5"]}
          />
        </div>
      </div>

      <div className="mt-3">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
          SPY 대비 초과수익 (참고)
        </div>
        <div className="mt-1 grid grid-cols-3 gap-3">
          <ExcessBox
            label="1d"
            raw={hero.excess_return_reference_raw["1"]}
            adjusted={hero.excess_return_reference_adjusted["1"]}
          />
          <ExcessBox
            label="3d"
            raw={hero.excess_return_reference_raw["3"]}
            adjusted={hero.excess_return_reference_adjusted["3"]}
          />
          <ExcessBox
            label="5d"
            raw={hero.excess_return_reference_raw["5"]}
            adjusted={hero.excess_return_reference_adjusted["5"]}
          />
        </div>
      </div>

      {/* raw 평균 수익률 · 참고 */}
      <div className="mt-4 grid grid-cols-5 gap-2 text-xs">
        {(["1", "3", "5", "10", "30"] as const).map((w) => (
          <div key={w} className="rounded border border-border/40 bg-background/40 px-2 py-1">
            <div className="text-[9px] uppercase text-muted-foreground">avg +{w}d (raw)</div>
            <div className={`font-mono font-bold ${_cls(hero.avg_return_by_window[w])}`}>
              {_fmtPct(hero.avg_return_by_window[w])}
            </div>
            <div className="text-[9px] text-muted-foreground">
              IWM {_fmtPct(hero.benchmark_iwm_avg[w])}
            </div>
          </div>
        ))}
      </div>

      {hero.warning_text && (
        <div className="mt-3 rounded border border-slate-500/40 bg-slate-500/10 px-3 py-2 text-xs text-muted-foreground">
          {hero.warning_text}
        </div>
      )}

      {hero.gate_close_reasons.length > 0 && (
        <div className="mt-3 text-[10px] text-muted-foreground">
          게이트 닫힘 사유: {hero.gate_close_reasons.join(" · ")}
        </div>
      )}
    </section>
  );
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border/40 bg-background/40 px-2 py-2">
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}

function ExcessBox({
  label,
  raw,
  adjusted,
}: {
  label: string;
  raw: number | null | undefined;
  adjusted: number | null | undefined;
}) {
  return (
    <div className="rounded border border-border/40 bg-background/40 px-2 py-2">
      <div className="text-[9px] uppercase text-muted-foreground">+{label}</div>
      <div className={`text-sm font-mono font-bold ${_cls(raw)}`}>
        raw {_fmtPct(raw, 2)}
      </div>
      <div className={`text-xs font-mono ${_cls(adjusted)}`}>
        adj {_fmtPct(adjusted, 2)}
      </div>
    </div>
  );
}
