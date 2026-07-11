"use client";

import { useEffect, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  SniperCandidateRow,
  SniperParams,
  SniperSignalRow,
  SniperStatus,
  SniperUniverseItem,
} from "@/lib/api";
import { fmtKstDateTime, fmtKstTime } from "@/lib/time";

const TOKEN_KEY = "sniper_api_token";

export default function SniperPage() {
  const [token, setToken] = useState<string>("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem(TOKEN_KEY) || "");
    }
  }, []);
  const saveToken = (v: string) => {
    setToken(v);
    if (typeof window !== "undefined") localStorage.setItem(TOKEN_KEY, v);
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🚀 급등주 스나이퍼</h1>
        <p className="text-sm text-muted-foreground">
          정체성: 급등주 사전 예측 (안정 수익 X) · 시드 100만원 · 100% 손실 감내 루틴 완결
        </p>
      </header>
      <TokenBar token={token} onSave={saveToken} />
      <StatusPanel />
      <CandidatesPanel />
      <SignalsPanel />
      <UniversePanel token={token} />
      <ParamsEditor token={token} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function TokenBar({ token, onSave }: { token: string; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(token);
  useEffect(() => setDraft(token), [token]);
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
        🔐 X-API-Token (편집·실행 라우트 필수)
      </h2>
      <div className="flex gap-2">
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="SNIPER_API_TOKEN 을 입력"
          className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm font-mono"
        />
        <button
          type="button"
          onClick={() => onSave(draft.trim())}
          className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
        >
          저장 (localStorage)
        </button>
      </div>
      {token && (
        <p className="mt-2 text-[10px] text-emerald-600">
          토큰 저장됨 · 편집·실행 요청에 자동 첨부
        </p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function StatusPanel() {
  const q = useQuery<SniperStatus>({
    queryKey: ["sniper", "status"],
    queryFn: api.sniper.status,
    refetchInterval: 5000,
  });
  if (q.isLoading || !q.data) return null;
  const s = q.data;
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">전역 상태</h2>
      <div className="grid grid-cols-4 gap-4">
        <Stat
          label="LIVE_ENABLED (env)"
          value={s.live_enabled ? "✅ 켜짐" : "⛔ 꺼짐"}
          tone={s.live_enabled ? "good" : "muted"}
        />
        <Stat
          label="Sniper enabled (params)"
          value={s.sniper_enabled ? "✅ 활성" : "⛔ 비활성"}
          tone={s.sniper_enabled ? "good" : "muted"}
        />
        <Stat
          label="Kill Switch"
          value={s.kill_switch_active ? "🚨 발동 중" : "대기"}
          tone={s.kill_switch_active ? "bad" : "good"}
        />
        <Stat label="유니버스" value={`${s.universe_size} 종목`} />
        <Stat label="Seed" value={`₩${s.seed_cap_krw.toLocaleString()}`} />
        <Stat label="Per Order" value={`₩${s.per_order_krw.toLocaleString()}`} />
        <Stat
          label="Trailing / Hard SL"
          value={`${(s.trailing_giveback_pct * 100).toFixed(1)}% / ${(s.hard_stop_loss_pct * 100).toFixed(1)}%`}
        />
        <Stat
          label="활성창 KST"
          value={`${s.active_window_kst.start}~${s.active_window_kst.end}`}
        />
        <Stat
          label="강제 청산"
          value={s.force_close_enabled ? `On · ${s.force_close_kst} KST` : "Off"}
          tone={s.force_close_enabled ? "good" : "muted"}
        />
      </div>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "muted" }) {
  const color =
    tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : "text-foreground";
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function CandidatesPanel() {
  const q = useQuery<SniperCandidateRow[]>({
    queryKey: ["sniper", "candidates"],
    queryFn: () => api.sniper.candidates(15),
    refetchInterval: 30_000,
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
        🎯 실시간 candidate 스캔 (Top 15)
      </h2>
      {q.isLoading ? (
        <p className="text-sm">스캔 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">티커</th>
                <th className="py-1">이름</th>
                <th className="py-1 text-right">tape</th>
                <th className="py-1 text-right">rank_z</th>
                <th className="py-1 text-right">trades_z</th>
                <th className="py-1 text-right">book_z</th>
                <th className="py-1 text-right">가격</th>
                <th className="py-1 text-right">return</th>
                <th className="py-1">판정</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.ticker} className="border-b border-border/60">
                  <td className="py-1 font-mono">{r.ticker}</td>
                  <td className="py-1">{r.name}</td>
                  <td className="py-1 text-right">{r.tape_score.toFixed(2)}</td>
                  <td className="py-1 text-right">{r.rank_velocity_score.toFixed(1)}</td>
                  <td className="py-1 text-right">{r.trades_intensity_score.toFixed(1)}</td>
                  <td className="py-1 text-right">{r.orderbook_score.toFixed(1)}</td>
                  <td className="py-1 text-right">{r.last_price.toFixed(0)}</td>
                  <td
                    className={`py-1 text-right ${
                      (r.return_pct ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {r.return_pct !== null ? `${(r.return_pct * 100).toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1">
                    {r.candidate ? (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                        ✓ candidate
                      </span>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">
                        {r.reject_reason ?? "reject"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">candidate 없음</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function SignalsPanel() {
  const q = useQuery<SniperSignalRow[]>({
    queryKey: ["sniper", "signals"],
    queryFn: () => api.sniper.signals({ hours: 24, limit: 30 }),
    refetchInterval: 15_000,
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
        📜 최근 24h 진입·청산 이력
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">감지 (KST)</th>
                <th className="py-1">티커</th>
                <th className="py-1 text-right">tape</th>
                <th className="py-1 text-right">진입가</th>
                <th className="py-1 text-right">peak</th>
                <th className="py-1 text-right">청산가</th>
                <th className="py-1 text-right">PnL</th>
                <th className="py-1">사유</th>
                <th className="py-1">상태</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.id} className="border-b border-border/60">
                  <td className="py-1 font-mono">{fmtKstDateTime(r.detected_at)}</td>
                  <td className="py-1 font-semibold">{r.ticker}</td>
                  <td className="py-1 text-right">{r.tape_score?.toFixed(2) ?? "—"}</td>
                  <td className="py-1 text-right">
                    {r.entry_price !== null ? r.entry_price.toFixed(2) : "—"}
                  </td>
                  <td className="py-1 text-right">
                    {r.peak_price !== null ? r.peak_price.toFixed(2) : "—"}
                  </td>
                  <td className="py-1 text-right">
                    {r.exit_price !== null ? r.exit_price.toFixed(2) : "—"}
                  </td>
                  <td
                    className={`py-1 text-right ${
                      (r.pnl_pct ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {r.pnl_pct !== null ? `${(r.pnl_pct * 100).toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1">{r.reason ?? "—"}</td>
                  <td className="py-1">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        r.exit_order_uuid
                          ? "bg-slate-100 text-slate-700"
                          : "bg-sky-100 text-sky-700"
                      }`}
                    >
                      {r.exit_order_uuid ? "closed" : "open"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">이력 없음 · 스나이퍼 활성 후 채워짐</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function UniversePanel({ token }: { token: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["sniper", "universe"],
    queryFn: () => api.sniper.universe({ limit: 30 }),
    refetchInterval: 60_000,
  });
  const refresh = useMutation({
    mutationFn: () => api.sniper.refreshUniverse(token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sniper", "universe"] }),
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted-foreground">
          🗂 유니버스 (Top 30 · nightly 22:00 KST 재싱크)
        </h2>
        <button
          type="button"
          onClick={() => token && refresh.mutate()}
          disabled={!token || refresh.isPending}
          className="rounded bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {refresh.isPending ? "재싱크 중…" : "🔄 지금 재싱크 (토큰 필요)"}
        </button>
      </div>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.items.length > 0 ? (
        <>
          <p className="mb-2 text-xs text-muted-foreground">총 {q.data.size} 종목</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="py-1">티커</th>
                  <th className="py-1">이름</th>
                  <th className="py-1 text-right">시총</th>
                  <th className="py-1 text-right">종가</th>
                  <th className="py-1 text-right">주식수</th>
                  <th className="py-1 text-right">당일 거래대금</th>
                  <th className="py-1">squeeze</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((r: SniperUniverseItem) => (
                  <tr key={r.ticker} className="border-b border-border/60">
                    <td className="py-1 font-mono">{r.ticker}</td>
                    <td className="py-1">{r.name}</td>
                    <td className="py-1 text-right">
                      {r.market_cap_krw ? `${(r.market_cap_krw / 1e8).toFixed(0)}억` : "—"}
                    </td>
                    <td className="py-1 text-right">
                      {r.close_price ? r.close_price.toFixed(0) : "—"}
                    </td>
                    <td className="py-1 text-right">
                      {r.shares ? `${(r.shares / 1e4).toFixed(0)}만` : "—"}
                    </td>
                    <td className="py-1 text-right">
                      {r.amount_today ? `${(r.amount_today / 1e8).toFixed(1)}억` : "—"}
                    </td>
                    <td className="py-1">
                      {r.is_squeeze && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                          🎯 squeeze
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">유니버스 비어있음 · 재싱크 필요</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function ParamsEditor({ token }: { token: string }) {
  const qc = useQueryClient();
  const q = useQuery<SniperParams>({
    queryKey: ["sniper", "params"],
    queryFn: api.sniper.params,
  });
  const [draft, setDraft] = useState<Partial<SniperParams>>({});
  const save = useMutation({
    mutationFn: (updates: Partial<SniperParams>) =>
      api.sniper.updateParams(token, updates),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sniper"] });
      setDraft({});
    },
  });

  if (q.isLoading || !q.data) return null;
  const merged: SniperParams = { ...q.data, ...draft };
  const dirty = Object.keys(draft).length > 0;

  const setField = <K extends keyof SniperParams>(k: K, v: SniperParams[K]) =>
    setDraft({ ...draft, [k]: v });

  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted-foreground">
          ⚙️ 하드 파라미터 편집 (토큰 필요 · hot reload)
        </h2>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-amber-600">변경사항</span>}
          <button
            type="button"
            onClick={() => token && save.mutate(draft)}
            disabled={!token || !dirty || save.isPending}
            className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
          >
            {save.isPending ? "저장 중…" : "💾 저장"}
          </button>
        </div>
      </div>
      {save.error && (
        <p className="mb-2 text-xs text-red-500">
          실패: {(save.error as Error).message}
        </p>
      )}

      {/* On/Off 토글 */}
      <div className="mb-4 grid grid-cols-2 gap-3">
        <ToggleField
          label="Sniper 활성 (enabled)"
          value={merged.enabled}
          onChange={(v) => setField("enabled", v)}
        />
        <ToggleField
          label="장 마감 강제 청산"
          value={merged.force_close_enabled}
          onChange={(v) => setField("force_close_enabled", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">시드·주문 상한</h3>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <NumField label="Seed cap (KRW)" v={merged.seed_cap_krw} on={(v) => setField("seed_cap_krw", v)} />
        <NumField label="Per order (KRW)" v={merged.per_order_krw} on={(v) => setField("per_order_krw", v)} />
        <NumField
          label="동시 보유"
          v={merged.max_concurrent_positions}
          on={(v) => setField("max_concurrent_positions", v)}
          int
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">Trailing · 손절 · 손실 캡</h3>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <PctField
          label="Trailing giveback"
          v={merged.trailing_giveback_pct}
          on={(v) => setField("trailing_giveback_pct", v)}
        />
        <PctField
          label="Hard Stop Loss"
          v={merged.hard_stop_loss_pct}
          on={(v) => setField("hard_stop_loss_pct", v)}
        />
        <PctField
          label="Daily loss limit"
          v={merged.daily_loss_limit_pct}
          on={(v) => setField("daily_loss_limit_pct", v)}
        />
        <PctField
          label="Weekly loss limit"
          v={merged.weekly_loss_limit_pct}
          on={(v) => setField("weekly_loss_limit_pct", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">활성 시간 (KST)</h3>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <StrField label="Start" v={merged.active_start_kst} on={(v) => setField("active_start_kst", v)} />
        <StrField label="End" v={merged.active_end_kst} on={(v) => setField("active_end_kst", v)} />
        <StrField label="Force close time" v={merged.force_close_kst} on={(v) => setField("force_close_kst", v)} />
      </div>

      <h3 className="mb-2 text-xs font-semibold">Composite Score 임계</h3>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <NumField label="tape 임계" v={merged.tape_score_threshold} on={(v) => setField("tape_score_threshold", v)} />
        <NumField label="rank z" v={merged.rank_velocity_z_min} on={(v) => setField("rank_velocity_z_min", v)} />
        <NumField label="trades z" v={merged.trades_intensity_z_min} on={(v) => setField("trades_intensity_z_min", v)} />
        <NumField label="orderbook z" v={merged.orderbook_z_min} on={(v) => setField("orderbook_z_min", v)} />
      </div>

      <h3 className="mb-2 text-xs font-semibold">진입 조건</h3>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <PctField
          label="return min"
          v={merged.entry_return_min_pct}
          on={(v) => setField("entry_return_min_pct", v)}
        />
        <PctField
          label="return max"
          v={merged.entry_return_max_pct}
          on={(v) => setField("entry_return_max_pct", v)}
        />
        <NumField
          label="상승 지속 (초)"
          v={merged.sustained_rise_min_sec}
          on={(v) => setField("sustained_rise_min_sec", v)}
          int
        />
        <NumField
          label="종목당 하루 진입"
          v={merged.same_ticker_daily_limit}
          on={(v) => setField("same_ticker_daily_limit", v)}
          int
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">폴링 주기 (초)</h3>
      <div className="grid grid-cols-4 gap-3">
        <NumField
          label="rankings"
          v={merged.poll_rankings_sec}
          on={(v) => setField("poll_rankings_sec", v)}
          int
        />
        <NumField
          label="trades"
          v={merged.poll_trades_sec}
          on={(v) => setField("poll_trades_sec", v)}
          int
        />
        <NumField
          label="orderbook"
          v={merged.poll_orderbook_sec}
          on={(v) => setField("poll_orderbook_sec", v)}
          int
        />
        <NumField
          label="trailing"
          v={merged.poll_trailing_price_sec}
          on={(v) => setField("poll_trailing_price_sec", v)}
          int
        />
      </div>
      <p className="mt-3 text-[10px] text-muted-foreground">
        저장 시 백엔드 hot reload · 다음 폴링부터 즉시 반영. 유니버스 필터 변경 시 재싱크 필요.
      </p>
    </section>
  );
}

function ToggleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded border border-border bg-background p-2 text-sm cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4"
      />
      <span className="font-semibold">{label}</span>
      <span className="ml-auto text-xs text-muted-foreground">
        {value ? "ON" : "OFF"}
      </span>
    </label>
  );
}

function NumField({
  label,
  v,
  on,
  int,
}: {
  label: string;
  v: number;
  on: (v: number) => void;
  int?: boolean;
}) {
  return (
    <div>
      <label className="mb-0.5 block text-[10px] font-semibold text-muted-foreground">
        {label}
      </label>
      <input
        type="number"
        value={v}
        step={int ? 1 : "any"}
        onChange={(e) => on(int ? parseInt(e.target.value, 10) || 0 : parseFloat(e.target.value) || 0)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
    </div>
  );
}

function PctField({ label, v, on }: { label: string; v: number; on: (v: number) => void }) {
  return (
    <div>
      <label className="mb-0.5 block text-[10px] font-semibold text-muted-foreground">
        {label} (%)
      </label>
      <input
        type="number"
        step="0.001"
        value={(v * 100).toFixed(2)}
        onChange={(e) => {
          const pct = parseFloat(e.target.value);
          on(Number.isNaN(pct) ? 0 : pct / 100);
        }}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
    </div>
  );
}

function StrField({ label, v, on }: { label: string; v: string; on: (v: string) => void }) {
  return (
    <div>
      <label className="mb-0.5 block text-[10px] font-semibold text-muted-foreground">
        {label}
      </label>
      <input
        type="text"
        value={v}
        onChange={(e) => on(e.target.value)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono"
      />
    </div>
  );
}
