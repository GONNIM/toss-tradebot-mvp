// Serenity Influencer API 타입 · Phase L6 · 2026-08-02
// Backend contract: backend/api/routes/serenity.py

export type Sentiment = "bullish" | "bearish" | "neutral" | "calibration";

export type Tier = "S" | "A" | "B" | "C" | "D" | "F";

export type SignalFeedItem = {
  id: string;
  tweet_id: number;
  ticker: string;
  sentiment: Sentiment;
  thesis_type: string | null;
  evidence_type: string | null;
  confidence: number;
  extracted_reasoning: string | null;
  extracted_at: string; // ISO
  tweet_text: string | null;
  tweet_url: string | null;
  tweet_posted_at: string | null;
};

export type TickerCardItem = {
  ticker: string;
  financing_tier: Tier | null;
  serenity_tier: Tier | null;
  total_score: number;
  auto_avoid: boolean;
  domain_tags: string[];
  anti_pattern_flags: string[];
  mention_count_90d: number;
  bullish_pct_90d: number;
  last_signal_at: string | null;
  latest_reasoning: string | null;
};

export type SerenitySummary = {
  tweets: number;
  signals: number;
  tickers_scored: number;
  tickers_auto_avoid: number;
  last_signal_at: string | null;
  last_tweet_at: string | null;
};

export type TickerDetailResponse = {
  ticker: string;
  score: TickerCardItem;
  recent_signals: SignalFeedItem[];
  backtest_avg: {
    return_5d: number | null;
    return_10d: number | null;
    return_30d: number | null;
    return_60d: number | null;
    return_180d: number | null;
  };
};
