// WP79 · cardText() 확인 스크립트 (backend/tests/test_biotech_wp74_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { cardText, daysSinceFiling, insiderTotalUsd, txCents, dday, THEME_RANK_NOTE, endLabel, stageLabel, exhibitLine, LEAD_LABEL, groupForm4, insiderSummary, insiderTxLine, mentionSentence, multSentence, trialSentence, rumorReason, shortName, summaryStatus, tickerOrUnknown } from "./biotech-display";

const beauty = cardText({ category: "미용", interventions: [{ name: "X-1", type: "DRUG", type_ko: "약물" }] }, "PHASE2", "2026-11-30", 62);
assert.ok(beauty.main?.startsWith("미용 · X-1 (약물) · 2상(효과 탐색)"), beauty.main ?? "null");

const other = cardText({ category: "기타", enrollment: "24" }, "PHASE1", "2026-10-31", 32);
assert.ok(other.main?.startsWith("기타 · 1상(안전성 확인) · 참가자 24명"), other.main ?? "null");

const raw = cardText({ category: "기타 (Healthy Volunteers)" }, "PHASE1", "2026-10-31", 32);
assert.ok(raw.main?.startsWith("기타 (Healthy Volunteers) · 1상"), raw.main ?? "null");
// WP80 · 신설 분류 3개 · 설명 문구 포함
const hv = cardText({ category: "건강인·약동학" }, "PHASE1", "2026-10-31", 32);
assert.ok(hv.main?.startsWith("건강인·약동학(건강한 사람 대상 안전성·약동학 시험) · 1상"), hv.main ?? "null");
const pain = cardText({ category: "통증" }, "PHASE2", "2026-10-31", 32);
assert.ok(pain.main?.startsWith("통증(통증 치료 시험) · 2상"), pain.main ?? "null");
const ent = cardText({ category: "청각·이비인후" }, "PHASE3", "2026-10-31", 32);
assert.ok(ent.main?.startsWith("청각·이비인후(청각·귀 질환 시험) · 3상"), ent.main ?? "null");
// WP81 · 자동 분류는 "분류(자동) · …" 로 시작 (설명 문구 대신 자동 표시)
const auto = cardText({ category: "신경·정신", category_auto: true }, "PHASE2", "2026-10-31", 32);
assert.ok(auto.main?.startsWith("신경·정신(자동) · 2상"), auto.main ?? "null");
const autoNew = cardText({ category: "통증", category_auto: true }, "PHASE2", "2026-10-31", 32);
assert.ok(autoNew.main?.startsWith("통증(자동) · 2상"), autoNew.main ?? "null");
// WP85 · 설명 문장 함수
assert.equal(mentionSentence("frenzy", 8, 32, "128.0", undefined, true), "급등 경보 · 기준선 8일(7일 이상 충족) · 24시간 언급 32건 · 평소 대비 128배");
// WP86 · 기준선 하한 문장
assert.equal(mentionSentence("frenzy", 8, 32, "32.0", 0.25, true), "급등 경보 · 기준선 8일(7일 이상 충족) · 평소 하루 0.25건 → 오늘 32건(32배), 평소 거의 없음");
assert.equal(multSentence(0, 14), "평소 하루 0건 → 오늘 14건(14배), 평소 거의 없음");
assert.equal(multSentence(3, 12), "평소 하루 3건 → 오늘 12건(4배)");
assert.equal(shortName("IOVANCE BIOTHERAPEUTICS, INC."), "Iovance Biotherapeutics");
// WP87-2 · 전부 대문자 원문만 표기 변경 · 대소문자 섞인 원문은 그대로 (접미사만 제거)
assert.equal(shortName("ORBIMED ADVISORS LLC"), "Orbimed Advisors");
assert.equal(shortName("ELECTRA THERAPEUTICS, INC."), "Electra Therapeutics");
assert.equal(shortName("OrbiMed Advisors LLC"), "OrbiMed Advisors");
assert.equal(shortName("McArdle Capital LLC"), "McArdle Capital");
assert.equal(shortName("BioNTech SE"), "BioNTech");  // WP94 · SE 도 접미사
// WP94 · LP · L.P. · SE · PLC 접미사 (대소문자 섞인 원문 표기는 그대로)
assert.equal(shortName("BAKER BROS. ADVISORS LP"), "Baker Bros. Advisors");
assert.equal(shortName("McArdle Capital, L.P."), "McArdle Capital");
assert.equal(shortName("GSK plc"), "GSK");
assert.equal(tickerOrUnknown(""), "비상장 추정");
assert.equal(summaryStatus({ ok: false, error: "ZaiError 400/1210" }), "자동 요약 실패(ZaiError 400/1210)");
assert.ok(rumorReason(2, "collecting", 6).startsWith("이 카드에 오른 이유: 임상 종료 예정 D-2"));
const short = cardText({ category: "암", interventions: [{ name: "Drug-1", type: "DRUG" }] }, "PHASE3", "2027-02-28", 153, undefined, { short: true });
assert.ok(short.main?.startsWith("암 · 3상 · Drug-1 · ") && short.main.endsWith("종료 예정(결과 발표일 아님)"), short.main ?? "null");

