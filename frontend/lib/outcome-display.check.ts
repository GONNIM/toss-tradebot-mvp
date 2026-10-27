// 1025-05 · /journal 결과 문구 (backend/tests/test_outcome_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { baseNote, notScoredText, outcomeText } from "./outcome-display";

assert.equal(outcomeText(0.3, 7), "결과 (T+7일): +30.00%");
assert.equal(outcomeText(-0.0512, 30), "결과 (T+30일): -5.12%");
assert.equal(outcomeText(null, 60), "결과 계산 대기 (T+60일 뒤 · 매일 08:10)");
assert.equal(baseNote(9, "entry"), "기준가: 적은 진입가 9 · 토스 일봉 종가 기준");
assert.equal(baseNote(10.5, "t0_close"), "기준가: 판정 시점 종가 10.5 · 토스 일봉 종가 기준");
assert.equal(baseNote(null, null), "");
assert.equal(notScoredText(true, "journal"), "자동 계산 대상 아님 (새 판정으로 대체됨)");
assert.equal(notScoredText(false, "close"), "자동 계산 대상 아님 (청산 기록)");
assert.equal(notScoredText(false, "journal"), "");
for (const t of [outcomeText(0.1, 7), baseNote(1, "entry")]) for (const w of ["매수", "매도", "추천"]) assert.ok(!t.includes(w));
console.log("outcome-display ok");
