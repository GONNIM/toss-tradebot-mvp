"use client";

// Principles v1.0.2 · 스크리너 결과 페이지 (2026-08-17)
// 최신 배치 요약 + 3탭 (PASS/FAIL/INSUFFICIENT_DATA) + 종목별 지표·근거

import { useEffect, useState } from "react";

interface Reason {
  code: string;
  status: "pass" | "fail" | "skip" | "insufficient";
  value?: unknown;
  threshold?: unknown;
  note?: string;
}

interface Result {
  ticker: string;
  name: string | null;
  industry_code: string | null;
  is_financial_sector: boolean;
  per_ttm: number | null;
  per_operating: number | null;
  payout_ratio_3y_avg: number | null;
  dividend_years: number | null;
  dividend_cut: boolean | null;
  debt_ratio: number | null;
  interest_coverage: number | null;
  reasons: Reason[] | null;
  missing_fields: string[] | null;
}

interface Run {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  charter_version: string | null;
  universe_size: number;
  pass_count: number;
  fail_count: number;
  insufficient_count: number;
  dart_call_count: number;
  elapsed_sec: number | null;
}

interface LatestResponse {
  run: Run | null;
  results: { PASS: Result[]; FAIL: Result[]; INSUFFICIENT_DATA: Result[] };
}

type Tab = "PASS" | "FAIL" | "INSUFFICIENT_DATA";

const TAB_LABEL: Record<Tab, string> = {
  PASS: "🟢 PASS",
  FAIL: "🔴 FAIL",
  INSUFFICIENT_DATA: "⚪ INSUFFICIENT",
};

function fmtPct(v: number | null, digits: number = 1): string {
  if (v === null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}
function fmtNum(v: number | null, digits: number = 2): string {
  if (v === null) return "—";
  return v.toFixed(digits);
}

export default function ScreenerPage() {
  const [data, setData] = useState<LatestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("PASS");
  const [openTicker, setOpenTicker] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/principles/screener/latest")
      .then((r) => {
        if (!r.ok) throw new Error(`latest ${r.status}`);
        return r.json();
      })
      .then((d: LatestResponse) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className="text-sm text-red-600">⚠️ {error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">배치 결과 로드 중…</p>;

  const { run, results } = data;

  if (!run) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">🧪 저평가 우량주 스크리너</h1>
        <p className="text-sm text-muted-foreground">
          아직 배치가 실행되지 않았습니다. 매일 23:00 KST 자동 실행 · 다음 사이클 대기.
        </p>
      </div>
    );
  }

  const currentList = results[tab] ?? [];

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🧪 저평가 우량주 스크리너</h1>
        <p className="text-xs text-muted-foreground">
          run #{run.id} · charter v{run.charter_version} · {run.started_at} · {run.elapsed_sec?.toFixed(1)}s
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div className="rounded border border-border bg-card p-3 text-center">
          <p className="text-xs text-muted-foreground">Universe</p>
          <p className="text-lg font-bold">{run.universe_size.toLocaleString()}</p>
        </div>
        <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-center dark:border-emerald-900 dark:bg-emerald-950">
          <p className="text-xs text-emerald-700 dark:text-emerald-300">PASS</p>
          <p className="text-lg font-bold text-emerald-700 dark:text-emerald-300">
            {run.pass_count.toLocaleString()}
          </p>
        </div>
        <div className="rounded border border-rose-200 bg-rose-50 p-3 text-center dark:border-rose-900 dark:bg-rose-950">
          <p className="text-xs text-rose-700 dark:text-rose-300">FAIL</p>
          <p className="text-lg font-bold text-rose-700 dark:text-rose-300">
            {run.fail_count.toLocaleString()}
          </p>
        </div>
        <div className="rounded border border-border bg-card p-3 text-center">
          <p className="text-xs text-muted-foreground">INSUFFICIENT</p>
          <p className="text-lg font-bold">{run.insufficient_count.toLocaleString()}</p>
        </div>
        <div className="rounded border border-border bg-card p-3 text-center">
          <p className="text-xs text-muted-foreground">DART calls</p>
          <p className="text-lg font-bold">{run.dart_call_count.toLocaleString()}</p>
        </div>
      </section>

      <section>
        <div className="flex gap-1 border-b border-border">
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm ${
                tab === t
                  ? "border-b-2 border-primary font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {TAB_LABEL[t]} ({results[t]?.length ?? 0})
            </button>
          ))}
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground border-b border-border">
              <tr className="text-left">
                <th className="py-2 pr-3">티커</th>
                <th className="py-2 pr-3">종목명</th>
                <th className="py-2 pr-3 text-right">PER TTM</th>
                <th className="py-2 pr-3 text-right">주주환원 3y</th>
                <th className="py-2 pr-3 text-right">배당년</th>
                <th className="py-2 pr-3 text-right">부채비율</th>
                <th className="py-2 pr-3 text-right">이자보상</th>
                <th className="py-2 pr-3">금융업</th>
                <th className="py-2 pr-3">근거</th>
              </tr>
            </thead>
            <tbody>
              {currentList.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-4 text-center text-muted-foreground">
                    해당 분류 종목 없음
                  </td>
                </tr>
              ) : (
                currentList.map((r) => (
                  <>
                    <tr
                      key={r.ticker}
                      className="border-b border-border/40 hover:bg-muted/20 cursor-pointer"
                      onClick={() => setOpenTicker(openTicker === r.ticker ? null : r.ticker)}
                    >
                      <td className="py-1 pr-3 font-mono">{r.ticker}</td>
                      <td className="py-1 pr-3">{r.name ?? "—"}</td>
                      <td className="py-1 pr-3 text-right font-mono">{fmtNum(r.per_ttm)}</td>
                      <td className="py-1 pr-3 text-right font-mono">
                        {fmtPct(r.payout_ratio_3y_avg)}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono">
                        {r.dividend_years ?? "—"}
                        {r.dividend_cut ? " ↓" : ""}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono">
                        {fmtPct(r.debt_ratio)}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono">
                        {fmtNum(r.interest_coverage)}
                      </td>
                      <td className="py-1 pr-3">{r.is_financial_sector ? "🏦" : ""}</td>
                      <td className="py-1 pr-3 text-xs text-muted-foreground">
                        {openTicker === r.ticker ? "▴ 닫기" : "▾ 펼치기"}
                      </td>
                    </tr>
                    {openTicker === r.ticker && (
                      <tr key={`${r.ticker}-detail`}>
                        <td colSpan={9} className="bg-muted/20 py-3 px-3">
                          <ul className="space-y-1 text-xs">
                            {r.reasons?.map((rn) => (
                              <li
                                key={rn.code}
                                className={
                                  rn.status === "pass"
                                    ? "text-emerald-600"
                                    : rn.status === "fail"
                                    ? "text-rose-600"
                                    : "text-muted-foreground"
                                }
                              >
                                <strong>[{rn.status}]</strong> {rn.code}: {rn.note}
                              </li>
                            ))}
                            {r.missing_fields && r.missing_fields.length > 0 && (
                              <li className="text-amber-600">
                                <strong>결측 필드:</strong> {r.missing_fields.join(", ")}
                              </li>
                            )}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="border-t border-border pt-4 text-xs text-muted-foreground">
        ⚠️ 본 정보는 투자 자문이 아니며, 투자 판단과 책임은 이용자 본인에게 있습니다.
      </footer>
    </div>
  );
}
