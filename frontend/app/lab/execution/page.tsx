"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  ExecutionParams,
  KillSwitchStatus,
  MarketStatus,
  OrderAuditRow,
  PaperState,
  ThresholdSet,
} from "@/lib/api";
import { fmtKstHm, fmtKstTime } from "@/lib/time";

// ─────────────────────────────────────────────
// Format helpers
// ─────────────────────────────────────────────
function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

function krw(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₩${Math.round(v).toLocaleString("ko-KR")}`;
}

function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toFixed(2)}`;
}

// ─────────────────────────────────────────────
// 편집 상태 (percent → fraction)
// ─────────────────────────────────────────────
type EditRow = {
  take_profit_pct: string;
  stop_loss_pct: string;
  trailing_arm_pct: string;
  trailing_giveback_pct: string;
};

function tsToEditRow(t: ThresholdSet | undefined): EditRow {
  const p = (v: number | null | undefined) =>
    v === null || v === undefined ? "" : (v * 100).toFixed(2);
  return {
    take_profit_pct: p(t?.take_profit_pct),
    stop_loss_pct: p(t?.stop_loss_pct),
    trailing_arm_pct: p(t?.trailing_arm_pct),
    trailing_giveback_pct: p(t?.trailing_giveback_pct),
  };
}

function editRowToTs(row: EditRow): ThresholdSet {
  const parse = (s: string): number | null => {
    if (s.trim() === "") return null;
    const n = parseFloat(s);
    return Number.isNaN(n) ? null : n / 100;
  };
  return {
    take_profit_pct: parse(row.take_profit_pct),
    stop_loss_pct: parse(row.stop_loss_pct),
    trailing_arm_pct: parse(row.trailing_arm_pct),
    trailing_giveback_pct: parse(row.trailing_giveback_pct),
  };
}

