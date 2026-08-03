"use client";

// 90일 언급 종목 리스트 · 테이블 · Phase L9 UX · 2026-08-03
// 사용자 요구 · Ticker · Industry · Latest mention · Mentions · Bull · Bear · Neu

import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtKstDateTimeSec } from "@/lib/time";
import type { TickerCardItem } from "@/lib/serenity/types";

type SortKey =
  | "mentions_90d"
  | "mentions_today"
  | "last_signal_at"
  | "bullish_pct_90d"
  | "vs_prior_close_pct"
  | "gain_since_first_mention_pct"
  | "ticker";

type SortDir = "desc" | "asc";

const STANCE_META: Record<string, { icon: string; cls: string }> = {
  bullish: { icon: "▲", cls: "text-emerald-500" },
  bearish: { icon: "▼", cls: "text-red-500" },
  mixed: { icon: "◆", cls: "text-amber-500" },
  neutral: { icon: "●", cls: "text-slate-400" },
};

function _fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function _priorCls(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-500" : "text-red-500";
}

export function TickerTable({ items }: { items: TickerCardItem[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("mentions_90d");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [query, setQuery] = useState("");

  const sorted = useMemo(() => {
    const filtered = query
      ? items.filter((t) =>
          [t.ticker, ...(t.domain_tags ?? [])]
            .join(" ")
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
      : items;

    const dir = sortDir === "desc" ? -1 : 1;
    const val = (t: TickerCardItem): number | string => {
      switch (sortKey) {
        case "ticker":
          return t.ticker;
        case "last_signal_at":
          return t.last_signal_at ? new Date(t.last_signal_at).getTime() : 0;
        case "vs_prior_close_pct":
          return t.vs_prior_close_pct ?? -Infinity * dir;
        case "gain_since_first_mention_pct":
          return t.gain_since_first_mention_pct ?? -Infinity * dir;
        default:
          return (t as unknown as Record<string, number>)[sortKey] ?? 0;
      }
    };
    return [...filtered].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (typeof va === "string" && typeof vb === "string") {
        return va.localeCompare(vb) * dir;
      }
      return ((va as number) - (vb as number)) * dir;
    });
  }, [items, sortKey, sortDir, query]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "desc" ? "asc" : "desc");
    else {
      setSortKey(k);
      setSortDir("desc");
    }
  }

  function SortHead({ k, label, align = "left" }: { k: SortKey; label: string; align?: "left" | "right" }) {
    const active = sortKey === k;
    const arrow = active ? (sortDir === "desc" ? "▼" : "▲") : "";
    return (
      <th
        onClick={() => toggleSort(k)}
        className={`cursor-pointer select-none px-2 py-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground text-${align}`}
      >
        {label} {arrow && <span className="text-[9px]">{arrow}</span>}
      </th>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">📋 90일 언급 종목 리스트 (테이블)</h2>
          <p className="text-[10px] text-muted-foreground">
            {items.length} 종목 · 컬럼 헤더 클릭 정렬 · Ticker · Industry · Latest · Mentions · Bull/Bear/Neu · vs Prior
          </p>
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="티커·도메인 검색"
          className="rounded border border-border bg-background px-2 py-1 text-xs w-48"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr>
              <SortHead k="ticker" label="Ticker" />
              <th className="px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground">Industry</th>
              <SortHead k="last_signal_at" label="Latest mention" />
              <SortHead k="mentions_today" label="Today" align="right" />
              <th className="px-2 py-1.5 text-right text-xs font-semibold text-muted-foreground">7d</th>
              <th className="px-2 py-1.5 text-right text-xs font-semibold text-muted-foreground">28d</th>
              <SortHead k="mentions_90d" label="90d" align="right" />
              <th className="px-2 py-1.5 text-right text-xs font-semibold text-emerald-500">Bull</th>
              <th className="px-2 py-1.5 text-right text-xs font-semibold text-red-500">Bear</th>
              <th className="px-2 py-1.5 text-right text-xs font-semibold text-slate-400">Neu</th>
              <SortHead k="bullish_pct_90d" label="Bull%" align="right" />
              <SortHead k="vs_prior_close_pct" label="vs Prior" align="right" />
              <SortHead k="gain_since_first_mention_pct" label="Gain" align="right" />
              <th className="px-2 py-1.5 text-center text-xs font-semibold text-muted-foreground">Stance</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const stance = STANCE_META[t.overall_stance] ?? STANCE_META.neutral;
              const industry = t.domain_tags.length > 0 ? t.domain_tags.join(", ") : "—";
              return (
                <tr
                  key={t.ticker}
                  className={`border-b border-border/40 hover:bg-muted/20 ${
                    t.auto_avoid ? "bg-red-500/5" : ""
                  }`}
                >
                  <td className="px-2 py-1.5 font-mono font-bold">
                    <Link href={`/influencer/serenity/${t.ticker}`} className="text-primary hover:underline">
                      {t.ticker}
                    </Link>
                    {t.auto_avoid && (
                      <span className="ml-1 text-[9px] font-semibold text-red-500">AVOID</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-xs text-muted-foreground">{industry}</td>
                  <td className="px-2 py-1.5 text-[11px] font-mono text-muted-foreground">
                    {fmtKstDateTimeSec(t.last_signal_at)}
                  </td>
                  <td className={`px-2 py-1.5 text-right font-mono ${t.mentions_today > 0 ? "font-bold" : ""}`}>
                    {t.mentions_today}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">{t.mentions_7d}</td>
                  <td className="px-2 py-1.5 text-right font-mono">{t.mentions_28d}</td>
                  <td className="px-2 py-1.5 text-right font-mono font-bold">{t.mention_count_90d}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-emerald-500">{t.stance_90d.bull}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-red-500">{t.stance_90d.bear}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-400">{t.stance_90d.neu}</td>
                  <td className="px-2 py-1.5 text-right font-mono">{t.bullish_pct_90d.toFixed(0)}%</td>
                  <td className={`px-2 py-1.5 text-right font-mono ${_priorCls(t.vs_prior_close_pct)}`}>
                    {_fmtPct(t.vs_prior_close_pct, 2)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono font-bold ${_priorCls(t.gain_since_first_mention_pct)}`}
                    title="Gain since first mention"
                  >
                    {_fmtPct(t.gain_since_first_mention_pct, 1)}
                  </td>
                  <td className={`px-2 py-1.5 text-center font-bold ${stance.cls}`} title={t.overall_stance}>
                    {stance.icon}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
