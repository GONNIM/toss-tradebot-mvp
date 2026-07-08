/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 'standalone' 은 next start 와 호환 안 됨 (PM2 crash loop 원인, 2026-06-21
  // restarts 241회). PM2 가 "next start -p 4000" 사용하므로 standalone 제거.
  // standalone 빌드를 원하면 PM2 script 를 ".next/standalone/server.js" 로 변경.

  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/api/v1/:path*`,
      },
    ];
  },

};

export default nextConfig;