// ═══════════════════════════════════════════════════════════════
// 페이지
// ═══════════════════════════════════════════════════════════════
export default function ExecutionPage() {
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">⚙️ Execution Layer</h1>
        <p className="text-sm text-muted-foreground">
          자동매매 실행 계층 — Kill Switch · Paper Adapter · 임계값 편집 (v2 트랙 C · Phase 1)
        </p>
      </header>
      <StatusPanel />
      <MarketStatusPanel />
      <KillSwitchPanel />
      <PendingOrdersPanel />
      <PaperPanel />
      <ParamsEditor />
      <AuditPanel />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Market Status (KR / US)
// ═══════════════════════════════════════════════════════════════
function MarketStatusPanel() {
  const q = useQuery<MarketStatus>({
    queryKey: ["execution", "market"],
    queryFn: api.execution.market.status,
    refetchInterval: 30_000,
  });

  const label: Record<string, string> = {
    regular: "정규장",
    pre_market: "프리마켓",
    after_hours: "애프터",
    closed: "휴장",
    halt: "거래정지",
  };
  const tone = (state: string) =>
    state === "regular"
      ? "bg-emerald-100 text-emerald-700"
      : state === "pre_market" || state === "after_hours"
      ? "bg-sky-100 text-sky-700"
      : "bg-slate-200 text-slate-600";

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">🗓 Market Calendar</h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data ? (
        <div className="grid grid-cols-2 gap-4">
          {(["KR", "US"] as const).map((mk) => {
            const w = q.data![mk];
            return (
              <div key={mk} className="rounded border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-semibold">{mk === "KR" ? "🇰🇷 KR (KRX)" : "🇺🇸 US"}</span>
                  <span
                    className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${tone(
                      w.state,
                    )}`}
                  >
                    {label[w.state] ?? w.state}
                  </span>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground">
                  {w.regular_market && (
                    <p>
                      정규장 · {fmtKstHm(w.regular_market.start)} ~ {fmtKstHm(w.regular_market.end)} KST
                    </p>
                  )}
                  {w.pre_market && (
                    <p>
                      프리 · {fmtKstHm(w.pre_market.start)} ~ {fmtKstHm(w.pre_market.end)} KST
                    </p>
                  )}
                  {w.after_market && (
                    <p>
                      애프터 · {fmtKstHm(w.after_market.start)} ~ {fmtKstHm(w.after_market.end)} KST
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}


// ═══════════════════════════════════════════════════════════════
// Pending Orders (Toss)
// ═══════════════════════════════════════════════════════════════
type TossOrder = {
  orderId?: string;
  symbol?: string;
  side?: string;
  orderType?: string;
  status?: string;
  price?: string;
  quantity?: string;
  orderedAt?: string;
};

function PendingOrdersPanel() {
  const qc = useQueryClient();
  const q = useQuery<{ orders: TossOrder[]; request_id: string | null }>({
    queryKey: ["execution", "pending"],
    queryFn: () =>
      api.execution.orders.pending() as Promise<{
        orders: TossOrder[];
        request_id: string | null;
      }>,
    refetchInterval: 10_000,
    retry: false,
  });
  const cancel = useMutation({
    mutationFn: (orderId: string) => api.execution.orders.cancel(orderId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["execution", "pending"] }),
  });

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
        🕒 미체결 주문 (Toss · OPEN 그룹)
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.error ? (
        <p className="text-xs text-red-500">
          조회 실패: {(q.error as Error).message} (Toss 미연동 시 정상)
        </p>
      ) : q.data && q.data.orders.length > 0 ? (
        <div className="space-y-2">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">orderId</th>
                <th className="py-1">티커</th>
                <th className="py-1">방향</th>
                <th className="py-1">타입</th>
                <th className="py-1 text-right">수량</th>
                <th className="py-1 text-right">가격</th>
                <th className="py-1">상태</th>
                <th className="py-1">액션</th>
              </tr>
            </thead>
            <tbody>
              {q.data.orders.map((o, i) => (
                <tr key={o.orderId || i} className="border-b border-border/60">
                  <td className="py-1 font-mono">{o.orderId ?? "—"}</td>
                  <td className="py-1 font-semibold">{o.symbol ?? "—"}</td>
                  <td
                    className={`py-1 ${
                      o.side === "BUY" ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {o.side ?? "—"}
                  </td>
                  <td className="py-1">{o.orderType ?? "—"}</td>
                  <td className="py-1 text-right">{o.quantity ?? "—"}</td>
                  <td className="py-1 text-right">{o.price ?? "—"}</td>
                  <td className="py-1">{o.status ?? "—"}</td>
                  <td className="py-1">
                    {o.orderId && (
                      <button
                        type="button"
                        onClick={() => cancel.mutate(o.orderId!)}
                        disabled={cancel.isPending}
                        className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-600 hover:bg-red-500/30 disabled:opacity-50"
                      >
                        {cancel.isPending ? "취소 중…" : "취소"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">
            request_id: <code>{q.data.request_id ?? "—"}</code>
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">미체결 주문 없음</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// 전역 상태
// ═══════════════════════════════════════════════════════════════
function StatusPanel() {
  const q = useQuery({
    queryKey: ["execution", "status"],
    queryFn: api.execution.status,
    refetchInterval: 5000,
  });

  const status = q.data;
  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">전역 상태</h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.error ? (
        <p className="text-sm text-red-500">오류: {(q.error as Error).message}</p>
      ) : status ? (
        <div className="grid grid-cols-3 gap-4">
          <StatCell
            label="EXECUTION_ENABLED"
            value={status.execution_enabled ? "✅ 활성" : "⛔ 비활성"}
            tone={status.execution_enabled ? "good" : "muted"}
          />
          <StatCell label="Broker" value={status.broker.toUpperCase()} />
          <StatCell
            label="Kill Switch"
            value={status.kill_switch.active ? "🚨 발동 중" : "대기"}
            tone={status.kill_switch.active ? "bad" : "good"}
          />
        </div>
      ) : null}
    </section>
  );
}

function StatCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "muted";
}) {
  const color =
    tone === "good"
      ? "text-emerald-600"
      : tone === "bad"
      ? "text-red-600"
      : "text-foreground";
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Kill Switch
// ═══════════════════════════════════════════════════════════════
function KillSwitchPanel() {
  const qc = useQueryClient();
  const q = useQuery<KillSwitchStatus>({
    queryKey: ["execution", "kill-switch"],
    queryFn: api.execution.killSwitch.status,
    refetchInterval: 5000,
  });
  const [reason, setReason] = useState("");
  const activate = useMutation({
    mutationFn: (r: string) => api.execution.killSwitch.activate(r),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["execution"] });
      setReason("");
    },
  });
  const deactivate = useMutation({
    mutationFn: () => api.execution.killSwitch.deactivate(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["execution"] }),
  });

  const active = q.data?.active === true;

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        🚨 Kill Switch
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <span
              className={`inline-flex items-center rounded px-2 py-1 text-xs font-semibold ${
                active
                  ? "bg-red-100 text-red-700"
                  : "bg-emerald-100 text-emerald-700"
              }`}
            >
              {active ? "발동 중" : "대기"}
            </span>
            {q.data?.reason && (
              <span className="text-xs text-muted-foreground">
                사유: {q.data.reason} · by {q.data.activated_by}
              </span>
            )}
          </div>
          {active ? (
            <button
              type="button"
              onClick={() => deactivate.mutate()}
              disabled={deactivate.isPending}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {deactivate.isPending ? "해제 중…" : "수동 해제"}
            </button>
          ) : (
            <div className="flex gap-2">
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="발동 사유 (예: 시장 급락 대응)"
                className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
              />
              <button
                type="button"
                onClick={() => reason.trim() && activate.mutate(reason.trim())}
                disabled={activate.isPending || !reason.trim()}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {activate.isPending ? "발동 중…" : "수동 발동"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// Paper Adapter
// ═══════════════════════════════════════════════════════════════
function PaperPanel() {
  const qc = useQueryClient();
  const q = useQuery<PaperState>({
    queryKey: ["execution", "paper"],
    queryFn: api.execution.paper.state,
    refetchInterval: 15000,
  });
  const resync = useMutation({
    mutationFn: api.execution.paper.resync,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["execution"] }),
  });
  const [resetCash, setResetCash] = useState("");
  const reset = useMutation({
    mutationFn: (v: number) => api.execution.paper.reset(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["execution"] });
      setResetCash("");
    },
  });

  const state = q.data;
  const positions = state ? Object.entries(state.positions) : [];

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        📄 Paper Adapter
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : state ? (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            <StatCell label="cash_krw" value={krw(state.cash_krw)} />
            <StatCell label="cash_usd" value={usd(state.cash_usd)} />
            <StatCell
              label="fx (USD→KRW)"
              value={`₩${state.fx_usd_krw.toFixed(0)}`}
            />
            <StatCell
              label="synced_from"
              value={state.synced_from}
              tone={state.synced_from === "toss" ? "good" : "muted"}
            />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
              보유 포지션 ({positions.length})
            </h3>
            {positions.length === 0 ? (
              <p className="text-xs text-muted-foreground">없음</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-1 text-left">티커</th>
                    <th className="py-1 text-right">수량</th>
                    <th className="py-1 text-right">평단</th>
                    <th className="py-1 text-right">통화</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map(([ticker, p]) => (
                    <tr key={ticker} className="border-b border-border/60">
                      <td className="py-1">{ticker}</td>
                      <td className="py-1 text-right">{p.qty}</td>
                      <td className="py-1 text-right">
                        {p.currency === "USD"
                          ? usd(p.avg_price)
                          : krw(p.avg_price)}
                      </td>
                      <td className="py-1 text-right">{p.currency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => resync.mutate()}
              disabled={resync.isPending}
              className="rounded bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {resync.isPending ? "재싱크 중…" : "🔄 Toss 재싱크"}
            </button>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={resetCash}
                onChange={(e) => setResetCash(e.target.value)}
                placeholder="KRW"
                className="w-32 rounded border border-border bg-background px-2 py-1 text-xs"
              />
              <button
                type="button"
                onClick={() => {
                  const v = parseFloat(resetCash);
                  if (!Number.isNaN(v)) reset.mutate(v);
                }}
                disabled={reset.isPending || !resetCash}
                className="rounded bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
              >
                {reset.isPending ? "리셋 중…" : "💰 수동 리셋"}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              재싱크는 Toss 실계좌 현재 잔고 반영 · 리셋은 임의 자본으로 시나리오 테스트
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
// Params Editor (Global · Tickers · Signals)
// ═══════════════════════════════════════════════════════════════
type Tab = "global" | "tickers" | "signals";

function ParamsEditor() {
  const qc = useQueryClient();
  const q = useQuery<ExecutionParams>({
    queryKey: ["execution", "params"],
    queryFn: api.execution.params.get,
  });
  const [tab, setTab] = useState<Tab>("global");
  const [dirty, setDirty] = useState(false);

  const [globalRow, setGlobalRow] = useState<EditRow>(() =>
    tsToEditRow(undefined),
  );
  const [tickers, setTickers] = useState<Record<string, EditRow>>({});
  const [signals, setSignals] = useState<Record<string, EditRow>>({});
  const [newTicker, setNewTicker] = useState("");
  const [newSignal, setNewSignal] = useState("");

  // 서버 응답 → 편집 상태 초기화
  useEffect(() => {
    if (!q.data) return;
    setGlobalRow(tsToEditRow(q.data.global));
    setTickers(
      Object.fromEntries(
        Object.entries(q.data.tickers).map(([k, v]) => [k, tsToEditRow(v)]),
      ),
    );
    setSignals(
      Object.fromEntries(
        Object.entries(q.data.signals).map(([k, v]) => [k, tsToEditRow(v)]),
      ),
    );
    setDirty(false);
  }, [q.data]);

  const save = useMutation({
    mutationFn: (body: ExecutionParams) => api.execution.params.put(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["execution", "params"] });
      setDirty(false);
    },
  });

  const payload: ExecutionParams | null = useMemo(() => {
    if (!q.data) return null;
    return {
      global: editRowToTs(globalRow),
      risk_budget: q.data.risk_budget,   // Phase 1 UI 미노출 · 값 유지
      tickers: Object.fromEntries(
        Object.entries(tickers).map(([k, v]) => [k, editRowToTs(v)]),
      ),
      signals: Object.fromEntries(
        Object.entries(signals).map(([k, v]) => [k, editRowToTs(v)]),
      ),
    };
  }, [q.data, globalRow, tickers, signals]);

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        🎯 임계값 편집 (TP · SL · Trailing)
      </h2>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data ? (
        <div className="space-y-4">
          <div className="flex gap-1">
            {(["global", "tickers", "signals"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`rounded-t px-3 py-1.5 text-xs font-semibold ${
                  tab === t
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {t === "global"
                  ? "Global"
                  : t === "tickers"
                  ? `종목별 (${Object.keys(tickers).length})`
                  : `시그널별 (${Object.keys(signals).length})`}
              </button>
            ))}
          </div>

          {tab === "global" && (
            <ThresholdEditor
              row={globalRow}
              onChange={(r) => {
                setGlobalRow(r);
                setDirty(true);
              }}
            />
          )}

          {tab === "tickers" && (
            <KeyedEditor
              entries={tickers}
              onChange={(k, r) => {
                setTickers({ ...tickers, [k]: r });
                setDirty(true);
              }}
              onDelete={(k) => {
                const { [k]: _, ...rest } = tickers;
                setTickers(rest);
                setDirty(true);
              }}
              newKey={newTicker}
              setNewKey={setNewTicker}
              onAdd={() => {
                const k = newTicker.trim().toUpperCase();
                if (!k || tickers[k]) return;
                setTickers({ ...tickers, [k]: tsToEditRow(undefined) });
                setNewTicker("");
                setDirty(true);
              }}
              placeholder="예: 005930 · WEN"
            />
          )}

          {tab === "signals" && (
            <KeyedEditor
              entries={signals}
              onChange={(k, r) => {
                setSignals({ ...signals, [k]: r });
                setDirty(true);
              }}
              onDelete={(k) => {
                const { [k]: _, ...rest } = signals;
                setSignals(rest);
                setDirty(true);
              }}
              newKey={newSignal}
              setNewKey={setNewSignal}
              onAdd={() => {
                const k = newSignal.trim().toLowerCase();
                if (!k || signals[k]) return;
                setSignals({ ...signals, [k]: tsToEditRow(undefined) });
                setNewSignal("");
                setDirty(true);
              }}
              placeholder="예: meme_stock · vip · activist"
            />
          )}

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => payload && save.mutate(payload)}
              disabled={!dirty || save.isPending}
              className="rounded bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
            >
              {save.isPending ? "저장 중…" : "💾 저장"}
            </button>
            {dirty && (
              <span className="text-xs text-amber-600">변경사항 있음</span>
            )}
            {save.isSuccess && !dirty && (
              <span className="text-xs text-emerald-600">저장됨</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            우선순위: <b>종목별</b> &gt; <b>시그널별</b> &gt; <b>global</b> &gt; env fallback.
            리스크 예산(per_ticker_max_pct · daily_loss_limit · ticker_dd_limit)은 Phase 3
            UI 노출 예정 · 현재는 JSON 직접 편집만 가능.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function ThresholdEditor({
  row,
  onChange,
}: {
  row: EditRow;
  onChange: (r: EditRow) => void;
}) {
  const fields: Array<{ key: keyof EditRow; label: string; hint: string }> = [
    { key: "take_profit_pct", label: "익절 (TP) %", hint: "예: 7 = +7%" },
    { key: "stop_loss_pct", label: "손절 (SL) %", hint: "예: -3 = -3%" },
    { key: "trailing_arm_pct", label: "Trailing Arm %", hint: "이 수익부터 trailing 작동" },
    {
      key: "trailing_giveback_pct",
      label: "Trailing Giveback %",
      hint: "peak 대비 되돌림 시 매도",
    },
  ];
  return (
    <div className="grid grid-cols-4 gap-3">
      {fields.map((f) => (
        <div key={f.key}>
          <label className="mb-1 block text-xs font-semibold">{f.label}</label>
          <input
            type="number"
            step="0.01"
            value={row[f.key]}
            onChange={(e) => onChange({ ...row, [f.key]: e.target.value })}
            placeholder="비우면 상위 계층 상속"
            className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">{f.hint}</p>
        </div>
      ))}
    </div>
  );
}

function KeyedEditor({
  entries,
  onChange,
  onDelete,
  newKey,
  setNewKey,
  onAdd,
  placeholder,
}: {
  entries: Record<string, EditRow>;
  onChange: (key: string, row: EditRow) => void;
  onDelete: (key: string) => void;
  newKey: string;
  setNewKey: (v: string) => void;
  onAdd: () => void;
  placeholder: string;
}) {
  const keys = Object.keys(entries).sort();
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          type="text"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder={placeholder}
          className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
        />
        <button
          type="button"
          onClick={onAdd}
          className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
        >
          + 추가
        </button>
      </div>
      {keys.length === 0 ? (
        <p className="text-xs text-muted-foreground">항목 없음</p>
      ) : (
        <div className="space-y-3">
          {keys.map((k) => (
            <div key={k} className="rounded border border-border p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-sm font-semibold">{k}</span>
                <button
                  type="button"
                  onClick={() => onDelete(k)}
                  className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-600 hover:bg-red-500/30"
                >
                  삭제
                </button>
              </div>
              <ThresholdEditor
                row={entries[k]}
                onChange={(r) => onChange(k, r)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Audit Log
// ═══════════════════════════════════════════════════════════════
function AuditPanel() {
  const [ticker, setTicker] = useState("");
  const q = useQuery<OrderAuditRow[]>({
    queryKey: ["execution", "audit", ticker],
    queryFn: () =>
      api.execution.audit({ ticker: ticker || undefined, limit: 30 }),
    refetchInterval: 15000,
  });

  return (
    <section className="rounded border border-border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        📜 최근 감사 로그 (최대 30건)
      </h2>
      <div className="mb-3 flex gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="ticker 필터 (예: 005930)"
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
                <th className="py-1">방향</th>
                <th className="py-1">타입</th>
                <th className="py-1 text-right">수량</th>
                <th className="py-1 text-right">체결가</th>
                <th className="py-1">상태</th>
                <th className="py-1">시그널</th>
                <th className="py-1">에러</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.order_uuid} className="border-b border-border/60">
                  <td className="py-1 font-mono">
                    {fmtKstTime(r.created_at)}
                  </td>
                  <td className="py-1 font-semibold">{r.ticker}</td>
                  <td
                    className={`py-1 ${
                      r.side === "buy" ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {r.side.toUpperCase()}
                  </td>
                  <td className="py-1">{r.order_type}</td>
                  <td className="py-1 text-right">
                    {r.filled_qty || r.qty}
                  </td>
                  <td className="py-1 text-right">
                    {r.avg_fill_price !== null
                      ? r.avg_fill_price.toFixed(2)
                      : "—"}
                  </td>
                  <td className="py-1">{r.status}</td>
                  <td className="py-1 text-muted-foreground">
                    {r.signal_source ?? "—"}
                  </td>
                  <td className="py-1 text-red-500">
                    {r.error_code ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">감사 로그 없음</p>
      )}
    </section>
  );
}
