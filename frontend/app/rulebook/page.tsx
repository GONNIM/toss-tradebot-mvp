// 📏 Rulebook · 판정 원칙집 · Phase E · 2026-08-02
// 참조: docs/plans/toss-tradebot-tobe/rulebook-integration.md
//       docs/operations/principles/johnma-8-fundamentals.md

import { BlueChipList } from "@/components/rulebook/BlueChipList";
import { PrincipleCards } from "@/components/rulebook/PrincipleCards";
import { RRCalculator } from "@/components/rulebook/RRCalculator";
import { InvalidationHitLog } from "@/components/rulebook/InvalidationHitLog";
import { RRStatsCard } from "@/components/rulebook/RRStatsCard";

export const metadata = {
  title: "📏 Rulebook · Toss Tradebot",
  description: "5단계 우량주 필터 · 손익비·물타기 감지·강의 소스 통합",
};

export default function RulebookPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">📏 Rulebook</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          5단계 우량주 필터 (핵심) + 손익비·물타기 감지 · 강의·서적·논문 원칙 통합 그릇.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          docs/operations/principles/ · Obsidian [[Rulebook]] 미러 동기.
        </p>
      </header>

      {/* 핵심 기능 · 원칙 1의 5단계 필터로 종목 발굴 */}
      <BlueChipList />

      <PrincipleCards />

      <div className="grid gap-4 lg:grid-cols-2">
        <RRCalculator />
        <RRStatsCard />
      </div>

      <InvalidationHitLog />
    </div>
  );
}
