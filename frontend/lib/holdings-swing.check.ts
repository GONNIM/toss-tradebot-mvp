// 1108-02 · 보유 종목 사실 문구 도우미 (backend/tests/test_holdings_swing.py 의 tsx 시험이 실행)
import assert from "node:assert/strict";
import { distanceText, gapText, peakNote, sourceText, toneOf } from "./holdings-swing";

assert.equal(distanceText({ days: 20, avg: 100, distance_pct: 3.2, note: null }), "위 +3.20%");
assert.equal(distanceText({ days: 20, avg: 100, distance_pct: -1.5, note: null }), "아래 -1.50%");
assert.equal(distanceText({ days: 120, avg: null, distance_pct: null, note: "자료 부족" }), "자료 부족");
assert.equal(toneOf(1), "up"); // 상승 빨강
assert.equal(toneOf(-1), "down"); // 하락 파랑
assert.equal(toneOf(null), "flat");
assert.equal(sourceText({ close_source: "krx", as_of: "2026-11-06" }), "KRX 공식 종가 · 11/6 기준");
assert.equal(sourceText({ close_source: "toss", as_of: null }), "토스 일봉 종가");
assert.equal(
  peakNote({ from_peak_pct: -4, peak_close: 10, peak_date: "2026-10-05", peak_complete: false, basis_date: "2026-10-01", basis_source: "record" }),
  "기준일 10/1(기록 시작) 뒤 최고 종가 · 기록 전 기간 제외",
);
assert.equal(gapText({ date: "2026-11-06", toss_close: 103, official_close: 100, gap_pct: 3, flag: true }), "11/6 토스 종가가 공식 종가보다 +3.00%");
console.log("holdings-swing ok");
