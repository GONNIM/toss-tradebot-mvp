// WP74 · Biotech Radar 표시 전용 도우미 (점수·판정 계산 없음)

const KST_TZ = "Asia/Seoul";

function kstParts(iso: string) {
  const d = new Date(iso);
  const f = new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TZ, year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(d);
  const g = (t: string) => Number(f.find((x) => x.type === t)?.value ?? 0);
  return { y: g("year"), m: g("month"), d: g("day"), hh: g("hour") % 24, mm: g("minute") };
}

// 서버 파이프는 매일 07:00 KST 실행 · 산출 파일 생성 시각 기준 표기
export function refreshLabel(generatedIso: string, now: Date = new Date()): string {
  const g = kstParts(generatedIso);
  const pad = (n: number) => String(n).padStart(2, "0");
  const genDay = Date.UTC(g.y, g.m - 1, g.d);
  const nextDay = genDay + 86_400_000;
  const n = kstParts(now.toISOString());
  const today = Date.UTC(n.y, n.m - 1, n.d);
  const diff = Math.round((nextDay - today) / 86_400_000);
  const nd = new Date(nextDay);
  const head = `${g.m}월 ${g.d}일 ${pad(g.hh)}:${pad(g.mm)} 갱신`;
  // 예정 시각 (다음 날 07:00 KST) 에서 1시간이 지났는데 새 산출이 없으면 지연으로 표시
  const overdue = diff < 0 || (diff === 0 && n.hh * 60 + n.mm >= 8 * 60);
  if (overdue) return `${head} · 갱신 지연 (예정 ${nd.getUTCMonth() + 1}월 ${nd.getUTCDate()}일 07:00)`;
  const nextLabel = diff === 1 ? "내일" : "오늘";
  return `${head} · 다음 갱신 ${nextLabel} 07:00`;
}

// 시총 배지 문구 · 계산 불가 (빈 값) 면 null → 배지 렌더 안 함
export function mcapBadge(bucket?: string, asof?: string): string | null {
  if (!bucket || bucket === "unknown" || bucket === "—") return null;
  if (!asof) return bucket;
  const [, m, d] = asof.split("-").map(Number);
  return `${bucket} · ${m}/${d} 종가 기준`;
}


// ── 2단계 · 카드 문장 ─────────────────────────────────────────
const PHASE_KO: Record<string, string> = {
  EARLY_PHASE1: "초기 1상",
  PHASE1: "1상",
  PHASE2: "2상",
  PHASE3: "3상",
  PHASE4: "4상",
  "PHASE1/PHASE2": "1·2상",
  "PHASE2/PHASE3": "2·3상",
};

export function phaseLabel(phase?: string): string {
  return (phase && PHASE_KO[phase]) || "임상";
}

// WP87 · D-day 표기 (API 가 화면 보는 날 KST 기준으로 계산) · 0 = D-0 · 지남 = D+n
export function dday(daysTo: number): string {
  return daysTo >= 0 ? `D-${daysTo}` : `D+${-daysTo}`;
}

// WP89 · 종료 예정일 문구 · 지난 시험은 "종료 예정일 지남(결과 발표 대기)" (D+n 대신)
export const PAST_DUE = "종료 예정일 지남(결과 발표 대기)";

export function endLabel(eventDate: string, daysTo: number, style: "short" | "long" | "reason" = "long"): string {
  if (daysTo < 0) return style === "reason" ? `임상 ${PAST_DUE}` : `${ymdLabel(eventDate)} ${PAST_DUE}`;
  if (style === "reason") return `임상 종료 예정 ${dday(daysTo)}`;
  return style === "short"
    ? `${ymdLabel(eventDate)}(${dday(daysTo)}) 종료 예정(결과 발표일 아님)`
    : `${ymdLabel(eventDate)}(${dday(daysTo)}) 종료 예정 · 결과 발표일은 아님`;
}

// "3상 시험이 9월 30일(3일 뒤)에 끝날 예정입니다. 결과 발표일은 아닙니다."
// 올해 날짜는 "9월 30일" · 다른 해는 "2027년 1월 31일" (KST 기준 올해)
export function ymdLabel(ymd: string, now: Date = new Date()): string {
  const [y, m, d] = ymd.split("-").map(Number);
  const thisYear = kstParts(now.toISOString()).y;
  return y === thisYear ? `${m}월 ${d}일` : `${y}년 ${m}월 ${d}일`;
}

