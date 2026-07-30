import Link from "next/link";

// L3 실험장 인덱스 · Phase A 주 2 · 2026-07-30
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §3-3
//
// 규율:
//   - nav 완전 제거 · /lab 인덱스에서만 접근
//   - 각 항목: 마지막 검토일 · 라이브 여부 · 정체성 정합성 명시
//   - 6개월 방치 라우트 자동 삭제 룰 (crontab 예정)
//   - Home L1 매일 여정에 편입되지 않은 이유 명시

type LabItem = {
  href: string;
  name: string;
  desc: string;
  lastReviewed: string;
  live: boolean;
  reason: string;
};

const ITEMS: LabItem[] = [
  {
    href: "/lab/crazy",
    name: "Crazy Picks",
    desc: "US 시총 ≥ $1B universe · 5인자 가중 · Claude Haiku thesis",
    lastReviewed: "2026-07-30",
    live: false,
    reason: "한국 주식 전환으로 무의미 · outcome UI 노출 미완 (stage1-optimization §2-1)",
  },
  {
    href: "/lab/moonshot",
    name: "Moonshot Picks",
    desc: "16:50 KST US 장 · Top 3 · 100만원 카지노 자금 워딩",
    lastReviewed: "2026-07-30",
    live: false,
    reason: "'카지노' 워딩 감정 매매 유도 · 정체성 부적합 (리뷰 A) · 리네임 or 폐기 판정 대기",
  },
  {
    href: "/lab/meme-watch",
    name: "Meme Watch",
    desc: "5요소 confluence Meme Score · 5분 batch · LAGGING",
    lastReviewed: "2026-07-30",
    live: true,
    reason: "정체성 상징이라 유지 · L1 아님 (사후 반응 시그널 · disclaimer '카지노 머니로만')",
  },
  {
    href: "/lab/super-signals",
    name: "Super Signals",
    desc: "meme + vip + activist 병합 (2+ 소스 승격)",
    lastReviewed: "2026-07-30",
    live: false,
    reason: "세 원천 모두 lagging/reflex · 병합이 공통 시점 편향 증폭 (리뷰 A) · powderkeg validated 게이트 이식 후 재승인",
  },
  {
    href: "/lab/backtest",
    name: "Backtest",
    desc: "다중 sources 백테스트 (조합 grid)",
    lastReviewed: "2026-07-30",
    live: true,
    reason: "임의 sources 조합 = datamining bias (리뷰 A) · 전체 조합 강제 실행 UI 미개편",
  },
  {
    href: "/lab/execution",
    name: "Execution",
    desc: "kill-switch · paper · threshold 편집 UI (896 lines)",
    lastReviewed: "2026-07-30",
    live: false,
    reason: "Stage 1 '자동매매 절대 금지' 원칙과 정면 충돌 (리뷰 A) · 존재만으로 유혹 · Stage 3까지 관리자 숨김",
  },
];

export default function LabIndex() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold">🧪 Lab (실험장)</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          L3 실험장 · nav 히든 · Phase A 주 2 재편 (2026-07-30) · docs/plans/toss-tradebot-tobe/stage1-optimization.md §3-3
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          규율: 6개월 방치 라우트 자동 삭제 (예정) · 각 항목 정체성 정합성 명시
        </p>
      </header>
      <div className="rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted/30">
            <tr className="text-left">
              <th className="p-3">항목</th>
              <th className="p-3">라이브</th>
              <th className="p-3">마지막 검토</th>
              <th className="p-3">L3 이관 이유</th>
            </tr>
          </thead>
          <tbody>
            {ITEMS.map((item) => (
              <tr key={item.href} className="border-b border-border/50 last:border-0">
                <td className="p-3">
                  <Link href={item.href} className="font-medium text-primary hover:underline">
                    {item.name}
                  </Link>
                  <div className="text-xs text-muted-foreground">{item.desc}</div>
                </td>
                <td className="p-3">
                  {item.live ? (
                    <span className="rounded bg-green-500/20 px-2 py-0.5 text-xs text-green-400">live</span>
                  ) : (
                    <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-400">dormant</span>
                  )}
                </td>
                <td className="p-3 text-xs text-muted-foreground">{item.lastReviewed}</td>
                <td className="p-3 text-xs text-muted-foreground">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
