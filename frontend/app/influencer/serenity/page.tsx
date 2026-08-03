"use client";

// Serenity 랜딩 · 최적 투자 종목 후보 중심 · Phase L9 UX 재구성 · 2026-08-03
// 참조: docs/plans/serenity-integration/01-ui-spec.md §5
// 재구성 원칙 (사용자 지시)
//   1. 최적 투자 종목 후보를 최상단 (Top Picks · Momentum · All Tickers)
//   2. Signal Feed 는 raw · 하단 접힘 (클릭 시 펼침)
//   3. Avoid 별도 섹션 · 접힘

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

// Top Picks 조건 (Serenity 프레임)
//   - serenity_tier S 또는 A
//   - auto_avoid false
//   - anti_pattern_flags 없음
//   - 90d bullish % >= 60
function isTopPick(t: TickerCardItem): boolean {
  if (t.auto_avoid) return false;
  if (t.anti_pattern_flags.length > 0) return false;
  if (t.bullish_pct_90d < 60) return false;
  return t.serenity_tier === "S" || t.serenity_tier === "A";
}

// Momentum: 최근 7일 mentions 이 90일 평균 대비 급증
//   ratio = mentions_7d / (mentions_90d / 90 * 7)
//   ratio >= 2 · Serenity 최근 관심 증가
function momentumRatio(t: TickerCardItem): number {
  if (t.mention_count_90d < 5) return 0;  // 표본 부족
  const expected7d = (t.mention_count_90d / 90) * 7;
  if (expected7d <= 0) return 0;
  return t.mentions_7d / expected7d;
}

