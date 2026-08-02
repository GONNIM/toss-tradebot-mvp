"use client";

// 15원칙 Serenity Style Fit 체크리스트 · Phase L7 · 2026-08-02
// 참조: docs/plans/serenity-integration/01-ui-spec.md §6

import type { TickerCardItem } from "@/lib/serenity/types";

type Item = {
  n: number;
  label: string;
  hint: string;
  check: (t: TickerCardItem) => "pass" | "fail" | "skip";
};

const ITEMS: Item[] = [
  {
    n: 1,
    label: "Bottleneck hunting",
    hint: "sole-source · pricing power",
    check: (t) => (t.serenity_tier && ["S", "A"].includes(t.serenity_tier) ? "pass" : "skip"),
  },
  {
    n: 2,
    label: "Multi-hop BOM",
    hint: "OSINT supply-chain mapping",
    check: (t) => (t.domain_tags.length ? "pass" : "skip"),
  },
  {
    n: 3,
    label: "Contract ARR",
    hint: "take-or-pay 계약 · ARR × 3+",
    check: () => "skip",
  },
  {
    n: 4,
    label: "Mag7 노출",
    hint: "customer 담보",
    check: () => "skip",
  },
  {
    n: 5,
    label: "GAAP margin > 60",
    hint: "정직한 discloser",
    check: () => "skip",
  },
  {
    n: 6,
    label: "Pre-ramp qualification",
    hint: "TTM 대비 미래 volume",
    check: () => "skip",
  },
  {
    n: 7,
    label: "Dilution / ATM 관리",
    hint: "ATM > 40% = 실격",
    check: (t) => (t.anti_pattern_flags.some((f) => f.includes("atm")) ? "fail" : "pass"),
  },
  {
    n: 8,
    label: "Financing tier",
    hint: "S > A > B > C > D > F",
    check: (t) => {
      if (!t.financing_tier) return "skip";
      if (["S", "A", "B"].includes(t.financing_tier)) return "pass";
      if (["D", "F"].includes(t.financing_tier)) return "fail";
      return "skip";
    },
  },
  {
    n: 9,
    label: "Short squeeze setup",
    hint: "profitable grower",
    check: () => "skip",
  },
  {
    n: 10,
    label: "Tariff-Buy",
    hint: "algo risk-off = 진입",
    check: () => "skip",
  },
  {
    n: 11,
    label: "Institutional lag",
    hint: "리테일 4-6주 리드",
    check: () => "skip",
  },
  {
    n: 12,
    label: "Vega/IV mispricing",
    hint: "options",
    check: () => "skip",
  },
  {
    n: 13,
    label: "Serenity Conviction Tier",
    hint: "S/A/B/C/D/F",
    check: (t) => {
      if (!t.serenity_tier) return "skip";
      if (["S", "A", "B"].includes(t.serenity_tier)) return "pass";
      if (t.serenity_tier === "F") return "fail";
      return "skip";
    },
  },
  {
    n: 14,
    label: "Anti-patterns",
    hint: "TA·layer 혼동·insider sales bear·cult",
    check: (t) => (t.anti_pattern_flags.length === 0 ? "pass" : "fail"),
  },
  {
    n: 15,
    label: "14점 체크리스트",
    hint: "종합 판정",
    check: () => "skip",
  },
];

const STYLE = {
  pass: { icon: "✅", cls: "text-emerald-500" },
  fail: { icon: "⛔", cls: "text-red-500" },
  skip: { icon: "⬜", cls: "text-muted-foreground" },
};

export function ChecklistCard({ ticker }: { ticker: TickerCardItem }) {
  const results = ITEMS.map((it) => ({ ...it, result: it.check(ticker) }));
  const passCount = results.filter((r) => r.result === "pass").length;
  const failCount = results.filter((r) => r.result === "fail").length;

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">📋 15원칙 · Serenity Style Fit</h2>
        <span className="text-xs">
          <span className="text-emerald-500">{passCount} pass</span>
          {" · "}
          <span className="text-red-500">{failCount} fail</span>
          {" · "}
          <span className="text-muted-foreground">
            {ITEMS.length - passCount - failCount} skip
          </span>
        </span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        일부 원칙은 자동 판정 불가 (skip) · 사용자 육안 판단 필요
      </p>
      <div className="mt-3 grid grid-cols-1 gap-1 sm:grid-cols-2">
        {results.map((r) => {
          const s = STYLE[r.result];
          return (
            <div
              key={r.n}
              className={`flex items-baseline gap-2 rounded border border-border/40 bg-background/40 px-2 py-1 text-xs`}
              title={r.hint}
            >
              <span className={s.cls}>{s.icon}</span>
              <span className="text-muted-foreground">#{r.n}</span>
              <span className={s.cls}>{r.label}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
