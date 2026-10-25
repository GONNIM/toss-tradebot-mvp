// 1025-01 · 실주문 안전 결론 한 줄 확인 (backend/tests/test_sniper_safety_display.py 가 tsx 로 실행)
// 자동 진입은 SNIPER_LIVE_ENABLED 를 보지 않는다 (live_tape/sniper.py · watchlist/execute.py · EXECUTION_BROKER 만 봄).
// 그래서 결론은 Kill Switch → 두 경로 → 주문 대상 순서로 정하고, 실주문 허용은 「수동 실주문 버튼」 줄로 따로 보인다.
import assert from "node:assert/strict";
import { lossLimitLabel, manualEntryLabel, safetyConclusion } from "./sniper-safety";

const base = { live_enabled: false, sniper_enabled: true, watchlist_enabled: false, kill_switch_active: false, order_target: "paper" as const };

const kill = safetyConclusion({ ...base, live_enabled: true, order_target: "toss", kill_switch_active: true });
assert.equal(kill.tone, "stop");
assert.equal(kill.text, "Kill Switch 발동 중 — 자동 주문이 멈춰 있습니다");

const bothOff = safetyConclusion({ ...base, live_enabled: true, order_target: "toss", sniper_enabled: false, watchlist_enabled: false });
assert.equal(bothOff.tone, "off");
assert.equal(bothOff.text, "자동 진입 두 경로가 모두 꺼져 있습니다 — 자동 주문이 나가지 않습니다");

// 리뷰 지적: 실주문 허용이 꺼져 있어도 주문 대상이 실계좌면 자동 진입은 실계좌로 나간다 → 거짓 안심 금지
const tossLiveOff = safetyConclusion({ ...base, order_target: "toss" });
assert.equal(tossLiveOff.tone, "live");
assert.equal(tossLiveOff.text, "실계좌 자동 주문이 켜져 있습니다");

const paper = safetyConclusion(base);
assert.equal(paper.tone, "on");
assert.equal(paper.text, "자동 진입이 켜져 있습니다 (주문 대상: 모의 · 실계좌 주문 없음)");
assert.equal(safetyConclusion({ ...base, sniper_enabled: false, watchlist_enabled: true }).tone, "on");

assert.equal(manualEntryLabel(false), "수동 실주문 버튼 잠김 (실주문 허용 꺼짐)");
assert.equal(manualEntryLabel(true), "수동 실주문 버튼 열림 (실주문 허용 켜짐)");

assert.equal(lossLimitLabel(-0.03), "-3.0%");
assert.equal(lossLimitLabel(undefined), "—");

const all = [kill, bothOff, tossLiveOff, paper].map((r) => r.text).concat([manualEntryLabel(true), manualEntryLabel(false)]);
for (const t of all) for (const w of ["지금", "매수", "매도", "추천"]) assert.ok(!t.includes(w), `${t} 금지어 ${w}`);
console.log("sniper-safety ok");
