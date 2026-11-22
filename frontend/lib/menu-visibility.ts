// 1120-01 메뉴 보이기 설정 · 화면 쪽 순수 함수 (설계: docs/plans/ui-ux-optimization/2026-11-20-menu-visibility-1120-01.md 3.3)
// 값 모양: 메뉴 탭 주소 → 보임(true)/숨김(false). 모르는 주소 · 값이 없으면 보임. menu 가 null 이면(읽기 실패 · 아직 못 읽음) 모두 보임.
// 시험: lib/menu-visibility.check.ts (backend/tests/test_menu_visibility.py 가 tsx 로 실행)

export type MenuMap = Record<string, boolean>;
export type MenuState = MenuMap | null;

export interface MenuScreenRow {
  key: string;
  visible: boolean;
  locked: boolean;
}

/**
 * 숨길 수 없는 화면 7개 · 서버 LOCKED(backend/api/routes/menu_visibility.py)와 같아야 한다 (시험이 대조).
 * 1120-01 단계 3 · 비상 정지 상황판을 /admin/settings 에도 두고 확인한 뒤 /sniper 잠금을 풀었다 (8 → 7).
 */
export const LOCKED_KEYS = [
  "/plans",
  "/plans/new",
  "/plans/adopt",
  "/account",
  "/admin/settings",
  "/admin/notifications",
  "/admin/menu",
] as const;

const LOCKED = new Set<string>(LOCKED_KEYS);

export function isLocked(key: string): boolean {
  return LOCKED.has(key);
}

/** 서버 응답 {screens:[...]} 를 값 모양으로 바꾼다. 모양이 틀리면 null (모두 보임). */
export function toMenuMap(raw: unknown): MenuState {
  const screens = (raw as { screens?: unknown } | null)?.screens;
  if (!Array.isArray(screens)) return null;
  const out: MenuMap = {};
  for (const s of screens) {
    const row = s as Partial<MenuScreenRow> | null;
    if (!row || typeof row.key !== "string" || typeof row.visible !== "boolean") return null;
    out[row.key] = row.visible;
  }
  return out;
}

/** 이 주소(메뉴 탭 key)가 숨김인가. 잠금 화면은 값이 숨김이어도 숨김이 아니다. */
export function isHidden(menu: MenuState, key: string): boolean {
  if (!menu || isLocked(key)) return false;
  return menu[key] === false;
}

export interface TabLike {
  href: string;
}

/** 숨긴 탭을 뺀다. 지금 화면의 탭은 숨김이어도 남긴다 (길을 잃지 않게). */
export function visibleTabs<T extends TabLike>(tabs: T[], menu: MenuState, currentHref: string | null): T[] {
  return tabs.filter((t) => t.href === currentHref || !isHidden(menu, t.href));
}

export interface GroupLike<T extends TabLike> {
  tabs: T[];
}

/**
 * 탭이 모두 숨은 묶음을 뺀다. 원래 탭이 없는 묶음(오늘)은 어떤 설정에서도 남긴다.
 * 지금 화면의 탭이 든 묶음은 남는다.
 */
export function visibleGroups<T extends TabLike, G extends GroupLike<T>>(groups: G[], menu: MenuState, currentHref: string | null): G[] {
  return groups.filter((g) => g.tabs.length === 0 || visibleTabs(g.tabs, menu, currentHref).length > 0);
}

/** 묶음 · 분류 링크가 갈 곳: 보이는 첫 탭. 모두 숨었으면 fallback. 지금 화면 예외는 두지 않는다 (진짜 설정 기준). */
export function firstVisibleHref(tabs: TabLike[], menu: MenuState, fallback: string): string {
  const t = tabs.find((x) => !isHidden(menu, x.href));
  return t ? t.href : fallback;
}

/** 지금 주소에 가장 길게 맞는 탭 key (/principles 와 /principles/screener 처럼 겹칠 때 · also 포함). */
export function bestTabKey(pathname: string, tabs: { href: string; also?: string[] }[]): string | null {
  const hit = (p: string, href: string) => (href === "/" ? p === "/" : p === href || p.startsWith(href + "/"));
  let best: { key: string; len: number } | null = null;
  for (const t of tabs) {
    for (const prefix of [t.href, ...(t.also ?? [])]) {
      if (hit(pathname, prefix) && (!best || prefix.length > best.len)) best = { key: t.href, len: prefix.length };
    }
  }
  return best ? best.key : null;
}

