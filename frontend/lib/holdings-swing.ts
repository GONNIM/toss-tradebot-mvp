// 1108-02 · 「보유 종목 사실」 칸 — 형식 · 문구 도우미 (사실만 · 규칙 이름 · 명령문 없음).
// 계획: docs/plans/holdings-swing/2026-11-08-plan.md 5절. 서버가 문장과 숫자를 함께 준다 (GET /account/swing).

export type Horizon = "long" | "short" | null;

export interface SwingMa {
  days: number;
  avg: number | null;
  distance_pct: number | null;
  note: string | null;
}

export interface SwingBlueItem {
  key: "size" | "earnings" | "vol";
  label: string;
  state: "met" | "not_met" | "none";
  text: string;
  as_of?: string | null;
}

export interface SwingLayer {
  title: string;
  mean: string;
  median_diff: string;
  bottom5: string;
  sample: string;
  caveat: string;
  source: string;
}

export interface SwingCard {
  market: "KR" | "US";
  symbol: string;
  horizon: Horizon;
  status: "ok" | "hold";
  hold_reason: string | null;
  as_of: string | null;
  close_source: "krx" | "toss";
  ma: SwingMa[];
  peak: {
    from_peak_pct: number | null;
    peak_close: number | null;
    peak_date: string | null;
    peak_complete: boolean;
    basis_date: string | null;
    basis_source: "journal" | "record" | null;
  } | null;
  blue_chip: { met: number; total: number; items: SwingBlueItem[] } | null;
  source_gap: { date: string; toss_close: number; official_close: number; gap_pct: number; flag: boolean } | null;
  real_avg: { status: string; text: string };
  profit_turn: {
    turn_date: string;
    rows_since: number;
    net_pnl_pct: number;
    cost_note: string;
    layer: SwingLayer;
  } | null;
  disclaimer: string;
}

export interface SwingResponse {
  ok: boolean;
  generated_at: string;
  cards: SwingCard[];
}

export const HORIZON_OPTIONS: { value: "long" | "short" | "unset"; label: string }[] = [
  { value: "long", label: "장기" },
  { value: "short", label: "단기" },
  { value: "unset", label: "미지정" },
];

function mmdd(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${Number(m)}/${Number(d)}`;
}

/** 평균과의 거리 — 평균 위면 +, 아래면 −. */
export function distanceText(m: SwingMa): string {
  if (m.distance_pct === null) return m.note ?? "자료 부족";
  const side = m.distance_pct > 0 ? "위" : m.distance_pct < 0 ? "아래" : "같음";
  const sign = m.distance_pct > 0 ? "+" : "";
  return `${side} ${sign}${m.distance_pct.toFixed(2)}%`;
}

export function toneOf(v: number | null | undefined): "up" | "down" | "flat" {
  if (v === null || v === undefined || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

export function sourceText(c: Pick<SwingCard, "close_source" | "as_of">): string {
  const s = c.close_source === "krx" ? "KRX 공식 종가" : "토스 일봉 종가";
  return c.as_of ? `${s} · ${mmdd(c.as_of)} 기준` : s;
}

export function peakNote(p: NonNullable<SwingCard["peak"]>): string {
  if (p.from_peak_pct === null || p.peak_close === null) return "—";
  const from = p.basis_source === "journal" ? "첫 저널 판단" : "기록 시작";
  const basis = p.basis_date ? `기준일 ${p.basis_date}(${from}) 뒤 최고 종가` : "최고 종가";
  const tail = p.peak_complete ? "" : " · 기록 전 기간 제외";
  return `${basis}${tail} · 토스 종가 기준`;
}

export function gapText(g: NonNullable<SwingCard["source_gap"]>): string {
  const sign = g.gap_pct > 0 ? "+" : "";
  return `${mmdd(g.date)} 토스 종가가 공식 종가보다 ${sign}${g.gap_pct.toFixed(2)}%`;
}

export const STATE_MARK: Record<SwingBlueItem["state"], string> = { met: "충족", not_met: "미충족", none: "자료 없음" };
