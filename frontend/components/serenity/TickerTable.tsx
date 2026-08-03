"use client";

// 90일 언급 종목 리스트 · 테이블 · Phase L9~L11 UX · 2026-08-03
// 사용자 요구:
//   L9  · Ticker · Industry · Latest mention · Mentions · Bullish/Bearish/Neutral
//   L10 · Gain since first mention 컬럼
//   L11 · Mentions 상단 정렬 컨트롤 (기간 today/7d/28d/90d + asc/desc) · 행 높이 50% 증가

import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtKstDateTimeSec } from "@/lib/time";
import type { TickerCardItem } from "@/lib/serenity/types";

type SortKey =
  | "mentions_today"
  | "mentions_7d"
  | "mentions_28d"
  | "mentions_90d"
  | "last_signal_at"
  | "first_mention_at"
  | "bullish_pct_90d"
  | "vs_prior_close_pct"
  | "gain_since_first_mention_pct"
  | "ticker";

type SortDir = "desc" | "asc";

type MentionsPeriod = "today" | "7d" | "28d" | "90d";

const MENTIONS_PERIOD_KEY: Record<MentionsPeriod, SortKey> = {
  today: "mentions_today",
  "7d": "mentions_7d",
  "28d": "mentions_28d",
  "90d": "mentions_90d",
};

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

function _mentionsForKey(t: TickerCardItem, k: SortKey): number {
  switch (k) {
    case "mentions_today":
      return t.mentions_today;
    case "mentions_7d":
      return t.mentions_7d;
    case "mentions_28d":
      return t.mentions_28d;
    case "mentions_90d":
      return t.mention_count_90d;
    default:
      return 0;
  }
}

