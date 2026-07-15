"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  PowderKegEventItem,
  PowderKegListItem,
  PowderKegReport,
  PowderKegTicket,
} from "@/lib/api";
import { fmtKstDateTime } from "@/lib/time";

const TOKEN_KEY = "sniper_api_token";
type Tab = "list" | "events" | "report";

export default function PowderKegPage() {
  const [tab, setTab] = useState<Tab>("list");
  const [token, setToken] = useState<string>("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem(TOKEN_KEY) || "");
    }
  }, []);

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🧨 화약고 스크리너</h1>
        <p className="text-sm text-muted-foreground">
          딥밸류 (그레이엄 net-net + 피오트로스키) × 지배구조 카탈리스트 (그린블라트 특수상황) ·
          hypothesis 모드 · 자동매매 미연결
        </p>
      </header>
      <IdentityBanner />
      <Tabs tab={tab} setTab={setTab} />
      {tab === "list" && <ListTab token={token} />}
      {tab === "events" && <EventsTab />}
      {tab === "report" && <ReportTab token={token} />}
      <Disclaimer />
    </div>
  );
}

function IdentityBanner() {
  return (
    <section className="rounded border-2 border-red-200 bg-red-50 p-3 text-xs dark:border-red-900 dark:bg-red-950">
      <div className="font-bold text-red-900 dark:text-red-100">
        ⚠️ 이 화면은 백테스트 검증 전 hypothesis 상태입니다.
      </div>
      <ul className="mt-1 space-y-0.5 text-red-800 dark:text-red-200">
        <li>· validated=true 이벤트만 반자동 티켓 생성 가능 (백테스트 t-stat &gt; 2 · 표본 ≥ 50)</li>
        <li>· 오너 개인 이벤트 표기는 공시/기사 원문 링크만 · 판단 문구 표시 X (§7-6-3 명예훼손 방지)</li>
        <li>· Type B (횡령·감사부적정·거래정지) 발생 시 자동 리스트 제거 + 최우선 알림</li>
      </ul>
    </section>
  );
}

