"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { StockLink } from "@/components/stock/StockLink";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  SniperStatus,
  WatchlistItem,
  WatchlistEvidence,
  WatchlistRankEvidence,
  WatchlistSourceStatus,
  WatchlistReport,
  WatchlistSignal,
} from "@/lib/api";
import { fmtKstDateTime, fmtKstTime, fmtKstDate } from "@/lib/time";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { JudgmentDialog } from "@/components/journal/JudgmentDialog";

export default function WatchlistPage() {
  // Phase D 주 7 (2026-07-31) · localStorage 토큰 → httpOnly 쿠키 세션.
  const [isAdmin, setIsAdmin] = useState<boolean>(false);
  const [tradeDate, setTradeDate] = useState<string>("");   // 빈 값이면 서버 default (next_trade_date)

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🌙 Watchlist · 마감후 예측</h1>
        <p className="text-sm text-muted-foreground">
          야간 축적 신호(뉴스·개인 관심·유튜브·공시·전일 순위) → 08:30 KST 확정 → 봇 자동 진입 창 (09:00~09:30) 의 대상 종목
        </p>
      </header>

      <PrincipleBanner />
      <ExecuteStatusPanel />
      <AdminSessionBar
        scope="watchlist"
        onSessionChange={(info) => setIsAdmin(info.role === "admin")}
      />
      <DateSelector tradeDate={tradeDate} setTradeDate={setTradeDate} />
      <WatchlistTable tradeDate={tradeDate} isAdmin={isAdmin} />
      <ManualAdd tradeDate={tradeDate} isAdmin={isAdmin} />
      <DoDReportPanel />
      <SignalsInspector tradeDate={tradeDate} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Sprint 2 DoD Report (Week 4 T70)
// ═══════════════════════════════════════════════════════════════
function DoDReportPanel() {
  const [days, setDays] = useState(30);
  const q = useQuery<WatchlistReport>({
    queryKey: ["watchlist", "report", days],
    queryFn: () => api.watchlist.report(days),
    refetchInterval: 60_000,
  });
  const r = q.data;
  return (
    <section className="rounded border p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold">
          📈 예측 성적표
          {r ? (
            <span
              className={`ml-3 rounded px-2 py-0.5 text-xs ${
                r.total_pass
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"
                  : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100"
              }`}
            >
              {r.total_pass ? "✅ PASS" : "⛔ 미달"}
            </span>
          ) : null}
        </h2>
        <div className="flex items-center gap-1 text-xs">
          <span className="text-muted-foreground">기간</span>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border px-1 py-0.5"
          >
            <option value={7}>7일</option>
            <option value={14}>14일</option>
            <option value={30}>30일</option>
            <option value={60}>60일</option>
          </select>
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        기준: 승률 ≥ 45% · R:R ≥ 2.0 · MDD ≤ -15% · 매매 ≥ 5건
      </p>
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : r ? (
        <>
          <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-4">
            <Stat label="총 매매" value={String(r.closed_trades)} />
            <Stat label="승 / 패" value={`${r.metrics.wins} / ${r.metrics.losses}`} />
            <Stat label="승률" value={`${(r.metrics.win_rate * 100).toFixed(1)}%`} />
            <Stat label="평균 PnL" value={`${(r.metrics.avg_pnl_pct * 100).toFixed(2)}%`} />
            <Stat label="평균 승" value={`${(r.metrics.avg_win_pct * 100).toFixed(2)}%`} />
            <Stat label="평균 패" value={`${(r.metrics.avg_loss_pct * 100).toFixed(2)}%`} />
            <Stat label="R:R" value={r.metrics.r_r_ratio.toFixed(2)} />
            <Stat label="MDD" value={`${(r.metrics.mdd_pct * 100).toFixed(2)}%`} />
          </div>
          <div className="grid gap-1">
            {r.checks.map((c) => (
              <div
                key={c.name}
                className={`flex items-center gap-2 rounded border px-2 py-1 text-xs ${
                  c.passed ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"
                }`}
              >
                <span className="w-4">{c.passed ? "✅" : "⛔"}</span>
                <span className="font-mono">{c.name}</span>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground">목표 {c.target}</span>
                <span className="ml-auto font-bold">실제 {c.actual}</span>
              </div>
            ))}
          </div>
          {r.metrics.reason_breakdown && Object.keys(r.metrics.reason_breakdown).length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
              {Object.entries(r.metrics.reason_breakdown).map(([k, v]) => (
                <span
                  key={k}
                  className="rounded bg-slate-100 px-1.5 py-0.5 dark:bg-slate-800"
                >
                  {k}: {v}
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <div className="text-xs text-muted-foreground">데이터 없음</div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between rounded border bg-slate-50 px-2 py-1 dark:bg-slate-900">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-bold">{value}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// 개장 실행 설정 상태 (Week 3 T64/T65/T66)
// ═══════════════════════════════════════════════════════════════
function ExecuteStatusPanel() {
  const q = useQuery<SniperStatus>({
    queryKey: ["sniper", "status"],
    queryFn: api.sniper.status,
    refetchInterval: 15_000,
  });
  const s = q.data;
  const we = s?.watchlist_execute;

  return (
    <section className="rounded border-2 border-sky-200 bg-sky-50 p-3 text-xs dark:border-sky-900 dark:bg-sky-950">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-bold text-sky-900 dark:text-sky-100">
          ⚡ 자동 진입 창 설정
        </div>
        <a href="/sniper" className="text-sky-600 hover:underline">
          ⚙️ 파라미터 편집 →
        </a>
      </div>
      {!we ? (
        <div className="text-muted-foreground">불러오는 중...</div>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] md:grid-cols-3">
          <div>
            <span className="text-muted-foreground">활성 </span>
            <span className={we.enabled ? "font-bold text-emerald-600" : "font-bold text-red-600"}>
              {we.enabled ? "🟢 ON" : "⛔ OFF"}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">활성창 </span>
            <span className="font-mono">{we.start_kst} ~ {we.end_kst} KST</span>
          </div>
          <div>
            <span className="text-muted-foreground">갭업 범위 </span>
            <span className="font-mono">
              +{(we.gap_min_pct * 100).toFixed(1)}% ~ +{(we.gap_max_pct * 100).toFixed(1)}%
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">최소 점수 </span>
            <span className="font-mono">{we.min_composite_score.toFixed(2)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Rankings confirm </span>
            <span>{we.use_rankings_confirm ? "on" : "off"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Broker </span>
            <span className={s?.sniper_enabled ? "text-emerald-600" : "text-muted-foreground"}>
              {s?.sniper_enabled ? "sniper.enabled=on" : "sniper.enabled=off"}
            </span>
          </div>
        </div>
      )}
      {/* 1025-07 · 관심 종목 자동 진입은 실주문 허용 값을 보지 않고 주문 대상 (EXECUTION_BROKER) 만 본다 */}
      {we?.enabled ? (
        <div className="mt-2 rounded border border-amber-300 bg-amber-100 px-2 py-1 text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          ⚠️ 관심 종목 자동 진입이 켜져 있습니다 · 주문 대상: {s?.order_target === "toss" ? "실계좌 (실제 돈)" : "모의 계좌 (실계좌 주문 없음)"}
        </div>
      ) : null}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// 원칙 배너 (전략 pivot 명시)
// ═══════════════════════════════════════════════════════════════
function PrincipleBanner() {
  return (
    <section className="rounded border-2 border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950">
      <div className="font-bold text-amber-900 dark:text-amber-100">
        🎯 3원칙 (2026-07-13 pivot)
      </div>
      <ul className="mt-1 space-y-0.5 text-xs text-amber-800 dark:text-amber-200">
        <li>1. 마감 후 예측 결정 (15:30 KST~ · 뉴스·소셜·이벤트 야간 축적)</li>
        <li>2. 개장 전 최종 Watchlist (08:30 KST · Top 30 확정 · 수동 편집 가능)</li>
        <li>3. 자동 진입 창 (09:00~09:30 KST · 봇이 Watchlist 종목만 시가 근처에서 진입 · 실행 스위치가 켜졌을 때만)</li>
      </ul>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// (Phase D 주 7) TokenHint 제거 · 공용 AdminSessionBar 사용
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
// 날짜 선택
// ═══════════════════════════════════════════════════════════════
function DateSelector({
  tradeDate,
  setTradeDate,
}: {
  tradeDate: string;
  setTradeDate: (v: string) => void;
}) {
  const q = useQuery<string[]>({
    queryKey: ["watchlist", "dates"],
    queryFn: () => api.watchlist.dates(),
    refetchInterval: 60_000,
  });

  return (
    <section className="rounded border p-3">
      <div className="mb-2 flex items-center gap-3">
        <label className="text-xs text-muted-foreground">거래일</label>
        <input
          type="date"
          value={tradeDate}
          onChange={(e) => setTradeDate(e.target.value)}
          className="rounded border px-2 py-1 text-sm"
        />
        {tradeDate && (
          <button
            type="button"
            onClick={() => setTradeDate("")}
            className="text-xs text-sky-600 hover:underline"
          >
            ↺ 다음 영업일로
          </button>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {tradeDate ? `조회: ${tradeDate}` : "조회: 다음 영업일 (자동)"}
        </span>
      </div>
      {q.data && q.data.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {q.data.slice(0, 10).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setTradeDate(d)}
              className={`rounded px-2 py-0.5 text-[10px] ${
                d === tradeDate
                  ? "bg-sky-600 text-white"
                  : "border hover:bg-sky-50"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// Watchlist 표 (Top 30)
// ═══════════════════════════════════════════════════════════════
function WatchlistTable({ tradeDate, isAdmin }: { tradeDate: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const q = useQuery<{ trade_date: string; size: number; items: WatchlistItem[] }>({
    queryKey: ["watchlist", "list", tradeDate || "default"],
    queryFn: () => api.watchlist.list(tradeDate || undefined),
    refetchInterval: 30_000,
  });

  const finalize = useMutation({
    mutationFn: () =>
      api.watchlist.finalize("", { trade_date: tradeDate || undefined, top_n: 30 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const toggleLock = useMutation({
    mutationFn: ({ id, locked }: { id: number; locked: boolean }) =>
      api.watchlist.toggleLock("", id, locked),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.watchlist.remove("", id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const src = useQuery<{ sources: WatchlistSourceStatus[]; score_version?: string | null }>({
    queryKey: ["watchlist", "sources"],
    queryFn: () => api.watchlist.sources(),
    refetchInterval: 300_000,
  });
  const off = new Set((src.data?.sources ?? []).filter((s) => !s.collecting).map((s) => s.key));
  // 수집하지 않는 칸의 0 은 「점수 0」이 아니라 「자료 없음」 · 1030-02
  const scoreCell = (key: WatchlistSourceStatus["key"], v: number | null | undefined) =>
    off.has(key) && !v ? <span className="text-[10px] text-muted-foreground">수집 안 함</span> : fmt3(v);

  const [open, setOpen] = useState<Set<number>>(new Set());
  const toggleOpen = (id: number) =>
    setOpen((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const items = q.data?.items ?? [];
  const showTradeDate = q.data?.trade_date ?? tradeDate;

  return (
    <section className="rounded border p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold">
          📊 Watchlist Top {q.data?.size ?? 0}
          <span className="ml-2 text-xs text-muted-foreground">
            거래일: {showTradeDate || "-"}
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!isAdmin || finalize.isPending}
            onClick={() => finalize.mutate()}
            className="rounded bg-sky-600 px-3 py-1 text-xs text-white disabled:opacity-50"
            title="지금 즉시 finalize 실행 (08:30 KST 잡과 동일)"
          >
            {finalize.isPending ? "실행 중..." : "🔄 지금 finalize"}
          </button>
        </div>
      </div>

      {finalize.data && (
        <div className="mb-2 rounded bg-slate-50 p-2 text-xs dark:bg-slate-900">
          ✅ finalize 완료 · {finalize.data.trade_date} · signals={finalize.data.signals_read} ·
          scored={finalize.data.candidates_scored} · written={finalize.data.written} (locked=
          {finalize.data.locked_kept} + auto={finalize.data.auto_picked})
        </div>
      )}
      {finalize.error && (
        <div className="mb-2 rounded bg-red-50 p-2 text-xs text-red-800 dark:bg-red-950">
          ⛔ finalize 실패 · {String((finalize.error as Error).message)}
        </div>
      )}

      <p className="mb-2 text-xs text-muted-foreground">
        점수 공식 {src.data?.score_version ?? "-"} · 점수는 0~1 · 수집 안 하는 칸은 빼고 계산합니다.
      </p>
      {src.data && <SourceStatusLine sources={src.data.sources} />}

      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          Watchlist 비어있음. 08:30 KST 자동 finalize 대기 · 또는 상단 "지금 finalize" 클릭.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-900">
                <th className="p-2 text-left">순위</th>
                <th className="p-2 text-left">근거</th>
                <th className="p-2 text-left">종목</th>
                <th className="p-2 text-right">종합 점수</th>
                <th className="p-2 text-right">뉴스</th>
                <th className="p-2 text-right">개인 관심</th>
                <th className="p-2 text-right">유튜브</th>
                <th className="p-2 text-right">이벤트</th>
                <th className="p-2 text-right">전일</th>
                <th className="p-2 text-center">소스</th>
                <th className="p-2 text-center">상태</th>
                <th className="p-2 text-center">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <Fragment key={it.id}>
                <tr className="border-b hover:bg-sky-50/30">
                  <td className="p-2 font-bold">{it.rank}</td>
                  <td className="p-2">
                    <button
                      type="button"
                      onClick={() => toggleOpen(it.id)}
                      aria-expanded={open.has(it.id)}
                      className="min-h-[44px] min-w-[44px] rounded border px-2 text-xs hover:bg-sky-50"
                    >
                      {open.has(it.id) ? "접기" : "근거"}
                    </button>
                  </td>
                  <td className="p-2">
                    <div className="font-medium">{it.name || "-"}</div>
                    <div className="text-[10px] text-muted-foreground"><StockLink ticker={it.ticker}>{it.ticker}</StockLink></div>
                  </td>
                  <td className="p-2 text-right font-bold text-sky-700">
                    {it.composite_score.toFixed(3)}
                    {it.evidence?.caution?.length ? (
                      <div className="mt-0.5 text-[10px] font-bold text-orange-700 dark:text-orange-300">⚠ 주의 공시</div>
                    ) : null}
                  </td>
                  <td className="p-2 text-right">{scoreCell("news", it.news_score)}</td>
                  <td className="p-2 text-right">{scoreCell("board", it.board_score)}</td>
                  <td className="p-2 text-right">{scoreCell("youtube", it.youtube_score)}</td>
                  <td className="p-2 text-right">{scoreCell("event", it.event_score)}</td>
                  <td className="p-2 text-right">{scoreCell("prev_day", it.prev_day_score)}</td>
                  <td className="p-2 text-center">
                    <SourceBadges breakdown={it.source_breakdown} />
                  </td>
                  <td className="p-2 text-center">
                    {it.locked ? (
                      <span
                        title="사용자 lock · finalize 실행 후에도 유지"
                        className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                      >
                        🔒 lock
                      </span>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">
                        {it.added_by}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    <div className="flex justify-center gap-1">
                      <button
                        type="button"
                        disabled={!isAdmin || toggleLock.isPending}
                        onClick={() => toggleLock.mutate({ id: it.id, locked: !it.locked })}
                        className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-amber-50 disabled:opacity-30"
                        title={it.locked ? "unlock (다음 finalize 시 재평가)" : "lock (다음 finalize 시 유지)"}
                      >
                        {it.locked ? "unlock" : "lock"}
                      </button>
                      <button
                        type="button"
                        disabled={!isAdmin || remove.isPending}
                        onClick={() => {
                          if (confirm(`삭제 · ${it.ticker} · id=${it.id}?`)) remove.mutate(it.id);
                        }}
                        className="rounded border border-red-300 px-1.5 py-0.5 text-[10px] text-red-700 hover:bg-red-50 disabled:opacity-30"
                        title="이 거래일 Watchlist 에서 완전 삭제"
                      >
                        ×
                      </button>
                    </div>
                  </td>
                </tr>
                {open.has(it.id) && (
                  <tr className="border-b bg-slate-50/60 dark:bg-slate-900/60">
                    <td colSpan={12} className="p-3">
                      <EvidenceBlock ev={it.evidence ?? null} version={it.score_version ?? null} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function rankSentence(r: WatchlistRankEvidence) {
  const rank = r.rank != null ? `${r.rank}위` : "순위 미상";
  let tail = "";
  if (r.is_new) tail = " (새로 진입)";
  else if (r.prev_rank != null && r.rank != null) tail = ` (${r.prev_rank}위→${r.rank}위)`;
  const rate = r.change_rate_pct != null ? ` · 등락률 ${r.change_rate_pct > 0 ? "+" : ""}${r.change_rate_pct}%` : "";
  return `${r.label} ${rank}${tail}${rate}`;
}

function EvidenceBlock({ ev, version }: { ev: WatchlistEvidence | null; version: string | null }) {
  if (!ev) {
    return (
      <div className="text-xs text-muted-foreground">
        근거 자료 없음 (직접 추가한 종목은 점수 근거를 저장하지 않습니다).
      </div>
    );
  }
  const none = (
    <li className="text-muted-foreground">없음</li>
  );
  const ranks = [...ev.interest, ...ev.prev_day];
  return (
    <div className="sticky left-0 max-w-[calc(100vw-5rem)] space-y-3 break-words text-xs md:max-w-none">
      {ev.caution.length > 0 && (
        <div className="rounded border-2 border-orange-400 bg-orange-50 p-2 text-orange-900 dark:bg-orange-950 dark:text-orange-100">
          <div className="font-bold">⚠ 주의 공시 (점수에 넣지 않음)</div>
          <ul className="mt-1 list-disc pl-4">
            {ev.caution.map((c, i) => (
              <li key={i}>{c.title}</li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <div className="font-semibold">
          뉴스 · 기사 {ev.news.count}건 · 언론사 {ev.news.publishers}곳
        </div>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {ev.news.articles.length === 0
            ? none
            : ev.news.articles.map((a, i) => (
                <li key={i}>
                  {a.url ? (
                    <a href={a.url} target="_blank" rel="noopener noreferrer" className="text-sky-700 underline dark:text-sky-300">
                      {a.title}
                    </a>
                  ) : (
                    a.title
                  )}
                  <span className="ml-1 text-muted-foreground">
                    {shortSource(a.source)}
                    {a.published ? ` · ${fmtKstDateTime(a.published)}` : ""}
                  </span>
                </li>
              ))}
        </ul>
      </div>
      <div>
        <div className="font-semibold">순위</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {ranks.length === 0 ? none : ranks.map((r, i) => <li key={i}>{rankSentence(r)}</li>)}
        </ul>
      </div>
      <div>
        <div className="font-semibold">유튜브 · 영상 {ev.youtube.count}건</div>
        {ev.youtube.videos.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {ev.youtube.videos.map((v, i) => (
              <li key={i}>{v.title}</li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="font-semibold">공시·이벤트</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {ev.event.length === 0
            ? none
            : ev.event.map((e, i) => (
                <li key={i}>
                  {e.title} <span className="text-muted-foreground">{shortSource(e.source)}</span>
                </li>
              ))}
        </ul>
      </div>
      {version && <div className="text-[10px] text-muted-foreground">점수 공식 {version}</div>}
    </div>
  );
}

function SourceStatusLine({ sources }: { sources: WatchlistSourceStatus[] }) {
  return (
    <div className="mb-2 rounded border border-border p-2 text-xs">
      <span className="font-semibold">수집 상태</span>
      <ul className="mt-1 space-y-0.5">
        {sources.map((s) => (
          <li key={s.key} className="flex flex-wrap gap-x-2">
            <span className="font-medium">{s.label}</span>
            {s.collecting ? (
              <span>
                수집 중 · 마지막 신호 {s.last_signal_at ? fmtKstDateTime(s.last_signal_at) : "최근 7일 없음"}
                {s.last_saved_at ? ` · 마지막 저장 ${fmtKstDateTime(s.last_saved_at)}` : ""}
              </span>
            ) : (
              <span className="text-red-600 dark:text-red-400">수집 안 함</span>
            )}
            {s.note && <span className="text-muted-foreground">{s.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function fmt3(v: number | null | undefined) {
  return v == null ? "-" : v.toFixed(3);
}

function SourceBadges({
  breakdown,
}: {
  breakdown: Record<string, { count: number; intensity_sum: number }> | null;
}) {
  if (!breakdown) return <span className="text-muted-foreground">-</span>;
  const sources = Object.keys(breakdown);
  return (
    <div className="flex flex-wrap justify-center gap-0.5">
      {sources.map((s) => (
        <span
          key={s}
          title={`${s} · count=${breakdown[s].count} · sum=${breakdown[s].intensity_sum}`}
          className="rounded bg-slate-100 px-1 py-0.5 text-[9px] text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {shortSource(s)}
        </span>
      ))}
    </div>
  );
}

// 언론사 한글 이름 (뉴스 출처 키 · backend news_rss.RSS_SOURCES 와 같은 이름)
const NEWS_NAMES: Record<string, string> = {
  news_yhap: "연합인포맥스",
  news_einfomax_all: "연합인포맥스",
  news_fnnews: "파이낸셜뉴스",
  news_hankyung: "한국경제",
  news_yonhap: "연합뉴스",
  news_yna_market: "연합뉴스",
  news_mk: "매일경제",
  news_sedaily: "서울경제",
  news_etoday: "이투데이",
  news_edaily: "이데일리",
};

const OTHER_NAMES: Record<string, string> = { rank_individual_netbuy: "개인 순매수", rank_toss_amount: "토스증권 체결 거래대금", rank_toss_volume: "토스증권 체결 거래량", rank_market_amount: "시장 거래대금", rank_market_volume: "시장 거래량", dart_disclosure: "공시", dart_caution: "주의 공시" };
function shortSource(s: string) {
  if (NEWS_NAMES[s]) return NEWS_NAMES[s];
  if (s.startsWith("news_")) return s.replace("news_", "");
  if (s.startsWith("youtube_")) return "yt·" + s.replace("youtube_", "");
  if (OTHER_NAMES[s]) return OTHER_NAMES[s];
  if (s === "board_naver") return "종토방";
  if (s === "assembly") return "국회";
  if (s.endsWith("_rss")) return s.replace("_rss", "");
  return s;
}

// ═══════════════════════════════════════════════════════════════
// 수동 add
// ═══════════════════════════════════════════════════════════════
function ManualAdd({ tradeDate, isAdmin }: { tradeDate: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [name, setName] = useState("");
  // Phase E · 판정 팝업 자동 트리거 · 수동 편입 성공 시 강제 판정 기록.
  const [judgmentOpen, setJudgmentOpen] = useState(false);
  const [judgmentTicker, setJudgmentTicker] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.watchlist.addManual("", {
        ticker,
        trade_date: tradeDate || undefined,
        name: name || undefined,
      }),
    onSuccess: () => {
      // 판정 팝업 트리거 (Phase B 주 3 계획 · Phase E 착수 · roadmap-12week.md)
      setJudgmentTicker(ticker);
      setJudgmentOpen(true);
      setTicker("");
      setName("");
      qc.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });

  return (
    <section className="rounded border p-4">
      <h2 className="mb-2 text-base font-bold">➕ 수동 add · locked=True</h2>
      <p className="mb-3 text-xs text-muted-foreground">
        사용자 판단으로 종목을 Watchlist 에 강제 편입. finalize 실행 후에도 유지됨.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.trim())}
          placeholder="티커 (예: 005930)"
          className="rounded border px-2 py-1 text-sm"
        />
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="종목명 (선택)"
          className="rounded border px-2 py-1 text-sm"
        />
        <button
          type="button"
          disabled={!isAdmin || !ticker || add.isPending}
          onClick={() => add.mutate()}
          className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50"
        >
          {add.isPending ? "추가 중..." : "🔒 추가 + lock"}
        </button>
        {add.data && (
          <span className="text-xs text-emerald-700">
            ✅ 저장 · id={add.data.id}
          </span>
        )}
        {add.error && (
          <span className="text-xs text-red-700">
            ⛔ {String((add.error as Error).message)}
          </span>
        )}
      </div>
      <JudgmentDialog
        open={judgmentOpen}
        onOpenChange={setJudgmentOpen}
        ticker={judgmentTicker}
        pageSource="watchlist"
        hypothesisId="watchlist-manual-add"
      />
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// 원본 signal Inspector (breakdown 감사)
// ═══════════════════════════════════════════════════════════════
function SignalsInspector({ tradeDate }: { tradeDate: string }) {
  const q = useQuery<{ count: number; items: WatchlistSignal[] }>({
    queryKey: ["watchlist", "signals", tradeDate || "default"],
    queryFn: () =>
      api.watchlist.signals({ trade_date: tradeDate || undefined, limit: 100 }),
    refetchInterval: 60_000,
  });

  const items = q.data?.items ?? [];

  const bySource = useMemo(() => {
    const acc: Record<string, WatchlistSignal[]> = {};
    for (const s of items) (acc[s.source] ||= []).push(s);
    return acc;
  }, [items]);

  return (
    <section className="rounded border p-4">
      <h2 className="mb-2 text-base font-bold">
        🔎 원본 signal (breakdown 감사)
        <span className="ml-2 text-xs text-muted-foreground">
          count={q.data?.count ?? 0}
        </span>
      </h2>
      {q.isLoading && (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      )}
      {!q.isLoading && items.length === 0 && (
        <div className="rounded border-2 border-dashed p-4 text-center text-xs text-muted-foreground">
          신호 없음. 뉴스 5분 · 유튜브 1시간 · 공시 08:20·20:40 · 순위 20:30 (KST) 수집 대기.
        </div>
      )}
      {Object.entries(bySource).map(([source, sigs]) => (
        <details key={source} className="mb-2 rounded border bg-slate-50 dark:bg-slate-900">
          <summary className="cursor-pointer p-2 text-xs font-medium">
            {shortSource(source)} · {sigs.length}건
          </summary>
          <ul className="space-y-0.5 p-2 text-[10px]">
            {sigs.slice(0, 30).map((s) => (
              <li key={s.id} className="flex gap-2">
                <span className="font-mono text-muted-foreground"><StockLink ticker={s.ticker}>{s.ticker}</StockLink></span>
                <span>{s.signal_type}</span>
                <span className="text-sky-700">int={s.intensity.toFixed(2)}</span>
                <span className="ml-auto text-muted-foreground">
                  {s.detected_at ? fmtKstTime(s.detected_at) : "-"}
                </span>
                {s.payload?.title ? (
                  <span className="ml-2 truncate italic">
                    &quot;{String(s.payload.title)}&quot;
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </section>
  );
}
