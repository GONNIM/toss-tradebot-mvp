// 1110-02 · VIP 탭 도우미 점검 (backend/tests/test_vip_tabs.py 의 tsx 시험이 실행) · 값은 모두 가짜
import assert from "node:assert/strict";
import { pickTab, pnlLines, priceText, tabKey, tabLabel, type VipTab } from "./vip-tabs";
import {
  CROSS_NOTE, crossDirText, crossPoints, crossRowText, dailySourceText, dailyTipText, longMaSourceText, monthTicks, recentCrosses,
  splitMa, spreadLabels,
} from "./holdings-swing";

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

// 1110-03 · 평균선 넘은 지점 — 앞 「쪽 있는」 날과 쪽이 다를 때만 · 선 없음·같음은 건너뜀 · 첫 날은 지점 아님
{
  const P = (date: string, c: number, m: number | null) => ({ date, c, m });
  const pts = [
    P("2026-01-02", 9, null), // 선 없음
    P("2026-01-09", 11, 10), // 첫 쪽(위) — 지점 아님
    P("2026-01-16", 9, 10), // 위 → 아래
    P("2026-01-23", 10, 10), // 같음 — 건너뜀
    P("2026-01-30", 9.5, 10), // 아래 그대로
    P("2026-02-06", 10.5, 10), // 아래 → 위
    P("2026-02-13", 11, 10.2), // 위 그대로
  ];
  const got = crossPoints(pts);
  assert.deepEqual(got.map((g) => [g.date, g.dir]), [["2026-01-16", "down"], ["2026-02-06", "up"]]);
  assert.deepEqual(got[1], { date: "2026-02-06", c: 10.5, m: 10, dir: "up" });
  // 같음을 사이에 둔 같은 쪽은 지점 아님
  assert.deepEqual(crossPoints([P("a", 9, 10), P("b", 10, 10), P("c", 9, 10)]), []);
  // 선 없음 뒤 처음 쪽은 지점 아님
  assert.deepEqual(crossPoints([P("a", 9, null), P("b", 11, 10)]), []);
  assert.deepEqual(crossPoints([]), []);
  // 마지막 지점 뒤로 같은 쪽이 이어진 수 = 서버 streak_weeks (쪽 없는 주가 없을 때)
  const series = [11, 12, 9, 8, 7, 12, 13, 14].map((c, i) => P(`w${i}`, c, 10));
  const last = crossPoints(series).at(-1)!;
  assert.equal(series.length - series.findIndex((s) => s.date === last.date), 3);
  // 최근 것 먼저 · 5개까지
  const many = Array.from({ length: 8 }, (_, i) => P(`d${i}`, i % 2 ? 9 : 11, 10));
  const rc = recentCrosses(crossPoints(many));
  assert.equal(rc.length, 5);
  assert.equal(rc[0].date, "d7");
  assert.equal(crossDirText("40주선", "up"), "▲ 40주선 위로 올라섬");
  assert.equal(crossDirText("200일선", "down"), "▼ 200일선 아래로 내려감");
  assert.deepEqual(crossRowText({ date: "2026-02-06T00:00:00", c: 12345.678, m: 12000, dir: "up" }, "200일선"), {
    date: "2026-02-06", dir: "▲ 200일선 위로 올라섬", close: "종가 12,345.68", line: "200일선 12,000",
  });
  assert.equal(CROSS_NOTE, "표시는 지난 사실이며 매매 지시가 아님");
}
console.log("cross ok");
