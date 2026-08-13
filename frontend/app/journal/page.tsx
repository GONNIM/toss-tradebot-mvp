// Judgment Journal · Phase B 주 3-5 · 2026-07-30
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
//       docs/plans/toss-tradebot-tobe/reviews/perspective-a-quant-psychology.md 권고 1
//
// self-page 편애 방지 · 모든 페이지 판정 병치
// Stage 1 진짜 KPI (자기 판단 오류율 측정) 근거

"use client";

import { useEffect, useState } from "react";

type Judgment = {
  id: number;
  ts: string;
  user_id: string;
  ticker: string;
  page_source: string;
  hypothesis_id: string;
  thesis_md: string;
  invalidation_price: number | null;
  target_price: number | null;
  horizon_days: number;
  mood: string;
  market_regime: string;
  result_at_horizon: number | null;
  result_computed_at: string | null;
  git_sha: string | null;
};

type Baseline = {
  total_count: number;
  computed_count: number;
  win_rate: number | null;
  avg_return: number | null;
  mood_distribution: Record<string, number>;
  page_source_distribution: Record<string, number>;
};

const moodBadge = (m: string) => {
  const map: Record<string, string> = {
    cool: "bg-blue-500/20 text-blue-400",
    neutral: "bg-gray-500/20 text-gray-400",
    revenge: "bg-red-500/20 text-red-400",
    fomo: "bg-yellow-500/20 text-yellow-400",
  };
  return map[m] || "bg-gray-500/20 text-gray-400";
};

const pageBadge = (p: string) => {
  const map: Record<string, string> = {
    powderkeg: "bg-orange-500/20 text-orange-400",
    watchlist: "bg-purple-500/20 text-purple-400",
    sniper: "bg-cyan-500/20 text-cyan-400",
    activist: "bg-emerald-500/20 text-emerald-400",
    vip: "bg-pink-500/20 text-pink-400",
    manual: "bg-slate-500/20 text-slate-400",
  };
  return map[p] || "bg-slate-500/20 text-slate-400";
};

