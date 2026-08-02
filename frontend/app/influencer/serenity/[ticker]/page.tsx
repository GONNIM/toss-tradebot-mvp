"use client";

// 티커 상세 페이지 · Phase L7 · 2026-08-02
// 참조: docs/plans/serenity-integration/01-ui-spec.md §6

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { serenityApi } from "@/lib/serenity/api";
import type { TickerDetailResponse } from "@/lib/serenity/types";
import { BacktestChart } from "@/components/serenity/BacktestChart";
import { ChecklistCard } from "@/components/serenity/ChecklistCard";
import { SignalFeedCard } from "@/components/serenity/SignalFeedCard";

type PageProps = { params: Promise<{ ticker: string }> };

export default function TickerDetailPage({ params }: PageProps) {
  const { ticker } = use(params);
  const upper = ticker.toUpperCase();
  const [data, setData] = useState<TickerDetailResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setErr(null);
    serenityApi
      .ticker(upper, 15)
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [upper]);

  if (err) {
    return (
      <div className="mx-auto max-w-4xl">
        <Link href="/influencer/serenity" className="text-xs text-sky-500 hover:underline">
          ← Serenity 랜딩
        </Link>
        <div className="mt-4 rounded border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          {err.includes("404") ? `티커 ${upper} · 스코어 없음 (seed 필요)` : `에러: ${err}`}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-4xl">
        <div className="text-xs text-muted-foreground">로딩...</div>
      </div>
    );
  }

  const s = data.score;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/influencer/serenity" className="text-xs text-sky-500 hover:underline">
        ← Serenity 랜딩
      </Link>

      <header
        className={`rounded-lg border p-4 ${
          s.auto_avoid ? "border-red-500/40 bg-red-500/5" : "border-border bg-card"
        }`}
      >
        <div className="flex items-baseline justify-between">
          <div>
            <h1 className="font-mono text-2xl font-bold">${s.ticker}</h1>
            {s.domain_tags.length > 0 && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {s.domain_tags.join(" · ")}
              </p>
            )}
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold text-primary">{s.total_score}</div>
            {s.auto_avoid ? (
              <span className="text-xs font-semibold text-red-500">🚨 AVOID</span>
            ) : (
              <span className="text-xs text-emerald-500">watch</span>
            )}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded bg-slate-500/20 px-2 py-0.5">
            Financing tier: <strong>{s.financing_tier ?? "-"}</strong>
          </span>
          <span className="rounded bg-slate-500/20 px-2 py-0.5">
            Serenity tier: <strong>{s.serenity_tier ?? "-"}</strong>
          </span>
          <span className="rounded bg-slate-500/20 px-2 py-0.5">
            90일 mentions: <strong>{s.mention_count_90d}</strong>
          </span>
          <span className="rounded bg-slate-500/20 px-2 py-0.5">
            bullish: <strong>{s.bullish_pct_90d.toFixed(0)}%</strong>
          </span>
        </div>
        {s.anti_pattern_flags.length > 0 && (
          <div className="mt-2 text-xs text-red-500">
            ⚠ Anti-pattern: {s.anti_pattern_flags.join(", ")}
          </div>
        )}
      </header>

      <ChecklistCard ticker={s} />

      <BacktestChart
        title="📊 Backtest 평균 수익률 (최근 90일 signals)"
        data={data.backtest_avg}
      />

      <section>
        <h2 className="mb-2 text-sm font-semibold">📡 Recent Signals · {data.recent_signals.length}건</h2>
        {data.recent_signals.length === 0 ? (
          <div className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            signal 없음 · 크론이 매일 07:00 KST 자동 수집 예정
          </div>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {data.recent_signals.map((sig) => (
              <SignalFeedCard key={sig.id} item={sig} />
            ))}
          </div>
        )}
      </section>

      <footer className="border-t border-border pt-4 text-xs text-muted-foreground">
        참조 · Serenity 원본 theses.md · methodology.md ({" "}
        <Link href="/influencer/serenity/methodology" className="text-sky-500 hover:underline">
          15원칙 열람
        </Link>{" "}
        )
      </footer>
    </div>
  );
}
