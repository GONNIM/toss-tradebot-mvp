// 1120-01 · 메뉴 보이기 화면 쪽 순수 함수 확인 (backend/tests/test_menu_visibility.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { GROUPS } from "../components/layout/AppNav";
import {
  bestTabKey,
  MERGED_INTO,
  mergedTarget,
  pathOf,
  RECOMMENDED_HIDE_KEYS,
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

// ─── 1120-01 단계 3 · 합침 ───
// 칸 숨김은 링크의 경로로 판단한다: Moonshot 칸(/lab/crazy?view=moonshot)은 /lab/moonshot 을 숨겨도 남고 /lab/crazy 를 숨기면 함께 빠진다
assert.equal(pathOf("/lab/crazy?view=moonshot"), "/lab/crazy");
assert.equal(pathOf("/biotech#biotech-docs"), "/biotech");
const blocks3 = ["/lab/crazy", "/lab/crazy?view=moonshot", "/biotech"].map((link) => ({ link }));
assert.equal(splitHiddenCandidates(blocks3, { "/lab/moonshot": false }).hiddenCount, 0);
assert.equal(splitHiddenCandidates(blocks3, { "/lab/crazy": false }).hiddenCount, 2);

const allTabs = GROUPS.flatMap((g) => g.tabs);
const menuKeys = new Set(allTabs.map((t) => t.href));
const recommended = new Set<string>(RECOMMENDED_HIDE_KEYS);
assert.equal(recommended.size, 7);
for (const k of recommended) assert.ok(menuKeys.has(k), `권고 key ${k} 가 메뉴 탭이 아님`);
// 「같은 내용」 안내: 옛 주소의 가장 길게 맞는 key 가 메뉴 key · 받을 주소의 경로가 메뉴 key 이고 권고 숨김이 아님
for (const [oldPath, t] of Object.entries(MERGED_INTO)) {
  const k = bestTabKey(oldPath, allTabs);
  assert.ok(k && menuKeys.has(k), `옛 주소 ${oldPath} 가 메뉴 key 에 맞지 않음`);
  const target = bestTabKey(pathOf(t.href), allTabs);
  assert.ok(target && menuKeys.has(target), `받을 주소 ${t.href} 가 메뉴 key 가 아님`);
  assert.ok(!recommended.has(target as string), `받을 주소 ${t.href} 가 권고 숨김 대상`);
}
// 옛 주소 정확 일치로만 찾는다: 합치지 않은 /principles/gate-history 에는 안내가 붙지 않는다
assert.equal(mergedTarget("/principles/gate-history"), null);
assert.equal(mergedTarget("/principles/verification")?.href, "/principles/screener?view=verification");
assert.equal(mergedTarget("/principles")?.href, "/principles/screener?view=charter");
assert.equal(mergedTarget("/vip")?.href, "/account?view=vip");

// 권고 7개를 모두 숨겨도 탭 있는 묶음과 PC 분류마다 보이는 탭이 1개 이상 남는다
const recMenu: Record<string, boolean> = {};
for (const k of recommended) recMenu[k] = false;
for (const g of GROUPS) {
  if (g.tabs.length === 0) continue;
  assert.ok(visibleTabs(g.tabs, recMenu, null).length >= 1, `묶음 ${g.key} 가 통째로 빠짐`);
  const sections = new Set(g.tabs.map((t) => t.section).filter(Boolean));
  for (const sec of sections) {
    const tabsIn = g.tabs.filter((t) => t.section === sec);
    assert.ok(visibleTabs(tabsIn, recMenu, null).length >= 1, `분류 ${sec} 가 통째로 빠짐`);
  }
}

// 서버 응답 변환 · 모양이 틀리면 null
assert.deepEqual(toMenuMap({ screens: [{ key: "/a", visible: false, locked: false }] }), { "/a": false });
assert.equal(toMenuMap({}), null);
assert.equal(toMenuMap({ screens: [{ key: 1 }] }), null);
assert.equal(toMenuMap(null), null);

console.log("menu-visibility ok");
