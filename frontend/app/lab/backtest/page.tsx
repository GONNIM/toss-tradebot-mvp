import Link from "next/link";

// 쉬는 기능 · 화면 퇴역 (1025-03 · 임의 조합 백테스트 편향) · 옛 화면 코드는 git 기록에 남음
export default function BacktestRetired() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">🧪 Backtest</h1>
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        이 기능은 쉬고 있습니다. 여러 원천을 마음대로 조합해 돌리는 백테스트는 우연히 좋아 보이는 조합을 고르게 만들어(데이터 마이닝 편향) 화면을 내렸습니다 (2026-10-27).
      </div>
      <Link href="/lab" className="text-sm text-primary hover:underline">
        ← 실험장 목록으로
      </Link>
    </div>
  );
}
