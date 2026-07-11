"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, BacktestReport } from "@/lib/api";
import { fmtKstDate, fmtKstFull } from "@/lib/time";

// ═══════════════════════════════════════════════════════════════
export default function BacktestPage() {
  const [days, setDays] = useState(30);
  const [holdingDays, setHoldingDays] = useState(5);
  const [tp, setTp] = useState<string>("");
  const [sl, setSl] = useState<string>("");
  const [tickers, setTickers] = useState<string>("");
  const [sources, setSources] = useState<Record<string, boolean>>({
    meme_stock: true,
    vip: true,
    activist: true,
  });

  const mutation = useMutation({
    mutationFn: (opts: Parameters<typeof api.backtest.run>[0]) =>
      api.backtest.run(opts),
  });

  const run = () => {
    const parsedTickers = tickers
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const selectedSources = Object.entries(sources)
      .filter(([, v]) => v)
      .map(([k]) => k);
    mutation.mutate({
      days,
      holding_days: holdingDays,
      sources: selectedSources,
      tickers: parsedTickers.length ? parsedTickers : undefined,
      take_profit_pct: tp ? parseFloat(tp) / 100 : undefined,
      stop_loss_pct: sl ? parseFloat(sl) / 100 : undefined,
    });
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🧪 Backtest</h1>
        <p className="text-sm text-muted-foreground">
          과거 SignalHit 로 Paper Adapter replay · 승률·평균수익·MDD·Sharpe (v2 Phase 3)
        </p>
      </header>

      <section className="rounded border border-border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">파라미터</h2>
        <div className="grid grid-cols-4 gap-3">
          <NumField label="백테스트 기간 (일)" value={days} onChange={setDays} />
          <NumField
            label="홀딩 기간 (일)"
            value={holdingDays}
            onChange={setHoldingDays}
          />
          <TextField
            label="TP % (비우면 default)"
            value={tp}
            onChange={setTp}
            placeholder="예: 5"
          />
          <TextField
            label="SL % (음수, 비우면 default)"
            value={sl}
            onChange={setSl}
            placeholder="예: -3"
          />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold">소스 필터</label>
            <div className="flex gap-3">
              {(["meme_stock", "vip", "activist"] as const).map((s) => (
                <label key={s} className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={sources[s]}
                    onChange={(e) =>
                      setSources({ ...sources, [s]: e.target.checked })
                    }
                  />
                  {s}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">
              티커 필터 (쉼표 구분 · 비우면 전체)
            </label>
            <input
              type="text"
              value={tickers}
              onChange={(e) => setTickers(e.target.value)}
              placeholder="예: 005930,WEN,TTD"
              className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
            />
          </div>
        </div>
        <div className="mt-3">
          <button
            type="button"
            onClick={run}
            disabled={mutation.isPending}
            className="rounded bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중… (수십초 소요)" : "🧪 백테스트 실행"}
          </button>
        </div>
      </section>

      {mutation.error && (
        <p className="text-sm text-red-500">
          실패 · {(mutation.error as Error).message}
        </p>
      )}

      {mutation.data && <ReportView report={mutation.data} />}
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
      />
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
      />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function ReportView({ report }: { report: BacktestReport }) {
  const s = report.summary;
  const pct = (v: number) =>
    v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
  const tone = (v: number) =>
    v > 0 ? "text-emerald-600" : v < 0 ? "text-red-600" : "text-foreground";

  return (
    <>
      <section className="rounded border border-border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
          📊 요약 (총 {s.total_trades}건)
        </h2>
        <div className="grid grid-cols-6 gap-4">
          <Stat label="승률" value={pct(s.win_rate)} />
          <Stat
            label="평균 수익"
            value={pct(s.avg_return_pct)}
            className={tone(s.avg_return_pct)}
          />
          <Stat
            label="총 수익"
            value={pct(s.total_return_pct)}
            className={tone(s.total_return_pct)}
          />
          <Stat
            label="MDD"
            value={pct(s.max_drawdown_pct)}
            className="text-red-600"
          />
          <Stat label="Sharpe" value={s.sharpe.toFixed(2)} />
          <Stat
            label="생성 시각 (KST)"
            value={fmtKstFull(report.generated_at)}
          />
        </div>
      </section>

      <StatsTable title="🎯 소스별" data={report.by_source} />
      <StatsTable title="💹 종목별" data={report.by_ticker} />

      <section className="rounded border border-border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
          🕒 트레이드 상세 ({report.trades.length})
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">티커</th>
                <th className="py-1">소스</th>
                <th className="py-1">진입 (KST)</th>
                <th className="py-1 text-right">진입가</th>
                <th className="py-1">청산 (KST)</th>
                <th className="py-1 text-right">청산가</th>
                <th className="py-1 text-right">PnL</th>
                <th className="py-1">사유</th>
              </tr>
            </thead>
            <tbody>
              {report.trades.map((t, i) => (
                <tr key={i} className="border-b border-border/60">
                  <td className="py-1 font-semibold">{t.ticker}</td>
                  <td className="py-1">{t.source}</td>
                  <td className="py-1 font-mono text-[10px]">
                    {fmtKstDate(t.entry_at)}
                  </td>
                  <td className="py-1 text-right">{t.entry_price.toFixed(2)}</td>
                  <td className="py-1 font-mono text-[10px]">
                    {fmtKstDate(t.exit_at)}
                  </td>
                  <td className="py-1 text-right">
                    {t.exit_price !== null ? t.exit_price.toFixed(2) : "—"}
                  </td>
                  <td
                    className={`py-1 text-right ${
                      t.pnl_pct === null
                        ? ""
                        : t.pnl_pct >= 0
                        ? "text-emerald-600"
                        : "text-red-600"
                    }`}
                  >
                    {t.pnl_pct !== null ? `${(t.pnl_pct * 100).toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        t.reason === "tp"
                          ? "bg-emerald-100 text-emerald-700"
                          : t.reason === "sl"
                          ? "bg-red-100 text-red-700"
                          : t.reason === "expire"
                          ? "bg-slate-200 text-slate-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {t.reason}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Stat({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold ${className ?? ""}`}>{value}</p>
    </div>
  );
}

function StatsTable({
  title,
  data,
}: {
  title: string;
  data: Record<
    string,
    {
      trades: number;
      wins: number;
      losses: number;
      win_rate: number;
      avg_return_pct: number;
      total_return_pct: number;
    }
  >;
}) {
  const entries = Object.entries(data).sort(
    (a, b) => b[1].total_return_pct - a[1].total_return_pct,
  );
  if (entries.length === 0) return null;
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{title}</h2>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left">
            <th className="py-1">키</th>
            <th className="py-1 text-right">건수</th>
            <th className="py-1 text-right">승/패</th>
            <th className="py-1 text-right">승률</th>
            <th className="py-1 text-right">평균 PnL</th>
            <th className="py-1 text-right">총 PnL</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k} className="border-b border-border/60">
              <td className="py-1 font-semibold">{k}</td>
              <td className="py-1 text-right">{v.trades}</td>
              <td className="py-1 text-right">
                {v.wins}/{v.losses}
              </td>
              <td className="py-1 text-right">{(v.win_rate * 100).toFixed(1)}%</td>
              <td
                className={`py-1 text-right ${
                  v.avg_return_pct >= 0 ? "text-emerald-600" : "text-red-600"
                }`}
              >
                {(v.avg_return_pct * 100).toFixed(2)}%
              </td>
              <td
                className={`py-1 text-right ${
                  v.total_return_pct >= 0 ? "text-emerald-600" : "text-red-600"
                }`}
              >
                {(v.total_return_pct * 100).toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
