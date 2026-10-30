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
    desc: "US 시총 ≥ $1B universe · 5인자 가중 · 분석 글은 Claude (실패 시 Z.ai)",
    lastReviewed: "2026-10-27",
    live: true,
    reason: "06:30 알림과 이어짐 · 1주·1달 과거 실현 결과 표시 · 로그인 필요 (1025-03)",
  },
  {
    href: "/lab/moonshot",
    name: "Moonshot Picks",
    desc: "16:50 KST US 장 · Top 3 · 100만원 고위험 시드",
    lastReviewed: "2026-10-27",
    live: true,
    reason: "16:50 알림과 이어짐 · 1·3·5일 과거 실현 결과 표시 · 로그인 필요 (1025-03)",
  },
  {
    href: "/lab/meme-watch",
    name: "Meme Watch",
    desc: "5요소 confluence Meme Score · 5분 batch · LAGGING",
    lastReviewed: "2026-07-30",
    live: true,
    reason: "정체성 상징이라 유지 · L1 아님 (사후 반응 시그널 · 안내 '잃어도 되는 고위험 시드로만')",
  },
  {
    href: "/lab/super-signals",
    name: "Super Signals",
    desc: "meme + vip + activist 병합 (2+ 소스 승격)",
    lastReviewed: "2026-10-27",
    live: false,
    reason: "쉬는 기능 · 5분 자동 승격·매수 잡을 껐습니다 (1025-03) · 세 원천 모두 사후 반응이라 병합이 편향을 키움 (리뷰 A)",
  },
  {
    href: "/lab/backtest",
    name: "Backtest",
    desc: "다중 sources 백테스트 (조합 grid)",
    lastReviewed: "2026-10-27",
    live: false,
    reason: "쉬는 기능 · 화면 퇴역 (1025-03) · 임의 조합 백테스트는 데이터 마이닝 편향 (리뷰 A)",
  },
  {
    href: "/sniper",
    name: "Execution → Sniper 안전 상황판",
    desc: "Kill Switch 발동·해제와 실주문 상태는 /sniper 「실주문 안전 상황판」 으로 옮겼습니다 (2026-10-25)",
    lastReviewed: "2026-10-25",
    live: false,
    reason: "옛 실행 화면 퇴역 · 서버에 연결되지 않은 카드 정리 · 원칙 1 (자동매매 연결 금지) 과 맞춤",
  },
];

export default function LabIndex() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">🧪 Lab (실험장)</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          아직 검증 중인 기능을 모아 둔 곳입니다. 메뉴에는 보이지 않으며, 결과를 실제 매매 판단에 쓰기 전에 검증이 필요합니다.
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
                    <span className="whitespace-nowrap rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-400">쉬는 기능</span>
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
