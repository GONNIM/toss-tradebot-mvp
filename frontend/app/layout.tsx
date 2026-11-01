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
// 5b (2026-11-01): 로고·로그인은 AppNav 윗줄에 넣어 머리글을 두 줄로.

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
            <div className="container mx-auto flex flex-col gap-1 px-4 py-1 md:gap-2 md:py-3">
              <AppNav
                brand={
                  <Link href="/" className="flex min-h-[44px] shrink-0 items-center text-lg font-bold">
                    <span aria-hidden>🌙</span>
                    <span className="sr-only md:not-sr-only md:ml-1">Toss Tradebot</span>
                  </Link>
                }
                session={<HeaderSession />}
              />
            </div>
          </header>
          <main className="container mx-auto break-words px-4 py-6">{children}</main>
          <footer className="mt-8 border-t border-border py-3 text-center text-xs text-muted-foreground">
            <span title="build sha · 배포 확증용 (3차 리뷰)">
              build {process.env.NEXT_PUBLIC_BUILD_SHA ?? "unknown"} · {process.env.NEXT_PUBLIC_BUILD_TIME ?? "-"}
            </span>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
