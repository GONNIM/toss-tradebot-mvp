import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Toss Tradebot",
  description: "개인 전문 정보 창구 · 2026-1억-Sprint 서브루틴 · Stage 1 개인 판단 도구",
};

// Phase A 주 2 · 2026-07-30 · 3계층 재편
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §3
//   L1 매일 (개장 여정 시간축) — 5개
//   L2 심층 (주말 리서치) — 4개
//   L3 실험장 (nav 히든 · /lab 인덱스만 노출)
//
// Stage 2 이행 시 관리자·외부 뷰 분리 대비 · docs/plans/toss-tradebot-tobe/stage2-architecture.md §2

const NAV_L1 = [
  { href: "/journal", label: "📓 Journal" },
  { href: "/watchlist", label: "🌙 Watchlist" },
  { href: "/sniper", label: "🚀 Sniper" },
  { href: "/positions", label: "💼 Positions" },
  { href: "/dashboard", label: "📊 Dashboard" },
  { href: "/logs", label: "📜 Logs" },
];

const NAV_L2 = [
  { href: "/rulebook", label: "📏 Rulebook" },
  { href: "/powderkeg", label: "🧨 Powderkeg" },
  { href: "/activist-radar", label: "🐺 Activist" },
  { href: "/vip", label: "🕵️ VIP" },
  { href: "/sector-leaders", label: "🇰🇷 Sector" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          <header className="sticky top-0 z-50 border-b border-border bg-card/95 backdrop-blur">
            <div className="container mx-auto flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center justify-between">
                <Link href="/" className="text-lg font-bold">
                  🌙 Toss Tradebot
                </Link>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <Link href="/lab" className="hover:text-foreground" title="L3 실험장">
                    🧪 Lab
                  </Link>
                  <Link href="/admin/settings" className="hover:text-foreground" title="관리자 설정">
                    ⚙️
                  </Link>
                </div>
              </div>
              <nav className="flex flex-wrap gap-4 text-sm">
                {NAV_L1.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
              <nav className="flex flex-wrap gap-4 border-t border-border/50 pt-2 text-xs">
                {NAV_L2.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="text-muted-foreground/70 hover:text-foreground"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="container mx-auto px-4 py-6">{children}</main>
          <footer className="mt-8 border-t border-border py-3 text-center text-[11px] text-muted-foreground">
            <span title="build sha · 배포 확증용 (3차 리뷰)">
              build {process.env.NEXT_PUBLIC_BUILD_SHA ?? "unknown"} · {process.env.NEXT_PUBLIC_BUILD_TIME ?? "-"}
            </span>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
