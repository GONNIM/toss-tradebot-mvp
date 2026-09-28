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

// "3상 시험이 9월 30일(3일 뒤)에 끝날 예정입니다. 결과 발표일은 아닙니다."
export function trialSentence(phase?: string, eventDate?: string, daysTo?: number | null): string | null {
  if (!eventDate || typeof daysTo !== "number") return null;
  const [, m, d] = eventDate.split("-").map(Number);
  const when = daysTo === 0 ? "오늘" : `${daysTo}일 뒤`;
  return `${phaseLabel(phase)} 시험이 ${m}월 ${d}일(${when})에 끝날 예정입니다. 결과 발표일은 아닙니다.`;
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

export type TrialDisplay = {
  category?: string;
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

export function cardText(
  trial: TrialDisplay | undefined,
  phase: string | undefined,
  eventDate: string | undefined,
  daysTo: number | null | undefined,
  theme?: ThemeRank,
): { main: string | null; theme: string | null } {
  const parts: string[] = [];
  const t = trial ?? {};
  if (t.category) parts.push(t.category);
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
  if (t.allocation) design.push(t.allocation_ko || t.allocation);
  if (t.placebo) design.push("위약 대조");
  if (design.length) parts.push(design.join(" · "));
  const po = (t.primary_outcomes ?? [])[0];
  if (po?.measure) parts.push(`1차 목표: ${clip(po.measure_ko || po.measure, 90)}`);
  if (eventDate && typeof daysTo === "number") {
    const [, m, d] = eventDate.split("-").map(Number);
    parts.push(`${m}월 ${d}일(D-${daysTo}) 종료 예정 · 결과 발표일은 아님`);
  }
  const main = parts.length >= 2 ? parts.join(" · ") : null; // 필드가 거의 없으면 기존 문장 (trialSentence) 사용
  const themeLine =
    theme && theme.rank && theme.theme_ko
      ? `이 분야(${theme.theme_ko})의 최근 테마 순위 ${theme.rank}위${theme.of ? ` (${theme.of}개 중` : " ("}${theme.quarter ? ` · ${theme.quarter}` : ""} · 논문·임상 증가율 기준)`
      : null;
  return { main, theme: themeLine };
}
