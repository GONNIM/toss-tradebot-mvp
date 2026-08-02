// Home · 오늘의 컨트롤 타워 · Phase A 주 2 · 2026-07-30
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §3-1
//       docs/plans/toss-tradebot-tobe/identity.md v3.0
//
// 폐기 슬로건: "1,000만원 → 1억원 · 절대 실현 손실 0" (v3.0 정체성 재정의)
// 실시간 배지 (Watchlist / Sniper / Tier1 / Kill Switch) · Phase B 신설 시 API 연결

import Link from "next/link";
import { JournalKpiBadge } from "@/components/home/JournalKpiBadge";

const L1 = [
  { href: "/journal", emoji: "📓", title: "Judgment Journal", desc: "판정→결과 폐루프 · rejection criteria 강제 · Phase B 신설 예정" },
  { href: "/watchlist", emoji: "🌙", title: "Watchlist", desc: "마감후 예측 · 다음날 top 30" },
  { href: "/sniper", emoji: "🚀", title: "Sniper", desc: "개장 진입 · tape_score · Kill Switch" },
  { href: "/positions", emoji: "💼", title: "Positions", desc: "보유 관찰 · Phase K 후 실 데이터" },
  { href: "/dashboard", emoji: "📊", title: "Dashboard", desc: "성과 · Phase K 후 실 데이터" },
  { href: "/logs", emoji: "📜", title: "Logs", desc: "감사 로그" },
];

const L2 = [
  { href: "/rulebook", emoji: "📏", title: "Rulebook", desc: "판정 원칙집 · 손익비·물타기 감지 · 강의·서적·논문 통합", badge: "PRINCIPLE" },
  { href: "/powderkeg", emoji: "🧨", title: "Powderkeg", desc: "딥밸류 스크리너 v2 · Tier 1 lock 10 종목", badge: "LEADING" },
  { href: "/activist-radar", emoji: "🐺", title: "Activist Radar", desc: "SEC 13D/G · Wolf Pack · DART", badge: "COINCIDENT" },
  { href: "/vip", emoji: "🕵️", title: "VIP", desc: "개별 종목 딥다이브", badge: "COINCIDENT" },
  { href: "/sector-leaders", emoji: "🇰🇷", title: "Sector Leaders", desc: "수출 매크로 상관", badge: "LAGGING" },
];

const badgeColor = (b: string) =>
  b === "LEADING"
    ? "bg-blue-500/20 text-blue-400"
    : b === "COINCIDENT"
    ? "bg-green-500/20 text-green-400"
    : b === "PRINCIPLE"
    ? "bg-purple-500/20 text-purple-400"
    : "bg-gray-500/20 text-gray-400";

export default function Home() {
  return (
    <div className="space-y-10">
      <section className="border-b border-border pb-6">
        <h1 className="text-3xl font-bold">🌙 Toss Tradebot</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          개인 전문 정보 창구 · Stage 1 개인 판단 도구 · 자동매매 절대 연결 금지
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          2026-1억-Sprint 서브루틴 ·{" "}
          <span className="italic">"판정→결과 폐루프로 자기 오류율 측정"</span>
        </p>
      </section>

      {/* Phase E · 판정 축적 실시간 배지 (사용 정착 유도) */}
      <JournalKpiBadge />

      {/* Stage 1 실시간 배지 4개 (Phase F API 연결 예정 · 지금은 안내) */}
      <section className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          오늘의 컨트롤 타워 (실시간 배지 · Phase F API 연결 예정)
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {["Watchlist 확정", "Sniper enabled", "Tier 1 lock", "Kill Switch"].map((label) => (
            <div key={label} className="rounded border border-border bg-card px-3 py-2">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-1 text-sm font-semibold text-muted-foreground/70">— (연결 대기)</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          L1 · 매일 (개장 여정 시간축)
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {L1.map((c) => (
            <Link
              key={c.href}
              href={c.href}
              className="rounded-lg border border-border bg-card p-4 transition hover:border-primary/60"
            >
              <div className="flex items-center gap-2">
                <span className="text-lg">{c.emoji}</span>
                <span className="font-semibold">{c.title}</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{c.desc}</p>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          L2 · 심층 (주말 리서치)
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {L2.map((c) => (
            <Link
              key={c.href}
              href={c.href}
              className="rounded-lg border border-border bg-card p-4 transition hover:border-primary/60"
            >
              <div className="flex items-center gap-2">
                <span className="text-lg">{c.emoji}</span>
                <span className="font-semibold">{c.title}</span>
                <span className={`ml-auto rounded px-2 py-0.5 text-[10px] font-semibold ${badgeColor(c.badge)}`}>
                  {c.badge}
                </span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{c.desc}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="text-xs text-muted-foreground">
        <p>
          L3 실험장은 <Link href="/lab" className="underline hover:text-foreground">🧪 Lab</Link> 인덱스에서 접근.
          관리자 설정은 우측 상단 ⚙️.
        </p>
      </section>
    </div>
  );
}
