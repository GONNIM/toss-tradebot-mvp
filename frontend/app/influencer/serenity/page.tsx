"use client";

// Serenity 랜딩 · Signal Feed + Ticker Grid · Phase L6 · 2026-08-02
// 참조: docs/plans/serenity-integration/01-ui-spec.md §5

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { serenityApi } from "@/lib/serenity/api";
import type {
  SerenitySummary,
  SignalFeedItem,
  TickerCardItem,
} from "@/lib/serenity/types";
import { SignalFeedCard } from "@/components/serenity/SignalFeedCard";
import { TickerCard } from "@/components/serenity/TickerCard";

const SENTIMENT_OPTS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "bullish", label: "🟢 Bullish" },
  { value: "bearish", label: "🔴 Bearish" },
  { value: "neutral", label: "⚪ Neutral" },
  { value: "calibration", label: "🟡 Calibration" },
];

const TIER_ORDER = ["S", "A", "B", "C", "D", "F"] as const;

export default function SerenityLanding() {
  const [summary, setSummary] = useState<SerenitySummary | null>(null);
  const [signals, setSignals] = useState<SignalFeedItem[] | null>(null);
  const [tickers, setTickers] = useState<TickerCardItem[] | null>(null);
  const [sentiment, setSentiment] = useState("");
  const [days, setDays] = useState(14);
  const [includeAvoid, setIncludeAvoid] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    serenityApi.summary().then(setSummary).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    setSignals(null);
    serenityApi
      .signals({ days, sentiment: sentiment || undefined, limit: 50 })
      .then(setSignals)
      .catch((e) => setErr(String(e)));
  }, [days, sentiment]);

  useEffect(() => {
    setTickers(null);
    serenityApi
      .tickers({ include_avoid: includeAvoid, limit: 200 })
      .then(setTickers)
      .catch((e) => setErr(String(e)));
  }, [includeAvoid]);

  const byTier = useMemo(() => {
    const buckets: Record<string, TickerCardItem[]> = {};
    for (const t of tickers ?? []) {
      const key = t.financing_tier ?? "?";
      (buckets[key] ??= []).push(t);
    }
    return buckets;
  }, [tickers]);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-2xl font-bold">🧠 Serenity Stock Tracker</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI·반도체 supply-chain 특화 · @aleabitoreddit · 900K+ 팔로워
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          docs/plans/serenity-integration · 15원칙·per-ticker 논지·dated calls
        </p>
        <nav className="mt-3 flex flex-wrap gap-3 text-xs">
          <Link
            href="/influencer/serenity/methodology"
            className="rounded border border-border bg-card px-2 py-1 hover:border-primary/60"
          >
            📚 Methodology (15원칙)
          </Link>
          <Link
            href="/influencer/serenity/backtest"
            className="rounded border border-border bg-card px-2 py-1 hover:border-primary/60"
          >
            📊 Backtest Report
          </Link>
        </nav>
      </header>

      {summary && (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryStat label="트윗 아카이브" value={summary.tweets} />
          <SummaryStat label="signals 추출" value={summary.signals} />
          <SummaryStat
            label="스코어 티커"
            value={summary.tickers_scored}
            hint={`${summary.tickers_auto_avoid} auto_avoid`}
          />
          <SummaryStat
            label="최근 signal"
            value={
              summary.last_signal_at
                ? new Date(summary.last_signal_at).toLocaleDateString("ko-KR")
                : "—"
            }
          />
        </section>
      )}

      {err && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-500">
          에러: {err}
        </div>
      )}

      {/* Signal Feed */}
      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">📡 Signal Feed</h2>
            <p className="text-xs text-muted-foreground">
              최근 {days}일 · z.ai GLM 추출 · sentiment 필터 지원
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded border border-border bg-background px-2 py-1"
            >
              <option value={7}>7일</option>
              <option value={14}>14일</option>
              <option value={30}>30일</option>
              <option value={90}>90일</option>
            </select>
            <select
              value={sentiment}
              onChange={(e) => setSentiment(e.target.value)}
              className="rounded border border-border bg-background px-2 py-1"
            >
              {SENTIMENT_OPTS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {signals === null && (
          <div className="text-xs text-muted-foreground">Signal 로딩...</div>
        )}
        {signals && signals.length === 0 && (
          <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
            해당 조건의 signal 없음 · 크론이 매일 07:00 KST 갱신 예정 (Phase L8)
          </div>
        )}
        {signals && signals.length > 0 && (
          <div className="grid gap-2 md:grid-cols-2">
            {signals.map((s) => (
              <SignalFeedCard key={s.id} item={s} />
            ))}
          </div>
        )}
      </section>

      {/* Ticker Grid */}
      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">🎯 Ticker Grid</h2>
            <p className="text-xs text-muted-foreground">
              15원칙 총 스코어 정렬 · financing tier 분류 (S/A/B/C/D/F)
            </p>
          </div>
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={includeAvoid}
              onChange={(e) => setIncludeAvoid(e.target.checked)}
            />
            <span>AVOID 포함</span>
          </label>
        </div>

        {tickers === null && (
          <div className="text-xs text-muted-foreground">Ticker 로딩...</div>
        )}
        {tickers && tickers.length === 0 && (
          <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
            seed 티커 없음 · <code>python -m backend.scripts.serenity_seed_tiers</code> 실행 필요
          </div>
        )}
        {tickers && tickers.length > 0 && (
          <div className="space-y-4">
            {TIER_ORDER.filter((t) => byTier[t]?.length).map((tier) => (
              <div key={tier}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {tier} tier · {byTier[tier].length}개
                </h3>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {byTier[tier].map((t) => (
                    <TickerCard key={t.ticker} item={t} />
                  ))}
                </div>
              </div>
            ))}
            {byTier["?"] && byTier["?"].length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Unclassified · {byTier["?"].length}개
                </h3>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {byTier["?"].map((t) => (
                    <TickerCard key={t.ticker} item={t} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded border border-border bg-muted/20 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-bold">{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}
