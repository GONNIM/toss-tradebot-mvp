"use client";

/**
 * 모든 계획 화면 맨 위 한 줄 (1116-01 A · 사용자 11/20 결정)
 * 「주문 나감 / 안 나감(까닭)」 + 목록에서는 「승인 기다리는 초안 N건」. 상태를 못 읽으면 「확인 못 함」.
 * 상태 칩 7개(실거래 · 모의 · 비상 정지 · 실행기 응답 · 시세 연결 · 토스와 맞춘 시각 · 토스 연결)는 「자세히」 안에 둔다.
 */

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { plansApi, heartbeatText, HEARTBEAT_STALE_SEC, WS_LABEL, errText, kst } from "@/lib/plans";
import { Chip } from "@/components/plans/ui";
import { KILL_NAME, KILL_TEXT, orderLine } from "@/components/plans/planView";

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
  const path = usePathname();
  const onList = path === "/plans";
  // 초안 수는 목록 화면에서만 센다 (목록 화면과 같은 질의 열쇠를 써서 요청이 겹치지 않는다)
  const list = useQuery({ queryKey: ["plans", "list"], queryFn: () => plansApi.list(), refetchInterval: 20_000, staleTime: 0, retry: false, enabled: onList });
  if (isLoading) return <div data-testid="plan-band" className="text-sm text-muted-foreground">실행기 상태를 읽는 중입니다</div>;

  const ol = orderLine(data, !!error || !data);
  const tone = ol.state === "go" ? "border-primary/40 bg-primary/10 text-primary" : ol.state === "stop" ? "border-warn/40 bg-warn/5 text-warn" : "border-border bg-card text-muted-foreground";
  const drafts = list.data ? `${list.data.plans.filter((p) => p.state === "DRAFT").length}건` : list.error ? "확인 못 함" : "읽는 중";
  const stale = !data || data.heartbeat_age_sec === null || data.heartbeat_age_sec > HEARTBEAT_STALE_SEC;
  const toss = list.data?.toss ?? data?.toss;

  return (
    <div data-testid="plan-band" aria-label="계획 실행기 상태" className="space-y-2">
      <div
        data-testid="order-line"
        data-state={ol.state}
        role={ol.state === "go" ? undefined : "alert"}
        className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border px-3 py-2 text-sm ${tone}`}
      >
        <span data-testid="order-line-head" className="font-bold">{ol.head}</span>
        <span data-testid="order-line-reason">{ol.reasons.join(" · ")}{error ? ` · ${errText(error)}` : ""}</span>
        {ol.note && <span data-testid="order-line-note" className="text-muted-foreground">{ol.note}</span>}
        {onList && <span data-testid="plans-draft-count" className="ml-auto tabular-nums text-foreground">승인 기다리는 초안 {drafts}</span>}
      </div>
      {data && (
        <details data-testid="plans-chips" className="text-sm">
          <summary className="min-h-[32px] cursor-pointer text-muted-foreground" aria-label="실행기 상태 자세히 펼치기">자세히</summary>
          <div aria-label="실행기 상태 칩" className="mt-2 flex flex-wrap gap-2">
            <Chip tone={data.switches.live ? "on" : "plain"} testid="band-live">
              실거래 주문 {data.switches.live ? "켜짐" : "꺼짐"}
            </Chip>
            <Chip tone={data.switches.paper ? "on" : "plain"} testid="band-paper">
              모의 시험 {data.switches.paper ? "켜짐" : "꺼짐"}
            </Chip>
            <Chip tone={data.kill_switch.active ? "warn" : "plain"} testid="band-kill">
              {KILL_NAME} {KILL_TEXT(data.kill_switch)}
            </Chip>
            <Chip tone={stale ? "warn" : "plain"} testid="band-heartbeat">
              실행기 마지막 응답 {heartbeatText(data.heartbeat_age_sec)}
              {stale ? " · 멈춘 것일 수 있습니다" : ""}
            </Chip>
            <Chip testid="chip-ws">시세 연결 {WS_LABEL[data.ws_status ?? "none"] ?? "확인 못 함"}</Chip>
            <Chip testid="chip-resync">토스와 마지막으로 맞춘 시각 {kst(data.last_resync_at)}</Chip>
            <Chip tone={toss?.status === "ok" ? "plain" : "warn"} testid="chip-toss">
              토스 API 연결 {toss?.status === "ok" ? "정상" : toss?.status === "error" ? "오류" : "확인 못 함"} · 마지막 성공 {kst(toss?.last_ok_at)}
            </Chip>
          </div>
        </details>
      )}
    </div>
  );
}