export function trialSentence(phase?: string, eventDate?: string, daysTo?: number | null): string | null {
  if (!eventDate || typeof daysTo !== "number") return null;
  if (daysTo < 0) return `${phaseLabel(phase)} 시험의 종료 예정일(${ymdLabel(eventDate)})이 지났습니다. 결과 발표를 기다리는 중입니다.`;
  const when = daysTo === 0 ? "오늘" : `${daysTo}일 뒤`;
  return `${phaseLabel(phase)} 시험이 ${ymdLabel(eventDate)}(${when})에 끝날 예정입니다. 결과 발표일은 아닙니다.`;
}

export function ctgovUrl(nctId?: string): string | null {
  return nctId && /^NCT\d{8}$/.test(nctId) ? `https://clinicaltrials.gov/study/${nctId}` : null;
}

// KPI 보조 문구용 · "오늘 07:00" 또는 "9월 27일 07:00"
export function checkedAtLabel(generatedIso: string, now: Date = new Date()): string {
  const g = kstParts(generatedIso);
  const n = kstParts(now.toISOString());
  const pad = (x: number) => String(x).padStart(2, "0");
  const day = g.y === n.y && g.m === n.m && g.d === n.d ? "오늘" : `${g.m}월 ${g.d}일`;
  return `${day} ${pad(g.hh)}:${pad(g.mm)}`;
}

// ── 4단계 · 카드 정렬·필터 (표시 순서만 · 점수 계산 없음) ─────────
export type CardSort = "date" | "score";
export type CardRowLike = { ticker: string; phase?: string; days_to?: number | null };

export function sortFilterCards<T extends CardRowLike>(
  rows: T[],
  opts: { sort: CardSort; phase3Only: boolean; within7: boolean },
  scoreOf: (ticker: string) => number | undefined,
): T[] {
  const far = Number.MAX_SAFE_INTEGER;
  let out = rows.filter((r) => {
    if (opts.phase3Only && !(r.phase ?? "").includes("PHASE3")) return false;
    if (opts.within7 && !(typeof r.days_to === "number" && r.days_to <= 7)) return false;
    return true;
  });
  out = [...out].sort((a, b) => {
    if (opts.sort === "score") {
      const sa = scoreOf(a.ticker);
      const sb = scoreOf(b.ticker);
      if (sa === undefined && sb === undefined) return 0;
      if (sa === undefined) return 1; // 순위표 밖 종목은 뒤로
      if (sb === undefined) return -1;
      return sb - sa;
    }
    return (a.days_to ?? far) - (b.days_to ?? far);
  });
  return out;
}

// ── WP76-3 · 카드 문장 틀 (수집 필드 + 사전만 · 없는 항목은 생략 · 추정 금지) ──────
// 단계 설명 고정 문구 (사용자 지시 · 사전 고정)
const PHASE_DESC: Record<string, string> = {
  "1상": "안전성 확인",
  "초기 1상": "안전성 확인",
  "2상": "효과 탐색",
  "3상": "승인 전 대규모 확인",
  "4상": "승인 후 관찰",
};

// 분류 설명 고정 문구 (사전 v2 신설 분류 · WP80 사용자 지시) · 카드에 "분류(설명)" 로 표시
const CATEGORY_DESC: Record<string, string> = {
  "건강인·약동학": "건강한 사람 대상 안전성·약동학 시험",
  "통증": "통증 치료 시험",
  "청각·이비인후": "청각·귀 질환 시험",
};

export function categoryLabel(category: string): string {
  const desc = CATEGORY_DESC[category];
  return desc ? `${category}(${desc})` : category;
}

export type TrialDisplay = {
  category?: string;
  category_auto?: boolean; // WP81 · 자동 분류 (MeSH 트리·어간) → "분류(자동)"
  interventions?: { name: string; type: string; type_ko?: string; name_ko?: string }[];
  placebo?: boolean;
  enrollment?: string;
  enrollment_type?: string;
  allocation?: string;
  allocation_ko?: string;
  primary_outcomes?: { measure: string; time_frame?: string; measure_ko?: string }[];
  official_title?: string;
  conditions?: { en: string; ko?: string }[];
};
export type ThemeRank = { theme_ko?: string; rank?: number; of?: number; quarter?: string };

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

