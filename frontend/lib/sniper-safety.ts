// 1025-01 · 실주문 안전 결론 한 줄 (사실만 · 권유 없음). 우선순위: Kill Switch → 자동 진입 두 경로 → 주문 대상.
// 자동 진입은 SNIPER_LIVE_ENABLED 를 보지 않으므로 (EXECUTION_BROKER 만 봄) 실주문 허용은 manualEntryLabel 로 따로 보인다.

export type OrderTarget = "paper" | "toss";

export interface SafetyInput {
  live_enabled: boolean;
  sniper_enabled: boolean;
  watchlist_enabled: boolean;
  kill_switch_active: boolean;
  order_target?: OrderTarget;
}

export interface SafetyConclusion {
  tone: "stop" | "off" | "on" | "live";
  text: string;
}

export function orderTargetLabel(t: OrderTarget | undefined): string {
  return t === "toss" ? "실계좌" : "모의";
}

export function safetyConclusion(s: SafetyInput): SafetyConclusion {
  if (s.kill_switch_active) return { tone: "stop", text: "Kill Switch 발동 중 — 자동 주문이 멈춰 있습니다" };
  if (!s.sniper_enabled && !s.watchlist_enabled) return { tone: "off", text: "자동 진입 두 경로가 모두 꺼져 있습니다 — 자동 주문이 나가지 않습니다" };
  if (s.order_target === "toss") return { tone: "live", text: "실계좌 자동 주문이 켜져 있습니다" };
  return { tone: "on", text: "자동 진입이 켜져 있습니다 (주문 대상: 모의 · 실계좌 주문 없음)" };
}

/** 실주문 허용 (SNIPER_LIVE_ENABLED) 이 막는 것은 수동 진입 (POST /sniper/entry) 하나다. */
export function manualEntryLabel(liveEnabled: boolean): string {
  return liveEnabled ? "수동 실주문 버튼 열림 (실주문 허용 켜짐)" : "수동 실주문 버튼 잠김 (실주문 허용 꺼짐)";
}

/** 비율 (-0.03) → 「-3.0%」. */
export function lossLimitLabel(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
