import Link from "next/link";

// 쉬는 기능 · 화면 퇴역 (1025-03 · 5분 자동 승격·매수 잡 끔) · 옛 화면 코드는 git 기록에 남음
export default function SuperSignalsRetired() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">⚡ Super Signals</h1>
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        이 기능은 쉬고 있습니다. 밈·VIP·행동주의 신호를 합쳐 자동으로 승격·매수하던 5분 작업을 껐습니다. 세 신호 모두 사후 반응이라 합치면 편향이 커집니다 (2026-10-27).
      </div>
      <Link href="/lab" className="text-sm text-primary hover:underline">
        ← 실험장 목록으로
      </Link>
    </div>
  );
}
