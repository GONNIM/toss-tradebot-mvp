// 1025-08 · 「내 계좌」 보유 종목 표 문구 (backend/tests/test_holdings_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { fxLabel, heldLabel, peakLabel, priceText, pctText, pnlTone, wonText } from "./holdings-display";

// 환율 출처를 숨기지 않는다
assert.equal(fxLabel(1400.5, "toss"), "환율: 토스 참고 환율 1,400.5원 (실제 환전과 다를 수 있음)");
assert.equal(fxLabel(1400.5, "cached"), "환율: 토스 참고 환율 1,400.5원 · 최근 값 (실제 환전과 다를 수 있음)");
assert.equal(fxLabel(1330, "fallback"), "환율: 추정 환율 · 1330 고정 (토스 환율을 받지 못함)");
assert.equal(fxLabel(null, null), "");

assert.equal(priceText(12.5, "USD"), "$12.50");
assert.equal(priceText(70000, "KRW"), "70,000원");
assert.equal(priceText(null, "USD"), "—");
assert.equal(wonText(84000.4), "84,000원");
assert.equal(pctText(16.67), "+16.67%");
assert.equal(pctText(-20), "-20.00%");
assert.equal(pctText(0), "0.00%");
assert.equal(pnlTone(1), "up");
assert.equal(pnlTone(-1), "down");
assert.equal(pnlTone(0), "flat");
assert.equal(pnlTone(null), "flat");

// 보유 일수 · 기준일 출처를 같이 적는다
assert.equal(heldLabel({ days_held: 55, basis_date: "2026-09-01", basis_source: "journal" }), "55일 (첫 저널 판단 9/1부터)");
assert.equal(heldLabel({ days_held: 0, basis_date: "2026-10-26", basis_source: "record" }), "0일 (기록 시작 10/26부터)");
assert.equal(heldLabel({ days_held: null, basis_date: null, basis_source: null }), "기록 쌓는 중");

// 최고가 대비 · 기간이 다 차지 않았으면 그렇게 말한다
assert.equal(
  peakLabel({ from_peak_pct: -20, peak_close: 15, peak_date: "2026-09-02", peak_complete: true, currency: "USD" }),
  "-20.00% (최고 종가 $15.00 · 9/2)",
);
assert.equal(
  peakLabel({ from_peak_pct: 0, peak_close: 12, peak_date: "2026-10-26", peak_complete: false, currency: "USD" }),
  "0.00% (기록된 기간 최고 $12.00 · 10/26)",
);
assert.equal(peakLabel({ from_peak_pct: null, peak_close: null, peak_date: null, peak_complete: false, currency: "KRW" }), "—");

// 권유 문구 없음
const all = [
  fxLabel(1400, "toss"), fxLabel(1330, "fallback"),
  heldLabel({ days_held: 3, basis_date: "2026-10-23", basis_source: "record" }),
  peakLabel({ from_peak_pct: -5, peak_close: 10, peak_date: "2026-10-01", peak_complete: false, currency: "USD" }),
];
for (const t of all) for (const w of ["지금", "매수", "매도", "추천", "팔", "사세요"]) assert.ok(!t.includes(w), `${t} 금지어 ${w}`);
console.log("holdings-display ok");
