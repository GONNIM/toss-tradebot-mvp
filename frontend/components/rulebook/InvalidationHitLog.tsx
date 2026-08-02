"use client";

/**
 * 물타기 감지 로그 · Phase E · 2026-08-02.
 *
 * 존마 강의 원칙 3 · 물타기 절대 금지.
 * invalidation_hit_ts != NULL 판정만 조회 · 이탈 후 outcome 결과 병치.
 */

import { useEffect, useState } from "react";

type Hit = {
  id: number;
  ts: string;
  ticker: string;
  page_source: string;
  hypothesis_id: string;
  invalidation_price: number | null;
  invalidation_hit_ts: string | null;
  invalidation_hit_low: number | null;
  result_at_horizon: number | null;
  horizon_days: number;
};

export function InvalidationHitLog() {
  const [items, setItems] = useState<Hit[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/rulebook/invalidation-hits?days=90&limit=50", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((j: Hit[]) => setItems(j))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">🚨 물타기 감지 로그 (최근 90일)</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            invalidation 이탈 후에도 보유·미청산 판정. 존마 원칙 3 위반 여부 자기 감사.
          </p>
        </div>
      </div>

      {loading && <div className="mt-3 text-xs text-muted-foreground">로딩...</div>}
      {error && <div className="mt-3 text-xs text-red-500">에러: {error}</div>}

      {!loading && !error && items !== null && items.length === 0 && (
        <div className="mt-3 rounded-lg border border-dashed border-emerald-500/40 bg-emerald-500/5 p-4 text-center text-xs text-emerald-500">
          ✅ 최근 90일 물타기 감지 판정 없음. 원칙 3 준수 중.
        </div>
      )}

      {!loading && items && items.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-1.5">판정</th>
                <th className="py-1.5">티커</th>
                <th className="py-1.5">source</th>
                <th className="py-1.5 text-right">invalidation</th>
                <th className="py-1.5 text-right">이탈 저가</th>
                <th className="py-1.5">이탈 시각</th>
                <th className="py-1.5 text-right">T+{"N"} outcome</th>
              </tr>
            </thead>
            <tbody>
              {items.map((h) => (
                <tr key={h.id} className="border-b border-border/40">
                  <td className="py-1.5 font-mono">#{h.id}</td>
                  <td className="py-1.5 font-mono font-bold">{h.ticker}</td>
                  <td className="py-1.5 text-[10px] text-muted-foreground">{h.page_source}</td>
                  <td className="py-1.5 text-right font-mono">
                    {h.invalidation_price?.toLocaleString() ?? "—"}
                  </td>
                  <td className="py-1.5 text-right font-mono text-red-500">
                    {h.invalidation_hit_low?.toLocaleString() ?? "—"}
                  </td>
                  <td className="py-1.5 text-[10px] text-muted-foreground">
                    {h.invalidation_hit_ts
                      ? new Date(h.invalidation_hit_ts).toLocaleString("ko-KR")
                      : "—"}
                  </td>
                  <td
                    className={`py-1.5 text-right font-semibold ${
                      h.result_at_horizon === null
                        ? "text-muted-foreground"
                        : h.result_at_horizon >= 0
                        ? "text-emerald-500"
                        : "text-red-500"
                    }`}
                  >
                    {h.result_at_horizon !== null
                      ? `${(h.result_at_horizon * 100).toFixed(2)}%`
                      : "대기"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
