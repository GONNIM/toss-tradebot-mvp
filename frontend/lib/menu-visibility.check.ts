// 1120-01 · 메뉴 보이기 화면 쪽 순수 함수 확인 (backend/tests/test_menu_visibility.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import {
  bestTabKey,
  firstVisibleHref,
  isHidden,
  splitHiddenCandidates,
  toMenuMap,
  visibleGroups,
  visibleTabs,
} from "./menu-visibility";

const tabs = [
  { href: "/watchlist", label: "a" },
  { href: "/sniper", label: "b" },
  { href: "/lab/crazy", label: "c" },
];
const groups = [
  { key: "today", tabs: [] as { href: string }[] },
  { key: "candidates", tabs },
  { key: "records", tabs: [{ href: "/journal" }, { href: "/logs" }] },
];

// 읽기 실패(null) · 값 없음 → 모두 보임
assert.equal(isHidden(null, "/watchlist"), false);
assert.equal(isHidden({}, "/watchlist"), false);
assert.equal(isHidden({ "/watchlist": false }, "/watchlist"), true);
// 잠금 화면은 숨김 값이 있어도 보임
assert.equal(isHidden({ "/sniper": false, "/admin/menu": false, "/plans": false }, "/sniper"), false);
assert.equal(isHidden({ "/admin/menu": false }, "/admin/menu"), false);

// 숨긴 탭 빠짐 · 지금 화면 탭은 남음
const m1 = { "/watchlist": false, "/lab/crazy": false };
assert.deepEqual(visibleTabs(tabs, m1, null).map((t) => t.href), ["/sniper"]);
assert.deepEqual(visibleTabs(tabs, m1, "/watchlist").map((t) => t.href), ["/watchlist", "/sniper"]);
assert.deepEqual(visibleTabs(tabs, null, null).length, 3);

// 빈 묶음 빠짐 · 오늘(원래 탭 없음)은 어떤 설정에서도 남음 · 지금 화면 탭 든 묶음은 남음
const all = { "/journal": false, "/logs": false, "/watchlist": false, "/sniper": false, "/lab/crazy": false };
// /sniper 는 잠금이라 숨김 값이 있어도 후보 묶음이 남는다 · 기록 묶음(잠금 없음)은 두 탭이 숨으면 빠진다
assert.deepEqual(visibleGroups(groups, all, null).map((g) => g.key), ["today", "candidates"]);
assert.deepEqual(visibleGroups(groups, all, "/journal").map((g) => g.key), ["today", "candidates", "records"]);
assert.deepEqual(visibleGroups(groups, null, null).map((g) => g.key), ["today", "candidates", "records"]);
assert.deepEqual(visibleGroups(groups, { "/journal": false }, null).map((g) => g.key), ["today", "candidates", "records"]);
// 모든 key 를 숨김으로 줘도 오늘은 남는다
const everything: Record<string, boolean> = {};
for (const g of groups) for (const t of g.tabs) everything[t.href] = false;
assert.ok(visibleGroups(groups, everything, null).some((g) => g.key === "today"));
// 잠금 탭이 없는 묶음만 있으면 오늘 외에는 모두 빠진다
assert.deepEqual(visibleGroups([groups[0], groups[2]], everything, null).map((g) => g.key), ["today"]);

// 묶음 링크 · 분류 링크는 보이는 첫 탭
assert.equal(firstVisibleHref(tabs, { "/watchlist": false }, "/watchlist"), "/sniper");
assert.equal(firstVisibleHref([{ href: "/journal" }, { href: "/logs" }], { "/journal": false }, "/journal"), "/logs");
assert.equal(firstVisibleHref(tabs, null, "/watchlist"), "/watchlist");
assert.equal(firstVisibleHref([{ href: "/journal" }], { "/journal": false }, "/journal"), "/journal"); // 모두 숨음 → 대체 주소

// 가장 길게 맞는 key · also 포함
const pt = [
  { href: "/principles", also: ["/principles/verification", "/principles/gate-history"] },
  { href: "/principles/screener" },
  { href: "/powderkeg", also: ["/docs/powderkeg-user-guide"] },
];
assert.equal(bestTabKey("/principles/screener/x", pt), "/principles/screener");
assert.equal(bestTabKey("/principles/verification", pt), "/principles");
assert.equal(bestTabKey("/docs/powderkeg-user-guide", pt), "/powderkeg");
assert.equal(bestTabKey("/nothing", pt), null);

// 오늘 후보 칸: 숨김 0개 → 줄 없음 · N 이 맞음 · 읽기 실패(null)면 7개 모두
const blocks = ["/watchlist", "/powderkeg", "/lab/meme-watch", "/activist-radar", "/lab/crazy", "/lab/moonshot", "/biotech"].map((link) => ({ link }));
assert.equal(splitHiddenCandidates(blocks, {}).hiddenCount, 0);
assert.equal(splitHiddenCandidates(blocks, null).shown.length, 7);
const sp = splitHiddenCandidates(blocks, { "/lab/crazy": false, "/biotech": false });
assert.equal(sp.hiddenCount, 2);
assert.equal(sp.shown.length, 5);

// 서버 응답 변환 · 모양이 틀리면 null
assert.deepEqual(toMenuMap({ screens: [{ key: "/a", visible: false, locked: false }] }), { "/a": false });
assert.equal(toMenuMap({}), null);
assert.equal(toMenuMap({ screens: [{ key: 1 }] }), null);
assert.equal(toMenuMap(null), null);

console.log("menu-visibility ok");
