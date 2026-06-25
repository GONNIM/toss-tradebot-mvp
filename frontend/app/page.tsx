/**
 * 홈 — Phase H 갱신: 모듈 카드 4종 + 빠른 액세스.
 */
import Link from "next/link";

const CARDS = [
  {
    href: "/sector-leaders",
    title: "🇰🇷 섹터별 주도주 Top 3",
    desc: "산업통상부 월간 수출입동향 ↔ KRX 주도주. 17품목 × 24개월 Pearson + lead/lag 시그널.",
    accent: "border-cyan-500/30 hover:border-cyan-500/60",
  },
  {
    href: "/dashboard",
    title: "📊 자동매매 대시보드",
    desc: "1,500만원 시드 단타 +20% 익절 (Phase K — Toss API 활성 후).",
    accent: "border-purple-500/30 hover:border-purple-500/60",
  },
  {
    href: "/positions",
    title: "💼 보유 포지션",
    desc: "현재 보유 종목 + 손익 (Phase K 활성 후).",
    accent: "border-yellow-500/30 hover:border-yellow-500/60",
  },
];

export default function Home() {
  return (
    <div className="space-y-8">
      <section className="text-center">
        <h1 className="text-4xl font-bold">🌙 Toss Tradebot MVP</h1>
        <p className="mt-2 text-muted-foreground">
          산업통상부 수출입동향 ↔ KRX 주도주 분석 + Toss API 자동매매 (한국 주식)
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          목표: 1,000만원 → 1억원 · 절대 실현 손실 0
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {CARDS.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className={`rounded-xl border bg-card p-6 transition ${c.accent}`}
          >
            <h2 className="text-xl font-semibold">{c.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{c.desc}</p>
          </Link>
        ))}
      </section>
    </div>
  );
}
