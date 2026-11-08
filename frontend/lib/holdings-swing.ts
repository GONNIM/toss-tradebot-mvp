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
  deadline: string | null; // 사용자가 정한 기한 (없으면 null = 기본값)
  memo: string | null;
  goal: SwingGoal | null; // 보류 카드는 null
}

// 3단계 · 목표까지 거리 (계획 6절 「응답 모양」)
export interface GoalBasis {
  close: number;
  date: string;
  source: "krx" | "toss";
}

export interface LongSeries {
  source: string;
  from: string;
  to: string;
  n: number;
}

export interface GoalWindow {
  label: "3개월" | "6개월" | "기한까지";
  days: number;
  own: { pct: number | null; n: number; note: string | null };
  model: { pct: number | null; note: string | null };
  diff_pp: number | null;
}

interface GoalCommon {
  basis: GoalBasis;
  cost_pct: number;
  limits: string[];
  disclaimer: string;
}

export interface GoalShort extends GoalCommon {
  kind: "short";
  need_pct: number | null; // null 이면 본전 위
  above_breakeven: boolean;
  deadline: string | null; // 기준일이 없고 사용자 기한도 없으면 null
  deadline_source: "user" | "default";
  deadline_basis_date: string | null;
  deadline_basis_source: "journal" | "record" | null;
  days_left: number | null; // 평일 수 · 지났으면 0 · 기한 없으면 null
  past_deadline: boolean;
  sigma120_pct: number | null;
  long_series: LongSeries | null;
  windows: GoalWindow[];
}

export interface GoalLong extends GoalCommon {
  kind: "long";
  cushion_pct: number;
  ath: { close: number; date: string; from_ath_pct: number } | null;
  long_series: LongSeries | null;
  drawdowns: {
    threshold_pct: number;
    ended: number;
    recovered: number;
    days_min: number | null;
    days_max: number | null;
    days_median: number | null;
    ongoing: { start: string; depth_pct: number } | null;
  } | null;
}

export type SwingGoal = GoalShort | GoalLong;

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

// ─── 3단계 문구 도우미 ─────────────────────────────────────────

/** 확률 표시용 % 한 자리. */
export function ratioText(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(1)}%`;
}

/** 미국 달러 손익 — 부호 붙여 $ 표기. */
export function usdPnlText(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const FX_SOURCE_LABEL: Record<string, string> = {
  toss: "토스 참고 환율",
  cached: "토스 참고 환율 · 최근 값",
  fallback: "추정 환율 · 고정값",
};

function mmddHm(iso: string): string {
  const d = iso.slice(0, 10).split("-");
  const t = iso.length >= 16 ? ` ${iso.slice(11, 16)}` : "";
  return `${Number(d[1])}/${Number(d[2])}${t}`;
}

/** 미국 손익 아래 작은 줄 — 원화 환산 · 지금 환율 · 출처 · 기준 시각. */
export function wonConvertText(
  pnlKrw: number | null | undefined,
  fx: { rate: number | null; source: string | null; validFrom: string | null },
): string {
  const won =
    pnlKrw === null || pnlKrw === undefined
      ? "—"
      : `${pnlKrw < 0 ? "-" : pnlKrw > 0 ? "+" : ""}₩${Math.abs(Math.round(pnlKrw)).toLocaleString("ko-KR")}`;
  if (fx.rate === null) return `원화 환산 ${won} · 환율 정보 없음`;
  const rate = fx.rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  const src = FX_SOURCE_LABEL[fx.source ?? ""] ?? "출처 미상";
  const at = fx.validFrom ? ` · ${mmddHm(fx.validFrom)} 기준` : "";
  return `원화 환산 ${won} · 지금 환율 ${rate} (${src}${at})`;
}

/** 단기 — 본전까지 필요 상승률 문장. */
export function needText(g: GoalShort): string {
  if (g.above_breakeven || g.need_pct === null) return "이미 본전 위";
  return `본전까지 필요 상승률 +${g.need_pct.toFixed(2)}%`;
}

export function goalBasisText(b: GoalBasis): string {
  const s = b.source === "krx" ? "KRX 공식 종가" : "토스 일봉 종가";
  return `${s} ${b.close.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} · ${mmdd(b.date)} 기준`;
}

export function deadlineText(g: GoalShort): string {
  if (g.deadline === null) return "기한 없음 (기준일이 아직 없습니다 · 기한 날짜를 직접 정하면 계산합니다)";
  if (g.deadline_source === "user") return `기한 ${g.deadline} (직접 정함)`;
  const from = g.deadline_basis_source === "journal" ? "첫 저널 판단" : g.deadline_basis_source === "record" ? "기록 시작" : null;
  const basis = g.deadline_basis_date ? `기준일 ${g.deadline_basis_date}${from ? `(${from})` : ""} + 1년` : "기준일 + 1년";
  return `기한 ${g.deadline} (기본값 · ${basis})`;
}

export function daysLeftText(g: GoalShort): string {
  if (g.past_deadline) return "기한 지남";
  if (g.days_left === null) return "남은 거래일 계산 안 함";
  return `약 ${g.days_left} 거래일 (평일 수 · 휴장일 안 뺌)`;
}

export function longSeriesText(s: LongSeries | null): string {
  return s ? `긴 일봉 ${LONG_SOURCE_LABEL[s.source] ?? s.source} · ${s.from} ~ ${s.to} · ${s.n.toLocaleString("ko-KR")}일` : "긴 일봉 자료 없음";
}

export function diffText(v: number | null): string {
  return v === null ? "—" : `${v.toFixed(1)}%p`;
}

export function drawdownText(d: NonNullable<GoalLong["drawdowns"]>): string {
  const head = `고점 대비 -${d.threshold_pct}% 넘게 내린 일 `;
  if (d.ended === 0) return `${head}끝난 사례 없음`;
  const done = d.ended === d.recovered ? `끝난 ${d.ended}번 모두 앞 고점 회복` : `끝난 ${d.ended}번 · 앞 고점 회복 ${d.recovered}번`;
  if (d.days_min === null || d.days_max === null || d.days_median === null) return `${head}${done}`;
  const med = d.days_median.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  return `${head}${done} · 걸린 거래일 ${d.days_min}~${d.days_max}일 (가운데 ${med}일)`;
}

/** 서버 출처 코드 → 쉬운 이름 (코드는 DB 값 그대로 · 화면만 바꿈). */
export const LONG_SOURCE_LABEL: Record<string, string> = {
  "pykrx adjusted": "KRX 일봉(pykrx · 수정주가)",
  "yfinance close": "Yahoo 종가(yfinance · 배당 미조정)",
};
