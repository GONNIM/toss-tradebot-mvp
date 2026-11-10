// 1110-02 · /vip 탭 도우미 (사실만 · 규칙 이름 · 명령문 없음). 서버: GET /account/vip
// 시험: lib/vip-tabs.check.ts (backend/tests/test_vip_tabs.py 가 실행)

import type { Chart, Horizon, SwingGoal, SwingMa } from "@/lib/holdings-swing";

export type VipReason = "loss" | "turned" | "config" | "config_only";

export interface VipPosition {
  avg_price: number;
  qty: number;
  current_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  currency: string;
  source: "toss";
}

export interface VipTab {
  market: "KR" | "US";
  symbol: string;
  name: string | null;
  reason: VipReason;
  turn_date: string | null;
  is_vip_config: boolean;
  position: VipPosition | null;
  chart: Chart | null;
  goal: SwingGoal | null;
  goal_hold_reason: string | null;
  horizon: Horizon;
  ma_text: SwingMa[];
  card_status: "ok" | "hold" | null;
  disclaimer?: string;
}

export interface VipTabsResponse {
  ok: boolean;
  fetched_at: string;
  error_reason?: string;
  tabs: VipTab[];
  limits: string[];
  config_symbol: string | null;
}

export const EMPTY_TEXT = "지금 적자인 종목이 없습니다";

export function tabKey(t: Pick<VipTab, "market" | "symbol">): string {
  return `${t.market}:${t.symbol}`;
}

function mmdd(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${Number(m)}/${Number(d)}`;
}

function signedPct(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** 탭 이름: 「종목명(종목코드) · 손익%」 · 흑자 전환은 「흑자 전환 MM/DD」 · 설정만이면 「보유 없음 · 설정만」. */
export function tabLabel(t: VipTab): string {
  const head = t.name ? `${t.name}(${t.symbol})` : t.symbol;
  if (t.reason === "config_only" || t.position === null) return `${head} · 보유 없음 · 설정만`;
  if (t.reason === "turned" && t.turn_date) return `${head} · 흑자 전환 ${mmdd(t.turn_date)}`;
  return t.position.pnl_pct === null ? head : `${head} · ${signedPct(t.position.pnl_pct)}`;
}

/** 주소의 ?t= 값으로 탭을 고른다. 없거나 목록에 없는 값이면 첫 탭. 탭이 없으면 null. */
export function pickTab(tabs: VipTab[], t: string | null | undefined): VipTab | null {
  if (tabs.length === 0) return null;
  return tabs.find((x) => tabKey(x) === t) ?? tabs[0];
}

/** 손익 칸: 위 %, 아래 금액 (미국은 달러). */
export function pnlLines(p: VipPosition): { pct: string; amount: string } {
  const pct = p.pnl_pct === null ? "—" : signedPct(p.pnl_pct);
  if (p.pnl === null) return { pct, amount: "—" };
  const sign = p.pnl > 0 ? "+" : p.pnl < 0 ? "-" : "";
  const abs = Math.abs(p.pnl);
  const amount =
    p.currency === "USD"
      ? `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : `${sign}₩${Math.round(abs).toLocaleString("ko-KR")}`;
  return { pct, amount };
}

export function priceText(v: number | null, currency: string): string {
  if (v === null) return "—";
  return currency === "USD"
    ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : `₩${Math.round(v).toLocaleString("ko-KR")}`;
}

export const POSITION_SOURCE_LINE = "토스 원장 값 그대로 · 사이트가 다시 계산하지 않음";
export const GOAL_HOLD_LINE = "보유 성격을 정하면 목표 칸이 보입니다";
