import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";
import { AppNav } from "@/components/layout/AppNav";
import { HeaderSession } from "@/components/layout/HeaderSession";

export const metadata: Metadata = {
  title: "Toss Tradebot",
  description: "주식 급등 후보와 보유 종목 상태를 쉽게 보여 주는 개인 판단 도구",
};

// 1022-10 1단계 · 2026-10-29 · 메뉴 묶음 4 + 설정 · 헤더 로그인 하나
// 참조: docs/plans/ui-ux-optimization/2026-10-28-information-architecture.md
//   주소는 그대로 (알림 링크 11곳) · 실험장은 설정 아래 · 종목 메뉴는 3단계
//
// Nav 조건부 렌더링 위해 client 컴포넌트 AppNav · HeaderSession 으로 분리 (layout.tsx server 유지).

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
                <HeaderSession />
              </div>
              <AppNav />
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
