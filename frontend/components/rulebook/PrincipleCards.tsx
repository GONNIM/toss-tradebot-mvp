"use client";

/**
 * 3원칙 요약 카드 · Phase E · 2026-08-02.
 * 원본: docs/operations/principles/johnma-8-fundamentals.md
 */

const PRINCIPLES = [
  {
    id: 1,
    icon: "🧪",
    title: "종목 선별 5단계",
    fit: "정체성 불일치 (우량주 중장기 관점)",
    fitBad: true,
    body:
      "시총 5조↑ · 업종 미래 · 매출·순이익 상승 · 연봉 턴어라운드 · 월봉 5MA 위 3개월+.",
    adopt: "/lab/blue-chip-filter 벤치마크로만 도입 예정 (Phase 2).",
  },
  {
    id: 2,
    icon: "⚖️",
    title: "손익비 > 승률",
    fit: "즉시 적용 (Sniper 손절 · R:R baseline)",
    fitBad: false,
    body:
      "손절 -5% 고정. 3번 손절 + 1번 +30% = 흑자. R:R (Reward:Risk) ≥ 2 목표.",
    adopt: "R:R 계산기 사용 · Journal baseline avg_rr_ratio 확인.",
  },
  {
    id: 3,
    icon: "🚨",
    title: "물타기 금지",
    fit: "즉시 적용 (invalidation_hit 감지)",
    fitBad: false,
    body:
      "하락 종목 빠른 손절 → 우량 종목 이체. 매몰비용 회피.",
    adopt: "invalidation_price 이탈 시 즉시 청산 · 아래 감지 로그 자기 감사.",
  },
];

export function PrincipleCards() {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">📏 3원칙 · 존마 강의 8편</h2>
        <a
          href="https://www.tiktok.com/@official_myohada/video/7667782611628051720"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-sky-500 hover:underline"
        >
          원본 →
        </a>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {PRINCIPLES.map((p) => (
          <div
            key={p.id}
            className={`rounded-lg border p-3 ${
              p.fitBad
                ? "border-slate-500/30 bg-slate-500/5"
                : "border-emerald-500/30 bg-emerald-500/5"
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="text-lg">{p.icon}</span>
              <span className="font-semibold">
                {p.id}. {p.title}
              </span>
            </div>
            <div
              className={`mt-1 rounded px-1.5 py-0.5 text-[10px] font-semibold w-fit ${
                p.fitBad
                  ? "bg-slate-500/20 text-slate-400"
                  : "bg-emerald-500/20 text-emerald-500"
              }`}
            >
              {p.fit}
            </div>
            <p className="mt-2 text-xs text-foreground">{p.body}</p>
            <p className="mt-1 text-[10px] text-muted-foreground">→ {p.adopt}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
