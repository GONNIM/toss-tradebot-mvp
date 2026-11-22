// 1120-01 단계 4 d · 오늘 화면 기한 문구 확인 (backend/tests/test_stage4_1120_01.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { daysPast, deadlineFact, todayKst } from "./today-display";

assert.equal(daysPast("2026-10-13", "2026-11-22"), 40);
assert.equal(daysPast("2026-11-22", "2026-11-22"), 0);
assert.equal(daysPast("2026-12-31", "2027-01-02"), 2);          // 해를 넘김
assert.equal(daysPast(null, "2026-11-22"), null);
assert.equal(daysPast("10/13", "2026-11-22"), null);
assert.equal(deadlineFact("2026-10-13", "2026-11-22"), "기한 도달 (10/13) · 40일 지남");
assert.equal(deadlineFact("2026-11-22", "2026-11-22"), "기한 도달 (11/22) · 오늘이 기한");
assert.equal(deadlineFact("2026-11-23", "2026-11-22"), "기한 도달 (11/23)");   // 미래 날짜는 일수를 붙이지 않음
assert.equal(deadlineFact(null, "2026-11-22"), "기한 도달");
assert.match(todayKst(new Date("2026-11-22T16:00:00Z")), /^2026-11-23$/);          // KST 자정 넘김
console.log("today-display ok");
