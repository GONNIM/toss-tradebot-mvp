import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";
import { AppNav } from "@/components/layout/AppNav";

export const metadata: Metadata = {
  title: "Toss Tradebot",
  description: "개인 전문 정보 창구 · 2026-1억-Sprint 서브루틴 · Stage 1 개인 판단 도구",
};

// Phase A 주 2 · 2026-07-30 · 3계층 재편 (Phase L6 · 2026-08-02 Influencer 삽입)
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §3
//       docs/plans/serenity-integration/01-ui-spec.md §1
//   L1 매일 (개장 여정 시간축) — 7개 (Journal ~ Logs · Influencer 포함)
//   L2 심층 (주말 리서치) — 5개 기본 / Influencer 활성 시 [Serenity] 단독
//   L3 실험장 (nav 히든 · /lab 인덱스만 노출)
//
// Nav 조건부 렌더링 위해 client 컴포넌트 AppNav 로 분리 (layout.tsx server 유지).

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
