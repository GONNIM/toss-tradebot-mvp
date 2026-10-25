"use client";

// 1025-01 · /sniper 맨 위 실주문 안전 상황판 — 결론 한 줄 · 주문 대상 · 하루 손실 한도 · Kill Switch (발동·해제).
// 주문을 넣지 않는다. 상태 조회 실패를 「대기」로 보이지 않게 한다 (401 = 로그인 필요).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, KillSwitchStatus, SniperParams, SniperStatus } from "@/lib/api";
import { fmtKstHm } from "@/lib/time";
import { lossLimitLabel, manualEntryLabel, orderTargetLabel, safetyConclusion } from "@/lib/sniper-safety";

const TONE = {
  stop: "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200",
  off: "border-slate-300 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200",
  on: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200",
  live: "border-red-400 bg-red-100 text-red-900 dark:border-red-700 dark:bg-red-950/60 dark:text-red-100",
} as const;

function statusOf(e: unknown): number | undefined {
  return (e as { status?: number } | null)?.status;
}

export function SafetyPanel() {
  const qc = useQueryClient();
  const st = useQuery<SniperStatus>({ queryKey: ["sniper", "status"], queryFn: api.sniper.status, refetchInterval: 5000 });
  const params = useQuery<SniperParams>({ queryKey: ["sniper", "params"], queryFn: api.sniper.params });
  const ks = useQuery<KillSwitchStatus>({
    queryKey: ["sniper", "kill-switch"],
    queryFn: api.sniper.killSwitch.status,
    refetchInterval: 5000,
    retry: (n, e) => ![401, 404].includes(statusOf(e) ?? 0) && n < 2,
  });
  const [reason, setReason] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["sniper"] });
  const activate = useMutation({
    mutationFn: (r: string) => api.sniper.killSwitch.activate(r),
    onSuccess: () => {
      setReason("");
      refresh();
    },
  });
  const deactivate = useMutation({ mutationFn: () => api.sniper.killSwitch.deactivate(), onSuccess: refresh });

  const s = st.data;
  const c = s
    ? safetyConclusion({
        live_enabled: s.live_enabled,
        sniper_enabled: s.sniper_enabled,
        watchlist_enabled: s.watchlist_execute?.enabled ?? false,
        kill_switch_active: s.kill_switch_active,
        order_target: s.order_target,
      })
    : null;
  const needLogin = statusOf(ks.error) === 401;
  // 조회 오류 (로그아웃 직후 401 포함) 가 있으면 지난 데이터로 버튼을 보이지 않는다
  const ksData = ks.error ? undefined : ks.data;
  const active = ksData?.active === true;

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">🛡 실주문 안전 상황판</h2>
      {c ? (
        <p className={`rounded-md border px-3 py-2 text-base font-semibold ${TONE[c.tone]}`}>{c.text}</p>
      ) : (
        <p className="rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
          {st.error ? "실주문 상태를 불러오지 못했습니다 — Kill Switch 는 아래에서 쓸 수 있습니다" : "실주문 상태 확인 중…"}
        </p>
      )}
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">주문 대상</dt>
          <dd className="font-semibold">{s ? orderTargetLabel(s.order_target) : "—"}</dd>
          {s && <dd className="text-xs text-muted-foreground">{manualEntryLabel(s.live_enabled)}</dd>}
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">하루 손실 한도</dt>
          <dd className="font-semibold">{lossLimitLabel(params.data?.daily_loss_limit_pct)}</dd>
          <dd className="text-xs text-muted-foreground">오늘 손익은 계산 수리 뒤 표시 (1025-02)</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Kill Switch</dt>
          <dd className="font-semibold">
            {needLogin ? "관리자 로그인이 필요합니다" : ks.error ? "조회 실패" : ks.isLoading ? "확인 중…" : active ? "🚨 발동 중" : "대기"}
          </dd>
          {active && ksData?.reason && (
            <dd className="text-xs text-muted-foreground">
              사유: {ksData.reason} · 누가: {ksData.activated_by ?? "—"}
              {ksData.activated_at ? ` · ${fmtKstHm(ksData.activated_at)}` : ""}
            </dd>
          )}
        </div>
      </dl>
      {ksData && (
        active ? (
          <button
            type="button"
            onClick={() => deactivate.mutate()}
            disabled={deactivate.isPending}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {deactivate.isPending ? "해제 중…" : "수동 해제"}
          </button>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="발동 사유 (예: 시장 급락 대응)"
              maxLength={200}
              className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={() => reason.trim() && activate.mutate(reason.trim())}
              disabled={activate.isPending || !reason.trim()}
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
            >
              {activate.isPending ? "발동 중…" : "수동 발동"}
            </button>
          </div>
        )
      )}
      {(activate.error || deactivate.error) && (
        <p className="text-xs text-red-600">요청 실패: {((activate.error || deactivate.error) as Error).message}</p>
      )}
    </section>
  );
}
