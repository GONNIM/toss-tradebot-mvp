"use client";

/**
 * Crazy Picks 페이지 — Top 10 테이블 + History 토글 + Thesis expand.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CrazyPick } from "@/lib/api";
import { formatMarketCap, formatUSD } from "@/lib/utils";

function parseJsonArray(s: string | null): string[] {
  if (!s) return [];
  try {
    const v = JSON.parse(s);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export default function CrazyPage() {
  const [tab, setTab] = useState<"today" | "history">("today");
  const [days, setDays] = useState(7);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            🎯 Crazy Picks
            <span className="rounded bg-gray-500/20 px-2 py-0.5 text-[10px] font-semibold text-gray-400">
              LAGGING
            </span>
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매일 06:30 KST · 시총 ≥ $1B 안전 universe · 정보 전용 (수동 매수) · 행 클릭 시 상세 보기
          </p>
          <p className="mt-1 text-[11px] text-amber-400/80">
            ⚠️ 모든 pick 의 outcome (T+7·T+30) 을 무조건 표시합니다. cherry-pick 금지 (리뷰 A 권고 2).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTab("today")}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              tab === "today"
                ? "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            최신
          </button>
          <button
            onClick={() => setTab("history")}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              tab === "history"
                ? "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            히스토리
          </button>
          {tab === "history" && (
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
            >
              <option value={3}>3일</option>
              <option value={7}>7일</option>
              <option value={14}>14일</option>
              <option value={30}>30일</option>
            </select>
          )}
        </div>
      </header>

      {tab === "today" ? <TodayTable /> : <HistoryTable days={days} />}
    </div>
  );
}

function TodayTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["crazy", "top"],
    queryFn: () => api.crazy.list(10),
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrBox />;
  if (!data || data.length === 0) return <Empty msg="저장된 Crazy Pick 없음. cron 활성 후 채워집니다." />;

  return <PicksTable picks={data} />;
}

function HistoryTable({ days }: { days: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["crazy", "history", days],
    queryFn: () => api.crazy.history(days),
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrBox />;
  if (!data || data.length === 0) return <Empty msg={`최근 ${days}일 Pick 없음.`} />;

  return <PicksTable picks={data} showDate />;
}

function PicksTable({ picks, showDate = false }: { picks: CrazyPick[]; showDate?: boolean }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggle = (id: number) => {
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40">
          <tr className="text-left">
            {showDate && <th className="px-4 py-3">날짜</th>}
            <th className="px-4 py-3">#</th>
            <th className="px-4 py-3">티커</th>
            <th className="px-4 py-3">회사</th>
            <th className="px-4 py-3">섹터</th>
            <th className="px-4 py-3 text-right">현재가</th>
            <th className="px-4 py-3 text-right">시총</th>
            <th className="px-4 py-3 text-right">점수</th>
            <th className="px-4 py-3 text-right" title="T+7 실 수익률 (cron 자동 · null=계산 대기)">T+7</th>
            <th className="px-4 py-3 text-right" title="T+30 실 수익률 (cron 자동 · null=계산 대기)">T+30</th>
            <th className="px-4 py-3">Thesis</th>
          </tr>
        </thead>
        <tbody>
          {picks.map((p) => {
            const isOpen = expanded.has(p.id);
            return (
              <>
                <tr
                  key={p.id}
                  className="cursor-pointer border-b border-border hover:bg-muted/20"
                  onClick={() => toggle(p.id)}
                >
                  {showDate && (
                    <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                      {p.pick_date}
                    </td>
                  )}
                  <td className="px-4 py-3 text-muted-foreground">#{p.rank}</td>
                  <td className="px-4 py-3 font-bold">
                    {isOpen ? "▾ " : "▸ "}
                    {p.ticker}
                  </td>
                  <td className="px-4 py-3 max-w-[180px] truncate">{p.company_name || "—"}</td>
                  <td className="px-4 py-3 text-muted-foreground">{p.sector || "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {p.close_price && p.close_price > 0 ? formatUSD(p.close_price) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{formatMarketCap(p.market_cap)}</td>
                  <td className="px-4 py-3 text-right font-bold">
                    {(p.composite_score ?? 0).toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    <PerfCell value={p.perf_1w} />
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    <PerfCell value={p.perf_1m} />
                  </td>
                  <td className="px-4 py-3 max-w-[300px] truncate text-muted-foreground">
                    {p.thesis || "(미생성)"}
                  </td>
                </tr>
                {isOpen && (
                  <tr key={`${p.id}-detail`} className="border-b border-border bg-muted/10">
                    <td colSpan={showDate ? 11 : 10} className="px-6 py-4">
                      <PickDetail pick={p} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PickDetail({ pick }: { pick: CrazyPick }) {
  const catalysts = parseJsonArray(pick.catalysts);
  const risks = parseJsonArray(pick.risks);
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="mb-1 font-semibold">📊 Thesis (전문)</div>
        <p className="whitespace-pre-line text-muted-foreground">
          {pick.thesis || "(미생성)"}
        </p>
      </div>

      {catalysts.length > 0 && (
        <div>
          <div className="mb-1 font-semibold text-green-400">🎯 Catalysts</div>
          <ul className="list-inside list-disc text-muted-foreground">
            {catalysts.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {risks.length > 0 && (
        <div>
          <div className="mb-1 font-semibold text-red-400">⚠️ Risks</div>
          <ul className="list-inside list-disc text-muted-foreground">
            {risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {pick.news_summary && (
        <div>
          <div className="mb-1 font-semibold text-cyan-400">📰 News summary</div>
          <p className="whitespace-pre-line text-muted-foreground">{pick.news_summary}</p>
        </div>
      )}
    </div>
  );
}

function Loading() {
  return <div className="text-muted-foreground">로딩 중...</div>;
}

function ErrBox() {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
      API 호출 실패.
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">{msg}</div>
  );
}

// Phase B 주 4-1 · outcome 셀 (cherry-pick 방지 · 모든 값 무조건 표시)
function PerfCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground/60" title="계산 대기 (cron 자동)">—</span>;
  }
  const pct = value * 100;
  const color = pct > 0 ? "text-green-400" : pct < 0 ? "text-red-400" : "text-muted-foreground";
  return <span className={color}>{pct >= 0 ? "+" : ""}{pct.toFixed(2)}%</span>;
}
