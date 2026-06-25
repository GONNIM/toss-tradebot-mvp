"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type LogEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

const LEVEL_COLORS: Record<string, string> = {
  CRITICAL: "text-red-500",
  ERROR: "text-red-400",
  WARNING: "text-yellow-400",
  WARN: "text-yellow-400",
  INFO: "text-cyan-400",
  DEBUG: "text-gray-400",
};

const JOB_LABELS: Record<string, string> = {
  monthly_full_refresh: "월간 갱신 (1일)",
  customs_interim_10day: "관세청 10일 잠정 (11일)",
  customs_interim_20day: "관세청 20일 잠정 (21일)",
};

type Tab = "audit" | "scheduler";

export default function LogsPage() {
  const [tab, setTab] = useState<Tab>("audit");
  const [hours, setHours] = useState(24);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">📜 로그</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            감사 로그 + 자동 갱신 이력 (최근 {hours}시간)
          </p>
        </div>
        <select
          className="rounded-lg border border-border bg-card px-3 py-2 text-sm"
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
        >
          <option value={1}>1시간</option>
          <option value={6}>6시간</option>
          <option value={24}>24시간</option>
          <option value={72}>3일</option>
          <option value={168}>7일</option>
          <option value={720}>30일</option>
        </select>
      </header>

      <div className="flex gap-2 border-b border-border">
        <TabButton active={tab === "audit"} onClick={() => setTab("audit")}>
          📜 감사 로그
        </TabButton>
        <TabButton
          active={tab === "scheduler"}
          onClick={() => setTab("scheduler")}
        >
          ⏰ 자동 갱신 이력
        </TabButton>
      </div>

      {tab === "audit" ? <AuditTable hours={hours} /> : <SchedulerTable hours={hours} />}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
        active
          ? "border-cyan-500 text-cyan-300"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function AuditTable({ hours }: { hours: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["logs", "audit", hours],
    queryFn: () => api.logs.list(200, hours),
  });

  if (isLoading) return <div className="text-muted-foreground">로딩 중...</div>;
  if (!data || data.length === 0)
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
        최근 {hours}시간 로그 없음.
      </div>
    );

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40 text-left">
          <tr>
            <th className="px-4 py-3">시각</th>
            <th className="px-4 py-3">레벨</th>
            <th className="px-4 py-3">모듈</th>
            <th className="px-4 py-3">메시지</th>
          </tr>
        </thead>
        <tbody>
          {data.map((log) => (
            <tr key={log.id} className="border-b border-border last:border-0">
              <td className="px-4 py-3 font-mono text-xs text-zinc-400">
                {formatTs(log.timestamp)}
              </td>
              <td
                className={cn(
                  "px-4 py-3 font-bold",
                  LEVEL_COLORS[log.level] || "",
                )}
              >
                {log.level}
              </td>
              <td className="px-4 py-3 text-zinc-300">{log.module}</td>
              <td className="px-4 py-3 max-w-[600px] truncate text-zinc-100">
                {log.message}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SchedulerTable({ hours }: { hours: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["logs", "scheduler", hours],
    queryFn: () => api.logs.list(200, hours, "scheduler"),
  });

  if (isLoading) return <div className="text-muted-foreground">로딩 중...</div>;
  if (!data || data.length === 0)
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground space-y-2">
        <div>최근 {hours}시간 자동 갱신 이력 없음.</div>
        <div className="text-xs">
          다음 예정 잡: 매월 1일 11:30 (월간 갱신) · 11일 12:00 (관세청 10일) ·
          21일 12:00 (관세청 20일) · 모두 KST
        </div>
      </div>
    );

  return (
    <div className="space-y-3">
      <div className="text-xs text-zinc-400">
        총 {data.length}건 · 매월 1일/11일/21일 KST 자동 실행
      </div>
      <div className="rounded-xl border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-cyan-500/40 bg-cyan-500/10 text-cyan-200 text-left">
            <tr>
              <th className="px-3 py-3">시각</th>
              <th className="px-3 py-3">잡</th>
              <th className="px-3 py-3 text-center">결과</th>
              <th className="px-3 py-3 text-right">소요</th>
              <th className="px-3 py-3">motir</th>
              <th className="px-3 py-3">customs</th>
              <th className="px-3 py-3">recompute</th>
            </tr>
          </thead>
          <tbody className="text-zinc-100">
            {data.map((log) => (
              <SchedulerRow key={log.id} log={log} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SchedulerRow({ log }: { log: LogEntry }) {
  const ctx = useMemo(() => parseContext(log.context), [log.context]);
  const jobId = ctx.job_id || extractJobId(log.message) || "—";
  const jobLabel = JOB_LABELS[jobId] || jobId;
  const isError = log.level === "ERROR";
  const stats = ctx.stats || {};

  return (
    <tr className="border-b border-border/40 last:border-0 hover:bg-muted/20">
      <td className="px-3 py-2.5 font-mono text-xs text-zinc-400 whitespace-nowrap">
        {formatTs(log.timestamp)}
      </td>
      <td className="px-3 py-2.5">
        <div className="font-semibold text-zinc-50">{jobLabel}</div>
        <div className="text-xs text-zinc-500 font-mono">{jobId}</div>
      </td>
      <td className="px-3 py-2.5 text-center">
        {isError ? (
          <span className="text-rose-400 font-semibold">✗ 실패</span>
        ) : (
          <span className="text-emerald-400 font-semibold">✓ 완료</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-300">
        {ctx.duration_ms != null ? formatDuration(ctx.duration_ms) : "—"}
      </td>
      <td className="px-3 py-2.5 text-xs">{renderStep(stats.motir)}</td>
      <td className="px-3 py-2.5 text-xs">{renderStep(stats.customs)}</td>
      <td className="px-3 py-2.5 text-xs">{renderStep(stats.recompute)}</td>
      {isError && (
        <td colSpan={7} className="px-3 py-2 text-xs text-rose-300 bg-rose-500/5">
          {ctx.error_type}: {ctx.error}
        </td>
      )}
    </tr>
  );
}

interface SchedulerContext {
  job_id?: string;
  duration_ms?: number | null;
  stats?: Record<string, unknown>;
  error?: string;
  error_type?: string;
}

function parseContext(raw: string | null): SchedulerContext {
  if (!raw) return {};
  try {
    return JSON.parse(raw) as SchedulerContext;
  } catch {
    return {};
  }
}

function extractJobId(message: string): string | null {
  const m = message.match(/^\[([a-z0-9_]+)\]/);
  return m ? m[1] : null;
}

function renderStep(step: unknown): React.ReactNode {
  if (step == null) return <span className="text-zinc-600">—</span>;
  if (typeof step !== "object") return <span>{String(step)}</span>;
  const obj = step as Record<string, unknown>;
  if ("error" in obj)
    return (
      <span className="text-rose-400" title={String(obj.error)}>
        ✗ error
      </span>
    );
  if ("skipped" in obj)
    return (
      <span className="text-amber-400" title={String(obj.skipped)}>
        skip
      </span>
    );
  // 수치 키 우선 표시
  const keys = ["inserted", "updated", "saved", "rows", "count"];
  for (const k of keys) {
    if (k in obj)
      return (
        <span className="text-emerald-300">
          ✓ {k}: {String(obj[k])}
        </span>
      );
  }
  // fallback — 첫 키
  const first = Object.keys(obj)[0];
  if (first)
    return (
      <span className="text-emerald-300">
        ✓ {first}: {String(obj[first])}
      </span>
    );
  return <span className="text-emerald-300">✓</span>;
}

function formatTs(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}
