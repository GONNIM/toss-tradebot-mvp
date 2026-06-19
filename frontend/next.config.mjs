import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",  // optimus8 self-host PM2 운영 최적화 (결정 42)

  // FastAPI Backend 프록시 (동일 도메인 운영 — 결정 42)
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/api/v1/:path*`,
      },
    ];
  },

  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
