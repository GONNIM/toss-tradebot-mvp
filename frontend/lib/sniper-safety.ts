// 1025-01 · 실주문 안전 결론 한 줄 (사실만 · 권유 없음). 우선순위: Kill Switch → 실주문 허용 → 자동 진입 두 경로.

export type OrderTarget = "paper" | "toss";

export interface SafetyInput {
  live_enabled: boolean;
  sniper_enabled: boolean;
  watchlist_enabled: boolean;
  kill_switch_active: boolean;
  order_target?: OrderTarget;
}

export interface SafetyConclusion {
  tone: "stop" | "off" | "on";
  text: string;
}

export function orderTargetLabel(t: OrderTarget | undefined): string {
  return t === "toss" ? "실계좌" : "모의";
}

export function safetyConclusion(s: SafetyInput): SafetyConclusion {
  if (s.kill_switch_active) return { tone: "stop", text: "Kill Switch 발동 중 — 자동 주문이 멈춰 있습니다" };
  if (!s.live_enabled) return { tone: "off", text: "실주문 허용 꺼짐 — 실계좌 주문이 나가지 않습니다" };
  if (!s.sniper_enabled && !s.watchlist_enabled) return { tone: "off", text: "자동 진입 두 경로가 모두 꺼져 있습니다" };
  return { tone: "on", text: `자동 진입이 켜져 있습니다 (주문 대상: ${orderTargetLabel(s.order_target)})` };
}

/** 비율 (-0.03) → 「-3.0%」. */
export function lossLimitLabel(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