export default function SerenityLanding() {
  const [summary, setSummary] = useState<SerenitySummary | null>(null);
  const [signals, setSignals] = useState<SignalFeedItem[] | null>(null);
  const [tickers, setTickers] = useState<TickerCardItem[] | null>(null);
  const [sentiment, setSentiment] = useState("");
  const [days, setDays] = useState(14);
  const [includeAvoid, setIncludeAvoid] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showSignals, setShowSignals] = useState(false);   // 하단 · 접힘 default
  const [showAvoid, setShowAvoid] = useState(false);       // Avoid · 접힘 default

  useEffect(() => {
    serenityApi.summary().then(setSummary).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!showSignals) return;   // 접힌 상태면 fetch 스킵
    setSignals(null);
    serenityApi
      .signals({ days, sentiment: sentiment || undefined, limit: 50 })
      .then(setSignals)
      .catch((e) => setErr(String(e)));
  }, [days, sentiment, showSignals]);

  useEffect(() => {
    setTickers(null);
    serenityApi
      .tickers({ include_avoid: true, limit: 500 })
      .then(setTickers)
      .catch((e) => setErr(String(e)));
  }, []);

  // ─── 자동 큐레이션 ───────────────────────────────────────────
  const topPicks = useMemo(
    () => (tickers ?? []).filter(isTopPick).sort((a, b) => b.bullish_pct_90d - a.bullish_pct_90d).slice(0, 8),
    [tickers],
  );

  const momentum = useMemo(() => {
    const withRatio = (tickers ?? [])
      .filter((t) => !t.auto_avoid)
      .map((t) => ({ t, r: momentumRatio(t) }))
      .filter((x) => x.r >= 2)
      .sort((a, b) => b.r - a.r)
      .slice(0, 6);
    return withRatio;
  }, [tickers]);

  const nonAvoid = useMemo(() => (tickers ?? []).filter((t) => !t.auto_avoid), [tickers]);
  const avoidTickers = useMemo(() => (tickers ?? []).filter((t) => t.auto_avoid), [tickers]);

  // financing_tier 별 그룹핑 (전체 · Avoid 제외)
  const displayGrid = includeAvoid ? tickers ?? [] : nonAvoid;
  const byTier = useMemo(() => {
    const buckets: Record<string, TickerCardItem[]> = {};
    for (const t of displayGrid) {
      if (t.auto_avoid) continue;  // Avoid 는 별도 섹션
      const key = t.financing_tier ?? "?";
      (buckets[key] ??= []).push(t);
    }
    return buckets;
  }, [displayGrid]);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-2xl font-bold">🧠 Serenity Stock Tracker</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI·반도체 supply-chain 특화 · @aleabitoreddit · 900K+ 팔로워
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          목표: Serenity 논지 aggregate 로 <strong>최적 투자 종목 찾기</strong>
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

      {/* ─── Top Picks · 자동 큐레이션 ────────────────────────────── */}
      <section>
        <div className="mb-3">
          <h2 className="text-lg font-semibold">🏆 Top Picks · 최고 conviction</h2>
          <p className="text-xs text-muted-foreground">
            Serenity tier S/A · 90d bullish ≥ 60% · anti-pattern 없음 · avoid 배제 · 자동 큐레이션
          </p>
        </div>
        {tickers === null && <div className="text-xs text-muted-foreground">로딩...</div>}
        {tickers && topPicks.length === 0 && (
          <div className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            조건 만족 종목 없음 · seed tier 확대 or bullish % 완화 필요
          </div>
        )}
        {topPicks.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {topPicks.map((t) => (
              <TickerCard key={t.ticker} item={t} />
            ))}
          </div>
        )}
      </section>

      {/* ─── Momentum Movers · 최근 급증 ──────────────────────────── */}
      {momentum.length > 0 && (
        <section>
          <div className="mb-3">
            <h2 className="text-lg font-semibold">🚀 Momentum Movers · Serenity 최근 관심 급증</h2>
            <p className="text-xs text-muted-foreground">
              7일 언급이 90일 평균 대비 2배 이상 · 표본 5+ · avoid 배제
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {momentum.map(({ t, r }) => (
              <div key={t.ticker} className="relative">
                <TickerCard item={t} />
                <span className="absolute right-2 top-2 rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-purple-400">
                  ×{r.toFixed(1)} momentum
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ─── All Tickers · Tier 별 ────────────────────────────────── */}
      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">📊 전체 언급 종목 · Tier 별</h2>
            <p className="text-xs text-muted-foreground">
              seed 티커는 15원칙 tier (S~F) · 미분류는 언급 순 · today/7d/28d rolling
            </p>
          </div>
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={includeAvoid}
              onChange={(e) => setIncludeAvoid(e.target.checked)}
            />
            <span>AVOID 포함 (미분류 섹션)</span>
          </label>
        </div>
        {tickers === null && <div className="text-xs text-muted-foreground">로딩...</div>}
        {tickers && Object.keys(byTier).length === 0 && (
          <div className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            표시할 종목 없음
          </div>
        )}
        {tickers && Object.keys(byTier).length > 0 && (
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
                  미분류 (seed 없음 · Serenity 언급) · {byTier["?"].length}개
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

      {/* ─── Avoid · 접힘 default ─────────────────────────────────── */}
      {avoidTickers.length > 0 && (
        <section>
          <button
            type="button"
            onClick={() => setShowAvoid(!showAvoid)}
            className="flex w-full items-baseline justify-between rounded border border-red-500/40 bg-red-500/5 px-3 py-2 text-left"
          >
            <div>
              <div className="text-sm font-semibold text-red-500">
                🚨 Avoid · {avoidTickers.length}개
              </div>
              <div className="text-[10px] text-muted-foreground">
                auto_avoid 또는 anti-pattern flag · 회피 대상
              </div>
            </div>
            <span className="text-xs text-muted-foreground">{showAvoid ? "▲ 접기" : "▼ 펼치기"}</span>
          </button>
          {showAvoid && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {avoidTickers.map((t) => (
                <TickerCard key={t.ticker} item={t} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ─── Signal Feed · 하단 · 접힘 default ────────────────────── */}
      <section>
        <button
          type="button"
          onClick={() => setShowSignals(!showSignals)}
          className="flex w-full items-baseline justify-between rounded border border-border bg-card px-3 py-2 text-left"
        >
          <div>
            <div className="text-sm font-semibold">📡 Raw Signal Feed</div>
            <div className="text-[10px] text-muted-foreground">
              트윗별 z.ai 추출 원문 · 감사·검증용 (판정에는 상단 aggregate 사용)
            </div>
          </div>
          <span className="text-xs text-muted-foreground">
            {showSignals ? "▲ 접기" : "▼ 펼치기"}
          </span>
        </button>
        {showSignals && (
          <>
            <div className="mt-3 flex items-center gap-2 text-xs">
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
            {signals === null && (
              <div className="mt-3 text-xs text-muted-foreground">로딩...</div>
            )}
            {signals && signals.length === 0 && (
              <div className="mt-3 rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                해당 조건의 signal 없음
              </div>
            )}
            {signals && signals.length > 0 && (
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {signals.map((s) => (
                  <SignalFeedCard key={s.id} item={s} />
                ))}
              </div>
            )}
          </>
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
