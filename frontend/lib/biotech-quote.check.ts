// 1111-01 · 가격·전문가 의견 칸 글자 확인 (backend/tests/test_biotech_quotes.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { changeLine, countLine, liveLine, ratioPct, shares, targetLine, usd, type QuoteOpinion, type QuoteView } from "./biotech-quote";

const op: QuoteOpinion = {
  head: "전문가 의견 모음 · 추정 · 보장 아님", grade_note: "증권사 표기 원문 (번역 · 해석 안 함)", n_opinions: 10,
  dist: { strongBuy: 3, buy: 8, hold: 0, sell: 0, strongSell: 0 }, dist_sum: 11, count_mismatch: true,
  targets: { mean: 95.7, median: 88, high: 150, low: 80 }, changes: [], source: "야후 (yfinance)",
};
assert.equal(countLine(op), "의견 수 10명 · 의견 분포 합 11명 (야후 집계끼리 다름 · 둘 다 그대로 보여 드립니다)");
assert.equal(targetLine(op), "목표가 평균 95.70 · 중앙 88.00 · 최고 150.00 · 최저 80.00 (달러)");
assert.equal(targetLine({ ...op, targets: {} }), null);
assert.equal(changeLine({ date: "2026-10-12", firm: "Firm One", to_grade: "Buy", from_grade: "Buy", action: "main", pt_now: 84, pt_prior: 70 }), "10/12 Firm One · Buy · 목표가 70 → 84");
assert.equal(changeLine({ date: "2026-01-28", firm: "Firm Two", to_grade: "Overweight", from_grade: "", action: "init", pt_now: 66, pt_prior: 0 }), "1/28 Firm Two · Overweight · 목표가 66");
assert.equal(usd(2_712_858_368), "2.71B 달러");
assert.equal(usd(481_593_984), "481.6M 달러");
assert.equal(shares(1_124_404), "1.12M주");
assert.equal(ratioPct(0.1192), "11.9%");
assert.equal(usd(null), "자료 없음");

const base: QuoteView = { ticker: "ZZQA", asof: "2026-11-12", live: null, live_note: null, basics: null, chart: null, opinion: null, summary: null, sec8k: null, use_note: "" };
assert.equal(
  liveLine({ ...base, live_note: "실시간 실패 · 저장 종가를 보여 드립니다", basics: { price_close: 12.5 } as QuoteView["basics"] }),
  "실시간 실패 · 저장 종가를 보여 드립니다 · 저장 종가 12.50 달러 (11/12 조회)",
);
assert.equal(
  liveLine({ ...base, live: { price: 13, change_pct: 4, market_status: "OPEN", source: "네이버 실시간" } }),
  "현재가 13.00 달러 (+4.00%) · 장중 · 네이버 실시간",
);

// 새 화면 파일 고정 문자열에 명령문 · 신호 낱말 · 계산 낱말 없음 (서버 자료 문자열은 대상 아님)
const SIGNAL = /골든|데드|크로스|교차|정배열|역배열|사십시오|사세요|파세요|여력|upside|downside/i;
const root = path.resolve(__dirname, "..");
const hits: string[] = [];
for (const f of [path.join(root, "components/biotech/QuotePanel.tsx"), path.join(root, "lib/biotech-quote.ts")]) {
  const src = fs.readFileSync(f, "utf8").replace(/\/\/[^\n]*/g, "");
  for (const m of src.matchAll(/>([^<>{}]+)</g)) if (SIGNAL.test(m[1])) hits.push(`${path.basename(f)}: ${m[1].trim()}`);
  for (const m of src.matchAll(/"([^"\n]*)"|`([^`]*)`/g)) {
    const s = m[1] ?? m[2] ?? "";
    if (SIGNAL.test(s)) hits.push(`${path.basename(f)}: ${s.slice(0, 60)}`);
  }
}
assert.deepEqual(hits, [], "새 화면 고정 문자열에 금지 낱말: " + hits.join(" | "));
console.log("ok");
