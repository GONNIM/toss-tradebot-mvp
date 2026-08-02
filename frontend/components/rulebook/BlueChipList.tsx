"use client";

/**
 * 5단계 우량주 필터 통과 종목 리스트 · Phase E+ · 2026-08-02.
 * 존마 강의 원칙 1.
 */

import { useEffect, useState } from "react";

type BlueChipItem = {
  ticker: string;
  name: string | null;
  market: string | null;
  sector: string | null;
  market_cap_krw: number | null;
  tier: string; // premium | entry | none
  close_price: number | null;
  revenue_3y_growing: boolean;
  net_income_3y_growing: boolean;
  annual_turnaround: boolean;
  monthly_ma5_above: boolean;
  monthly_ma5_months_above: number;
  pass_count: number;
  overall_pass: boolean;
  reject_reasons: string | null;
};

type ListResp = {
  run_id: string | null;
  run_started_at: string | null;
  universe_size: number;
  passed_count: number;
  partial_count: number;
  items: BlueChipItem[];
};

const STEP_LABELS = [
  { key: 1, name: "시총 5조+", fld: "capOk" },
  { key: 2, name: "업종", fld: "sectorOk" },
  { key: 3, name: "매출·순이익 3Y", fld: "finOk" },
  { key: 4, name: "연봉 3Y 증가", fld: "annOk" },
  { key: 5, name: "월봉 5MA 3M+", fld: "maOk" },
];

function tierBadge(tier: string): { label: string; className: string } {
  if (tier === "premium") {
    return { label: "🏆 10조+ Premium", className: "bg-purple-500/20 text-purple-400" };
  }
  if (tier === "entry") {
    return { label: "💎 5조+ Entry", className: "bg-blue-500/20 text-blue-400" };
  }
  return { label: "—", className: "bg-slate-500/20 text-slate-400" };
}

function fmtCapKrw(v: number | null): string {
  if (v === null || v === undefined) return "—";
  const cho = v / 1_000_000_000_000;
  if (cho >= 10) return `${cho.toFixed(1)}조`;
  return `${cho.toFixed(2)}조`;
}

export function BlueChipList() {
  const [data, setData] = useState<ListResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyPass, setOnlyPass] = useState(false);
  const [minPass, setMinPass] = useState(3);

  const load = () => {
    setLoading(true);
    setError(null);
    const qs = `min_pass=${minPass}&only_overall_pass=${onlyPass}&limit=200`;
    fetch(`/api/v1/rulebook/blue-chip/list?${qs}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((j: ListResp) => setData(j))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [onlyPass, minPass]);

  return (
    <section className="rounded-lg border border-primary/40 bg-primary/5 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">🎯 오늘의 5단계 통과 종목</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            존마 강의 원칙 1 · 시총·재무·연봉·월봉 5MA 자동 스캔. 매일 22:30 KST nightly.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <label className="flex items-center gap-1">
            <span className="text-muted-foreground">min pass</span>
            <select
              value={minPass}
              onChange={(e) => setMinPass(Number(e.target.value))}
              className="rounded border border-border bg-background px-1 py-0.5"
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  ≥ {n}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={onlyPass}
              onChange={(e) => setOnlyPass(e.target.checked)}
            />
            <span>전 5단계</span>
          </label>
        </div>
      </div>

      {data && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>run: {data.run_id ?? "—"}</span>
          <span>유니버스 {data.universe_size}</span>
          <span className="text-emerald-500">전 통과 {data.passed_count}</span>
          <span className="text-amber-500">부분 통과 {data.partial_count}</span>
        </div>
      )}

      {loading && <div className="mt-3 text-xs text-muted-foreground">로딩...</div>}
      {error && <div className="mt-3 text-xs text-red-500">에러: {error}</div>}

      {!loading && data && data.items.length === 0 && (
        <div className="mt-3 rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          {data.run_id === null
            ? "스크리너 run 없음 · 관리자가 최초 실행 필요 (POST /api/v1/rulebook/blue-chip/run)"
            : "조건 통과 종목 없음 · min pass 를 낮추거나 매일 22:30 KST 크론 결과 대기"}
        </div>
      )}

      {!loading && data && data.items.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-1.5">티커</th>
                <th className="py-1.5">종목</th>
                <th className="py-1.5">tier</th>
                <th className="py-1.5 text-right">시총</th>
                <th className="py-1.5 text-right">종가</th>
                <th className="py-1.5 text-center">1</th>
                <th className="py-1.5 text-center">2</th>
                <th className="py-1.5 text-center">3</th>
                <th className="py-1.5 text-center">4</th>
                <th className="py-1.5 text-center">5</th>
                <th className="py-1.5 text-right">pass</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => {
                const tb = tierBadge(it.tier);
                const flags = {
                  capOk: it.tier !== "none",
                  sectorOk: true,
                  finOk: it.revenue_3y_growing && it.net_income_3y_growing,
                  annOk: it.annual_turnaround,
                  maOk: it.monthly_ma5_above,
                };
                return (
                  <tr
                    key={it.ticker}
                    className={`border-b border-border/40 ${
                      it.overall_pass ? "bg-emerald-500/5" : ""
                    }`}
                    title={it.reject_reasons || "5단계 모두 통과"}
                  >
                    <td className="py-1.5 font-mono font-bold">{it.ticker}</td>
                    <td className="py-1.5">
                      <div>{it.name ?? "—"}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {it.market}
                      </div>
                    </td>
                    <td className="py-1.5">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${tb.className}`}
                      >
                        {tb.label}
                      </span>
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {fmtCapKrw(it.market_cap_krw)}
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {it.close_price?.toLocaleString() ?? "—"}
                    </td>
                    {STEP_LABELS.map((s) => (
                      <td key={s.key} className="py-1.5 text-center">
                        {flags[s.fld as keyof typeof flags] ? "✅" : "—"}
                      </td>
                    ))}
                    <td
                      className={`py-1.5 text-right font-bold ${
                        it.overall_pass ? "text-emerald-500" : "text-amber-500"
                      }`}
                    >
                      {it.pass_count}/5
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-[10px] text-muted-foreground">
        단계: 1시총 · 2업종(자동통과) · 3매출·순이익 3Y↑ · 4연봉 3Y↑ · 5월봉 5MA 3M+
      </p>
    </section>
  );
}
