// WP79 · cardText() 확인 스크립트 (backend/tests/test_biotech_wp74_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { cardText, mentionSentence, multSentence, rumorReason, shortName, summaryStatus, tickerOrUnknown } from "./biotech-display";

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
assert.equal(mentionSentence("frenzy", 8, 32, "128.0"), "언급 급증 · 기준선 8일(7일 이상 충족) · 24시간 언급 32건 · 평소 대비 128배");
// WP86 · 기준선 하한 문장
assert.equal(mentionSentence("frenzy", 8, 32, "32.0", 0.25), "언급 급증 · 기준선 8일(7일 이상 충족) · 평소 하루 0.25건 → 오늘 32건(32배), 평소 거의 없음");
assert.equal(multSentence(0, 14), "평소 하루 0건 → 오늘 14건(14배), 평소 거의 없음");
assert.equal(multSentence(3, 12), "평소 하루 3건 → 오늘 12건(4배)");
assert.equal(shortName("IOVANCE BIOTHERAPEUTICS, INC."), "Iovance Biotherapeutics");
assert.equal(tickerOrUnknown(""), "티커 미확인");
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
console.log("ok");
