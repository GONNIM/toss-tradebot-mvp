// 1128-01 · 종목 상세 화면 글자 만들기 · 계산 없음 (받은 값을 읽기 쉽게만 바꾼다)
// 서버: GET /api/v1/stock/{code}/quote (backend/services/kr_quotes.py quote_view)
import type { Chart } from "@/lib/holdings-swing";

// ─── 자료가 오래됐다는 표시 (가-4) ───────────────────────────────
// 기준은 출처가 새 자료를 만드는 주기다 (backend 스케줄러 · 11/28 확인).
//  daily  7일 : blue_chip(매일 22:30 · api/main.py) · crazy(06:30) · moonshot(16:50) · meme(5분~일) · biotech(화~토 08:45) · serenity(일일) · watchlist(거래일) · sniper(이벤트지만 매일 감시)
//  weekly 21일: principles(주 1회 일요일 21:00 + 매일 재계산 → 후보 행 생성일은 주 단위) · activist(공시일 · 공시가 없으면 몇 주 비는 것이 정상)
//               · powderkeg
//  monthly 45일: sector_leaders(매월 1일 11:30)
export type StaleCadence = "daily" | "weekly" | "monthly";
export const STALE_DAYS: Record<StaleCadence, number> = { daily: 7, weekly: 21, monthly: 45 };

export const SIGNAL_CADENCE: Record<string, StaleCadence> = {
  crazy: "daily",
  moonshot: "daily",
  meme: "daily",
  biotech: "daily",
  serenity: "daily",
  watchlist: "daily",
  sniper: "daily",
  principles: "weekly",
  activist: "weekly",
  powderkeg: "weekly",
  blue_chip: "daily",
  sector_leaders: "monthly",
};

