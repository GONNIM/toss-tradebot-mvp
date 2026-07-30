"use client";

import { useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, SignalHitRow, SuperSignalRow } from "@/lib/api";
import { fmtKstDateTime, fmtKstTime } from "@/lib/time";

// ═══════════════════════════════════════════════════════════════
export default function SuperSignalsPage() {
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🌟 Super Signal</h1>
        <p className="text-sm text-muted-foreground">
          다중 시그널 병합 (Meme + VIP + Activist) · 30일 window · 2+ 소스 승격 · OCO 자동 익절/손절 (v2 Phase 3)
        </p>
      </header>
      <PromoteControl />
      <SuperSignalsList />
      <RecentHits />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function PromoteControl() {
  const qc = useQueryClient();
  const promote = useMutation({
    mutationFn: api.superSignals.promote,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["super-signals"] }),
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground">
            🎯 즉시 승격+OCO 실행
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            스케줄러(5분 주기) 대기 없이 지금 병합기 실행. 승격 조건 만족 시 SignalRouter → OCO 등록.
          </p>
        </div>
        <button
          type="button"
          onClick={() => promote.mutate()}
          disabled={promote.isPending}
          className="rounded bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {promote.isPending ? "실행 중…" : "🚀 지금 실행"}
        </button>
      </div>
      {promote.data && (
        <p className="mt-2 text-xs text-emerald-600">
          완료 · {promote.data.count}건 처리
        </p>
      )}
      {promote.error && (
        <p className="mt-2 text-xs text-red-500">
          실패 · {(promote.error as Error).message}
        </p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function SuperSignalsList() {
  const q = useQuery<SuperSignalRow[]>({
    queryKey: ["super-signals", "list"],
    queryFn: () => api.superSignals.list(30),
    refetchInterval: 30_000,
  });

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
        🌟 최근 승격 이벤트 (최대 30건)
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="space-y-2">
          {q.data.map((r) => (
            <SuperSignalCard key={r.id} row={r} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">승격 이벤트 없음</p>
      )}
    </section>
  );
}

function SuperSignalCard({ row }: { row: SuperSignalRow }) {
  const [open, setOpen] = useState(false);
  const ocoStatus = row.oco_status;
  const ocoTone =
    ocoStatus === "OPEN"
      ? "bg-emerald-100 text-emerald-700"
      : ocoStatus === "TRIGGERED"
      ? "bg-amber-100 text-amber-700"
      : ocoStatus === "CANCELED"
      ? "bg-slate-200 text-slate-600"
      : "bg-slate-100 text-slate-500";

  return (
    <div className="rounded border border-border p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold">{row.ticker}</span>
          <span className="rounded bg-purple-100 px-2 py-0.5 text-xs font-semibold text-purple-700">
            intensity {row.intensity.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">
            sources: {row.sources} · hits: {row.hit_count}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {ocoStatus && (
            <span
              className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${ocoTone}`}
            >
              OCO {ocoStatus}
            </span>
          )}
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-xs text-primary hover:underline"
          >
            {open ? "접기" : "상세"}
          </button>
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        승격 {fmtKstDateTime(row.promoted_at)} KST
        {row.oco_id && <> · oco_id: <code>{row.oco_id}</code></>}
      </div>
      {open && (
        <div className="mt-3 space-y-2 rounded bg-muted/40 p-3 text-xs">
          {row.metadata.oco && (
            <div className="grid grid-cols-4 gap-2">
              <div>
                <p className="text-muted-foreground">진입가</p>
                <p className="font-semibold">
                  {row.metadata.oco.entry_price.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">TP ({(row.metadata.oco.tp_pct * 100).toFixed(1)}%)</p>
                <p className="font-semibold text-emerald-600">
                  {row.metadata.oco.tp_price}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">SL ({(row.metadata.oco.sl_pct * 100).toFixed(1)}%)</p>
                <p className="font-semibold text-red-600">
                  {row.metadata.oco.sl_price}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">request_id</p>
                <p className="font-mono text-[10px] break-all">
                  {row.metadata.oco.request_id ?? "-"}
                </p>
              </div>
            </div>
          )}
          {row.metadata.hits && (
            <div>
              <p className="mb-1 text-muted-foreground">기여 히트 ({row.metadata.hits.length})</p>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-0.5 text-left">source</th>
                    <th className="py-0.5 text-left">signal_id</th>
                    <th className="py-0.5 text-right">score</th>
                    <th className="py-0.5 text-left">at</th>
                  </tr>
                </thead>
                <tbody>
                  {row.metadata.hits.map((h, i) => (
                    <tr key={i} className="border-b border-border/60">
                      <td className="py-0.5">{h.source}</td>
                      <td className="py-0.5 font-mono text-[10px]">{h.signal_id}</td>
                      <td className="py-0.5 text-right">{h.score.toFixed(2)}</td>
                      <td className="py-0.5 text-muted-foreground">
                        {fmtKstTime(h.at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function RecentHits() {
  const [ticker, setTicker] = useState("");
  const q = useQuery<SignalHitRow[]>({
    queryKey: ["super-signals", "hits", ticker],
    queryFn: () => api.superSignals.hits({ ticker: ticker || undefined, limit: 50 }),
    refetchInterval: 30_000,
  });

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
        🎯 최근 SignalHit (30일 · 최대 50건)
      </h2>
      <div className="mb-3 flex gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="ticker 필터 (예: WEN · 005930)"
          className="w-48 rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">시각 (KST)</th>
                <th className="py-1">티커</th>
                <th className="py-1">source</th>
                <th className="py-1">action</th>
                <th className="py-1 text-right">score</th>
                <th className="py-1">signal_id</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((h) => (
                <tr key={h.id} className="border-b border-border/60">
                  <td className="py-1 font-mono">
                    {fmtKstTime(h.hit_at)}
                  </td>
                  <td className="py-1 font-semibold">{h.ticker}</td>
                  <td className="py-1">{h.source}</td>
                  <td
                    className={`py-1 ${
                      h.action === "buy" ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {h.action.toUpperCase()}
                  </td>
                  <td className="py-1 text-right">{h.score.toFixed(2)}</td>
                  <td className="py-1 font-mono text-[10px] text-muted-foreground">
                    {h.signal_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">SignalHit 없음</p>
      )}
    </section>
  );
}