/** 주소에서 `?` · `#` 뒤를 뗀 경로 (메뉴 key 대조용 · 1120-01 단계 3). */
export function pathOf(href: string): string {
  return href.split(/[?#]/)[0] || "/";
}

/**
 * 오늘 화면 「오늘 후보」 칸: 가리키는 화면(link 의 경로)이 숨김이면 뺀다. menu 가 null 이면 모두 보인다.
 * 단계 3 · Moonshot 칸은 `/lab/crazy?view=moonshot` 을 가리킨다 → /lab/crazy 를 숨기면 Crazy · Moonshot 두 칸이 함께 빠지고,
 * /lab/moonshot 을 숨겨도 칸은 남는다.
 */
export function splitHiddenCandidates<B extends { link: string }>(blocks: B[], menu: MenuState): { shown: B[]; hiddenCount: number } {
  const shown = blocks.filter((b) => !isHidden(menu, pathOf(b.link)));
  return { shown, hiddenCount: blocks.length - shown.length };
}

// ─── 단계 3 합침 (1120-01) ───

/** 「권고대로 숨기기」 대상 · 서버 RECOMMENDED_HIDE(backend/api/routes/menu_visibility.py)와 같아야 한다 (시험이 대조). */
export const RECOMMENDED_HIDE_KEYS = [
  "/lab",
  "/influencer/serenity-hunter",
  "/vip",
  "/logs",
  "/lab/moonshot",
  "/principles",
  "/rulebook",
] as const;

/**
 * 합친 옛 주소 → 같은 내용이 있는 받을 화면 탭.
 * 옛 주소와 정확히 같을 때만 쓴다 (메뉴 key 로 찾으면 /principles/gate-history 처럼 합치지 않은 화면에 틀린 안내가 붙는다).
 */
export const MERGED_INTO: Record<string, { href: string; label: string }> = {
  "/vip": { href: "/account?view=vip", label: "내 계좌 › VIP 감시 탭" },
  "/logs": { href: "/journal?view=logs", label: "기록 › 판단 기록 화면의 실행 로그 탭" },
  "/lab/moonshot": { href: "/lab/crazy?view=moonshot", label: "후보 › Crazy 화면의 Moonshot 탭" },
  "/influencer/serenity/backtest": { href: "/influencer/serenity?view=backtest", label: "Serenity 화면의 백테스트 탭" },
  "/influencer/serenity/methodology": { href: "/influencer/serenity?view=methodology", label: "Serenity 화면의 방법론 탭" },
  "/principles": { href: "/principles/screener?view=charter", label: "원칙 스크리너 화면의 원칙 탭" },
  "/principles/verification": { href: "/principles/screener?view=verification", label: "원칙 스크리너 화면의 확인 대기 탭" },
  "/rulebook": { href: "/principles/screener?view=rulebook", label: "원칙 스크리너 화면의 5단계 필터 탭" },
  "/biotech/docs": { href: "/biotech#biotech-docs", label: "바이오 화면 맨 아래 「바이오 문서」 접기" },
};

/** 지금 주소(정확 일치)의 받을 화면 안내. 없으면 null. */
export function mergedTarget(pathname: string): { href: string; label: string } | null {
  return MERGED_INTO[pathname] ?? null;
}

// ─── 브라우저 보관 (마지막 값 · 첫 그림에서 메뉴가 흔들리지 않게) ───
const STORAGE_KEY = "menu-visibility:v1";

export function readStored(): MenuState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const out: MenuMap = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v !== "boolean") return null; // 깨진 값은 모두 보임
      out[k] = v;
    }
    return out;
  } catch {
    return null;
  }
}

export function writeStored(menu: MenuMap): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(menu));
  } catch {
    // 보관 불가(비공개 창 등)여도 화면은 그대로 동작
  }
}