function ymdUtc(s: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/** 오래된 자료면 「N일 전 자료」 / 「N개월 전 자료」, 아니면 null. today 는 'YYYY-MM-DD' (화면에서는 오늘 날짜). */
export function staleBadge(source: string, asOf: string | null, today: string): string | null {
  if (!asOf) return null;
  const a = ymdUtc(asOf);
  const t = ymdUtc(today);
  if (a === null || t === null) return null;
  const days = Math.floor((t - a) / 86_400_000);
  const limit = STALE_DAYS[SIGNAL_CADENCE[source] ?? "weekly"];
  if (days <= limit) return null;
  if (days >= 60) return `${Math.floor(days / 30)}개월 전 자료`;
  return `${days}일 전 자료`;
}

/** 오늘(한국 날짜) 'YYYY-MM-DD'. */
export function todayKst(now: Date = new Date()): string {
  return new Date(now.getTime() + 9 * 3_600_000).toISOString().slice(0, 10);
}

// ─── 한국식 단위 ─────────────────────────────────────────────────
export const NO_DATA = "자료 없음";

/** 주식 수 · 거래량 (1.2억 주 · 345만 주 · 8,200주). */
export function volumeKo(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  const a = Math.abs(v);
  if (a >= 1e8) return `${trim(v / 1e8, 2)}억 주`;
  if (a >= 1e4) return `${trim(v / 1e4, 1)}만 주`;
  return `${Math.round(v).toLocaleString("ko-KR")}주`;
}

function trim(n: number, d: number): string {
  return Number(n.toFixed(d)).toLocaleString("ko-KR", { maximumFractionDigits: d });
}

/** 원 단위 큰 금액 (412조 3,000억 원 · 8,500억 원 · 5,000만 원). */
export function wonKo(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  const a = Math.abs(v);
  if (a >= 1e12) {
    const jo = Math.floor(a / 1e12);
    const eok = Math.floor((a % 1e12) / 1e8);
    const sign = v < 0 ? "-" : "";
    return eok > 0 ? `${sign}${jo.toLocaleString("ko-KR")}조 ${eok.toLocaleString("ko-KR")}억 원` : `${sign}${jo.toLocaleString("ko-KR")}조 원`;
  }
  if (a >= 1e8) return `${trim(v / 1e8, 0)}억 원`;
  if (a >= 1e4) return `${trim(v / 1e4, 0)}만 원`;
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function krw(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? NO_DATA : `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function signedPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export function pct1(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? NO_DATA : `${v.toFixed(2)}%`;
}

export function md(ymd?: string | null): string {
  return ymd && /^\d{4}-\d{2}-\d{2}/.test(ymd) ? `${Number(ymd.slice(5, 7))}/${Number(ymd.slice(8, 10))}` : "";
}

// ─── 거래량 막대 (다) ────────────────────────────────────────────
export type VolBar = { x: string; c: number; v: number | null; up: boolean | null };

/** 전날(전주) 종가보다 오르면 up=true, 내리면 false, 같거나 첫 점이면 null (한국식: 상승 빨강 · 하락 파랑). v 가 null 이면 막대 없음. */
export function volumeBars(points: { x: string; c: number; v?: number | null }[]): VolBar[] {
  return points.map((p, i) => {
    const prev = i > 0 ? points[i - 1].c : null;
    const up = prev === null || p.c === prev ? null : p.c > prev;
    return { x: p.x, c: p.c, v: p.v ?? null, up };
  });
}

export function hasVolume(points: { v?: number | null }[]): boolean {
  return points.some((p) => p.v != null && p.v > 0);
}

export const VOL_COLOR = { up: "hsl(var(--up))", down: "hsl(var(--down))", flat: "hsl(var(--muted-foreground))" } as const;
export function volColor(up: boolean | null): string {
  return up === null ? VOL_COLOR.flat : up ? VOL_COLOR.up : VOL_COLOR.down;
}

// ─── 국내 종목 가격 칸 자료 모양 ─────────────────────────────────
export type KrLive = { price: number; change_pct: number; market_status: string; traded_at?: string | null; source: string };
export type KrBasics = {
  price_close: number | null;
  volume: number | null;
  avg_volume: number | null;
  avg_volume_note?: string | null;
  market_cap: number | null;
  low_52w: number | null;
  high_52w: number | null;
  foreign_rate: number | null;
  source: string;
};
export type KrOpinion = {
  head: string;
  grade_note: string;
  mean_rating: number | null;
  mean_target: number | null;
  created: string | null;
  source: string;
  use_note: string;
};
/** 「계획으로 옮기기」 미리 채우기용 값 (표시 전용 · 지금은 어디에도 쓰지 않음). */
export type PlanHints = {
  last_close: number | null;
  week40_line: number | null;
  low_52w: number | null;
  high_52w: number | null;
  asof: string | null;
  note: string;
};
export type KrQuote = {
  ticker: string;
  name: string | null;
  market_label: "KOSPI" | "KOSDAQ" | null;
  asof: string | null;
  live: KrLive | null;
  live_note: string | null;
  basics: KrBasics | null;
  chart: Chart | null;
  opinion: KrOpinion | null;
  opinion_status: "ok" | "none" | "failed";
  opinion_note: string | null;
  plan_hints: PlanHints;
  notes: string[];
  use_note: string;
};

export function marketText(market: "KR" | "US", label?: string | null): string {
  if (market !== "KR") return "미국";
  return label === "KOSPI" ? "코스피" : label === "KOSDAQ" ? "코스닥" : "국내";
}

export function krLiveLine(v: KrQuote): string {
  if (v.live) {
    const status = v.live.market_status === "OPEN" ? "장중" : v.live.market_status === "CLOSE" ? "장 마감" : v.live.market_status;
    return `현재가 ${krw(v.live.price)} (${signedPct(v.live.change_pct)}) · ${status} · ${v.live.source}`;
  }
  const close = v.basics?.price_close;
  return `${v.live_note ?? "실시간 실패"}${close != null ? ` · 저장 종가 ${krw(close)}${v.asof ? ` (${md(v.asof)} 기준)` : ""}` : ""}`;
}

export function rangeText(lo: number | null, hi: number | null): string {
  return lo != null && hi != null ? `${krw(lo)} ~ ${krw(hi)}` : NO_DATA;
}

// 국내 칸 그림 아래 설명 줄 — 국내 일봉은 화면을 열 때 받아 10분 보관한다 (바이오 · 미국의 「하루 1회 저장」 문장과 다름 · Fable 권고 ㄷ)
export const KR_BASIS_LINE = "그림 평균선은 화면을 열 때 받아 10분 보관한 긴 일봉으로 계산 · 사실 표시이며 매매 지시가 아님";
