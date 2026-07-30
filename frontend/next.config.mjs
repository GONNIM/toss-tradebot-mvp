import { execSync } from "node:child_process";

// Build-time git SHA · 배포 확증 (3차 리뷰: SSR 마커 검증 결함 우회)
function readBuildSha() {
  const fromEnv = process.env.NEXT_PUBLIC_BUILD_SHA?.trim();
  if (fromEnv) return fromEnv;
  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf-8" }).trim();
  } catch {
    return "unknown";
  }
}
const BUILD_SHA = readBuildSha();
const BUILD_TIME = new Date().toISOString();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 'standalone' 은 next start 와 호환 안 됨 (PM2 crash loop 원인, 2026-06-21
  // restarts 241회). PM2 가 "next start -p 4000" 사용하므로 standalone 제거.
  // standalone 빌드를 원하면 PM2 script 를 ".next/standalone/server.js" 로 변경.

  env: {
    NEXT_PUBLIC_BUILD_SHA: BUILD_SHA,
    NEXT_PUBLIC_BUILD_TIME: BUILD_TIME,
  },

  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/api/v1/:path*`,
      },
    ];
  },

  // Phase A 주 2 · 2026-07-30 · 301 redirects · 크론·Telegram 알림·docs 링크 사망 방지
  // 참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §2-3
  //       리뷰 B 리스크 B1 (URL 북마크 파괴)
  async redirects() {
    return [
      // L3 실험장 이관 → /lab/*
      { source: "/crazy", destination: "/lab/crazy", permanent: true },
      { source: "/crazy/:path*", destination: "/lab/crazy/:path*", permanent: true },
      { source: "/moonshot", destination: "/lab/moonshot", permanent: true },
      { source: "/moonshot/:path*", destination: "/lab/moonshot/:path*", permanent: true },
      { source: "/meme-watch", destination: "/lab/meme-watch", permanent: true },
      { source: "/meme-watch/:path*", destination: "/lab/meme-watch/:path*", permanent: true },
      { source: "/super-signals", destination: "/lab/super-signals", permanent: true },
      { source: "/super-signals/:path*", destination: "/lab/super-signals/:path*", permanent: true },
      { source: "/backtest", destination: "/lab/backtest", permanent: true },
      { source: "/backtest/:path*", destination: "/lab/backtest/:path*", permanent: true },
      { source: "/execution", destination: "/lab/execution", permanent: true },
      { source: "/execution/:path*", destination: "/lab/execution/:path*", permanent: true },
      // 관리자 이관 → /admin/*
      { source: "/settings", destination: "/admin/settings", permanent: true },
      { source: "/settings/:path*", destination: "/admin/settings/:path*", permanent: true },
    ];
  },

  // 3차 리뷰: 기본 Next.js 정적 캐시(s-maxage=31536000)는 배포 후에도
  // nginx/CDN 이 구버전 SSR 을 계속 서빙하는 원인. 60s 캐시 + 5분 SWR 로 하향.
  async headers() {
    return [
      {
        source: "/powderkeg",
        headers: [
          { key: "Cache-Control", value: "s-maxage=60, stale-while-revalidate=300" },
        ],
      },
      {
        source: "/powderkeg/:path*",
        headers: [
          { key: "Cache-Control", value: "s-maxage=60, stale-while-revalidate=300" },
        ],
      },
    ];
  },
};

export default nextConfig;
