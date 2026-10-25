// 1025-01 · 실주문 안전 결론 한 줄 확인 (backend/tests/test_sniper_safety_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { lossLimitLabel, safetyConclusion } from "./sniper-safety";

const base = { live_enabled: true, sniper_enabled: true, watchlist_enabled: false, kill_switch_active: false, order_target: "paper" as const };

const kill = safetyConclusion({ ...base, live_enabled: false, sniper_enabled: false, kill_switch_active: true });
assert.equal(kill.tone, "stop");
assert.equal(kill.text, "Kill Switch 발동 중 — 자동 주문이 멈춰 있습니다");

const liveOff = safetyConclusion({ ...base, live_enabled: false });
assert.equal(liveOff.tone, "off");
assert.equal(liveOff.text, "실주문 허용 꺼짐 — 실계좌 주문이 나가지 않습니다");

const bothOff = safetyConclusion({ ...base, sniper_enabled: false, watchlist_enabled: false });
assert.equal(bothOff.tone, "off");
assert.equal(bothOff.text, "자동 진입 두 경로가 모두 꺼져 있습니다");

assert.equal(safetyConclusion(base).text, "자동 진입이 켜져 있습니다 (주문 대상: 모의)");
assert.equal(safetyConclusion({ ...base, order_target: "toss" }).text, "자동 진입이 켜져 있습니다 (주문 대상: 실계좌)");
assert.equal(safetyConclusion({ ...base, sniper_enabled: false, watchlist_enabled: true }).tone, "on");

assert.equal(lossLimitLabel(-0.03), "-3.0%");
assert.equal(lossLimitLabel(undefined), "—");

for (const r of [kill, liveOff, bothOff, safetyConclusion(base)]) {
  for (const w of ["지금 사", "매수하", "매도하", "추천"]) assert.ok(!r.text.includes(w), `${r.text} 금지어 ${w}`);
}
console.log("sniper-safety ok");
