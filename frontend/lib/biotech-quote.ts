// 1111-01 · 바이오 종목 가격·전문가 의견 칸 — 자료 모양과 글자 만들기 (계산 없음 · 받은 값을 읽기 쉽게만)
// 서버: GET /api/v1/biotech/quote/{ticker} (backend/services/biotech_quotes.py quote_view)
import type { Chart } from "@/lib/holdings-swing";

export type QuoteLive = { price: number; change_pct: number; market_status: string; traded_at?: string | null; source: string };
export type QuoteBasics = {
  price_close: number | null;
  volume: number | null;
  avg_volume: number | null;
  market_cap: number | null;
  low_52w: number | null;
  high_52w: number | null;
  total_cash: number | null;
  short_pct_float: number | null;
  short_asof: string | null;
  source: string;
};
export type QuoteChange = { date: string; firm: string; to_grade: string; from_grade: string; action: string; pt_now: number | null; pt_prior: number | null };
export type QuoteOpinion = {
  head: string;
  grade_note: string;
  n_opinions: number | null;
  dist: Partial<Record<"strongBuy" | "buy" | "hold" | "sell" | "strongSell", number | null>>;
  dist_sum: number | null;
  count_mismatch: boolean;
  targets: Partial<Record<"mean" | "median" | "high" | "low", number | null>>;
  changes: QuoteChange[];
  source: string;
};
export type QuoteSummary = { head: string; lines: string[]; sources: string[]; model?: string | null; made_at?: string | null };
export type QuoteSec = { accession?: string; filing_date?: string; title?: string; lead?: string; url?: string };
export type QuoteView = {
  ticker: string;
  asof: string | null;
  live: QuoteLive | null;
  live_note: string | null;
  basics: QuoteBasics | null;
  chart: Chart | null;
  opinion: QuoteOpinion | null;
  summary: QuoteSummary | null;
  sec8k: QuoteSec | null;
  use_note: string;
};

// 의견 분포 라벨 · 증권사 표기 원문 그대로 (번역 안 함 · Fable 2차 질문 2)
export const DIST_LABELS: { key: keyof QuoteOpinion["dist"]; label: string }[] = [
  { key: "strongBuy", label: "Strong Buy" },
  { key: "buy", label: "Buy" },
  { key: "hold", label: "Hold" },
  { key: "sell", label: "Sell" },
  { key: "strongSell", label: "Strong Sell" },
];

export const QUOTE_TOGGLE_OPEN = "가격·전문가 의견 보기";
export const QUOTE_TOGGLE_CLOSE = "가격·전문가 의견 접기";
export const NO_DATA = "자료 없음";
// 1112-01 · 바이오 칸 그림 아래 출처 줄 (계좌 카드·VIP 의 「카드 글자 줄」 낱말을 쓰지 않음 · Fable 1111-01 권고)
export const BIOTECH_BASIS_LINE = "그림 평균선은 하루 1회 저장한 긴 일봉으로 계산 · 사실 표시이며 매매 지시가 아님";

// 달러 금액 · 큰 값은 B · M 단위 (예: 2.71B 달러)
export function usd(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B 달러`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M 달러`;
  return `${v.toFixed(digits)} 달러`;
}

// 주식 수 · 거래량 (예: 1.12M주)
export function shares(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M주`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K주`;
  return `${Math.round(v)}주`;
}

// 받은 비율 (0.1192 → 11.9%) · 원래 값의 표기만 바꿈
export function ratioPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  return `${(v * 100).toFixed(1)}%`;
}

export function signedPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

// "2026-11-11" → "11/11"
export function md(ymd?: string | null): string {
  return ymd && /^\d{4}-\d{2}-\d{2}/.test(ymd) ? `${Number(ymd.slice(5, 7))}/${Number(ymd.slice(8, 10))}` : "";
}

export function liveLine(v: QuoteView): string {
  if (v.live) {
    const status = v.live.market_status === "OPEN" ? "장중" : v.live.market_status === "CLOSE" ? "장 마감" : v.live.market_status;
    return `현재가 ${v.live.price.toFixed(2)} 달러 (${signedPct(v.live.change_pct)}) · ${status} · ${v.live.source}`;
  }
  const close = v.basics?.price_close;
  return `${v.live_note ?? "실시간 실패"}${close != null ? ` · 저장 종가 ${close.toFixed(2)} 달러 (${md(v.asof)} 조회)` : ""}`;
}

export function distLine(o: QuoteOpinion): string {
  return DIST_LABELS.map((d) => `${d.label} ${o.dist[d.key] ?? "-"}`).join(" · ");
}

export function countLine(o: QuoteOpinion): string {
  if (o.count_mismatch) return `의견 수 ${o.n_opinions}명 · 의견 분포 합 ${o.dist_sum}명 (야후 집계끼리 다름 · 둘 다 그대로 보여 드립니다)`;
  return `의견 수 ${o.n_opinions ?? o.dist_sum ?? "-"}명`;
}

export function targetLine(o: QuoteOpinion): string | null {
  const t = o.targets;
  if ([t.mean, t.median, t.high, t.low].every((x) => x == null)) return null;
  const f = (x: number | null | undefined) => (x == null ? "-" : x.toFixed(2));
  return `목표가 평균 ${f(t.mean)} · 중앙 ${f(t.median)} · 최고 ${f(t.high)} · 최저 ${f(t.low)} (달러)`;
}

export function changeLine(c: QuoteChange): string {
  const grade = c.from_grade && c.from_grade !== c.to_grade ? `${c.from_grade} → ${c.to_grade}` : c.to_grade;
  const pt = c.pt_now != null ? ` · 목표가 ${c.pt_prior != null && c.pt_prior > 0 ? `${c.pt_prior} → ` : ""}${c.pt_now}` : "";
  return `${md(c.date)} ${c.firm} · ${grade}${pt}`;
}

export function sourceLine(v: QuoteView): string {
  const parts = [`시세·전문가 의견: 야후 (${md(v.asof)} 조회 · 의견이 나온 날 아님)`, "현재가: 네이버 (펼칠 때 조회 · 60초 보관)"];
  if (v.sec8k?.filing_date) parts.push(`회사 공시: SEC 8-K (${md(v.sec8k.filing_date)} 제출)`);
  return parts.join(" · ");
}
