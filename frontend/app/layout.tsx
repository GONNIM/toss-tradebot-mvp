import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Toss Tradebot",
  description: "Toss API 기반 자동매매 + Discovery 모듈 (Crazy Picks + Moonshot Picks)",
};

const NAV = [
  { href: "/", label: "홈" },
  { href: "/sector-leaders", label: "🇰🇷 섹터별 주도주 Top 3" },
  { href: "/meme-watch", label: "🔥 밈주 워치" },
  { href: "/vip", label: "🕵️ VIP 감시" },
  { href: "/activist-radar", label: "🐺 Activist Radar" },
  { href: "/watchlist", label: "🌙 Watchlist (마감후 예측)" },
  { href: "/powderkeg", label: "🧨 화약고 스크리너" },
  { href: "/sniper", label: "🚀 급등주 스나이퍼" },
  // 아래 3개 메뉴는 정체성 재정의(급등주 사전 예측)에 따라 네비에서 제거.
  // 코드/라우트는 백업 목적으로 유지 · 직접 URL 접근은 여전히 가능.
  // { href: "/super-signals", label: "🌟 Super Signal" },
  // { href: "/backtest", label: "🧪 Backtest" },
  // { href: "/execution", label: "⚙️ 실행" },
  // { href: "/crazy", label: "Crazy Picks" },        // 한국 주식 전환으로 숨김 (라우트 유지)
  // { href: "/moonshot", label: "Moonshot" },        // 한국 주식 전환으로 숨김 (라우트 유지)
  { href: "/dashboard", label: "대시보드" },
  { href: "/positions", label: "포지션" },
  { href: "/settings", label: "설정" },
  { href: "/logs", label: "로그" },
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
            <div className="container mx-auto flex items-center justify-between px-4 py-3">
              <Link href="/" className="text-lg font-bold">
                🌙 Toss Tradebot
              </Link>
              <nav className="flex gap-4 text-sm">
                {NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="container mx-auto px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
