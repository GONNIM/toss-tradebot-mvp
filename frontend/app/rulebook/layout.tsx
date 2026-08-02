import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "📏 Rulebook · Toss Tradebot",
  description: "5단계 우량주 필터 · 손익비·물타기 감지·강의 소스 통합",
};

export default function RulebookLayout({ children }: { children: React.ReactNode }) {
  return children;
}
