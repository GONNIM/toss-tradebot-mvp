// 1025-08 · 「내 계좌」 토스 실계좌 보유 종목 표 문구 — 사실만 (권유·예상 없음).
// 환율 출처 · 보유 일수 기준일 출처 · 최고가 기간이 다 찼는지를 숨기지 않는다.

export type FxSource = "toss" | "cached" | "fallback";

function mmdd(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${Number(m)}/${Number(d)}`;
}

export function fxLabel(rate: number | null, source: FxSource | null): string {
  if (rate === null || source === null) return "";
  if (source === "fallback") return "환율: 추정 환율 · 1330 고정 (토스 환율을 받지 못함)";
  const r = rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  return `환율: 토스 참고 환율 ${r}원${source === "cached" ? " · 최근 값" : ""} (실제 환전과 다를 수 있음)`;
}

export function priceText(v: number | null | undefined, currency: string): string {
  if (v === null || v === undefined) return "—";
  return currency === "KRW" ? `${Math.round(v).toLocaleString("ko-KR")}원` : `$${v.toFixed(2)}`;
}

export function wonText(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function pctText(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** 오르면 up (빨강) · 내리면 down (파랑) — 토스·국내 관례. */
export function pnlTone(v: number | null | undefined): "up" | "down" | "flat" {
  if (v === null || v === undefined || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

export function heldLabel(h: { days_held: number | null; basis_date: string | null; basis_source: string | null }): string {
  if (h.days_held === null || !h.basis_date) return "기록 쌓는 중";
  const from = h.basis_source === "journal" ? "첫 저널 판단" : "기록 시작";
  return `${h.days_held}일 (${from} ${mmdd(h.basis_date)}부터)`;
}

export function peakLabel(h: {
  from_peak_pct: number | null;
  peak_close: number | null;
  peak_date: string | null;
  peak_complete: boolean;
  currency: string;
}): string {
  if (h.from_peak_pct === null || h.peak_close === null || !h.peak_date) return "—";
  const what = h.peak_complete ? "최고 종가" : "기록된 기간 최고";
  return `${pctText(h.from_peak_pct)} (${what} ${priceText(h.peak_close, h.currency)} · ${mmdd(h.peak_date)})`;
}
