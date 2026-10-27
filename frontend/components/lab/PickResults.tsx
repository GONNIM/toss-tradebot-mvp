"use client";

/**
 * Crazy · Moonshot 공용 · 로그인 안내 + 과거 실현 결과 요약 (1025-03 · B1).
 * 요약 값은 outcomes 가 채운 실현값 · 20건 미만이면 서버가 median 을 null 로 준다.
 */
import { useQueryClient } from "@tanstack/react-query";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import type { PickSummary } from "@/lib/api";

export function isUnauthorized(error: unknown): boolean {
  const status = (error as (Error & { status?: number }) | null)?.status;
  return status === 401 || status === 403;
}

// 로그인 칸 · 로그인·로그아웃하면 이 화면 조회를 다시 부른다 (queryKey 첫 칸 = crazy | moonshot)
export function PicksSessionBar({ queryRoot }: { queryRoot: "crazy" | "moonshot" }) {
  const qc = useQueryClient();
  return <AdminSessionBar scope="picks" onSessionChange={() => qc.invalidateQueries({ queryKey: [queryRoot] })} />;
}

export function LoginNotice() {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-700 dark:text-amber-300">
      🔒 관리자 로그인이 필요합니다. 위 칸에 관리자 토큰을 넣고 로그인하면 목록이 보입니다.
    </div>
  );
}

export function OutcomeSummary({
  summary,
  labels,
}: {
  summary: PickSummary | undefined;
  labels: Record<string, string>;
}) {
  if (!summary) return null;
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">과거 실현 결과 · 미래 수익 보장 아님 · 고른 종목 전부의 중앙값</div>
      <div className="mt-2 flex flex-wrap gap-6">
        {Object.entries(labels).map(([key, label]) => {
          const s = summary[key];
          if (!s) return null;
          const pct = s.median === null ? null : s.median * 100;
          const color =
            pct === null ? "text-muted-foreground" : pct > 0 ? "text-green-400" : pct < 0 ? "text-red-400" : "text-muted-foreground";
          return (
            <div key={key}>
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className={`font-mono text-lg font-bold ${color}`}>
                {pct === null ? "—" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {s.n}건{s.median === null ? " · 20건부터 표시" : ""}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
