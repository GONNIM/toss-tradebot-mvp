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
