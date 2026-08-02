"use client";

// 개별 signal 카드 · Phase L6 · 2026-08-02

import Link from "next/link";
import type { SignalFeedItem } from "@/lib/serenity/types";

const SENTIMENT_STYLE: Record<string, { chip: string; label: string }> = {
  bullish: { chip: "bg-emerald-500/20 text-emerald-500", label: "🟢 Bullish" },
  bearish: { chip: "bg-red-500/20 text-red-500", label: "🔴 Bearish" },
  neutral: { chip: "bg-slate-500/20 text-slate-400", label: "⚪ Neutral" },
  calibration: { chip: "bg-amber-500/20 text-amber-500", label: "🟡 Calibration" },
};

export function SignalFeedCard({ item }: { item: SignalFeedItem }) {
  const s = SENTIMENT_STYLE[item.sentiment] ?? SENTIMENT_STYLE.neutral;
  const date = new Date(item.extracted_at).toLocaleDateString("ko-KR");
  return (
    <article className="rounded-lg border border-border bg-card p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">{date}</span>
        <Link
          href={`/influencer/serenity/${item.ticker}`}
          className="font-mono font-bold text-foreground hover:underline"
        >
          ${item.ticker}
        </Link>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${s.chip}`}>
          {s.label}
        </span>
        {item.thesis_type && (
          <span className="rounded bg-indigo-500/20 px-1.5 py-0.5 text-[10px] text-indigo-400">
            {item.thesis_type}
          </span>
        )}
        {item.evidence_type && (
          <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] text-purple-400">
            {item.evidence_type}
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground">
          conf {item.confidence.toFixed(2)}
        </span>
      </div>

      {item.extracted_reasoning && (
        <p className="mt-2 text-sm text-foreground">{item.extracted_reasoning}</p>
      )}

      {item.tweet_text && (
        <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">
          &ldquo;{item.tweet_text}&rdquo;
        </p>
      )}

      {item.tweet_url && (
        <a
          href={item.tweet_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-[10px] text-sky-500 hover:underline"
        >
          원문 트윗 →
        </a>
      )}
    </article>
  );
}
