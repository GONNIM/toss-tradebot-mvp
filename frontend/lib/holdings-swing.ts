// 1108-02 · 「보유 종목 사실」 칸 — 형식 · 문구 도우미 (사실만 · 규칙 이름 · 명령문 없음).
// 계획: docs/plans/holdings-swing/2026-11-08-plan.md 5절. 서버가 문장과 숫자를 함께 준다 (GET /account/swing).

export type Horizon = "long" | "short" | null;

export interface SwingMa {
  days: number;
  avg: number | null;
  distance_pct: number | null;
  note: string | null;
  source?: string; // 1110-02 · 200일 줄만: 긴 일봉 출처 (20·60·120일 줄은 카드 기준 종가)
  as_of?: string | null;
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
  chart: Chart | null; // 긴 일봉이 없으면 null (보유 성격 미지정 · 보류 카드도 그림은 있음)
}

// 1110-02 · 그림 자료 — 일봉 1년 + 20·50·200일선 · 주봉 40주선
export interface DailyPoint {
  d: string;
  c: number;
  m20: number | null;
  m50: number | null;
  m200: number | null;
}

export interface Chart {
  daily: DailyPoint[];
  daily_note: string | null; // 마지막 날 200일선이 비었을 때만 「자료 부족」
  daily_source: { source: string; from: string; to: string; n: number };
  week40: Week40 | null;
}

// 4단계 · 40주 평균선 (계획 7절 「검토 조건」)
export interface Week40Point {
  w: string; // 그 주 금요일
  c: number; // 주 종가
  m: number | null; // 40주 평균선
}

export interface Week40Check {
  from: string;
  to: string;
  years: number;
  source: string;
  rule_cagr: number | null;
  hold_cagr: number | null;
  rule_mdd: number | null;
  hold_mdd: number | null;
  whipsaw_pct: number | null;
  cost_pct: number;
}