// WP85 · 화면 문자열에 내부 필드 이름 금지 (frenzy · baseline · ST24 · cik) · 컴포넌트 원문 검사
const FORBIDDEN = /(?<![-\w])(frenzy|baseline|ST24|cik)(?![-\w])/i; // 하이픈 뒤 (Tailwind items-baseline 등) 는 제외
const root = path.resolve(__dirname, "..");
const files = [path.join(root, "app/biotech/page.tsx"), path.join(root, "app/biotech/docs/page.tsx"),
  ...fs.readdirSync(path.join(root, "components/biotech")).filter((f) => f.endsWith(".tsx")).map((f) => path.join(root, "components/biotech", f))];
const hits: string[] = [];
for (const f of files) {
  const src = fs.readFileSync(f, "utf8").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
  // JSX 텍스트 (태그 사이 · 중괄호 식 제외)
  for (const m of src.matchAll(/>([^<>{}]+)</g)) if (FORBIDDEN.test(m[1])) hits.push(`${path.basename(f)}: JSX "${m[1].trim()}"`);
  // 문자열 리터럴 (따옴표 · 백틱 · 백틱 안 ${...} 식은 제외) · import 경로 · 객체 키 접근은 대상 아님
  for (const m of src.matchAll(/(["'`])((?:\\.|(?!\1)[^\\])*?)\1/g)) {
    const body = m[2].replace(/\$\{[^}]*\}/g, "");
    if (FORBIDDEN.test(body) && !body.startsWith("@/") && !/^[a-z_]+$/.test(body)) hits.push(`${path.basename(f)}: 문자열 "${body.slice(0, 60)}"`);
  }
}
assert.deepEqual(hits, [], "화면 문자열에 내부 필드 이름: " + hits.join(" | "));
// WP87 · D-day
assert.equal(dday(0), "D-0");
assert.equal(dday(-1), "D+1");
assert.equal(trialSentence("PHASE3", "2026-09-29", -1), "3상 시험의 종료 예정일(9월 29일)이 지났습니다. 결과 발표를 기다리는 중입니다.");
// WP89 · 지난 시험 · 짧은 판 · 카드 이유
assert.equal(endLabel("2026-09-30", -1, "short"), "9월 30일 종료 예정일 지남(결과 발표 대기)");
assert.equal(endLabel("2026-10-03", 2, "short"), "10월 3일(D-2) 종료 예정(결과 발표일 아님)");
assert.ok(rumorReason(-1, "quiet", 9).startsWith("이 카드에 오른 이유: 임상 종료 예정일 지남(결과 발표 대기)"));
assert.equal(stageLabel("spread"), "언급 있음(평소 수준)");
// WP87 · 언급 카드 표현 (경보 아님 frenzy = 언급 늘어남)
assert.ok(mentionSentence("frenzy", 8, 4, "4.0", 0.625, false).startsWith("언급 늘어남 · "));   // 24시간 4건 · 6.4배 (경보 아님)
assert.ok(mentionSentence("frenzy", 8, 32, "32.0", 0.25, true).startsWith("급등 경보 · "));
// WP87 · 임원 매수 묶음
const f4 = [
  { ticker: "ETRA", name: "Electra Therapeutics, Inc.", cik: "0002088082", form4: { filer_cik: "1", filer_name: "ORBIMED ADVISORS LLC", filer_type: "전문 펀드", shares: 333333, price: null, filing_date: "2026-09-23", tx_date: "2026-09-21", elapsed_days: 8 } },
  { ticker: "ETRA", name: "Electra Therapeutics, Inc.", cik: "0002088082", form4: { filer_cik: "1", filer_name: "ORBIMED ADVISORS LLC", filer_type: "전문 펀드", shares: 1000000, price: null, filing_date: "2026-09-23", tx_date: "2026-09-21", elapsed_days: 8 } },
];
const gs = groupForm4(f4);
assert.equal(gs.length, 1);
assert.equal(insiderSummary(gs[0], new Date("2026-10-01T03:00:00Z")), "ETRA · Electra Therapeutics · Orbimed Advisors(전문 펀드) · 8일 전 신고 · 거래 2건 · 합계 1,333,333주 · 금액 미기재");
const priced = groupForm4(f4.map((r) => ({ ...r, form4: { ...r.form4, price: 3 } })));
assert.ok(insiderSummary(priced[0]).endsWith("금액 $3,999,999"));
assert.equal(insiderTxLine({ tx_date: "2026-09-21", shares: 333333, price: 3 }), "9/21 거래 · 333,333주 · 주당 $3.00 · $999,999.00");
// WP88 · 보도자료 제목 줄 · 상한 도달 · 첫 문단 라벨
assert.equal(exhibitLine({ ex99_1_title: "Acme Announces Results", ex99_1_status: "ok" }), "보도자료: Acme Announces Results");
assert.equal(exhibitLine({ ex99_1_title: "", ex99_1_status: "ok" }), "보도자료: 제목 없음");
assert.equal(exhibitLine({ ex99_1_status: "daily_cap" }), "보도자료: 읽지 않음 (오늘 SEC 요청 상한 도달)");
assert.equal(exhibitLine({ ex99_1_status: "none" }), "");
assert.ok(LEAD_LABEL.includes("진위 미검증"));
// WP91 · H6 폐기 확정 · 테마 순위 줄에 참고 표시
assert.ok((cardText({ category: "암" }, "PHASE2", undefined, null, { theme_ko: "비만", rank: 2, of: 6, quarter: "2026Q2" }).theme ?? "").endsWith(` · ${THEME_RANK_NOTE}`));
// WP93 · "N일 전 신고" 는 신고일 기준 (거래일 기준 elapsed_days 10 이어도 신고 9/23 → 10/1 은 8일)
assert.equal(daysSinceFiling("2026-09-23", new Date("2026-10-01T03:00:00Z")), 8);
assert.equal(daysSinceFiling("2026-09-30", new Date("2026-09-30T16:00:00Z")), 1);   // UTC 9/30 16시 = KST 10/1 01시
// WP94 · KOD 82행 (서버 복사본 실측) · 카드 요약 금액 = 자세히 줄 (센트) 합계를 마지막에 반올림한 값 · 두 화면이 같은 값
{
  const fs = require("node:fs") as typeof import("node:fs");
  const path = require("node:path") as typeof import("node:path");
  const kod = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../backend/tests/fixtures/biotech_form4_kod_rows_20260930.json"), "utf8")).rows as { tx_date: string; shares: number; price: number }[];
  const lineCents = kod.reduce((a, t) => a + (txCents(t.shares, t.price) as number), 0);
  assert.equal(kod.length, 82);
  assert.equal(insiderTotalUsd(kod), 156_986_394);
  assert.equal(Math.round(lineCents / 100), insiderTotalUsd(kod));
  const kodRows = kod.map((t) => ({ ticker: "KOD", name: "Kodiak Sciences Inc.", cik: "0001468748",
    form4: { filer_cik: "0001263508", filer_name: "BAKER BROS. ADVISORS LP", filer_type: "전문 펀드", shares: t.shares, price: t.price, filing_date: "2026-09-30", tx_date: t.tx_date, elapsed_days: 2 } }));
  const g = groupForm4(kodRows);
  assert.equal(g.length, 1);
  assert.equal(insiderSummary(g[0], new Date("2026-10-01T03:00:00Z")), "KOD · Kodiak Sciences · Baker Bros. Advisors(전문 펀드) · 1일 전 신고 · 거래 82건 · 합계 1,941,755주 · 금액 $156,986,394");
}
console.log("ok");
