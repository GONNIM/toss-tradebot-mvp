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
          <h1 className="text-3xl font-bold">🎯 Crazy Picks</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매일 06:30 KST · 시총 ≥ $1B 안전 universe · 정보 전용 (수동 매수) · 행 클릭 시 상세 보기
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTab("today")}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              tab === "today"
                ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-400"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            최신
          </button>
          <button
            onClick={() => setTab("history")}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              tab === "history"
                ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-400"
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
                  <td className="px-4 py-3 max-w-[300px] truncate text-muted-foreground">
                    {p.thesis || "(미생성)"}
                  </td>
                </tr>
                {isOpen && (
                  <tr key={`${p.id}-detail`} className="border-b border-border bg-muted/10">
                    <td colSpan={showDate ? 9 : 8} className="px-6 py-4">
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
