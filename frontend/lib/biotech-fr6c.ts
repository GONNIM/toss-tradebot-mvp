// P4-3 · FR-6c 과거 기록 표 · 문구는 봉인 설계 docs/plans/biotech/design/fr6c_design_v1.md 그대로 (1절 14행 · 3절 57행 · 9절 123행)

export const FR6C_NOTICE = "과거 사건의 분포입니다. 이 종목의 예상 반응이 아닙니다. 같은 조건에서도 반응의 폭은 넓습니다.";
export const FR6C_SURVIVOR =
  "소급 표본은 지금 추적 중인 회사의 과거 발표만 담습니다. 그 사이 상장 폐지된 회사는 빠져 있습니다. 전향 표본은 발표 때 기록하므로 뒤에 상장 폐지되어도 남습니다.";
export const FR6C_METRIC = "반응일(0~+1거래일) XBI 대비 초과 수익률";
export const FR6C_PENDING = "과거 기록 준비 중(첫 집계 전)";
export const FR6C_MIN_N = 20;

export type Fr6cCell = {
  level: string;
  key: string[];
  label: string;
  n: number;
  missing_price: number;
  status: "표시" | "표본 부족" | "잔여";
  source?: Record<string, number>;
  median?: number;
  q25?: number;
  q75?: number;
  min?: number;
  max?: number;
  period?: [string, string];
};

export type Fr6cCells = {
  ready: boolean;
  file?: string | null;
  asof?: string | null;
  window?: { from?: string; to?: string; months?: number };
  events_in_window?: number;
  missing_price?: number;
  cells?: Fr6cCell[];
  display_rows?: string[];
};

export function fr6cPct(x: number | undefined): string {
  if (typeof x !== "number" || !Number.isFinite(x)) return "-";
  const v = x * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

// 방향 출처 비율 (설계 2.3절 43행 · 예: "사전 커밋 태그 68 · 사용자 확정 0")
export function fr6cSourceLine(source: Record<string, number> | undefined): string {
  let pre = 0;
  let user = 0;
  for (const [k, v] of Object.entries(source ?? {})) {
    if (k.includes("사용자")) user += v;
    else pre += v;
  }
  return `사전 커밋 태그 ${pre} · 사용자 확정 ${user}`;
}

// 잔여 칸은 행으로 보여 주지 않는다 (설계 4절 78행)
export function fr6cRows(cells: Fr6cCell[] | undefined): Fr6cCell[] {
  return (cells ?? []).filter((c) => c.status !== "잔여");
}

export type Fr6cRowText = { level: string; label: string; n: string; median: string; iqr: string; range: string; period: string; missing: string; source: string };

export function fr6cRowText(c: Fr6cCell): Fr6cRowText {
  const shown = c.status === "표시" && c.n >= FR6C_MIN_N;
  return {
    level: c.level,
    label: c.label,
    n: shown ? `${c.n}건` : `표본 부족(${c.n}건)`,
    median: shown ? fr6cPct(c.median) : "",
    iqr: shown ? `${fr6cPct(c.q25)} ~ ${fr6cPct(c.q75)}` : "",
    range: shown ? `${fr6cPct(c.min)} ~ ${fr6cPct(c.max)}` : "",
    period: shown && c.period ? `${c.period[0]} ~ ${c.period[1]}` : "",
    missing: `가격 없음 ${c.missing_price}건`,
    source: fr6cSourceLine(c.source),
  };
}

export function fr6cHeader(d: Fr6cCells): string {
  const w = d.window ?? {};
  return `집계 기준일 ${d.asof ?? "-"} · 표시 창 최근 ${w.months ?? 24}개월(${w.from ?? "-"} ~ ${w.to ?? "-"}) · 창 안 발표 ${d.events_in_window ?? 0}건 · 가격 없음 ${d.missing_price ?? 0}건`;
}
