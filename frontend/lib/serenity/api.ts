// Serenity API 클라이언트 · Phase L6 · 2026-08-02
// 프록시: next.config.mjs rewrites · /api/v1/serenity/* → backend

import type {
  BacktestSummary,
  MethodologyResponse,
  SerenitySummary,
  SignalFeedItem,
  TickerCardItem,
  TickerDetailResponse,
} from "./types";

const BASE = "/api/v1/serenity";

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url} · ${r.status}`);
  return (await r.json()) as T;
}

export const serenityApi = {
  summary: () => json<SerenitySummary>(`${BASE}/summary`),

  signals: (opts?: {
    days?: number;
    sentiment?: string;
    ticker?: string;
    limit?: number;
  }) => {
    const p = new URLSearchParams();
    if (opts?.days) p.set("days", String(opts.days));
    if (opts?.sentiment) p.set("sentiment", opts.sentiment);
    if (opts?.ticker) p.set("ticker", opts.ticker);
    if (opts?.limit) p.set("limit", String(opts.limit));
    const qs = p.toString();
    return json<SignalFeedItem[]>(`${BASE}/signals${qs ? `?${qs}` : ""}`);
  },

  tickers: (opts?: {
    min_score?: number;
    include_avoid?: boolean;
    limit?: number;
  }) => {
    const p = new URLSearchParams();
    if (opts?.min_score !== undefined) p.set("min_score", String(opts.min_score));
    if (opts?.include_avoid !== undefined) p.set("include_avoid", String(opts.include_avoid));
    if (opts?.limit) p.set("limit", String(opts.limit));
    const qs = p.toString();
    return json<TickerCardItem[]>(`${BASE}/tickers${qs ? `?${qs}` : ""}`);
  },

  ticker: (ticker: string, recentLimit = 10) =>
    json<TickerDetailResponse>(
      `${BASE}/tickers/${encodeURIComponent(ticker.toUpperCase())}?recent_limit=${recentLimit}`,
    ),

  methodology: () => json<MethodologyResponse>(`${BASE}/methodology`),

  backtestSummary: (days = 180) =>
    json<BacktestSummary>(`${BASE}/backtest/summary?days=${days}`),
};
