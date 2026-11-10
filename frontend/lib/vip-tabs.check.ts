// 1110-02 · VIP 탭 도우미 점검 (backend/tests/test_vip_tabs.py 의 tsx 시험이 실행) · 값은 모두 가짜
import assert from "node:assert/strict";
import { pickTab, pnlLines, priceText, tabKey, tabLabel, type VipTab } from "./vip-tabs";
import { dailySourceText, dailyTipText, longMaSourceText, monthTicks, splitMa, spreadLabels } from "./holdings-swing";

const base = {
  turn_date: null, is_vip_config: false, chart: null, goal: null, goal_hold_reason: null, horizon: null, ma_text: [] as never[], card_status: null,
};
const pos = { avg_price: 100, qty: 3, current_price: 90, pnl: -30, pnl_pct: -10, currency: "USD", source: "toss" as const };
const loss = { ...base, market: "US", symbol: "ZZA", name: "가짜 가", reason: "loss", position: pos } as VipTab;
const turned = { ...base, market: "KR", symbol: "900001", name: "가짜 나", reason: "turned", turn_date: "2026-11-06", position: { ...pos, pnl_pct: 1.234 } } as VipTab;
const cfg = { ...base, market: "US", symbol: "ZZC", name: "가짜 다", reason: "config_only", is_vip_config: true, position: null } as VipTab;

assert.equal(tabLabel(loss), "가짜 가(ZZA) · -10.00%");
assert.equal(tabLabel(turned), "가짜 나(900001) · 흑자 전환 11/6");
assert.equal(tabLabel(cfg), "가짜 다(ZZC) · 보유 없음 · 설정만");
assert.equal(tabKey(loss), "US:ZZA");

// ?t= 복원 · 없는 값이면 첫 탭 · 탭이 없으면 null
const tabs = [cfg, loss, turned];
assert.equal(pickTab(tabs, "KR:900001"), turned);
assert.equal(pickTab(tabs, "US:ZZA"), loss);
assert.equal(pickTab(tabs, "US:NOPE"), cfg);
assert.equal(pickTab(tabs, null), cfg);
assert.equal(pickTab([], "US:ZZA"), null);

// 손익 칸: 위 %, 아래 금액 (미국 달러 · 국내 원)
assert.deepEqual(pnlLines(pos), { pct: "-10.00%", amount: "-$30.00" });
assert.deepEqual(pnlLines({ ...pos, currency: "KRW", pnl: 12345, pnl_pct: 2.5 }), { pct: "+2.50%", amount: "+₩12,345" });
assert.deepEqual(pnlLines({ ...pos, pnl: null, pnl_pct: null }), { pct: "—", amount: "—" });
assert.equal(priceText(90, "USD"), "$90.00");
assert.equal(priceText(null, "KRW"), "—");

// 그림 문구
const chart = {
  daily: [], daily_note: null, week40: null,
  daily_source: { source: "Yahoo 종가(yfinance · 배당 미조정)", from: "2016-11-01", to: "2026-11-06", n: 2520 },
};
assert.equal(dailySourceText(chart), "일봉 출처 Yahoo 종가(yfinance · 배당 미조정) · 2016-11-01 ~ 2026-11-06 · 2,520일 · 평균선은 이 자료 전체로 계산");
assert.deepEqual(dailyTipText({ d: "2026-11-06", c: 96.5, m20: 100, m50: null, m200: 90 }),
  ["2026-11-06", "종가 96.5", "20일선 100", "50일선 자료 부족", "200일선 90"]);

// 카드 글자 줄 200일 분리
const ma = [
  { days: 20, avg: 1, distance_pct: 1, note: null }, { days: 60, avg: 1, distance_pct: 1, note: null },
  { days: 120, avg: 1, distance_pct: 1, note: null },
  { days: 200, avg: 1, distance_pct: 2, note: null, source: "KRX 일봉(pykrx · 수정주가)", as_of: "2026-11-06" },
];
const sp = splitMa(ma);
assert.equal(sp.base.length, 3);
assert.equal(longMaSourceText(sp.long!), "출처 KRX 일봉(pykrx · 수정주가) · 11/6 기준");
assert.equal(splitMa(ma.slice(0, 3)).long, null);

console.log("vip-tabs ok");

// 선 끝 글자 간격: 가까운 두 글자는 12px 이상 벌어지고, 먼 글자는 그대로
{
  const ys = spreadLabels([100, 104, 160], 12);
  assert.ok(Math.abs(ys[1] - ys[0]) >= 12 - 1e-9);
  assert.equal(ys[2], 160);
  const three = spreadLabels([50, 52, 55, 200], 12);
  const s = [three[0], three[1], three[2]].sort((a, b) => a - b);
  assert.ok(s[1] - s[0] >= 12 - 1e-9 && s[2] - s[1] >= 12 - 1e-9);
  assert.equal(three[3], 200);
}

// x축 눈금 — 달마다 첫 거래일 하나만 (같은 달 두 번 금지)
{
  const t = monthTicks(["2026-01-02", "2026-01-05", "2026-01-30", "2026-02-02", "2026-02-27", "2026-03-03"]);
  assert.deepEqual(t, ["2026-01-02", "2026-02-02", "2026-03-03"]);
  assert.equal(new Set(t.map((d) => d.slice(0, 7))).size, t.length);
}
