// P4-3 · 과거 기록 표 문구 · 금지어 확인 (backend/tests/test_biotech_fr6c_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { FR6C_NOTICE, FR6C_PENDING, FR6C_SURVIVOR, fr6cHeader, fr6cPct, fr6cRowText, fr6cRows, fr6cSourceLine } from "./biotech-fr6c";
import type { Fr6cCell } from "./biotech-fr6c";

// 봉인 설계 문구 그대로 (1절 14행 · 9절 123행)
const design = fs.readFileSync(path.join(__dirname, "../../docs/plans/biotech/design/fr6c_design_v1.md"), "utf8");
assert.ok(design.includes(FR6C_NOTICE), "고지 문구가 설계 1절과 다름");
assert.ok(design.includes(FR6C_SURVIVOR), "생존편향 문장이 설계 9절과 다름");

const shown: Fr6cCell = { level: "방향", key: ["긍정"], label: "긍정", n: 43, missing_price: 0, status: "표시",
  source: { "WP39 사전 커밋 태그": 43 }, median: 0.0111, q25: -0.0222, q75: 0.1667, min: -0.5, max: 1.2, period: ["2025-10-08", "2026-09-01"] };
const thin: Fr6cCell = { level: "방향", key: ["혼재"], label: "혼재", n: 19, missing_price: 1, status: "표본 부족", source: { "WP39 사전 커밋 태그": 19 } };
const resid: Fr6cCell = { level: "방향 × 단계", key: ["긍정", "단계 미확인"], label: "긍정 · 단계 미확인", n: 20, missing_price: 0, status: "잔여" };

// 잔여 칸 비표시 · 20건 미만 "표본 부족(n건)" · 숫자 없음
assert.deepEqual(fr6cRows([shown, thin, resid]).map((c) => c.label), ["긍정", "혼재"]);
const t = fr6cRowText(thin);
assert.equal(t.n, "표본 부족(19건)");
assert.equal(t.median + t.iqr + t.range + t.period, "");
assert.equal(t.missing, "가격 없음 1건");
const s = fr6cRowText(shown);
assert.equal(s.n, "43건");
assert.equal(s.median, "+1.1%");
assert.equal(s.iqr, "-2.2% ~ +16.7%");
assert.equal(s.period, "2025-10-08 ~ 2026-09-01");
assert.equal(fr6cSourceLine({ "WP39 사전 커밋 태그": 68 }), "사전 커밋 태그 68 · 사용자 확정 0");
assert.equal(fr6cPct(undefined), "-");
assert.equal(
  fr6cHeader({ ready: true, asof: "2026-10-16", window: { from: "2024-10-16", to: "2026-10-16", months: 24 }, events_in_window: 68, missing_price: 0 }),
  "집계 기준일 2026-10-16 · 표시 창 최근 24개월(2024-10-16 ~ 2026-10-16) · 창 안 발표 68건 · 가격 없음 0건",
);
assert.ok(FR6C_PENDING.startsWith("과거 기록 준비 중"));

// 금지어 (예상 수익률 · 확률 · 매수 시기 등) · 과거 기록 표 소스 전체
const FORBIDDEN = ["예상 수익률", "기대 수익", "확률", "매수 시기", "매수 추천", "목표가", "평균"];
for (const f of ["./biotech-fr6c.ts", "../components/biotech/Fr6cTable.tsx"]) {
  const src = fs.readFileSync(path.join(__dirname, f), "utf8");
  for (const w of FORBIDDEN) assert.ok(!src.includes(w), `${f} 금지어 "${w}"`);
}
console.log("biotech-fr6c.check OK");