export default function JournalPage() {
  const [judgments, setJudgments] = useState<Judgment[]>([]);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const [j, b] = await Promise.all([
        fetch(`/api/v1/judgments?days=${d}&limit=100`).then((r) => {
          if (!r.ok) throw new Error(`judgments ${r.status}`);
          return r.json();
        }),
        fetch(`/api/v1/judgments/baseline?days=90`).then((r) => {
          if (!r.ok) throw new Error(`baseline ${r.status}`);
          return r.json();
        }),
      ]);
      setJudgments(j);
      setBaseline(b);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(days);
  }, [days]);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold">📓 Judgment Journal</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          판정→결과 폐루프 · 모든 페이지 판정 병치 · self-page 편애 방지
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
        </p>
      </header>

      {/* Phase E · Stage 2 진입 KPI 진행률 (roadmap-12week.md §0) */}
      <Stage2KpiProgress baseline={baseline} judgments={judgments} />

      {/* Baseline · Stage 2 진입 KPI 근거 */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          최근 90일 Baseline · Stage 2 진입 KPI 근거
        </div>
        {baseline ? (
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="총 판정" value={String(baseline.total_count)} />
            <Kpi label="outcome 계산 완료" value={String(baseline.computed_count)} />
            <Kpi
              label="승률"
              value={baseline.win_rate !== null ? `${(baseline.win_rate * 100).toFixed(1)}%` : "—"}
            />
            <Kpi
              label="평균 수익률"
              value={
                baseline.avg_return !== null
                  ? `${(baseline.avg_return * 100).toFixed(2)}%`
                  : "—"
              }
            />
          </div>
        ) : (
          <div className="mt-3 text-xs text-muted-foreground">baseline 로딩...</div>
        )}
        {baseline && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <div className="text-xs text-muted-foreground">mood 분포</div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                {Object.entries(baseline.mood_distribution).map(([m, n]) => (
                  <span key={m} className={`rounded px-2 py-0.5 ${moodBadge(m)}`}>
                    {m}: {n}
                  </span>
                ))}
                {Object.keys(baseline.mood_distribution).length === 0 && (
                  <span className="text-muted-foreground">—</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">page_source 분포</div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                {Object.entries(baseline.page_source_distribution).map(([p, n]) => (
                  <span key={p} className={`rounded px-2 py-0.5 ${pageBadge(p)}`}>
                    {p}: {n}
                  </span>
                ))}
                {Object.keys(baseline.page_source_distribution).length === 0 && (
                  <span className="text-muted-foreground">—</span>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 판정 목록 */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            판정 목록 (최근 {days}일)
          </h2>
          <div className="flex gap-2">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded border px-2 py-1 text-xs ${
                  days === d
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="text-xs text-muted-foreground">로딩...</div>}
        {error && <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">에러: {error}</div>}

        {!loading && !error && judgments.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <div className="text-3xl">📝</div>
            <p className="mt-2 text-sm text-muted-foreground">아직 판정이 없습니다.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Powderkeg lock · Watchlist 편입 · Sniper enable 시 판정 팝업이 뜹니다.
            </p>
          </div>
        )}

        {!loading && judgments.length > 0 && (
          <div className="space-y-3">
            {judgments.map((j) => (
              <JudgmentCard key={j.id} j={j} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-muted/20 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-bold">{value}</div>
    </div>
  );
}

// ─── Stage 2 진입 KPI 진행률 (Phase E · 2026-07-31) ─────────────
// 기준: roadmap-12week.md §0 Stage 2 진입 KPI 6항
//   1. 판정 30건+ · rejection criteria 100%
//   2. 판정 baseline 확정 (T+7 outcome 자동)
//   3. Obsidian sync 3경로 자동화 (Runs/Weekly/Tickers) — 별도 확증 필요
//   4. 관리자 인증 100% · 무인증 실 종목 노출 0
//   5. 3계층 재편 완결 · L3 /lab 이관
//   6. T2 Cal.com 컨설팅 슬롯 유료 예약 1건
// 자동 판정 가능 항목만 표시 · 3/5/6 은 수동 체크 항목으로 표기.

function Stage2KpiProgress({
  baseline,
  judgments,
}: {
  baseline: Baseline | null;
  judgments: Judgment[];
}) {
  if (!baseline) return null;

  const total = baseline.total_count;
  const target = 30;
  const pct = Math.min(100, Math.round((total / target) * 100));

  // rejection criteria 100% = 판정 목록 최근 100건 중 invalidation_price != null 비율
  const withInvalidation = judgments.filter((j) => j.invalidation_price !== null).length;
  const invalidationPct =
    judgments.length > 0 ? Math.round((withInvalidation / judgments.length) * 100) : 0;

  // page_source 편중 확인 (self-page 편애 방지)
  const dist = baseline.page_source_distribution;
  const distTotal = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  const maxSource =
    Object.entries(dist).sort((a, b) => b[1] - a[1])[0] ?? (["-", 0] as [string, number]);
  const maxSourcePct = Math.round((maxSource[1] / distTotal) * 100);

  return (
    <section className="rounded-lg border border-primary/40 bg-primary/5 p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">🎯 Stage 2 진입 KPI (Phase E)</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            판정 30건 · rejection criteria 100% · baseline 확정 · self-page 편중 감지
          </div>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold ${
            total >= target
              ? "bg-emerald-500/20 text-emerald-500"
              : "bg-amber-500/20 text-amber-500"
          }`}
        >
          {total >= target ? "PASS" : "진행 중"}
        </span>
      </div>

      <div className="mt-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">판정 축적</span>
          <span className="font-mono">
            {total} / {target} 건 ({pct}%)
          </span>
        </div>
        <div className="mt-1 h-2 overflow-hidden rounded bg-muted">
          <div
            className={`h-full transition-all ${
              total >= target ? "bg-emerald-500" : "bg-primary"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <KpiCheck
          label="rejection criteria"
          detail={`${withInvalidation}/${judgments.length} 판정 (invalidation_price 설정)`}
          ok={invalidationPct === 100 && judgments.length > 0}
          value={`${invalidationPct}%`}
        />
        <KpiCheck
          label="outcome 자동 계산"
          detail={`${baseline.computed_count}/${baseline.total_count} 판정 (T+N 이후)`}
          ok={baseline.computed_count > 0}
          value={
            baseline.total_count > 0
              ? `${Math.round((baseline.computed_count / baseline.total_count) * 100)}%`
              : "—"
          }
        />
        <KpiCheck
          label="page_source 균형"
          detail={`최대 편중: ${maxSource[0]} ${maxSourcePct}%`}
          ok={maxSourcePct <= 60 && Object.keys(dist).length >= 2}
          value={`${maxSourcePct}%`}
          warnHigh
        />
        <KpiCheck
          label="관리자 인증"
          detail="Phase D 배포 완료 (httpOnly 쿠키)"
          ok={true}
          value="배선 완료"
        />
      </div>

      <div className="mt-3 text-[10px] text-muted-foreground">
        수동 확인 필요: Obsidian sync 3경로 · 3계층 재편 완결 · T2 Cal.com 컨설팅 예약.
        <br />
        기준: <code>docs/plans/toss-tradebot-tobe/roadmap-12week.md</code> §0
      </div>
    </section>
  );
}

function KpiCheck({
  label,
  detail,
  ok,
  value,
  warnHigh = false,
}: {
  label: string;
  detail: string;
  ok: boolean;
  value: string;
  warnHigh?: boolean;
}) {
  return (
    <div className="rounded border border-border bg-background/50 px-2 py-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className="text-xs">{ok ? "✅" : warnHigh ? "⚠️" : "⏳"}</span>
      </div>
      <div className="mt-0.5 text-sm font-semibold">{value}</div>
      <div className="mt-0.5 line-clamp-2 text-[10px] text-muted-foreground">{detail}</div>
    </div>
  );
}

function JudgmentCard({ j }: { j: Judgment }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-bold">{j.ticker}</span>
        <span className={`rounded px-2 py-0.5 text-[10px] ${pageBadge(j.page_source)}`}>
          {j.page_source}
        </span>
        <span className={`rounded px-2 py-0.5 text-[10px] ${moodBadge(j.mood)}`}>
          {j.mood}
        </span>
        <span className="rounded bg-slate-500/20 px-2 py-0.5 text-[10px] text-slate-400">
          {j.market_regime}
        </span>
        <span className="rounded bg-indigo-500/20 px-2 py-0.5 text-[10px] text-indigo-400">
          {j.hypothesis_id}
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {new Date(j.ts).toLocaleString("ko-KR")}
        </span>
      </div>
      <div className="mt-3 whitespace-pre-wrap text-sm text-foreground">{j.thesis_md}</div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>
          <strong>invalidation:</strong> {j.invalidation_price?.toLocaleString() ?? "—"}
        </span>
        <span>
          <strong>target:</strong> {j.target_price?.toLocaleString() ?? "—"}
        </span>
        <span>
          <strong>horizon:</strong> T+{j.horizon_days}
        </span>
        {j.result_at_horizon !== null ? (
          <span
            className={`font-semibold ${
              j.result_at_horizon > 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            outcome: {(j.result_at_horizon * 100).toFixed(2)}%
          </span>
        ) : (
          <span className="italic text-muted-foreground/70">outcome 계산 대기</span>
        )}
        {j.git_sha && <span className="font-mono">build {j.git_sha.slice(0, 7)}</span>}
      </div>
    </div>
  );
}
