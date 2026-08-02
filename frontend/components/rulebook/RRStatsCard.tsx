"use client";

/**
 * R:R 분포 요약 카드 · Phase E · 2026-08-02.
 * 존마 강의 권장 (R:R ≥ 2) 달성률 · 판정 규율 baseline.
 */

import { useEffect, useState } from "react";

type Bucket = { label: string; count: number };
type RRStats = {
  computable_count: number;
  avg_rr_ratio: number | null;
  median_rr_ratio: number | null;
  target_rr_min: number;
  target_hit_count: number;
  target_hit_rate: number | null;
  buckets: Bucket[];
};

export function RRStatsCard() {
  const [stats, setStats] = useState<RRStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/rulebook/rr-stats?days=90", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((j: RRStats) => setStats(j))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const rate = stats?.target_hit_rate;
  const rateOk = rate !== null && rate !== undefined && rate >= 0.5;

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div>
        <h2 className="text-sm font-semibold">📊 R:R 분포 (최근 90일 판정)</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          강의 권장 R:R ≥ 2 달성률 · entry·target·invalidation 모두 입력된 판정만 집계.
        </p>
      </div>

      {loading && <div className="mt-3 text-xs text-muted-foreground">로딩...</div>}
      {error && <div className="mt-3 text-xs text-red-500">에러: {error}</div>}

      {!loading && stats && (
        <>
          <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
            <div className="rounded border border-border bg-muted/20 px-2 py-1.5">
              <div className="text-muted-foreground">계산 가능</div>
              <div className="mt-0.5 text-lg font-bold">
                {stats.computable_count}
              </div>
            </div>
            <div className="rounded border border-border bg-muted/20 px-2 py-1.5">
              <div className="text-muted-foreground">평균 R:R</div>
              <div className="mt-0.5 text-lg font-bold">
                {stats.avg_rr_ratio !== null ? stats.avg_rr_ratio.toFixed(2) : "—"}
              </div>
            </div>
            <div
              className={`rounded border px-2 py-1.5 ${
                rateOk
                  ? "border-emerald-500/40 bg-emerald-500/10"
                  : "border-amber-500/40 bg-amber-500/10"
              }`}
            >
              <div className="text-muted-foreground">
                R:R ≥ {stats.target_rr_min} 비율
              </div>
              <div className="mt-0.5 text-lg font-bold">
                {rate !== null && rate !== undefined
                  ? `${(rate * 100).toFixed(0)}%`
                  : "—"}
              </div>
            </div>
          </div>

          <div className="mt-3 space-y-1">
            {stats.buckets.map((b) => {
              const pct =
                stats.computable_count > 0
                  ? Math.round((b.count / stats.computable_count) * 100)
                  : 0;
              const good = b.label.startsWith("R:R ≥");
              return (
                <div key={b.label}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span>{b.label}</span>
                    <span className="font-mono">
                      {b.count} ({pct}%)
                    </span>
                  </div>
                  <div className="mt-0.5 h-1.5 overflow-hidden rounded bg-muted">
                    <div
                      className={`h-full ${good ? "bg-emerald-500" : "bg-amber-500"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {stats.computable_count === 0 && (
            <p className="mt-2 text-[10px] text-muted-foreground">
              R:R 계산 판정 0건 · JudgmentDialog 저장 시 entry_price·target_price·invalidation_price
              모두 입력하면 여기 집계 시작.
            </p>
          )}
        </>
      )}
    </section>
  );
}
