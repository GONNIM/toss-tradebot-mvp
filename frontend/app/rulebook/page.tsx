// 📏 Rulebook · 판정 원칙집 · Phase E · 2026-08-02
// 참조: docs/plans/toss-tradebot-tobe/rulebook-integration.md
//       docs/operations/principles/johnma-8-fundamentals.md

import { PrincipleCards } from "@/components/rulebook/PrincipleCards";
import { RRCalculator } from "@/components/rulebook/RRCalculator";
import { InvalidationHitLog } from "@/components/rulebook/InvalidationHitLog";
import { RRStatsCard } from "@/components/rulebook/RRStatsCard";

export const metadata = {
  title: "📏 Rulebook · Toss Tradebot",
  description: "판정 원칙집 · 손익비·물타기 감지·강의 소스 통합",
};

export default function RulebookPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">📏 Rulebook</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          판정 원칙집 · 손익비·물타기 감지 · 강의·서적·논문 원칙 통합 그릇.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          docs/operations/principles/ · Obsidian [[Rulebook]] 미러 동기.
        </p>
      </header>

      <PrincipleCards />

      <div className="grid gap-4 lg:grid-cols-2">
        <RRCalculator />
        <RRStatsCard />
      </div>

      <InvalidationHitLog />
    </div>
  );
}
