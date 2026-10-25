// 1025-06 · 「토스증권에서 열기」 화면 규칙 (backend/tests/test_broker_link_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { BROKER_LABEL, SEARCH_LABEL, isKrCode, krOrderUrl, TOSS_HOME, TOSS_ACCOUNT, uniqueSymbols, usSymbolChunks } from "./broker-link";

assert.equal(krOrderUrl("005930"), "https://www.tossinvest.com/stocks/A005930/order");
assert.equal(krOrderUrl("0101N0"), "https://www.tossinvest.com/stocks/A0101N0/order");
assert.ok(isKrCode("005930") && isKrCode("0101N0"));
assert.ok(!isKrCode("AAPL") && !isKrCode("ABCDEF") && !isKrCode("12345"));
assert.equal(TOSS_HOME, "https://www.tossinvest.com/");
assert.equal(TOSS_ACCOUNT, "https://www.tossinvest.com/account");
assert.deepEqual(uniqueSymbols(["wen", "WEN", "", " aapl ", "005930"]), ["WEN", "AAPL", "005930"]);

assert.equal(BROKER_LABEL, "토스증권에서 열기 ↗");
assert.equal(SEARCH_LABEL, "토스증권 검색에서 찾기 ↗");
for (const t of [BROKER_LABEL, SEARCH_LABEL]) for (const w of ["지금", "매수", "매도", "추천"]) assert.ok(!t.includes(w), `${t} 금지어 ${w}`);
// 최종 검토 · 조회 묶음: 국내 제외 · 정렬 (순서가 바뀌어도 같은 키) · 50개씩 (뒤쪽이 빠지지 않게)
assert.deepEqual(usSymbolChunks(["WEN", "005930", "aapl", "WEN"]), [["AAPL", "WEN"]]);
assert.deepEqual(usSymbolChunks(["WEN", "AAPL"]), usSymbolChunks(["AAPL", "WEN"]));
const many = Array.from({ length: 120 }, (_, i) => `T${String(i).padStart(3, "0")}`);
const chunks = usSymbolChunks(many);
assert.deepEqual(chunks.map((c) => c.length), [50, 50, 20]);
assert.equal(chunks.flat().length, 120);
assert.deepEqual(usSymbolChunks(["005930"]), []);
console.log("broker-link ok");
