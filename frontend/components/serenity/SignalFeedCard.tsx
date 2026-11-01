"use client";

// 개별 signal 카드 · Phase L6 · 2026-08-02

import Link from "next/link";
import { fmtKstDateTimeSec } from "@/lib/time";
import type { SignalFeedItem } from "@/lib/serenity/types";

const SENTIMENT_STYLE: Record<string, { chip: string; label: string }> = {
  bullish: { chip: "bg-up/15 text-up", label: "▲ Bullish" },
  bearish: { chip: "bg-down/15 text-down", label: "▼ Bearish" },
  neutral: { chip: "bg-slate-500/20 text-slate-400", label: "⚪ Neutral" },
  calibration: { chip: "bg-warn/20 text-warn", label: "🟡 Calibration" },
};

export function SignalFeedCard({ item }: { item: SignalFeedItem }) {
  const s = SENTIMENT_STYLE[item.sentiment] ?? SENTIMENT_STYLE.neutral;
  // 트윗 발행 시각 우선 · 없으면 z.ai 추출 시각 fallback (YYYY-MM-DD HH:MM:SS KST)
  const date = fmtKstDateTimeSec(item.tweet_posted_at ?? item.extracted_at);
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
        <span className={`rounded-lg px-1.5 py-0.5 text-xs font-semibold ${s.chip}`}>
          {s.label}
        </span>
        {item.thesis_type && (
          <span className="rounded-lg bg-primary/20 px-1.5 py-0.5 text-xs text-primary">
            {item.thesis_type}
          </span>
        )}
        {item.evidence_type && (
          <span className="rounded-lg bg-primary/20 px-1.5 py-0.5 text-xs text-primary">
            {item.evidence_type}
          </span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          conf {item.confidence.toFixed(2)}
        </span>
      </div>

      {item.extracted_reasoning && (
        <p className="mt-2 text-sm text-foreground">{item.extracted_reasoning}</p>
      )}

      {item.tweet_text && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          &ldquo;{item.tweet_text}&rdquo;
        </p>
      )}

      {item.tweet_url && (
        <a
          href={item.tweet_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-xs text-primary hover:underline"
        >
          원문 트윗 →
        </a>
      )}
    </article>
  );
}
