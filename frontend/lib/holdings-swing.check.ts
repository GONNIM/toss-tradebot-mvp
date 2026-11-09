// 1108-02 · 보유 종목 사실 문구 도우미 (backend/tests/test_holdings_swing.py 의 tsx 시험이 실행)
import assert from "node:assert/strict";
import {
  daysLeftText, deadlineText, distanceText, drawdownText, gapText, needText, peakNote, sourceText, toneOf, usdPnlText, wonConvertText,
  type GoalShort,
} from "./holdings-swing";

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
  "기준일 2026-10-01(기록 시작) 뒤 최고 종가 · 기록 전 기간 제외 · 토스 종가 기준",
);
assert.equal(gapText({ date: "2026-11-06", toss_close: 103, official_close: 100, gap_pct: 3, flag: true }), "11/6 토스 종가가 공식 종가보다 +3.00%");
// 3단계 · 미국 달러 손익 · 원화 환산 · 환율 표기
assert.equal(usdPnlText(12.3), "+$12.30");
assert.equal(usdPnlText(-1234.5), "-$1,234.50");
assert.equal(usdPnlText(null), "—");
assert.equal(
  wonConvertText(17220, { rate: 1400, source: "toss", validFrom: "2026-11-06T09:00:00+09:00" }),
  "원화 환산 +₩17,220 · 지금 환율 1,400 (토스 참고 환율 · 11/6 09:00 기준)",
);
assert.equal(
  wonConvertText(-500, { rate: 1330, source: "fallback", validFrom: null }),
  "원화 환산 -₩500 · 지금 환율 1,330 (추정 환율 · 고정값)",
);
assert.equal(wonConvertText(100, { rate: null, source: null, validFrom: null }), "원화 환산 +₩100 · 환율 정보 없음");
// 필요 상승률 · 본전 위 · 기한 지남
const g = {
  kind: "short", basis: { close: 100, date: "2026-11-06", source: "krx" }, cost_pct: 0.215, limits: [], disclaimer: "",
  need_pct: 12.345, above_breakeven: false, deadline: "2027-02-01", deadline_source: "default",
  deadline_basis_date: "2026-10-01", deadline_basis_source: "record", days_left: 63, past_deadline: false,
  sigma120_pct: 2, long_series: null, windows: [],
} as GoalShort;
assert.equal(needText(g), "본전까지 필요 상승률 +12.35%");
assert.equal(needText({ ...g, need_pct: null, above_breakeven: true }), "이미 본전 위");
assert.equal(daysLeftText(g), "약 63 거래일 (평일 수 · 휴장일 안 뺌)");
assert.equal(daysLeftText({ ...g, days_left: 0, past_deadline: true }), "기한 지남");
assert.equal(deadlineText(g), "기한 2027-02-01 (기본값 · 기준일 2026-10-01(기록 시작) + 1년)");
assert.equal(deadlineText({ ...g, deadline_source: "user" }), "기한 2027-02-01 (직접 정함)");
assert.equal(
  drawdownText({ threshold_pct: 30, ended: 2, recovered: 1, days_min: 40, days_max: 300, days_median: 90, ongoing: null }),
  "고점 대비 -30% 넘게 내린 일 끝난 2번 · 앞 고점 회복 1번 · 걸린 거래일 40~300일 (가운데 90일)",
);
assert.equal(
  drawdownText({ threshold_pct: 30, ended: 3, recovered: 3, days_min: 40, days_max: 300, days_median: 90.5, ongoing: null }),
  "고점 대비 -30% 넘게 내린 일 끝난 3번 모두 앞 고점 회복 · 걸린 거래일 40~300일 (가운데 90.5일)",
);
assert.equal(drawdownText({ threshold_pct: 30, ended: 0, recovered: 0, days_min: null, days_max: null, days_median: null, ongoing: null }), "고점 대비 -30% 넘게 내린 일 끝난 사례 없음");
assert.equal(daysLeftText({ ...g, deadline: null, days_left: null }), "남은 거래일 계산 안 함");
console.log("holdings-swing ok");
