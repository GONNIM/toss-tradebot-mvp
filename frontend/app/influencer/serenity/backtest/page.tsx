"use client";

// 백테스트 리포트 · Phase L7 · 2026-08-02
// sentiment/tier/top-ticker 별 평균 return

import Link from "next/link";
import { useEffect, useState } from "react";
import { serenityApi } from "@/lib/serenity/api";
import type { BacktestBucket, BacktestSummary } from "@/lib/serenity/types";

export default function BacktestReportPage() {
  const [data, setData] = useState<BacktestSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [days, setDays] = useState(180);

  useEffect(() => {
    setData(null);
    setErr(null);
    serenityApi
      .backtestSummary(days)
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [days]);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link href="/influencer/serenity" className="text-xs text-sky-500 hover:underline">
        ← Serenity 랜딩
      </Link>

      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">📊 Serenity Backtest Report</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            signal → 실 주가 대조 (yfinance) · 5·10·30·60·180일 후 평균 % return
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        >
          <option value={30}>최근 30일</option>
          <option value={90}>최근 90일</option>
          <option value={180}>최근 180일</option>
          <option value={365}>최근 365일</option>
        </select>
      </header>

      {err && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-500">
          에러: {err}
        </div>
      )}

      {!data && !err && (
        <div className="text-xs text-muted-foreground">로딩...</div>
      )}

      {data && data.total_backtests === 0 && (
        <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
          백테스트 데이터 없음 · signals 있어야 backtest 실행 가능
          <br />
          매주 월 00:00 KST 크론 자동 (Phase L8) · 수동:{" "}
          <code>python -m backend.scripts.serenity_backtest --batch 100</code>
        </div>
      )}

      {data && data.total_backtests > 0 && (
        <>
          <BucketBlock title="전체 평균" buckets={[data.overall]} />
          <BucketBlock title="Sentiment 별" buckets={data.by_sentiment} />
          <BucketBlock title="Financing Tier 별 (S~F)" buckets={data.by_financing_tier} />
          <BucketBlock title="60일 평균 상위 티커" buckets={data.top_tickers_60d} />
        </>
      )}
    </div>
  );
}

function BucketBlock({ title, buckets }: { title: string; buckets: BacktestBucket[] }) {
  if (buckets.length === 0) {
    return (
      <section>
        <h2 className="mb-2 text-sm font-semibold">{title}</h2>
        <div className="rounded border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          데이터 없음
        </div>
      </section>
    );
  }
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-1.5">key</th>
              <th className="py-1.5 text-right">n</th>
              <th className="py-1.5 text-right">5d</th>
              <th className="py-1.5 text-right">10d</th>
              <th className="py-1.5 text-right">30d</th>
              <th className="py-1.5 text-right">60d</th>
              <th className="py-1.5 text-right">180d</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.key} className="border-b border-border/40">
                <td className="py-1.5 font-mono">{b.key}</td>
                <td className="py-1.5 text-right">{b.count}</td>
                {(["avg_return_5d", "avg_return_10d", "avg_return_30d", "avg_return_60d", "avg_return_180d"] as const).map((f) => {
                  const v = b[f];
                  const cls =
                    v === null
                      ? "text-muted-foreground"
                      : v >= 0
                      ? "text-emerald-500"
                      : "text-red-500";
                  return (
                    <td key={f} className={`py-1.5 text-right font-mono ${cls}`}>
                      {v !== null ? `${v.toFixed(2)}%` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