function Tabs({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const items: { key: Tab; label: string }[] = [
    { key: "list", label: "🧨 화약고 리스트" },
    { key: "events", label: "🔥 불꽃 피드" },
    { key: "report", label: "📊 백테스트 리포트" },
  ];
  return (
    <div className="flex gap-1 border-b">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          onClick={() => setTab(it.key)}
          className={`px-3 py-1.5 text-sm ${
            tab === it.key
              ? "border-b-2 border-sky-600 font-bold text-sky-700"
              : "text-muted-foreground hover:text-sky-600"
          }`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function Disclaimer() {
  const q = useQuery<{ disclaimer: string }>({
    queryKey: ["powderkeg", "disclaimer"],
    queryFn: api.powderkeg.disclaimer,
    staleTime: Infinity,
  });
  return (
    <footer className="rounded border border-slate-300 bg-slate-50 p-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
      📌 <strong>고지</strong>: {q.data?.disclaimer || "본 화면은 관찰 후보이며 투자 권유가 아닙니다."}
    </footer>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 1 · 화약고 리스트
// ═══════════════════════════════════════════════════════════════
function ListTab({ token }: { token: string }) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["powderkeg", "list", statusFilter],
    queryFn: () =>
      api.powderkeg.list({ status: statusFilter || undefined, limit: 200 }),
    refetchInterval: 60_000,
  });
  const items: PowderKegListItem[] = q.data?.items || [];

  const toggleLock = useMutation({
    mutationFn: ({ id, locked }: { id: number; locked: boolean }) =>
      api.powderkeg.toggleListLock(token, id, locked),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });
  const remove = useMutation({
    mutationFn: ({ ticker, reason }: { ticker: string; reason: string }) =>
      api.powderkeg.removeListItem(token, ticker, reason, q.data?.run_id || undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });
  const saveNote = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      api.powderkeg.setListNote(token, id, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <span className="font-bold">Run: {q.data?.run_id || "-"}</span>
          <span className="ml-2 text-muted-foreground">· {q.data?.count || 0} 종목</span>
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded border px-2 py-1 text-xs"
        >
          <option value="">전체</option>
          <option value="passed">✅ passed</option>
          <option value="rejected">❌ rejected</option>
          <option value="cash_suspect">⚠️ cash_suspect</option>
        </select>
      </div>
      <ManualAddForm token={token} runId={q.data?.run_id || undefined} />
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          화약고 리스트가 비어있음. Screener 를 실행하려면{" "}
          <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">
            POST /api/v1/powderkeg/screener/run
          </code>{" "}
          (X-API-Token 필요).
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-900">
                <th className="p-2 text-left">종목</th>
                <th className="p-2 text-center">상태</th>
                <th className="p-2 text-right">순현금/시총</th>
                <th className="p-2 text-right">F-Score</th>
                <th className="p-2 text-right">지분율</th>
                <th className="p-2 text-right">PBR</th>
                <th className="p-2 text-right">자사주</th>
                <th className="p-2 text-left">사유</th>
                <th className="p-2 text-center">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={`border-b hover:bg-sky-50/30 ${it.locked ? "bg-amber-50/40 dark:bg-amber-950/20" : ""}`}>
                  <td className="p-2">
                    <div className="flex items-center gap-1">
                      <span className="font-medium">{it.name || "-"}</span>
                      {it.locked ? (
                        <span
                          title={`🔒 lock · added_by=${it.added_by}`}
                          className="rounded bg-amber-200 px-1 py-0.5 text-[9px] text-amber-900"
                        >
                          🔒
                        </span>
                      ) : null}
                      {it.added_by === "user" ? (
                        <span
                          title="사용자 수동 추가"
                          className="rounded bg-sky-100 px-1 py-0.5 text-[9px] text-sky-800"
                        >
                          user
                        </span>
                      ) : null}
                    </div>
                    <div className="text-[10px] text-muted-foreground">{it.ticker}</div>
                    <NoteInput
                      item={it}
                      onSave={(note) => saveNote.mutate({ id: it.id, note })}
                      disabled={!token || saveNote.isPending}
                    />
                  </td>
                  <td className="p-2 text-center">
                    <StatusBadge status={it.status} />
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.net_cash_ratio)}</td>
                  <td className="p-2 text-right font-mono">
                    {it.piotroski_f_score ?? "-"}/9
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.owner_pct)}</td>
                  <td className="p-2 text-right font-mono">
                    {it.pbr != null ? it.pbr.toFixed(2) : "-"}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.treasury_pct)}</td>
                  <td className="p-2 text-[10px] text-muted-foreground">
                    {it.reject_reasons || "-"}
                  </td>
                  <td className="p-2 text-center">
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        disabled={!token || toggleLock.isPending}
                        onClick={() =>
                          toggleLock.mutate({ id: it.id, locked: !it.locked })
                        }
                        className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-amber-50 disabled:opacity-30"
                        title={
                          it.locked
                            ? "unlock (다음 screener run 시 재평가)"
                            : "lock (다음 screener run 후에도 유지)"
                        }
                      >
                        {it.locked ? "🔓 unlock" : "🔒 lock"}
                      </button>
                      <button
                        type="button"
                        disabled={!token || remove.isPending}
                        onClick={() => {
                          const reason = prompt(
                            `삭제 · ${it.ticker} ${it.name || ""}\n사유 (감사 로그):`,
                            it.status === "cash_suspect" ? "cash_suspect · 사용자 판단 배제" : "",
                          );
                          if (reason !== null) {
                            remove.mutate({ ticker: it.ticker, reason });
                          }
                        }}
                        className="rounded border border-red-300 px-1.5 py-0.5 text-[10px] text-red-700 hover:bg-red-50 disabled:opacity-30"
                        title="화약고 리스트에서 완전 삭제 (snapshot 감사 저장)"
                      >
                        × 삭제
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

