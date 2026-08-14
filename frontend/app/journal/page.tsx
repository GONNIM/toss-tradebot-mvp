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
  superseded_by_id: number | null;
  superseded_at: string | null;
  supersede_reason: string | null;
  updated_history: string | null;
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

// 심볼별 현재가 조회 (dashboard toss-account 재활용 · 하향 편집 예외 판정용)
async function loadPriceMap(): Promise<Record<string, number>> {
  try {
    const r = await fetch("/api/v1/dashboard/toss-account", { credentials: "include" });
    if (!r.ok) return {};
    const d = await r.json();
    const map: Record<string, number> = {};
    for (const h of [...(d.kr_holdings ?? []), ...(d.us_holdings ?? [])]) {
      if (h.symbol && h.current_price) {
        map[String(h.symbol).toUpperCase()] = h.current_price;
      }
    }
    return map;
  } catch {
    return {};
  }
}

export default function JournalPage() {
  const [judgments, setJudgments] = useState<Judgment[]>([]);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [priceMap, setPriceMap] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const [j, b, pm] = await Promise.all([
        fetch(`/api/v1/judgments?days=${d}&limit=100`).then((r) => {
          if (!r.ok) throw new Error(`judgments ${r.status}`);
          return r.json();
        }),
        fetch(`/api/v1/judgments/baseline?days=90`).then((r) => {
          if (!r.ok) throw new Error(`baseline ${r.status}`);
          return r.json();
        }),
        loadPriceMap(),
      ]);
      setJudgments(j);
      setBaseline(b);
      setPriceMap(pm);
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

      {/* 신규 판정 입력 폼 (2026-08-14 · Fable 5 · 30건 캠페인) */}
      <NewJudgmentForm onCreated={() => load(days)} />

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
              <JudgmentCard
                key={j.id}
                j={j}
                currentPrice={priceMap[j.ticker.toUpperCase()]}
                onChanged={() => load(days)}
              />
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

  // Fable 5 (2026-08-14): superseded 는 정리 작업이지 판정 아님 · 카운터에서 제외.
  // 30 부풀리기 방지.
  const activeJudgments = judgments.filter((j) => j.superseded_by_id === null);
  const total = activeJudgments.length;
  const target = 30;
  const pct = Math.min(100, Math.round((total / target) * 100));

  // rejection criteria 100% = 활성 판정 중 invalidation_price != null 비율
  const withInvalidation = activeJudgments.filter((j) => j.invalidation_price !== null).length;
  const invalidationPct =
    activeJudgments.length > 0 ? Math.round((withInvalidation / activeJudgments.length) * 100) : 0;

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

type HistoryEntry = {
  at: string;
  note: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
};

function parseHistory(raw: string | null): HistoryEntry[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function JudgmentCard({
  j,
  currentPrice,
  onChanged,
}: {
  j: Judgment;
  currentPrice: number | undefined;
  onChanged: () => void;
}) {
  const superseded = j.superseded_by_id !== null;
  const [mode, setMode] = useState<"view" | "edit" | "close">("view");
  const [showHistory, setShowHistory] = useState(false);

  const cardClass = superseded
    ? "rounded-lg border border-border bg-card/40 p-4 opacity-60"
    : "rounded-lg border border-border bg-card p-4";

  const history = parseHistory(j.updated_history);
  const triggerHit =
    currentPrice !== undefined &&
    j.invalidation_price !== null &&
    currentPrice <= j.invalidation_price;
  const abnormalState =
    currentPrice !== undefined &&
    j.invalidation_price !== null &&
    j.invalidation_price >= currentPrice; // 롱 기준: invalidation 이 현재가 이상 = 이미 발동 (비정상)

  return (
    <div className={cardClass}>
      {/* 헤더 · 배지 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={"font-mono text-sm font-bold " + (superseded ? "line-through" : "")}>
          {j.ticker}
        </span>
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
          id={j.id}
        </span>
        {superseded && (
          <span
            className="rounded bg-gray-500/30 px-2 py-0.5 text-[10px] font-semibold text-gray-400"
            title={j.supersede_reason ?? undefined}
          >
            ↷ superseded by id={j.superseded_by_id}
          </span>
        )}
        {(j.mood === "revenge" || j.mood === "fomo") && !superseded && (
          <span className="rounded bg-red-500/30 px-2 py-0.5 text-[10px] font-semibold text-red-400">
            🚫 오늘 실행 금지
          </span>
        )}
        {triggerHit && !superseded && (
          <span className="rounded bg-red-500/40 px-2 py-0.5 text-[10px] font-semibold text-red-300">
            🚨 트리거 도달 (현재가 {currentPrice})
          </span>
        )}
        {abnormalState && !triggerHit && !superseded && (
          <span className="rounded bg-amber-500/30 px-2 py-0.5 text-[10px] font-semibold text-amber-400">
            ⚠ invalidation 비정상 (≥ 현재가)
          </span>
        )}
        {history.length > 0 && (
          <span
            className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-400"
            title={`갱신 ${history.length}회`}
          >
            ✎ updated ×{history.length}
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {new Date(j.ts).toLocaleString("ko-KR")}
        </span>
      </div>

      {/* 본문 · thesis */}
      {mode === "view" && (
        <>
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
            {currentPrice !== undefined && (
              <span>
                <strong>현재가:</strong> {currentPrice.toLocaleString()}
              </span>
            )}
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
          </div>
          {j.supersede_reason && (
            <div className="mt-2 text-[10px] italic text-muted-foreground">
              Supersede 사유: {j.supersede_reason}
            </div>
          )}

          {/* 액션 버튼 · 활성 판정만 */}
          {!superseded && (
            <div className="mt-3 flex flex-wrap gap-2 border-t border-border/40 pt-2">
              <button
                type="button"
                onClick={() => setMode("edit")}
                className="rounded border border-border px-3 py-1 text-xs hover:bg-muted"
              >
                ✎ 수정
              </button>
              <button
                type="button"
                onClick={() => setMode("close")}
                className="rounded border border-red-500/40 px-3 py-1 text-xs text-red-400 hover:bg-red-500/10"
              >
                청산
              </button>
              {history.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowHistory(!showHistory)}
                  className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                >
                  이력 {showHistory ? "▲" : "▼"} ({history.length})
                </button>
              )}
            </div>
          )}
        </>
      )}

      {/* 편집 폼 · 인라인 */}
      {mode === "edit" && (
        <EditForm
          j={j}
          currentPrice={currentPrice}
          onCancel={() => setMode("view")}
          onSaved={() => {
            setMode("view");
            onChanged();
          }}
        />
      )}

      {/* 청산 폼 */}
      {mode === "close" && (
        <CloseForm
          j={j}
          currentPrice={currentPrice}
          onCancel={() => setMode("view")}
          onClosed={() => {
            setMode("view");
            onChanged();
          }}
        />
      )}

      {/* 이력 접힘 */}
      {mode === "view" && showHistory && history.length > 0 && (
        <div className="mt-3 space-y-1 rounded border border-border/40 bg-background/40 p-2 text-[11px]">
          {history.map((h, i) => (
            <div key={i} className="border-b border-border/20 pb-1 last:border-0">
              <div className="text-[10px] text-muted-foreground">
                {new Date(h.at).toLocaleString("ko-KR")} · <em>{h.note}</em>
              </div>
              <div className="mt-0.5 font-mono">
                {Object.keys(h.after).map((k) => (
                  <span key={k} className="mr-3">
                    {k}: <span className="text-muted-foreground">{String(h.before[k] ?? "—")}</span>
                    {" → "}
                    <span className="font-bold">{String(h.after[k])}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── 인라인 편집 폼 (Fable 5 · 2026-08-14) ────────────────────────────
// 필수: change_note + mood 재선택 (이전값 미리 선택 X)
// 가드: invalidation 하향 편집 시 10초 카운트다운 (예외: 비정상 상태 정상화)

function EditForm({
  j,
  currentPrice,
  onCancel,
  onSaved,
}: {
  j: Judgment;
  currentPrice: number | undefined;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [invalidation, setInvalidation] = useState(String(j.invalidation_price ?? ""));
  const [target, setTarget] = useState(j.target_price !== null ? String(j.target_price) : "");
  const [horizon, setHorizon] = useState(j.horizon_days);
  const [thesis, setThesis] = useState(j.thesis_md);
  const [note, setNote] = useState("");
  const [mood, setMood] = useState<"cool" | "neutral" | "revenge" | "fomo" | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 하향 편집 감지 (롱 기준: invalidation 이 내려가는 방향)
  const invNew = parseFloat(invalidation);
  const invOld = j.invalidation_price;
  const isLowering =
    Number.isFinite(invNew) &&
    invOld !== null &&
    invNew < invOld;
  // 예외: 비정상 상태 (invalidation >= 현재가) 정상화 (현재가 아래로 내림)
  const isFixingAbnormal =
    isLowering &&
    currentPrice !== undefined &&
    invOld !== null &&
    invOld >= currentPrice &&
    invNew < currentPrice;
  const needsCountdown = isLowering && !isFixingAbnormal;

  const canSave =
    note.trim().length > 0 &&
    mood !== null &&
    !submitting &&
    (!needsCountdown || countdown === 0);

  const startCountdown = () => {
    if (countdown !== null) return;
    setCountdown(10);
  };

  useEffect(() => {
    if (countdown === null || countdown === 0) return;
    const t = setTimeout(() => setCountdown(countdown - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const moveTargetToWish = () => {
    if (!target.trim()) return;
    const wishLine = `\n\n장기 신념: ${j.ticker} $${target} (target 필드에서 이관 · ${new Date().toLocaleDateString("ko-KR")})`;
    setThesis(thesis + wishLine);
    setTarget("");
    if (!note) setNote("target 소원으로 이관");
  };

  const submit = async () => {
    setError(null);
    if (!Number.isFinite(invNew)) {
      setError("invalidation 숫자 형식 오류");
      return;
    }
    if (!mood) {
      setError("지금 기분 재선택 필수");
      return;
    }
    setSubmitting(true);
    const body: Record<string, unknown> = {
      change_note: note.trim(),
      mood,
    };
    if (invNew !== invOld) body.invalidation_price = invNew;
    const tgtNew = target.trim() ? parseFloat(target) : null;
    if (tgtNew !== j.target_price) body.target_price = tgtNew;
    if (horizon !== j.horizon_days) body.horizon_days = horizon;
    if (thesis !== j.thesis_md) body.thesis_md = thesis;
    try {
      const r = await fetch(`/api/v1/judgments/${j.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-3 space-y-3 rounded border border-primary/30 bg-primary/5 p-3 text-sm">
      <div className="text-xs font-semibold text-primary">✎ 판정 수정</div>

      {/* 값 4 · invalidation·target·horizon·thesis */}
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="block">
          <div className="text-[10px] text-muted-foreground">Invalidation</div>
          <input
            type="number"
            step="any"
            value={invalidation}
            onChange={(e) => setInvalidation(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
          />
          {currentPrice !== undefined && (
            <div className="mt-0.5 text-[9px] text-muted-foreground">
              현재가 {currentPrice.toLocaleString()}
            </div>
          )}
        </label>
        <label className="block">
          <div className="text-[10px] text-muted-foreground">
            Target
            {target.trim() && (
              <button
                type="button"
                onClick={moveTargetToWish}
                className="ml-2 text-[9px] text-sky-500 hover:underline"
              >
                소원으로 이관
              </button>
            )}
          </div>
          <input
            type="number"
            step="any"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
          />
        </label>
        <label className="block">
          <div className="text-[10px] text-muted-foreground">Horizon (일)</div>
          <input
            type="number"
            min={1}
            max={3650}
            value={horizon}
            onChange={(e) => setHorizon(parseInt(e.target.value) || 30)}
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
          />
        </label>
      </div>

      <label className="block">
        <div className="text-[10px] text-muted-foreground">Thesis / 사건 조건</div>
        <textarea
          value={thesis}
          onChange={(e) => setThesis(e.target.value)}
          rows={5}
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
        />
      </label>

      {/* 필수 1 · change_note */}
      <label className="block">
        <div className="text-[10px] text-muted-foreground">
          변경 사유 <span className="text-red-500">*</span>
        </div>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="한 줄 · 왜 수정하는지"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </label>

      {/* 필수 2 · mood 재선택 (이전값 미리 선택 X · 매번 새로 탭) */}
      <div>
        <div className="text-[10px] text-muted-foreground">
          지금 기분 <span className="text-red-500">*</span>
          <span className="ml-2 text-muted-foreground/70">(재선택 필수 · 이전값 미리 선택 X)</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {(["cool", "neutral", "revenge", "fomo"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMood(m)}
              className={
                "rounded border px-3 py-1 text-xs " +
                (mood === m
                  ? "border-primary bg-primary/20 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted")
              }
            >
              {m === "cool" && "🧘 Cool"}
              {m === "neutral" && "😐 Neutral"}
              {m === "revenge" && "😡 Revenge"}
              {m === "fomo" && "🔥 FOMO"}
            </button>
          ))}
        </div>
        {(mood === "revenge" || mood === "fomo") && (
          <div className="mt-1 text-[10px] text-red-400">
            🚫 이 상태의 변경은 저장은 되지만 카드에 「오늘 실행 금지」 태그가 붙습니다.
          </div>
        )}
      </div>

      {/* 하향 편집 카운트다운 (Fable 5 가드) */}
      {needsCountdown && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-xs">
          <div className="font-semibold text-red-500">
            🚨 손절선을 내리는 중입니다 ({invOld} → {invNew}).
          </div>
          <div className="mt-1 text-muted-foreground">
            물타기의 문서 버전이 아닌지 확인하십시오.
          </div>
          {countdown === null ? (
            <button
              type="button"
              onClick={startCountdown}
              className="mt-2 rounded bg-red-500/20 px-3 py-1 text-xs text-red-400 hover:bg-red-500/30"
            >
              그래도 진행 (10초 카운트다운)
            </button>
          ) : (
            <div className="mt-2 font-mono">
              {countdown > 0 ? `⏱ ${countdown}초 후 저장 가능...` : "✓ 카운트다운 완료 · 저장 가능"}
            </div>
          )}
        </div>
      )}
      {isFixingAbnormal && (
        <div className="rounded border border-emerald-500/40 bg-emerald-500/10 p-2 text-[10px] text-emerald-400">
          ✓ 첫 정정 (발동 상태 해소) · 카운트다운 예외 · 즉시 저장 가능
        </div>
      )}

      {error && <div className="text-xs text-red-500">⚠ {error}</div>}

      <div className="flex gap-2 border-t border-border/40 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
        >
          취소
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={!canSave}
          className="ml-auto rounded bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50 hover:bg-primary/80"
          title={!canSave ? "변경 사유·기분 필수 (하향 편집 시 카운트다운 완료)" : undefined}
        >
          {submitting ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}

// ─── 청산 폼 (신규 판정 + 이전 판정 supersede) ─────────────────────────

function CloseForm({
  j,
  currentPrice,
  onCancel,
  onClosed,
}: {
  j: Judgment;
  currentPrice: number | undefined;
  onCancel: () => void;
  onClosed: () => void;
}) {
  const [closePrice, setClosePrice] = useState(String(currentPrice ?? ""));
  const [reason, setReason] = useState<"invalidation_hit" | "target_reached" | "manual" | null>(null);
  const [mood, setMood] = useState<"cool" | "neutral" | "revenge" | "fomo" | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave =
    reason !== null && mood !== null && closePrice.trim() !== "" && !submitting;

  const submit = async () => {
    setError(null);
    const priceNum = parseFloat(closePrice);
    if (!Number.isFinite(priceNum)) {
      setError("청산가 숫자 형식 오류");
      return;
    }
    if (!reason || !mood) return;
    const reasonLabel =
      reason === "invalidation_hit" ? "invalidation 도달"
      : reason === "target_reached" ? "target 도달"
      : "수동 판단";
    setSubmitting(true);
    try {
      // 1) 신규 청산 판정 저장
      const thesis = `[청산 · ${reasonLabel}]\n청산가: ${priceNum}\n사유: ${note || reasonLabel}\n기분: ${mood}`;
      const createR = await fetch("/api/v1/judgments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: j.ticker,
          page_source: "close",
          hypothesis_id: `close-v1-${reason}`,
          thesis_md: thesis,
          invalidation_price: priceNum,  // 청산 판정 · invalidation = 청산가 (기록용)
          horizon_days: 1,
          mood,
        }),
      });
      if (!createR.ok) throw new Error(`create ${createR.status}`);
      const newRow = await createR.json();
      // 2) 이전 판정 supersede
      const sr = await fetch(`/api/v1/judgments/${j.id}/supersede`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          by_id: newRow.id,
          reason: `청산 (${reasonLabel}) @ ${priceNum}`,
        }),
      });
      if (!sr.ok) throw new Error(`supersede ${sr.status}`);
      onClosed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-3 space-y-3 rounded border border-red-500/40 bg-red-500/5 p-3 text-sm">
      <div className="text-xs font-semibold text-red-400">청산 판정</div>

      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block">
          <div className="text-[10px] text-muted-foreground">청산가 <span className="text-red-500">*</span></div>
          <input
            type="number"
            step="any"
            value={closePrice}
            onChange={(e) => setClosePrice(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
          />
        </label>
        <label className="block">
          <div className="text-[10px] text-muted-foreground">메모 (선택)</div>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="한 줄"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
          />
        </label>
      </div>

      <div>
        <div className="text-[10px] text-muted-foreground">청산 사유 <span className="text-red-500">*</span></div>
        <div className="mt-1 flex flex-wrap gap-2">
          {[
            { v: "invalidation_hit" as const, label: "invalidation 도달" },
            { v: "target_reached" as const, label: "target 도달" },
            { v: "manual" as const, label: "수동 판단" },
          ].map((o) => (
            <button
              key={o.v}
              type="button"
              onClick={() => setReason(o.v)}
              className={
                "rounded border px-3 py-1 text-xs " +
                (reason === o.v
                  ? "border-red-500 bg-red-500/20 text-red-400"
                  : "border-border text-muted-foreground hover:bg-muted")
              }
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="text-[10px] text-muted-foreground">
          지금 기분 <span className="text-red-500">*</span>
          <span className="ml-2 text-muted-foreground/70">(재선택 필수)</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {(["cool", "neutral", "revenge", "fomo"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMood(m)}
              className={
                "rounded border px-3 py-1 text-xs " +
                (mood === m
                  ? "border-primary bg-primary/20 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted")
              }
            >
              {m === "cool" && "🧘 Cool"}
              {m === "neutral" && "😐 Neutral"}
              {m === "revenge" && "😡 Revenge"}
              {m === "fomo" && "🔥 FOMO"}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="text-xs text-red-500">⚠ {error}</div>}

      <div className="flex gap-2 border-t border-border/40 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
        >
          취소
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={!canSave}
          className="ml-auto rounded bg-red-500 px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50 hover:bg-red-500/80"
        >
          {submitting ? "저장 중..." : "청산 판정 저장 · 이전 판정 supersede"}
        </button>
      </div>
    </div>
  );
}

// ─── 신규 판정 입력 폼 (2026-08-14 · Fable 5 · 30건 캠페인) ────────────

function NewJudgmentForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [ticker, setTicker] = useState("");
  const [thesis, setThesis] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [target, setTarget] = useState("");
  const [entry, setEntry] = useState("");
  const [horizon, setHorizon] = useState(30);
  const [mood, setMood] = useState<"cool" | "neutral" | "revenge" | "fomo">("neutral");
  const [pageSource, setPageSource] = useState("manual");
  const [hypothesisId, setHypothesisId] = useState("manual-v1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const reset = () => {
    setTicker("");
    setThesis("");
    setInvalidation("");
    setTarget("");
    setEntry("");
    setHorizon(30);
    setMood("neutral");
    setPageSource("manual");
    setHypothesisId("manual-v1");
  };

  const submit = async () => {
    setError(null);
    setSuccess(null);
    if (!ticker.trim() || !thesis.trim() || !invalidation.trim()) {
      setError("ticker · thesis · invalidation_price 는 필수");
      return;
    }
    const invNum = parseFloat(invalidation);
    if (!Number.isFinite(invNum)) {
      setError("invalidation_price 숫자 형식 오류");
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        ticker: ticker.trim().toUpperCase(),
        page_source: pageSource.trim() || "manual",
        hypothesis_id: hypothesisId.trim() || "manual-v1",
        thesis_md: thesis,
        invalidation_price: invNum,
        horizon_days: Math.max(1, Math.min(3650, horizon)),
        mood,
      };
      if (target.trim()) {
        const t = parseFloat(target);
        if (Number.isFinite(t)) body.target_price = t;
      }
      if (entry.trim()) {
        const e = parseFloat(entry);
        if (Number.isFinite(e)) body.entry_price = e;
      }
      const r = await fetch("/api/v1/judgments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
      const saved = await r.json();
      setSuccess(`✅ 저장 · id=${saved.id} · ${saved.ticker}`);
      reset();
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between p-4 text-left"
      >
        <span>
          <span className="text-sm font-semibold">📝 신규 판정 기록</span>
          <span className="ml-2 text-xs text-muted-foreground">
            보유 이유 · 청산 조건 · 지금 기분 3줄 (Fable 5)
          </span>
        </span>
        <span className="text-xs text-muted-foreground">{open ? "▲ 접기" : "▼ 펼치기"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-border/40 p-4 text-sm">
          {/* 티커·페이지·가설 */}
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <div className="text-xs text-muted-foreground">Ticker <span className="text-red-500">*</span></div>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="예: NBIS · 005930 · WEN"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
              />
            </label>
            <label className="block">
              <div className="text-xs text-muted-foreground">Page source</div>
              <input
                type="text"
                value={pageSource}
                onChange={(e) => setPageSource(e.target.value)}
                placeholder="manual / positions / watchlist"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
              />
            </label>
            <label className="block">
              <div className="text-xs text-muted-foreground">Hypothesis id</div>
              <input
                type="text"
                value={hypothesisId}
                onChange={(e) => setHypothesisId(e.target.value)}
                placeholder="manual-v1"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
              />
            </label>
          </div>

          {/* Thesis */}
          <label className="block">
            <div className="text-xs text-muted-foreground">
              Thesis (판정 본문) <span className="text-red-500">*</span>
              <span className="ml-2 text-muted-foreground/70">
                권장 3줄: 보유 이유 · 청산 조건 · 지금 기분
              </span>
            </div>
            <textarea
              value={thesis}
              onChange={(e) => setThesis(e.target.value)}
              rows={5}
              placeholder="보유 이유: ...&#10;청산 조건: ...&#10;지금 기분: ..."
              className="mt-1 w-full rounded border border-border bg-background px-2 py-2 text-sm font-mono"
            />
          </label>

          {/* 가격 · 기한 */}
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="block">
              <div className="text-xs text-muted-foreground">
                Invalidation <span className="text-red-500">*</span>
              </div>
              <input
                type="number"
                step="any"
                value={invalidation}
                onChange={(e) => setInvalidation(e.target.value)}
                placeholder="손절가"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
              />
            </label>
            <label className="block">
              <div className="text-xs text-muted-foreground">Target (선택)</div>
              <input
                type="number"
                step="any"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="목표가"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
              />
            </label>
            <label className="block">
              <div className="text-xs text-muted-foreground">Entry (선택 · R:R)</div>
              <input
                type="number"
                step="any"
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                placeholder="진입가"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
              />
            </label>
            <label className="block">
              <div className="text-xs text-muted-foreground">Horizon (일)</div>
              <input
                type="number"
                min={1}
                max={365}
                value={horizon}
                onChange={(e) => setHorizon(parseInt(e.target.value) || 30)}
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 font-mono text-sm"
              />
            </label>
          </div>

          {/* Mood */}
          <div>
            <div className="text-xs text-muted-foreground">Mood (Kahneman hot/cold)</div>
            <div className="mt-1 flex flex-wrap gap-2">
              {(["cool", "neutral", "revenge", "fomo"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMood(m)}
                  className={
                    "rounded border px-3 py-1 text-xs " +
                    (mood === m
                      ? "border-primary bg-primary/20 text-primary"
                      : "border-border text-muted-foreground hover:bg-muted")
                  }
                >
                  {m === "cool" && "🧘 Cool"}
                  {m === "neutral" && "😐 Neutral"}
                  {m === "revenge" && "😡 Revenge"}
                  {m === "fomo" && "🔥 FOMO"}
                </button>
              ))}
            </div>
          </div>

          {/* 액션 */}
          <div className="flex items-center justify-between border-t border-border/40 pt-3">
            <div className="text-xs">
              {error && <span className="text-red-500">⚠ {error}</span>}
              {success && <span className="text-emerald-500">{success}</span>}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={reset}
                disabled={submitting}
                className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
              >
                초기화
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting}
                className="rounded bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50 hover:bg-primary/80"
              >
                {submitting ? "저장 중..." : "저장"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
