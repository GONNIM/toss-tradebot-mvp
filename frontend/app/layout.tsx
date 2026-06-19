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
  { href: "/crazy", label: "Crazy Picks" },
  { href: "/moonshot", label: "Moonshot" },
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