export function TickerTable({ items }: { items: TickerCardItem[] }) {
  // 기본 정렬: Mentions 총 카운트 (90d) · desc (사용자 지시 L12 · 총 카운트 = 셀 맨 앞 큰 숫자)
  const [mentionsPeriod, setMentionsPeriod] = useState<MentionsPeriod>("90d");
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
    const val = (t: TickerCardItem): number | string | null => {
      switch (sortKey) {
        case "ticker":
          return t.ticker;
        case "last_signal_at":
          return t.last_signal_at ? new Date(t.last_signal_at).getTime() : null;
        case "first_mention_at":
          return t.first_mention_at ? new Date(t.first_mention_at).getTime() : null;
        case "vs_prior_close_pct":
          return t.vs_prior_close_pct ?? null;
        case "gain_since_first_mention_pct":
          return t.gain_since_first_mention_pct ?? null;
        case "mentions_today":
        case "mentions_7d":
        case "mentions_28d":
        case "mentions_90d":
          return _mentionsForKey(t, sortKey);
        default:
          return (t as unknown as Record<string, number>)[sortKey] ?? 0;
      }
    };
    // null · undefined · NaN · Infinity 는 방향과 무관하게 항상 뒤로 (데이터 없음 UX)
    const isMissing = (v: number | string | null) =>
      v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v));
    return [...filtered].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      const am = isMissing(va);
      const bm = isMissing(vb);
      if (am && bm) return 0;
      if (am) return 1;
      if (bm) return -1;
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

  function onMentionsPeriodChange(p: MentionsPeriod) {
    setMentionsPeriod(p);
    setSortKey(MENTIONS_PERIOD_KEY[p]);
  }

  function SortHead({ k, label, align = "left" }: { k: SortKey; label: string; align?: "left" | "right" }) {
    const active = sortKey === k;
    // 정렬 가능 상시 표시 · active=▼/▲ · inactive=⇅ (희미) · 사용자 클릭 유도
    const icon = active ? (sortDir === "desc" ? "▼" : "▲") : "⇅";
    const iconCls = active ? "text-primary" : "text-muted-foreground/50";
    return (
      <th
        onClick={() => toggleSort(k)}
        className={`cursor-pointer select-none px-2 py-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground text-${align}`}
        title={`정렬 · 현재 ${active ? (sortDir === "desc" ? "내림차순" : "오름차순") : "비활성"} · 클릭 시 ${active ? "방향 반전" : "이 컬럼 기준 정렬"}`}
      >
        {label} <span className={`text-[9px] ${iconCls}`}>{icon}</span>
      </th>
    );
  }

  const mentionsActive = MENTIONS_PERIOD_KEY[mentionsPeriod] === sortKey;

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">📋 90일 언급 종목 리스트 (테이블)</h2>
          <p className="text-[10px] text-muted-foreground">
            {items.length} 종목 · 상단 컨트롤로 Mentions 기간/방향 선택 · 각 컬럼 헤더 클릭으로도 정렬
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Mentions 정렬 컨트롤 (사용자 요구 · L11) */}
          <div className="flex items-center gap-1 rounded border border-border bg-background px-2 py-1">
            <span className="text-[10px] text-muted-foreground">Mentions</span>
            <select
              value={mentionsPeriod}
              onChange={(e) => onMentionsPeriodChange(e.target.value as MentionsPeriod)}
              className="bg-transparent text-xs font-semibold outline-none"
              title="Mentions 정렬 기간 · 셀 맨 앞 큰 숫자도 이 기간으로 표시"
            >
              <option value="90d">90d (총)</option>
              <option value="28d">28d</option>
              <option value="7d">7d</option>
              <option value="today">today</option>
            </select>
            <button
              type="button"
              onClick={() => {
                if (!mentionsActive) setSortKey(MENTIONS_PERIOD_KEY[mentionsPeriod]);
                setSortDir(sortDir === "desc" ? "asc" : "desc");
              }}
              className="rounded border border-border px-1.5 text-[10px] font-semibold hover:bg-muted/40"
              title={`현재 ${mentionsActive ? (sortDir === "desc" ? "내림차순" : "오름차순") : "다른 컬럼 정렬 중"} · 클릭 시 반전`}
            >
              {mentionsActive ? (sortDir === "desc" ? "▼ desc" : "▲ asc") : "▼ desc"}
            </button>
          </div>

          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="티커·도메인 검색"
            className="rounded border border-border bg-background px-2 py-1 text-xs w-44"
          />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-muted/30">
            <tr>
              <SortHead k="ticker" label="Ticker" />
              <th className="px-2 py-2.5 text-left text-xs font-semibold text-muted-foreground">Industry</th>
              <SortHead k="first_mention_at" label="First mention" />
              <SortHead k="last_signal_at" label="Latest mention" />
              <th
                onClick={() => toggleSort(MENTIONS_PERIOD_KEY[mentionsPeriod])}
                className="cursor-pointer select-none px-2 py-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground text-right"
                title="맨 앞 큰 숫자 = 상단 컨트롤에서 선택한 기간의 총 카운트 · 괄호 = 나머지 기간"
              >
                Mentions{" "}
                <span
                  className={`text-[9px] ${mentionsActive ? "text-primary" : "text-muted-foreground/50"}`}
                >
                  {mentionsActive ? (sortDir === "desc" ? "▼" : "▲") : "⇅"}
                </span>
                <div className="text-[9px] font-normal opacity-70">{mentionsPeriod} (나머지 기간)</div>
              </th>
              <th className="px-2 py-2.5 text-right text-xs font-semibold text-emerald-500">Bull</th>
              <th className="px-2 py-2.5 text-right text-xs font-semibold text-red-500">Bear</th>
              <th className="px-2 py-2.5 text-right text-xs font-semibold text-slate-400">Neutral</th>
              <SortHead k="bullish_pct_90d" label="Bull%" align="right" />
              <SortHead k="vs_prior_close_pct" label="vs Prior" align="right" />
              <SortHead k="gain_since_first_mention_pct" label="Gain" align="right" />
              <th className="px-2 py-2.5 text-center text-xs font-semibold text-muted-foreground">Stance</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const stance = STANCE_META[t.overall_stance] ?? STANCE_META.neutral;
              // Industry · yfinance industry 우선 · fallback yfinance sector · fallback domain_tags · "—"
              const industry =
                t.industry ||
                t.sector ||
                (t.domain_tags.length > 0 ? t.domain_tags.join(", ") : "—");
              return (
                <tr
                  key={t.ticker}
                  className={`border-b border-border/40 hover:bg-muted/20 ${
                    t.auto_avoid ? "bg-red-500/5" : ""
                  }`}
                >
                  <td className="px-2 py-3 font-mono font-bold">
                    <Link href={`/influencer/serenity/${t.ticker}`} className="text-primary hover:underline">
                      {t.ticker}
                    </Link>
                    {t.auto_avoid && (
                      <span className="ml-1 text-[9px] font-semibold text-red-500">AVOID</span>
                    )}
                  </td>
                  <td className="px-2 py-3 text-xs text-muted-foreground">{industry}</td>
                  <td className="px-2 py-3 text-[11px] font-mono text-muted-foreground">
                    {fmtKstDateTimeSec(t.first_mention_at)}
                  </td>
                  <td className="px-2 py-3 text-[11px] font-mono text-muted-foreground">
                    {fmtKstDateTimeSec(t.last_signal_at)}
                  </td>
                  <td
                    className="px-2 py-3 text-right font-mono"
                    title={`today ${t.mentions_today} · 7d ${t.mentions_7d} · 28d ${t.mentions_28d} · 90d ${t.mention_count_90d}`}
                  >
                    <span className="font-bold text-primary text-sm">
                      {_mentionsForKey(t, MENTIONS_PERIOD_KEY[mentionsPeriod])}
                    </span>
                    <span className="text-[9px] text-muted-foreground ml-1">
                      ({[
                        mentionsPeriod !== "today" ? `t:${t.mentions_today}` : null,
                        mentionsPeriod !== "7d" ? `7d:${t.mentions_7d}` : null,
                        mentionsPeriod !== "28d" ? `28d:${t.mentions_28d}` : null,
                        mentionsPeriod !== "90d" ? `90d:${t.mention_count_90d}` : null,
                      ].filter(Boolean).join(" · ")})
                    </span>
                  </td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-emerald-500">{t.stance_90d.bull}</td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-red-500">{t.stance_90d.bear}</td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-slate-400">{t.stance_90d.neu}</td>
                  <td className="px-2 py-3 text-right font-mono font-bold">{t.bullish_pct_90d.toFixed(0)}%</td>
                  <td className={`px-2 py-3 text-right font-mono font-bold ${_priorCls(t.vs_prior_close_pct)}`}>
                    {_fmtPct(t.vs_prior_close_pct, 2)}
                  </td>
                  <td
                    className={`px-2 py-3 text-right font-mono font-bold ${_priorCls(t.gain_since_first_mention_pct)}`}
                    title="Gain since first mention"
                  >
                    {_fmtPct(t.gain_since_first_mention_pct, 1)}
                  </td>
                  <td className={`px-2 py-3 text-center font-bold ${stance.cls}`} title={t.overall_stance}>
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
