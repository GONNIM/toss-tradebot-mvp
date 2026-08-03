"use client";

// Serenity Ticker Card · 이미지 UX 스타일 (mentions today 중심 · rolling window · stance).
// Phase L6 · 2026-08-02 · Phase L9 (UX 고도화) · 2026-08-03

import Link from "next/link";
import type { TickerCardItem } from "@/lib/serenity/types";

const TIER_STYLE: Record<string, string> = {
  S: "bg-purple-500/20 text-purple-400 border-purple-500/40",
  A: "bg-blue-500/20 text-blue-400 border-blue-500/40",
  B: "bg-emerald-500/20 text-emerald-500 border-emerald-500/40",
  C: "bg-amber-500/20 text-amber-500 border-amber-500/40",
  D: "bg-orange-500/20 text-orange-500 border-orange-500/40",
  F: "bg-red-500/20 text-red-500 border-red-500/40",
};

const STANCE_META: Record<string, { label: string; icon: string; cls: string }> = {
  bullish: { label: "Bullish", icon: "▲", cls: "text-emerald-500" },
  bearish: { label: "Bearish", icon: "▼", cls: "text-red-500" },
  mixed: { label: "Mixed", icon: "◆", cls: "text-amber-500" },
  neutral: { label: "Neutral", icon: "●", cls: "text-slate-400" },
};

function _fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

function _fmtSignedPct(v: number | null): { txt: string; cls: string } {
  if (v === null || v === undefined) return { txt: "—", cls: "text-muted-foreground" };
  const sign = v >= 0 ? "+" : "";
  const cls = v >= 0 ? "text-emerald-500" : "text-red-500";
  return { txt: `${sign}${v.toFixed(1)}%`, cls };
}

export function TickerCard({ item }: { item: TickerCardItem }) {
  const stance = STANCE_META[item.overall_stance] ?? STANCE_META.neutral;
  const financing = item.financing_tier;
  const serenity = item.serenity_tier;
  const prior = _fmtSignedPct(item.vs_prior_close_pct);

  return (
    <Link
      href={`/influencer/serenity/${item.ticker}`}
      className={`block rounded-lg border p-3 transition hover:border-primary/60 ${
        item.auto_avoid ? "border-red-500/40 bg-red-500/5" : "border-border bg-card"
      }`}
    >
      {/* 헤더: 티커 + vs prior close + overall stance 배지 */}
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-lg font-bold">{item.ticker}</span>
          {financing && (
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                TIER_STYLE[financing] ?? "border-slate-500/40 bg-slate-500/20 text-slate-400"
              }`}
              title={`Financing tier ${financing}`}
            >
              F:{financing}
            </span>
          )}
          {serenity && (
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                TIER_STYLE[serenity] ?? "border-slate-500/40 bg-slate-500/20 text-slate-400"
              }`}
              title={`Serenity conviction tier ${serenity}`}
            >
              S:{serenity}
            </span>
          )}
          <span className={`text-xs ${prior.cls}`} title="전일 종가 대비 · vs prior close">
            vs prior {prior.txt}
          </span>
        </div>
        <span className={`text-sm font-bold ${stance.cls}`}>
          {stance.icon} {stance.label}
        </span>
      </div>

      {/* Mentions rolling window (오늘 큰 숫자 강조) */}
      <div className="mt-3 flex items-baseline justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Mentions today
          </div>
          <div className="text-4xl font-bold">{item.mentions_today}</div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>7d <strong className="text-foreground">{item.mentions_7d}</strong></div>
          <div>28d <strong className="text-foreground">{item.mentions_28d}</strong></div>
          <div>90d <strong className="text-foreground">{item.mention_count_90d}</strong></div>
        </div>
      </div>

      {/* Stance today · bull / bear / neu / cal */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
        <span className="text-muted-foreground">Stance · today</span>
        <span className="text-emerald-500">
          {item.stance_today.bull} <span className="text-muted-foreground">bull</span>
        </span>
        <span className="text-red-500">
          {item.stance_today.bear} <span className="text-muted-foreground">bear</span>
        </span>
        <span className="text-slate-400">
          {item.stance_today.neu} <span className="text-muted-foreground">neu</span>
        </span>
        {item.stance_today.cal > 0 && (
          <span className="text-amber-500">
            {item.stance_today.cal} <span className="text-muted-foreground">cal</span>
          </span>
        )}
      </div>

      {/* 90d bullish 비율 · overall 참조 */}
      <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
        <div className="h-1 flex-1 overflow-hidden rounded bg-muted">
          <div
            className="h-full bg-emerald-500/60"
            style={{ width: `${Math.min(100, Math.max(0, item.bullish_pct_90d))}%` }}
          />
        </div>
        <span>{item.bullish_pct_90d.toFixed(0)}% bullish (90d)</span>
      </div>

      {/* 태그 · anti-pattern */}
      {(item.domain_tags.length > 0 || item.anti_pattern_flags.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
          {item.domain_tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-slate-500/20 px-1.5 py-0.5 text-slate-300"
            >
              {tag}
            </span>
          ))}
          {item.anti_pattern_flags.map((flag) => (
            <span
              key={flag}
              className="rounded bg-red-500/20 px-1.5 py-0.5 text-red-400"
            >
              ⚠ {flag}
            </span>
          ))}
        </div>
      )}

      {/* Meta · first mention */}
      <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>First mention · {_fmtDate(item.first_mention_at)}</span>
        {item.auto_avoid && <span className="font-semibold text-red-500">AVOID</span>}
      </div>

      {item.latest_reasoning && (
        <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">
          {item.latest_reasoning}
        </p>
      )}
    </Link>
  );
}
