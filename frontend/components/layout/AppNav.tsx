"use client";

// Toss Tradebot 상하 nav · 1022-10 1단계 (2026-10-29)
// - 윗줄: 묶음 4 (오늘 · 후보 · 내 계좌 · 기록) + 설정 · 「종목」 은 3단계 종목 화면과 함께
// - 아랫줄: 지금 묶음의 화면 탭 · 주소는 옮기지 않음 (알림 링크 11곳 그대로)
// - 메뉴에 없는 화면 (바이오 문서 · Serenity 종목 상세 등) 은 지금처럼 링크로만
// - 5b (2026-11-01): 로고 · 윗줄 묶음 · 로그인을 한 줄에 (휴대폰 머리글 178→약 100px)
// - 1108-01 (2026-11-08): 「후보」 13개 탭을 분류 6개로 묶음. PC 는 분류 줄 → 고른 분류의 화면 줄 ·
//   휴대폰은 지금처럼 탭 한 줄 가로 스크롤. 주소는 그대로 (알림 링크 그대로 닿음).
// 참조: docs/plans/ui-ux-optimization/2026-10-28-information-architecture.md

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

interface Tab {
  href: string;
  label: string;
  /** 이 탭이 켜지는 다른 주소 앞부분 (하위 화면) */
  also?: string[];
  /** 분류 이름 (PC 에서 분류 줄로 묶음 · 1108-01) */
  section?: string;
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
      { href: "/watchlist", label: "단기 · Watchlist", section: "국내 단기" },
      { href: "/sniper", label: "단기 · Sniper", section: "국내 단기" },
      { href: "/lab/crazy", label: "미국 · Crazy", section: "미국·밈" },
      { href: "/lab/moonshot", label: "미국 · Moonshot", section: "미국·밈" },
      { href: "/lab/meme-watch", label: "밈 (국내·미국)", section: "미국·밈" },
      { href: "/biotech", label: "바이오", section: "바이오" },
      { href: "/influencer/serenity", label: "인플루언서 · Serenity", section: "인플루언서" },
      { href: "/influencer/serenity-hunter", label: "인플루언서 · Hunter", section: "인플루언서" },
      { href: "/activist-radar", label: "이벤트 · 행동주의", section: "큰손 공시" },
      { href: "/powderkeg", label: "국내 가치 · 화약고", also: ["/docs/powderkeg-user-guide"], section: "국내 가치" },
      { href: "/principles/screener", label: "국내 가치 · 원칙 스크리너", section: "국내 가치" },
      { href: "/rulebook", label: "국내 가치 · 5단계 필터", section: "국내 가치" },
      { href: "/sector-leaders", label: "국내 가치 · 섹터", section: "국내 가치" },
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

/** 탭 목록을 분류 순서대로 묶는다. 분류가 없는 탭이 하나라도 있으면 빈 배열 (분류 줄 안 씀). */
function sectionsOf(tabs: Tab[]): { name: string; tabs: Tab[] }[] {
  if (tabs.length === 0 || tabs.some((t) => !t.section)) return [];
  const out: { name: string; tabs: Tab[] }[] = [];
  for (const t of tabs) {
    const last = out[out.length - 1];
    if (last && last.name === t.section) last.tabs.push(t);
    else out.push({ name: t.section as string, tabs: [t] });
  }
  return out;
}

/** 분류 안 화면 이름에서 앞의 「분류 ·」 글자를 뗀다 (PC 분류 줄 아래에서는 겹치는 말). */
function shortLabel(label: string): string {
  const i = label.indexOf(" · ");
  return i >= 0 ? label.slice(i + 3) : label;
}

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

export function AppNav({ brand, session }: { brand: ReactNode; session: ReactNode }) {
  const pathname = usePathname();
  const { group: current, tab: currentTab } = activeTab(pathname);
  const groupsRef = useRef<HTMLElement>(null);
  const tabsRef = useRef<HTMLElement>(null);
  const sections = sectionsOf(current.tabs);
  const currentSection = sections.find((sec) => currentTab !== null && sec.tabs.includes(currentTab)) ?? null;

  // 좁은 화면에서 지금 묶음·탭이 가로 스크롤 밖에 있으면 보이게 한다
  useEffect(() => {
    for (const ref of [groupsRef, tabsRef]) {
      ref.current
        ?.querySelector<HTMLElement>('[aria-current="page"]')
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [pathname]);

  return (
    <>
      <div className="flex items-center gap-2">
        {brand}
        <nav
          ref={groupsRef}
          aria-label="주 메뉴"
          className="flex min-w-0 flex-1 overflow-x-auto text-base md:gap-1"
        >
        {GROUPS.map((g) => {
          const active = g.key === current.key;
          return (
            <Link
              key={g.key}
              href={g.href}
              aria-current={active ? "page" : undefined}
              className={
                "flex min-h-[44px] shrink-0 items-center rounded-lg px-2 md:px-3 " +
                (active ? "font-semibold text-foreground" : "text-muted-foreground hover:text-foreground")
              }
            >
              {g.label}
            </Link>
          );
        })}
        </nav>
        <div className="shrink-0">{session}</div>
      </div>
      {sections.length > 0 && (
        // PC 전용 분류 줄 · 분류를 누르면 그 분류의 첫 화면으로 간다
        <nav aria-label={`${current.label} 분류`} className="-mx-1 hidden gap-1 border-t border-border/50 pt-1 text-sm md:flex md:flex-wrap">
          {sections.map((sec) => {
            const active = currentSection?.name === sec.name;
            return (
              <Link
                key={sec.name}
                href={sec.tabs[0].href}
                aria-current={active ? "true" : undefined}
                className={
                  "flex min-h-[44px] shrink-0 items-center whitespace-nowrap rounded-lg px-3 " +
                  (active ? "bg-primary/10 font-semibold text-primary" : "text-muted-foreground hover:text-foreground")
                }
              >
                {sec.name}
                <span className="ml-1 text-xs tabular-nums text-muted-foreground">{sec.tabs.length}</span>
              </Link>
            );
          })}
        </nav>
      )}
      {sections.length > 0 && currentSection && currentSection.tabs.length > 1 && (
        // PC 전용 · 고른 분류 안의 화면만
        <nav aria-label={`${currentSection.name} 화면`} className="-mx-1 hidden gap-1 pt-0.5 text-sm md:flex md:flex-wrap">
          {currentSection.tabs.map((t) => {
            const active = t.href === currentTab?.href && tabMatches(pathname, t);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={
                  "flex min-h-[44px] shrink-0 items-center whitespace-nowrap rounded-lg px-3 " +
                  (active
                    ? "font-semibold text-primary underline decoration-2 underline-offset-8"
                    : "text-muted-foreground hover:text-foreground")
                }
              >
                {shortLabel(t.label)}
              </Link>
            );
          })}
        </nav>
      )}
      {current.tabs.length > 0 && (
        <nav
          ref={tabsRef}
          aria-label={`${current.label} 화면`}
          className={
            "-mx-1 flex gap-1 overflow-x-auto border-t border-border/50 pt-1 text-sm " +
            // 분류가 있는 묶음은 PC 에서 위 두 줄이 대신한다 · 휴대폰은 이 한 줄 그대로
            (sections.length > 0 ? "md:hidden" : "md:flex-wrap md:overflow-visible")
          }
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
                    ? "font-semibold text-primary underline decoration-2 underline-offset-8"
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