function NoteInput({
  item,
  onSave,
  disabled,
}: {
  item: PowderKegListItem;
  onSave: (note: string) => void;
  disabled: boolean;
}) {
  const [val, setVal] = useState<string>(item.user_note || "");
  const dirty = val !== (item.user_note || "");
  return (
    <div className="mt-1 flex items-center gap-1">
      <input
        type="text"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="분석 노트..."
        className="w-40 rounded border px-1 py-0.5 text-[10px]"
      />
      {dirty ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSave(val)}
          className="rounded bg-sky-600 px-1.5 py-0.5 text-[9px] text-white disabled:opacity-30"
        >
          저장
        </button>
      ) : null}
    </div>
  );
}

function ManualAddForm({ token, runId }: { token: string; runId?: string }) {
  const qc = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () =>
      api.powderkeg.addManualToList(token, {
        ticker,
        note: note || undefined,
        run_id: runId,
      }),
    onSuccess: () => {
      setTicker("");
      setNote("");
      qc.invalidateQueries({ queryKey: ["powderkeg", "list"] });
    },
  });
  return (
    <div className="rounded border border-dashed border-sky-300 bg-sky-50 p-2 text-xs dark:border-sky-900 dark:bg-sky-950">
      <div className="mb-1 font-bold text-sky-900 dark:text-sky-100">
        ➕ 수동 추가 (사용자 판단 · locked=True)
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.trim())}
          placeholder="티커 (예: 035890)"
          className="rounded border px-2 py-1 text-xs"
        />
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="분석 노트 (선택)"
          className="w-64 rounded border px-2 py-1 text-xs"
        />
        <button
          type="button"
          disabled={!token || !ticker || add.isPending}
          onClick={() => add.mutate()}
          className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-40"
        >
          {add.isPending ? "추가 중..." : "🔒 추가 + lock"}
        </button>
        {add.data ? (
          <span className="text-xs text-emerald-700">
            ✅ {add.data.ticker} {add.data.name} 추가됨
          </span>
        ) : null}
        {add.error ? (
          <span className="text-xs text-red-700">
            ⛔ {String((add.error as Error).message)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    passed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    rejected: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
    cash_suspect: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
  };
  const cls = map[status] || "bg-slate-100 text-slate-700";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${cls}`}>
      {status}
    </span>
  );
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "-";
  return `${(v * 100).toFixed(1)}%`;
}

// ═══════════════════════════════════════════════════════════════
// 탭 2 · 불꽃 피드 (Type A/B 타임라인)
// ═══════════════════════════════════════════════════════════════
function EventsTab() {
  const [hours, setHours] = useState(72);
  const q = useQuery({
    queryKey: ["powderkeg", "events", hours],
    queryFn: () => api.powderkeg.events({ hours, limit: 100 }),
    refetchInterval: 30_000,
  });
  const items: PowderKegEventItem[] = q.data?.items || [];

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <span className="font-bold">최근 {hours}시간</span>
          <span className="ml-2 text-muted-foreground">· {q.data?.count || 0} 건</span>
        </div>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="rounded border px-2 py-1 text-xs"
        >
          <option value={24}>24시간</option>
          <option value={72}>72시간</option>
          <option value={168}>7일</option>
          <option value={720}>30일</option>
        </select>
      </div>
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          이벤트 없음 · DART 폴링 필요.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((e) => (
            <li key={e.id} className={`rounded border p-2 ${eventBg(e.kind)}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <EventTypeBadge event_type={e.event_type} kind={e.kind} />
                  <span className="font-bold">{e.ticker}</span>
                  {e.needs_human_review ? (
                    <span className="rounded bg-amber-200 px-1 py-0.5 text-[10px] text-amber-900">
                      🟡 사람 확인 필요
                    </span>
                  ) : null}
                  {e.validated ? (
                    <span className="rounded bg-emerald-200 px-1 py-0.5 text-[10px] text-emerald-900">
                      ✅ validated
                    </span>
                  ) : null}
                </div>
                <span className="text-[10px] text-muted-foreground">
                  {e.detected_at ? fmtKstDateTime(e.detected_at) : "-"}
                </span>
              </div>
              <div className="mt-1 text-sm">{e.title}</div>
              {e.url ? (
                <a
                  href={e.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] text-sky-600 hover:underline"
                >
                  원문 →
                </a>
              ) : null}
              {e.action_taken ? (
                <div className="mt-1 text-[10px] text-muted-foreground">
                  action: <code>{e.action_taken}</code>
                  {e.confidence != null ? ` · confidence ${e.confidence.toFixed(2)}` : ""}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function eventBg(kind: "A" | "B"): string {
  return kind === "B"
    ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950"
    : "border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950";
}

function EventTypeBadge({ event_type, kind }: { event_type: string; kind: "A" | "B" }) {
  const cls = kind === "B"
    ? "bg-red-600 text-white"
    : "bg-orange-500 text-white";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${cls}`}>
      {kind === "B" ? "🚨 " : ""}
      {event_type}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 3 · 백테스트 리포트
// ═══════════════════════════════════════════════════════════════
const EVENT_TYPES = ["A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3"];

function ReportTab({ token }: { token: string }) {
  const [type, setType] = useState<string>("A3");
  const q = useQuery<PowderKegReport>({
    queryKey: ["powderkeg", "report", type],
    queryFn: () => api.powderkeg.report(type),
  });
  const r = q.data;

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center gap-2 text-sm">
        <span>이벤트 타입:</span>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border px-2 py-1 text-xs"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {r ? (
          <span
            className={`ml-3 rounded px-2 py-0.5 text-xs ${
              r.decision.validated
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"
                : "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
            }`}
          >
            {r.decision.validated ? "✅ validated" : "hypothesis"}
          </span>
        ) : null}
      </div>
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : !r ? (
        <div className="text-xs text-muted-foreground">데이터 없음</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-3">
            <Stat label="전체 이벤트" value={String(r.aggregate.total_events)} />
            <Stat label="유효 (가격)" value={String(r.aggregate.valid_events)} />
            <Stat
              label="승격 결과"
              value={r.decision.validated ? "PASS · " + (r.decision.passing_window || "") : "미달"}
            />
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-slate-50 dark:bg-slate-900">
                  <th className="p-2 text-left">Window</th>
                  <th className="p-2 text-right">n</th>
                  <th className="p-2 text-right">mean</th>
                  <th className="p-2 text-right">median</th>
                  <th className="p-2 text-right">win_rate</th>
                  <th className="p-2 text-right">std</th>
                  <th className="p-2 text-right">t-stat</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(r.aggregate.per_window).map(([k, w]) => (
                  <tr key={k} className="border-b">
                    <td className="p-2 font-mono">{k}</td>
                    <td className="p-2 text-right font-mono">{w.n}</td>
                    <td className="p-2 text-right font-mono">{(w.mean_return * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{(w.median_return * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{(w.win_rate * 100).toFixed(1)}%</td>
                    <td className="p-2 text-right font-mono">{(w.std * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{w.t_stat.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-[10px] text-muted-foreground">
            게이트: 표본 ≥ 50 · t-stat &gt; 2 · win_rate ≥ 50% · mean_return &gt; 0 · window (1m or 3m)
          </div>
          {r.decision.reasons.length > 0 ? (
            <div className="mt-2 text-[10px] text-muted-foreground">
              사유: {r.decision.reasons.join(" · ")}
            </div>
          ) : null}
          {Object.keys(r.aggregate.error_counts).length > 0 ? (
            <div className="mt-2 text-[10px] text-red-600">
              에러: {Object.entries(r.aggregate.error_counts).map(([k, v]) => `${k}(${v})`).join(" · ")}
            </div>
          ) : null}
        </>
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
