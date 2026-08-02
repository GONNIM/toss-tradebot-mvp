"use client";

// Toss Tradebot 상하 nav · Phase L6 · 2026-08-02
// - L1 · 매일 여정 (Journal ~ Logs) · Dashboard 좌측에 🎯 Influencer 삽입
// - L2 · 조건부 · pathname /influencer 로 시작 시 [Serenity] 단독 · 그 외 기존 5개
// 참조: docs/plans/serenity-integration/01-ui-spec.md §1, §3

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_L1 = [
  { href: "/journal", label: "📓 Journal" },
  { href: "/watchlist", label: "🌙 Watchlist" },
  { href: "/sniper", label: "🚀 Sniper" },
  { href: "/positions", label: "💼 Positions" },
  { href: "/influencer", label: "🎯 Influencer" },
  { href: "/dashboard", label: "📊 Dashboard" },
  { href: "/logs", label: "📜 Logs" },
];

const NAV_L2_DEFAULT = [
  { href: "/rulebook", label: "📏 Rulebook" },
  { href: "/powderkeg", label: "🧨 Powderkeg" },
  { href: "/activist-radar", label: "🐺 Activist" },
  { href: "/vip", label: "🕵️ VIP" },
  { href: "/sector-leaders", label: "🇰🇷 Sector" },
];

const NAV_L2_INFLUENCER = [
  { href: "/influencer/serenity", label: "🧠 Serenity" },
];

function isActive(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  if (href === "/") return false;
  return pathname.startsWith(href + "/");
}

export function AppNav() {
  const pathname = usePathname();
  const isInfluencer = pathname.startsWith("/influencer");
  const l2 = isInfluencer ? NAV_L2_INFLUENCER : NAV_L2_DEFAULT;

  return (
    <>
      <nav className="flex flex-wrap gap-4 text-sm">
        {NAV_L1.map((item) => {
          const active =
            isActive(pathname, item.href) ||
            (item.href === "/influencer" && pathname.startsWith("/influencer"));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                active
                  ? "text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground"
              }
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <nav className="flex flex-wrap gap-4 border-t border-border/50 pt-2 text-xs">
        {l2.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={
              isActive(pathname, item.href)
                ? "text-foreground font-medium"
                : "text-muted-foreground/70 hover:text-foreground"
            }
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
