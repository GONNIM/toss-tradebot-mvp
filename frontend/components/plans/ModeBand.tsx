"use client";

/** 모든 계획 화면 맨 위 띠 · 실거래 · 모의 · Kill Switch · 실행기 하트비트(마지막 시각) */

import { useQuery } from "@tanstack/react-query";
import { plansApi, heartbeatText, HEARTBEAT_STALE_SEC, errText } from "@/lib/plans";
import { Chip } from "@/components/plans/ui";

export function usePlanStatus(enabled = true) {
  return useQuery({
    queryKey: ["plans", "status"],
    queryFn: () => plansApi.status(),
    refetchInterval: 15_000,
    staleTime: 0,
    enabled,
    retry: false,
  });
}

export function ModeBand() {
  const { data, error, isLoading } = usePlanStatus();
  if (isLoading) return <div data-testid="plan-band" className="text-sm text-muted-foreground">실행기 상태를 읽는 중입니다</div>;
  if (error || !data)
    return (
      <div data-testid="plan-band" role="alert" className="rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-sm text-warn">
        실행기 상태를 읽지 못했습니다 · {errText(error)}
      </div>
    );
  const stale = data.heartbeat_age_sec === null || data.heartbeat_age_sec > HEARTBEAT_STALE_SEC;
  const k = data.kill_switch;
  return (
    <div data-testid="plan-band" aria-label="계획 실행기 상태 띠" className="flex flex-wrap gap-2">
      <Chip tone={data.switches.live ? "on" : "plain"} testid="band-live">
        실거래 주문 {data.switches.live ? "켜짐" : "꺼짐"}
      </Chip>
      <Chip tone={data.switches.paper ? "on" : "plain"} testid="band-paper">
        모의 시험 {data.switches.paper ? "켜짐" : "꺼짐"}
      </Chip>
      <Chip tone={k.active ? "warn" : "plain"} testid="band-kill">
        Kill Switch {k.active ? (k.sell_allowed ? "작동 중 · 새 주문 멈춤" : "작동 중 · 매도도 멈춤") : "꺼짐"}
      </Chip>
      <Chip tone={stale ? "warn" : "plain"} testid="band-heartbeat">
        실행기 마지막 응답 {heartbeatText(data.heartbeat_age_sec)}
        {stale ? " · 멈춘 것일 수 있습니다" : ""}
      </Chip>
    </div>
  );
}
