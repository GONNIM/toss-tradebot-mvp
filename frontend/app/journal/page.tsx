// Judgment Journal · Phase B 주 3~4 신설 예정 (2026-08-12 ~ 08-25)
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
//       docs/plans/toss-tradebot-tobe/reviews/perspective-a-quant-psychology.md 권고 1
//
// 이번 Phase A 주 2 (2026-07-30) 는 라우트 재편만 · placeholder 로 라우트 확보.

export default function JournalPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold">📓 Judgment Journal</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          판정→결과 폐루프 · 모든 페이지 판정 병치 · self-page 편애 방지
        </p>
      </header>
      <div className="rounded-lg border border-dashed border-border p-8 text-center">
        <div className="text-4xl">🚧</div>
        <h2 className="mt-4 text-lg font-semibold">Phase B 주 3~4 신설 예정 (2026-08-12 ~ 08-25)</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          user_judgments 테이블 · rejection criteria 필수 · mood/market_regime 자동 태깅 · T+7·T+30 outcome 자동
        </p>
        <p className="mt-4 text-xs text-muted-foreground">
          참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
        </p>
      </div>
    </div>
  );
}
