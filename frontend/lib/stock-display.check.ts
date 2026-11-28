// 1128-01 · 종목 상세 글자 · 오래됨 표시 · 거래량 색 확인 (npx tsx lib/stock-display.check.ts)
import assert from "node:assert/strict";
import { hasVolume, marketText, staleBadge, volColor, volumeBars, volumeKo, wonKo } from "./stock-display";

const T = "2026-11-28";
assert.equal(staleBadge("meme", "2026-11-21", T), null); // 7일 = 기준 안
assert.equal(staleBadge("meme", "2026-11-20", T), "8일 전 자료");
assert.equal(staleBadge("activist", "2026-11-10", T), null); // 주 단위 21일
assert.equal(staleBadge("activist", "2026-10-30", T), "29일 전 자료");
assert.equal(staleBadge("sector_leaders", "2026-10-20", T), null); // 월 단위 45일 안
assert.equal(staleBadge("sector_leaders", "2026-09-01", T), "2개월 전 자료");
assert.equal(staleBadge("blue_chip", "2026-11-21", T), null); // 매일 22:30 잡 · 7일 기준
assert.equal(staleBadge("blue_chip", "2026-11-20", T), "8일 전 자료");
assert.equal(staleBadge("powderkeg", null, T), null);
assert.equal(staleBadge("unknown_source", "2026-10-01", T), "58일 전 자료"); // 모르는 출처는 주 단위

assert.equal(volumeKo(345_6789), "345.7만 주");
assert.equal(volumeKo(123_456_789), "1.23억 주");
assert.equal(volumeKo(8200), "8,200주");
assert.equal(volumeKo(null), "자료 없음");
assert.equal(wonKo(412_300_000_000_000), "412조 3,000억 원");
assert.equal(wonKo(850_000_000_000), "8,500억 원");
assert.equal(wonKo(5_000_000), "500만 원");
assert.equal(wonKo(null), "자료 없음");

const bars = volumeBars([{ x: "a", c: 10, v: 5 }, { x: "b", c: 11, v: 6 }, { x: "c", c: 9, v: null }, { x: "d", c: 9, v: 7 }]);
assert.deepEqual(bars.map((b) => b.up), [null, true, false, null]);
assert.equal(volColor(true), "hsl(var(--up))");
assert.equal(volColor(false), "hsl(var(--down))");
assert.equal(hasVolume([{ v: null }, {}]), false);
assert.equal(hasVolume([{ v: null }, { v: 3 }]), true);
assert.equal(marketText("KR", "KOSPI"), "코스피");
assert.equal(marketText("KR", "KOSDAQ"), "코스닥");
assert.equal(marketText("KR", null), "국내");
assert.equal(marketText("US", null), "미국");
console.log("stock-display.check OK");
