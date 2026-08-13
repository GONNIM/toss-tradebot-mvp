"use client";

// Hunter 발굴 리스트 · v6 · default sort first_mention_at desc (Fable 5 4차)
// 게이트 open + not deprecated 시만 렌더 (부모에서 조건부)

import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtKstDateTimeSec } from "@/lib/time";
import type { HunterRow } from "@/lib/serenity-hunter/types";

type SortKey =
  | "first_mention_at"
  | "latest_signal_at"
  | "mentions_today"
  | "mentions_90d"
  | "bull_pct_90d"
  | "market_cap"
  | "avg_dollar_volume_20d"
  | "vs_prior_close_pct"
  | "gain_since_first_mention_pct";

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

function _cls(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-500" : "text-red-500";
}

function _fmtMcap(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`;
  return v.toFixed(0);
}

export function HunterTable({ rows }: { rows: HunterRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("first_mention_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [query, setQuery] = useState("");

  const sorted = useMemo(() => {
    const filtered = query
      ? rows.filter((r) =>
          [r.ticker, r.industry ?? "", r.sector ?? ""]
            .join(" ")
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
      : rows;
    const dir = sortDir === "desc" ? -1 : 1;
    const val = (r: HunterRow): number | string | null => {
      switch (sortKey) {
        case "first_mention_at":
          return r.first_mention_at ? new Date(r.first_mention_at).getTime() : null;
        case "latest_signal_at":
          return r.latest_signal_at ? new Date(r.latest_signal_at).getTime() : null;
        case "mentions_today":
          return r.mentions_today;
        case "mentions_90d":
          return r.mentions_90d;
        case "bull_pct_90d":
          return r.bull_pct_90d;
        case "market_cap":
          return r.market_cap;
        case "avg_dollar_volume_20d":
          return r.avg_dollar_volume_20d;
        case "vs_prior_close_pct":
          return r.vs_prior_close_pct;
        case "gain_since_first_mention_pct":
          return r.gain_since_first_mention_pct;
      }
    };
    const isMissing = (v: number | string | null) =>
      v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v));
    return [...filtered].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (isMissing(va) && isMissing(vb)) return 0;
      if (isMissing(va)) return 1;
      if (isMissing(vb)) return -1;
      if (typeof va === "string" && typeof vb === "string") {
        return va.localeCompare(vb) * dir;
      }
      return ((va as number) - (vb as number)) * dir;
    });
  }, [rows, sortKey, sortDir, query]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "desc" ? "asc" : "desc");
    else {
      setSortKey(k);
      setSortDir("desc");
    }
  }

  function SortHead({ k, label, align = "left" }: { k: SortKey; label: string; align?: "left" | "right" }) {
    const active = sortKey === k;
    const icon = active ? (sortDir === "desc" ? "▼" : "▲") : "⇅";
    const iconCls = active ? "text-primary" : "text-muted-foreground/50";
    return (
      <th
        onClick={() => toggleSort(k)}
        className={`cursor-pointer select-none px-2 py-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground text-${align}`}
      >
        {label} <span className={`text-[9px] ${iconCls}`}>{icon}</span>
      </th>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">🎯 발굴 리스트 (Hunter)</h2>
          <p className="text-[10px] text-muted-foreground">
            {rows.length} 종목 · 기본 정렬 · 최초 언급 최신순 · 헤더 클릭 시 정렬 반전
          </p>
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="티커·산업·섹터 검색"
          className="rounded border border-border bg-background px-2 py-1 text-xs w-56"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr>
              <th className="px-2 py-2.5 text-left text-xs font-semibold text-muted-foreground">Ticker</th>
              <th className="px-2 py-2.5 text-left text-xs font-semibold text-muted-foreground">Industry</th>
              <SortHead k="first_mention_at" label="First mention" />
              <SortHead k="latest_signal_at" label="Latest" />
              <SortHead k="mentions_today" label="Today" align="right" />
              <SortHead k="mentions_90d" label="90d" align="right" />
              <th className="px-2 py-2.5 text-left text-xs font-semibold text-muted-foreground">Thesis</th>
              <SortHead k="bull_pct_90d" label="Bull%" align="right" />
              <SortHead k="market_cap" label="Market cap" align="right" />
              <SortHead k="avg_dollar_volume_20d" label="ADV 20d" align="right" />
              <SortHead k="vs_prior_close_pct" label="vs Prior" align="right" />
              <SortHead k="gain_since_first_mention_pct" label="Gain" align="right" />
              <th className="px-2 py-2.5 text-center text-xs font-semibold text-muted-foreground">Stance</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const stance = STANCE_META[r.stance] ?? STANCE_META.neutral;
              const liquidityGray = !r.passes_liquidity;
              return (
                <tr
                  key={r.ticker}
                  className={`border-b border-border/40 hover:bg-muted/20 ${
                    r.is_avoid_new ? "bg-red-500/5" : ""
                  } ${liquidityGray ? "opacity-60" : ""}`}
                  title={liquidityGray ? "유동성 필터 미통과 (ADV<$2M or 주문>0.5%)" : ""}
                >
                  <td className="px-2 py-3 font-mono font-bold">
                    <Link href={`/influencer/serenity/${r.ticker}`} className="text-primary hover:underline">
                      {r.ticker}
                    </Link>
                    {r.is_avoid_new && (
                      <span className="ml-1 text-[9px] font-semibold text-red-500" title="인플루언서 경고 신규">
                        ⚠경고신규
                      </span>
                    )}
                    {!r.is_avoid_new && r.is_new && (
                      <span className="ml-1 text-[9px] font-semibold text-emerald-500">NEW</span>
                    )}
                  </td>
                  <td className="px-2 py-3 text-xs text-muted-foreground">
                    {r.industry ?? r.sector ?? "—"}
                  </td>
                  <td className="px-2 py-3 text-[11px] font-mono text-muted-foreground">
                    {fmtKstDateTimeSec(r.first_mention_at)}
                  </td>
                  <td className="px-2 py-3 text-[11px] font-mono text-muted-foreground">
                    {fmtKstDateTimeSec(r.latest_signal_at)}
                  </td>
                  <td className={`px-2 py-3 text-right font-mono font-bold ${r.mentions_today > 0 ? "text-primary" : ""}`}>
                    {r.mentions_today}
                  </td>
                  <td className="px-2 py-3 text-right font-mono font-bold">{r.mentions_90d}</td>
                  <td className="px-2 py-3 text-[11px] text-muted-foreground">
                    {r.latest_thesis ?? "—"}
                  </td>
                  <td className="px-2 py-3 text-right font-mono font-bold">
                    {r.bull_pct_90d.toFixed(0)}%
                  </td>
                  <td className="px-2 py-3 text-right font-mono">
                    {_fmtMcap(r.market_cap)}
                    <div className="text-[9px] text-muted-foreground">{r.market_cap_tier}</div>
                  </td>
                  <td className="px-2 py-3 text-right font-mono">
                    {r.avg_dollar_volume_20d === null ? "—" : `$${_fmtMcap(r.avg_dollar_volume_20d)}`}
                    <div className="text-[9px] text-muted-foreground">
                      order {r.order_pct_of_adv_1M === null ? "—" : `${r.order_pct_of_adv_1M.toFixed(3)}%`}
                    </div>
                  </td>
                  <td className={`px-2 py-3 text-right font-mono font-bold ${_cls(r.vs_prior_close_pct)}`}>
                    {_fmtPct(r.vs_prior_close_pct, 2)}
                  </td>
                  <td className={`px-2 py-3 text-right font-mono font-bold ${_cls(r.gain_since_first_mention_pct)}`}>
                    {_fmtPct(r.gain_since_first_mention_pct, 1)}
                  </td>
                  <td className={`px-2 py-3 text-center font-bold ${stance.cls}`}>{stance.icon}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
