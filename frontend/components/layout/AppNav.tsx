"use client";

// Toss Tradebot 상하 nav · 1022-10 1단계 (2026-10-29)
// - 윗줄: 묶음 4 (오늘 · 후보 · 내 계좌 · 기록) + 설정 · 「종목」 은 3단계 종목 화면과 함께
// - 아랫줄: 지금 묶음의 화면 탭 · 주소는 옮기지 않음 (알림 링크 11곳 그대로)
// - 메뉴에 없는 화면 (바이오 문서 · Serenity 종목 상세 등) 은 지금처럼 링크로만
// 참조: docs/plans/ui-ux-optimization/2026-10-28-information-architecture.md

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

interface Tab {
  href: string;
  label: string;
  /** 이 탭이 켜지는 다른 주소 앞부분 (하위 화면) */
  also?: string[];
}

interface Group {
  key: string;
  label: string;
  href: string;
  tabs: Tab[];
}

const GROUPS: Group[] = [
  { key: "today", label: "오늘", href: "/", tabs: [] },
  {
    key: "candidates",
    label: "후보",
    href: "/watchlist",
    tabs: [
      { href: "/watchlist", label: "단기 · Watchlist" },
      { href: "/sniper", label: "단기 · Sniper" },
      { href: "/lab/crazy", label: "미국 · Crazy" },
      { href: "/lab/moonshot", label: "미국 · Moonshot" },
      { href: "/lab/meme-watch", label: "미국 · 밈" },
      { href: "/biotech", label: "바이오" },
      { href: "/influencer/serenity", label: "인플루언서 · Serenity" },
      { href: "/influencer/serenity-hunter", label: "인플루언서 · Hunter" },
      { href: "/activist-radar", label: "이벤트 · 행동주의" },
      { href: "/powderkeg", label: "국내 가치 · 화약고", also: ["/docs/powderkeg-user-guide"] },
      { href: "/principles/screener", label: "국내 가치 · 원칙 스크리너" },
      { href: "/rulebook", label: "국내 가치 · 5단계 필터" },
      { href: "/sector-leaders", label: "국내 가치 · 섹터" },
    ],
  },
  {
    key: "account",
    label: "내 계좌",
    href: "/account",
    // 2단계 (10/29) · 옛 /dashboard·/positions 는 /account 로 합침 (next.config redirect)
    tabs: [
      { href: "/account", label: "계좌" },
      { href: "/vip", label: "VIP 감시" },
    ],
  },
  {
    key: "records",
    label: "기록",
    href: "/journal",
    tabs: [
      { href: "/journal", label: "판단 기록" },
      { href: "/logs", label: "실행 로그" },
    ],
  },
  {
    key: "settings",
    label: "설정",
    href: "/admin/settings",
    tabs: [
      { href: "/admin/settings", label: "운영 값" },
      { href: "/admin/notifications", label: "알림" },
      { href: "/principles", label: "원칙", also: ["/principles/verification", "/principles/gate-history"] },
      { href: "/lab", label: "실험장", also: ["/lab/backtest", "/lab/super-signals"] },
    ],
  },
];

function matches(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

function tabMatches(pathname: string, tab: Tab): boolean {
  return matches(pathname, tab.href) || (tab.also ?? []).some((p) => matches(pathname, p));
}

/** 가장 길게 맞는 탭을 고른다 (/principles 와 /principles/screener 처럼 겹칠 때). */
function activeTab(pathname: string): { group: Group; tab: Tab | null } {
  let best: { group: Group; tab: Tab; len: number } | null = null;
  for (const group of GROUPS) {
    for (const tab of group.tabs) {
      const prefixes = [tab.href, ...(tab.also ?? [])].filter((p) => matches(pathname, p));
      for (const p of prefixes) {
        if (!best || p.length > best.len) best = { group, tab, len: p.length };
      }
    }
  }
  if (best) return { group: best.group, tab: best.tab };
  // /influencer 는 서버 redirect · /biotech/docs 등 하위 화면은 위 prefix 로 잡힘
  return { group: GROUPS[0], tab: null };
}

export function AppNav() {
  const pathname = usePathname();
  const { group: current, tab: currentTab } = activeTab(pathname);
  const tabsRef = useRef<HTMLElement>(null);

  // 좁은 화면에서 지금 탭이 가로 스크롤 밖에 있으면 보이게 한다
  useEffect(() => {
    tabsRef.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [pathname]);

  return (
    <>
      <nav aria-label="주 메뉴" className="-mx-1 flex gap-1 overflow-x-auto text-base">
        {GROUPS.map((g) => {
          const active = g.key === current.key;
          return (
            <Link
              key={g.key}
              href={g.href}
              aria-current={active ? "page" : undefined}
              className={
                "flex min-h-[44px] shrink-0 items-center rounded-lg px-3 " +
                (active ? "font-semibold text-foreground" : "text-muted-foreground hover:text-foreground")
              }
            >
              {g.label}
            </Link>
          );
        })}
      </nav>
      {current.tabs.length > 0 && (
        <nav
          ref={tabsRef}
          aria-label={`${current.label} 화면`}
          className="-mx-1 flex gap-1 overflow-x-auto border-t border-border/50 pt-1 text-sm md:flex-wrap md:overflow-visible"
        >
          {current.tabs.map((t) => {
            const active = currentTab !== null && t.href === currentTab.href && tabMatches(pathname, t);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={
                  "flex min-h-[44px] shrink-0 items-center whitespace-nowrap rounded-lg px-3 " +
                  (active
                    ? "font-semibold text-teal-700 underline decoration-2 underline-offset-8"
                    : "text-muted-foreground hover:text-foreground")
                }
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      )}
    </>
  );
}
