"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  SniperStatus,
  WatchlistItem,
  WatchlistReport,
  WatchlistSignal,
} from "@/lib/api";
import { fmtKstDateTime, fmtKstTime, fmtKstDate } from "@/lib/time";

const TOKEN_KEY = "sniper_api_token"; // sniper 와 공유

export default function WatchlistPage() {
  const [token, setToken] = useState<string>("");
  const [tradeDate, setTradeDate] = useState<string>("");   // 빈 값이면 서버 default (next_trade_date)
  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem(TOKEN_KEY) || "");
    }
  }, []);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🌙 Watchlist · 마감후 예측</h1>
        <p className="text-sm text-muted-foreground">
          야간 축적 신호(뉴스·종토방·유튜브·국회·정부) → 08:30 KST 확정 → 개장 즉시 급등 전 매수 후보
        </p>
      </header>

      <PrincipleBanner />
      <ExecuteStatusPanel />
      <TokenHint token={token} />
      <DateSelector tradeDate={tradeDate} setTradeDate={setTradeDate} />
      <WatchlistTable tradeDate={tradeDate} token={token} />
      <ManualAdd tradeDate={tradeDate} token={token} />
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
          📈 Sprint 2 DoD Report
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
          ⚡ 개장 실행 설정 (Week 3 T64~T66)
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
      {we?.enabled && !s?.live_enabled ? (
        <div className="mt-2 rounded border border-amber-300 bg-amber-100 px-2 py-1 text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          ⚠️ watchlist_execute.enabled=ON 이지만 SNIPER_LIVE_ENABLED=false · 실주문 시도해도 auth 차단됨.
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
        <li>3. 급등 전 매수 (09:00~09:30 KST · Watchlist 종목만 시가 근처 진입)</li>
      </ul>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// Token 안내 (sniper 페이지에서 저장된 값 재사용)
// ═══════════════════════════════════════════════════════════════
function TokenHint({ token }: { token: string }) {
  if (token) {
    return (
      <div className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
        🔐 X-API-Token 감지됨 · 편집·finalize 요청 자동 첨부
      </div>
    );
  }
  return (
    <div className="rounded border border-orange-300 bg-orange-50 px-3 py-2 text-xs text-orange-900 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-100">
      ⚠️ X-API-Token 미저장 · 편집·finalize 불가. 먼저{" "}
      <a href="/sniper" className="underline">
        /sniper
      </a>{" "}
      에서 토큰 저장 필요.
    </div>
  );
}

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
function WatchlistTable({ tradeDate, token }: { tradeDate: string; token: string }) {
  const qc = useQueryClient();
  const q = useQuery<{ trade_date: string; size: number; items: WatchlistItem[] }>({
    queryKey: ["watchlist", "list", tradeDate || "default"],
    queryFn: () => api.watchlist.list(tradeDate || undefined),
    refetchInterval: 30_000,
  });

  const finalize = useMutation({
    mutationFn: () =>
      api.watchlist.finalize(token, { trade_date: tradeDate || undefined, top_n: 30 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const toggleLock = useMutation({
    mutationFn: ({ id, locked }: { id: number; locked: boolean }) =>
      api.watchlist.toggleLock(token, id, locked),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.watchlist.remove(token, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
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
            disabled={!token || finalize.isPending}
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
                <th className="p-2 text-left">종목</th>
                <th className="p-2 text-right">종합 점수</th>
                <th className="p-2 text-right">뉴스</th>
                <th className="p-2 text-right">종토방</th>
                <th className="p-2 text-right">유튜브</th>
                <th className="p-2 text-right">이벤트</th>
                <th className="p-2 text-center">소스</th>
                <th className="p-2 text-center">상태</th>
                <th className="p-2 text-center">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className="border-b hover:bg-sky-50/30">
                  <td className="p-2 font-bold">{it.rank}</td>
                  <td className="p-2">
                    <div className="font-medium">{it.name || "-"}</div>
                    <div className="text-[10px] text-muted-foreground">{it.ticker}</div>
                  </td>
                  <td className="p-2 text-right font-bold text-sky-700">
                    {it.composite_score.toFixed(3)}
                  </td>
                  <td className="p-2 text-right">{fmt3(it.news_score)}</td>
                  <td className="p-2 text-right">{fmt3(it.board_score)}</td>
                  <td className="p-2 text-right">{fmt3(it.youtube_score)}</td>
                  <td className="p-2 text-right">{fmt3(it.event_score)}</td>
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
                        disabled={!token || toggleLock.isPending}
                        onClick={() => toggleLock.mutate({ id: it.id, locked: !it.locked })}
                        className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-amber-50 disabled:opacity-30"
                        title={it.locked ? "unlock (다음 finalize 시 재평가)" : "lock (다음 finalize 시 유지)"}
                      >
                        {it.locked ? "unlock" : "lock"}
                      </button>
                      <button
                        type="button"
                        disabled={!token || remove.isPending}
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
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

function shortSource(s: string) {
  if (s.startsWith("news_")) return s.replace("news_", "");
  if (s.startsWith("youtube_")) return "yt·" + s.replace("youtube_", "");
  if (s === "board_naver") return "종토방";
  if (s === "assembly") return "국회";
  if (s.endsWith("_rss")) return s.replace("_rss", "");
  return s;
}

// ═══════════════════════════════════════════════════════════════
// 수동 add
// ═══════════════════════════════════════════════════════════════
function ManualAdd({ tradeDate, token }: { tradeDate: string; token: string }) {
  const qc = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [name, setName] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.watchlist.addManual(token, {
        ticker,
        trade_date: tradeDate || undefined,
        name: name || undefined,
      }),
    onSuccess: () => {
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
          disabled={!token || !ticker || add.isPending}
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
          신호 없음. 뉴스 5m · 종토방 30m · 유튜브 1h · 국회 06:00 KST 잡 대기.
        </div>
      )}
      {Object.entries(bySource).map(([source, sigs]) => (
        <details key={source} className="mb-2 rounded border bg-slate-50 dark:bg-slate-900">
          <summary className="cursor-pointer p-2 text-xs font-medium">
            {source} · {sigs.length}건
          </summary>
          <ul className="space-y-0.5 p-2 text-[10px]">
            {sigs.slice(0, 30).map((s) => (
              <li key={s.id} className="flex gap-2">
                <span className="font-mono text-muted-foreground">{s.ticker}</span>
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