// WP91 · H6 (테마 관심도 → 주가) 관문 2 폐기 확정 (2026-10-01) · 순위는 참고 표시만
export const THEME_RANK_NOTE = "검증 폐기 · 참고용";

export function cardText(
  trial: TrialDisplay | undefined,
  phase: string | undefined,
  eventDate: string | undefined,
  daysTo: number | null | undefined,
  theme?: ThemeRank,
  opts: { short?: boolean } = {},
): { main: string | null; theme: string | null } {
  const parts: string[] = [];
  const t = trial ?? {};
  if (opts.short) {
    // WP85 · 짧은 판 (순위표 행) · "분류 · 단계 · 약물 · 종료 예정(결과 발표일 아님)"
    if (t.category) parts.push(t.category_auto ? `${t.category}(자동)` : t.category);
    const ph0 = phase ? phaseLabel(phase) : "";
    if (ph0 && ph0 !== "임상") parts.push(ph0);
    const d0 = (t.interventions ?? []).find((i) => !/placebo/i.test(i.name));
    if (d0) parts.push(d0.name_ko || d0.name);
    if (eventDate && typeof daysTo === "number") parts.push(endLabel(eventDate, daysTo, "short"));
    return { main: parts.length ? parts.join(" · ") : null, theme: null };
  }
  if (t.category) parts.push(t.category_auto ? `${t.category}(자동)` : categoryLabel(t.category));
  const drugs = (t.interventions ?? []).filter((i) => !/placebo/i.test(i.name));
  if (drugs.length > 0) {
    const d = drugs[0];
    const type = d.type_ko || d.type;
    parts.push(`${d.name_ko || d.name}${type ? ` (${type})` : ""}${drugs.length > 1 ? ` 외 ${drugs.length - 1}개` : ""}`);
  }
  const ph = phase ? phaseLabel(phase) : "";
  if (ph && ph !== "임상") {
    const desc = PHASE_DESC[ph] ?? (ph === "1·2상" ? "안전성 확인·효과 탐색" : ph === "2·3상" ? "효과 탐색·승인 전 대규모 확인" : "");
    parts.push(desc ? `${ph}(${desc})` : ph);
  }
  const n = Number(t.enrollment);
  if (t.enrollment && Number.isFinite(n) && n > 0) {
    parts.push(`참가자 ${n.toLocaleString("ko-KR")}명${t.enrollment_type === "ESTIMATED" ? " (예정)" : ""}`);
  }
  const design: string[] = [];
  if (t.allocation && t.allocation !== "NA") design.push(t.allocation_ko || t.allocation); // NA = 배정 해당 없음 (단일군) → 생략
  if (t.placebo) design.push("위약 대조");
  if (design.length) parts.push(design.join(" · "));
  const po = (t.primary_outcomes ?? [])[0];
  if (po?.measure) parts.push(`1차 목표: ${clip(po.measure_ko || po.measure, 90)}`);
  if (eventDate && typeof daysTo === "number") {
    parts.push(endLabel(eventDate, daysTo));
  }
  const main = parts.length >= 2 ? parts.join(" · ") : null; // 필드가 거의 없으면 기존 문장 (trialSentence) 사용
  const themeLine =
    theme && theme.rank && theme.theme_ko
      ? `이 분야(${theme.theme_ko})의 최근 테마 순위 ${theme.rank}위${theme.of ? ` (${theme.of}개 중` : " ("}${theme.quarter ? ` · ${theme.quarter}` : ""} · 논문·임상 증가율 기준) · ${THEME_RANK_NOTE}`
      : null;
  return { main, theme: themeLine };
}


// ── WP85 · 화면 설명 문장 (내부 필드 이름을 화면에 쓰지 않음) ─────────────
const CORP_SUFFIX = /[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings|n\.?v|s\.?a|ag|llc)\.?$/i;

// 대문자 법인명 → 짧은 이름 (예: "IOVANCE BIOTHERAPEUTICS, INC." → "Iovance Biotherapeutics")
export function shortName(name?: string): string {
  let n = (name ?? "").trim();
  for (let i = 0; i < 3 && CORP_SUFFIX.test(n); i++) n = n.replace(CORP_SUFFIX, "").trim();
  n = n.replace(/[,.]$/, "").trim();
  if (n && n === n.toUpperCase() && /[A-Z]{3}/.test(n)) {
    n = n.toLowerCase().replace(/\b([a-z])/g, (c) => c.toUpperCase());
  }
  return n;
}

export function sortLabel(sort: CardSort): string {
  return sort === "score" ? "정렬: 레이더 점수 높은 순" : "정렬: 임상 종료 예정일 가까운 순";
}

const STAGE_KO: Record<string, string> = {
  quiet: "조용",
  collecting: "수집 중",
  early: "언급 증가 초기",
  frenzy: "언급 급증",
  spread: "언급 있음(평소 수준)", // WP89 · confirm stage() 마지막 분기 (조용·초기·급증 아님)
};

export function stageLabel(stage?: string): string {
  return (stage && STAGE_KO[stage]) || "단계 미확인";
}

const BASELINE_MIN = 7; // 기준선 판정에 필요한 최소 수집 일수 (confirm · biotech_alert_rule 과 같은 값)

const MULT_FLOOR = 1; // WP86 · 배수 기준선 하한 (confirm baseline_multiple 과 같은 값)

function fmtNum(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

// WP86 · "평소 하루 0.25건 → 오늘 32건(32배), 평소 거의 없음" · 배수 = 오늘 / max(1, 평균)
export function multSentence(mean?: number | null, today?: number | null): string | null {
  if (typeof mean !== "number" || typeof today !== "number") return null;
  const mult = today / Math.max(MULT_FLOOR, mean);
  const m = mult >= 10 ? Math.round(mult) : Math.round(mult * 10) / 10;
  return `평소 하루 ${fmtNum(mean)}건 → 오늘 ${today}건(${m}배)${mean < 1 ? ", 평소 거의 없음" : ""}`;
}

// 예: "언급 급증 · 기준선 8일(7일 이상 충족) · 평소 하루 0.25건 → 오늘 32건(32배), 평소 거의 없음"
export function mentionSentence(stage?: string, baselineDays?: number | null, mentions24h?: number | null, mult?: string, mean?: number | null, isAlert = false): string {
  const parts = [mentionHeadline(stage, isAlert)];
  if (typeof baselineDays === "number") {
    parts.push(`기준선 ${baselineDays}일(${baselineDays >= BASELINE_MIN ? "7일 이상 충족" : "7일 미만 · 수집 중"})`);
  }
  const ms = multSentence(mean, mentions24h);
  if (ms) {
    parts.push(ms);
  } else {
    if (typeof mentions24h === "number") parts.push(`24시간 언급 ${mentions24h}건`);
    const m = Number(mult);
    if (mult && Number.isFinite(m) && m > 0) parts.push(`평소 대비 ${m >= 10 ? Math.round(m) : m.toFixed(1)}배`);
  }
  return parts.join(" · ");
}

// 소문에 살 자리 카드에 오른 이유 (API 표1 규칙: 뉴스 예정 A 상태 · 언급 단계 조용/수집 중 · 예정일 가까운 15)
export function rumorReason(daysTo?: number | null, stage?: string, baselineDays?: number | null): string {
  const parts: string[] = [];
  if (typeof daysTo === "number") parts.push(endLabel("", daysTo, "reason"));
  const st = stageLabel(stage);
  parts.push(
    stage === "collecting" && typeof baselineDays === "number"
      ? `커뮤니티 언급 '${st}'(기준선 ${baselineDays}일 · 7일 미만)`
      : `커뮤니티 언급 '${st}'`,
  );
  return `이 카드에 오른 이유: ${parts.join(" · ")} · 순위표 상위 30 밖이라 점수 요소는 없습니다.`;
}

// 임원·대주주 매수 한 줄 · 예: "전문 펀드 · 333,333주"
export function insiderLine(detail?: string): string {
  return (detail ?? "").replace(/(\d{4,})주/, (_, n: string) => `${Number(n).toLocaleString("ko-KR")}주`);
}

export function tickerOrUnknown(ticker?: string): string {
  return ticker && ticker.trim() ? ticker : "비상장 추정"; // WP89 · SEC 명부 (company_tickers) 에 없는 발행사
}

// 자동 요약 상태 · 실패면 "자동 요약 실패(사유)" · 성공이면 null
export function summaryStatus(summary?: { ok: boolean; error?: string } | null): string | null {
  if (!summary) return "자동 요약 없음(이 종목은 요약 대상이 아님)";
  if (summary.ok) return null;
  return `자동 요약 실패(${summary.error || "사유 미기록"})`;
}


// ── WP87 · 임원·대주주 매수 카드 (같은 회사 · 같은 신고자 · 같은 신고일 = 한 카드) ─────────
export type Form4Tx = {
  filer_cik?: string; filer_name?: string; filer_type?: string; shares?: number | null;
  price?: number | null; filing_date?: string; tx_date?: string; elapsed_days?: number | null;
};
export type Form4RowLike = { ticker: string; name: string; cik?: string; form4?: Form4Tx };
export type Form4Group<T extends Form4RowLike> = { key: string; rows: T[] };

export function groupForm4<T extends Form4RowLike>(rows: T[]): Form4Group<T>[] {
  const out = new Map<string, T[]>();
  for (const r of rows) {
    const f = r.form4 ?? {};
    const key = `${r.cik || r.ticker}|${f.filer_cik ?? ""}|${f.filing_date ?? ""}`;
    out.set(key, [...(out.get(key) ?? []), r]);
  }
  return [...out.entries()].map(([key, rs]) => ({ key, rows: rs }));
}

export function filedAgo(days?: number | null): string {
  if (typeof days !== "number") return "신고일 미확인";
  return days === 0 ? "오늘 신고" : `${days}일 전 신고`;
}

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

// 예: "ETRA · Electra Therapeutics · Orbimed Advisors(전문 펀드) · 8일 전 신고 · 거래 2건 · 합계 1,333,333주 · 금액 미기재"
export function insiderSummary<T extends Form4RowLike>(g: Form4Group<T>): string {
  const first = g.rows[0];
  const f = first.form4 ?? {};
  const total = g.rows.reduce((a, r) => a + (r.form4?.shares ?? 0), 0);
  const priced = g.rows.every((r) => typeof r.form4?.price === "number" && (r.form4?.shares ?? 0) > 0);
  const amount = priced ? g.rows.reduce((a, r) => a + (r.form4!.shares ?? 0) * (r.form4!.price as number), 0) : null;
  const filer = f.filer_name ? `${shortName(f.filer_name)}${f.filer_type ? `(${f.filer_type})` : ""}` : f.filer_type || "신고자 미확인";
  return [
    tickerOrUnknown(first.ticker), shortName(first.name), filer, filedAgo(f.elapsed_days),
    `거래 ${g.rows.length}건`, `합계 ${Math.round(total).toLocaleString("ko-KR")}주`,
    amount !== null ? `금액 ${usd(amount)}` : "금액 미기재",
  ].join(" · ");
}

// 개별 거래 한 줄 (자세히) · 예: "9/21 거래 · 333,333주 · 주당 $3.00 · $1,000,000" 또는 "… · 가격 미기재"
export function insiderTxLine(f: Form4Tx): string {
  const [, m, d] = (f.tx_date ?? "").split("-").map(Number);
  const when = m && d ? `${m}/${d} 거래` : "거래일 미확인";
  const sh = `${Math.round(f.shares ?? 0).toLocaleString("ko-KR")}주`;
  if (typeof f.price === "number") return `${when} · ${sh} · 주당 $${f.price.toFixed(2)} · ${usd((f.shares ?? 0) * f.price)}`;
  return `${when} · ${sh} · 가격 미기재`;
}

// WP87 · 언급 카드 표현 · 경보 조건 충족 = "급등 경보" · 과열 단계지만 경보 아님 = "언급 늘어남" (단계 판정은 그대로)
export function mentionHeadline(stage: string | undefined, isAlert: boolean): string {
  if (isAlert) return "급등 경보";
  if (stage === "frenzy") return "언급 늘어남";
  return stageLabel(stage);
}

// WP88 · 브리핑 (c) 회사 공시 · 보도자료 (EX-99.1) 제목 줄 · 첫 문단은 접힌 영역 (원문 · 진위 미검증)
export type Exhibit = { ex99_1_title?: string; ex99_1_lead?: string; ex99_1_status?: string };

export const LEAD_LABEL = "첫 문단 (원문 · 진위 미검증)";

export function exhibitLine(f: Exhibit): string {
  if (f.ex99_1_status === "daily_cap") return "보도자료: 읽지 않음 (오늘 SEC 요청 상한 도달)";
  if (f.ex99_1_title) return `보도자료: ${f.ex99_1_title}`;
  if (f.ex99_1_status === "ok") return "보도자료: 제목 없음";
  return "";
}