export interface Week40 {
  as_of_week: string;
  data_last_date: string;
  side: "above" | "below" | null;
  distance_pct: number | null;
  streak_weeks: number | null;
  slope4w_pct: number | null;
  series: Week40Point[];
  check: Week40Check | null;
  note: string | null;
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

// ─── 4단계 · 40주 평균선 문구 도우미 ────────────────────────────

export const WEEK40_FIRST_LINE = "사실로 보이는 것이며 매매 규칙 적용이 아님";
export const WEEK40_LIMIT_LINE =
  "공개 시세 152종목 검증: 개별 종목은 통과 기준 미통과 · 지수는 큰 낙폭을 줄임 (2026-11-09) · 20·50일선 규칙도 미통과 (2026-11-10 · 공개 시세 145종목)";
export const WEEK40_BASIS_LINE = "카드 숫자는 운영 자료 기간으로 계산 · 전체 이력과 다를 수 있음";

function signed(v: number, digits = 1): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** 그림 위 사실 한 줄. 자료가 그 주 금요일보다 일찍 멈췄으면 「자료 MM/DD 까지」를 붙인다. */
export function week40FactText(w: Week40): string {
  if (w.side === null || w.distance_pct === null) return w.note ?? "40주 자료 부족";
  const side = w.side === "above" ? "위" : "아래";
  const parts = [`주 종가가 40주 평균선 ${side} ${Math.abs(w.distance_pct).toFixed(1)}%`];
  if (w.streak_weeks !== null) parts.push(`${w.streak_weeks}주째`);
  parts.push(w.slope4w_pct === null ? "기울기 자료 부족" : `선 기울기 ${signed(w.slope4w_pct)}(4주 전 대비)`);
  parts.push(`${mmdd(w.as_of_week)} 끝난 주`);
  if (w.data_last_date.slice(0, 10) < w.as_of_week.slice(0, 10)) parts.push(`자료 ${mmdd(w.data_last_date)} 까지`);
  return parts.join(" · ");
}

function pctOrDash(v: number | null): string {
  return v === null ? "—" : `${v.toFixed(1)}%`;
}

/** 그림 아래 첫 줄 — 규칙 쪽과 그대로 쪽을 나란히. 어느 쪽이 낫다는 말은 없다. */
export function week40CheckText(c: Week40Check): string {
  const ym = (iso: string) => iso.slice(0, 7);
  return (
    `이 종목 최근 ${c.years.toFixed(1)}년(${ym(c.from)}~${ym(c.to)} · ${c.source}): ` +
    `선 아래 주에 쉬었다면 연 ${pctOrDash(c.rule_cagr)} · 최대 낙폭 ${pctOrDash(c.rule_mdd)} / ` +
    `그대로 연 ${pctOrDash(c.hold_cagr)} · ${pctOrDash(c.hold_mdd)} · ` +
    `4주 안 되돌림 ${pctOrDash(c.whipsaw_pct)} · 비용 ${c.cost_pct}%/회 · 현금 이자 0 · ${DISCLAIMER_TEXT}`
  );
}

const DISCLAIMER_TEXT = "추정 · 보장 아님";

/** 마우스 올림 글 — 날짜 · 종가 · 선 값 · 거리 (사실만). */
export function week40TipText(p: Week40Point): string[] {
  const lines = [`${p.w.slice(0, 10)} 끝난 주`, `종가 ${p.c.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}`];
  if (p.m === null) {
    lines.push("40주선 자료 부족");
  } else {
    lines.push(`40주선 ${p.m.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}`);
    lines.push(`거리 ${signed((p.c / p.m - 1) * 100)}`);
  }
  return lines;
}

// ─── 1110-02 · 일봉 1년 + 평균선 세 줄 문구 도우미 ───────────────

export const DAILY_BASIS_LINE = "그림 평균선과 카드 글자 줄은 출처가 달라 값이 조금 다를 수 있음 · 사실 표시이며 매매 지시가 아님";
export const MA_LINES: { key: "m20" | "m50" | "m200"; label: string; width: number; dash?: string }[] = [
  { key: "m20", label: "20일", width: 1.5 },
  { key: "m50", label: "50일", width: 1.5, dash: "5 3" },
  { key: "m200", label: "200일(≈40주)", width: 2.5 },
];

/** 일봉 그림 아래 출처 줄. */
export function dailySourceText(c: Chart): string {
  const s = c.daily_source;
  return `일봉 출처 ${s.source} · ${s.from} ~ ${s.to} · ${s.n.toLocaleString("ko-KR")}일 · 평균선은 이 자료 전체로 계산`;
}

/** 마우스 올림 글 — 날짜 · 종가 · 세 선 값 (사실만). */
export function dailyTipText(p: DailyPoint): string[] {
  const f = (v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  return [
    p.d.slice(0, 10),
    `종가 ${f(p.c)}`,
    `20일선 ${p.m20 === null ? "자료 부족" : f(p.m20)}`,
    `50일선 ${p.m50 === null ? "자료 부족" : f(p.m50)}`,
    `200일선 ${p.m200 === null ? "자료 부족" : f(p.m200)}`,
  ];
}

/** 카드 글자 줄(20·60·120일)과 200일 줄을 나눈다. 200일 줄은 출처가 따로다. */
export function splitMa(ma: SwingMa[]): { base: SwingMa[]; long: SwingMa | null } {
  return { base: ma.filter((m) => m.days !== 200), long: ma.find((m) => m.days === 200) ?? null };
}

export function longMaSourceText(m: SwingMa): string {
  const at = m.as_of ? ` · ${mmdd(m.as_of)} 기준` : "";
  return m.source ? `출처 ${m.source}${at}` : "";
}

/** 선 끝 글자 세로 자리 — 입력 순서 그대로 돌려주되, 가까운 글자끼리는 최소 gap(px) 벌린다(무리 가운데를 중심으로). */
/** 일봉 x축 눈금 — 달마다 첫 거래일 하나만 (글자가 년-월이라 같은 달이 두 번 찍히지 않게). */
export function monthTicks(dates: string[]): string[] {
  const out: string[] = [];
  let last = "";
  for (const d of dates) {
    const ym = d.slice(0, 7);
    if (ym !== last) {
      out.push(d);
      last = ym;
    }
  }
  return out;
}

export function spreadLabels(ys: number[], gap: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  // 겹치는 무리를 묶어 가운데 기준으로 펼친다
  const groups: { items: { y: number; i: number }[]; center: number }[] = [];
  for (const it of order) {
    groups.push({ items: [it], center: it.y });
    // 앞 무리와 겹치면 합친다 (합친 뒤 다시 앞 무리와 비교)
    while (groups.length > 1) {
      const b = groups[groups.length - 1];
      const a = groups[groups.length - 2];
      const aBottom = a.center + ((a.items.length - 1) * gap) / 2;
      const bTop = b.center - ((b.items.length - 1) * gap) / 2;
      if (bTop - aBottom >= gap) break;
      const items = [...a.items, ...b.items];
      const center = items.reduce((s, x) => s + x.y, 0) / items.length;
      groups.splice(groups.length - 2, 2, { items, center });
    }
  }
  const out = new Array<number>(ys.length);
  for (const g of groups) {
    const top = g.center - ((g.items.length - 1) * gap) / 2;
    g.items.forEach((it, k) => (out[it.i] = top + k * gap));
  }
  return out;
}
