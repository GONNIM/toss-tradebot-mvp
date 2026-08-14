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

export type StanceBreakdown = {
  bull: number;
  bear: number;
  neu: number;
  cal: number;
};

export type OverallStance = "bullish" | "bearish" | "mixed" | "neutral";

export type TickerCardItem = {
  ticker: string;
  financing_tier: Tier | null;
  serenity_tier: Tier | null;
  total_score: number;
  auto_avoid: boolean;
  domain_tags: string[];
  anti_pattern_flags: string[];

  // Rolling window mentions
  mentions_today: number;
  mentions_7d: number;
  mentions_28d: number;
  mention_count_90d: number;
  bullish_pct_90d: number;

  // Stance
  stance_today: StanceBreakdown;
  stance_90d: StanceBreakdown;
  overall_stance: OverallStance;
  thesis_types: string[];

  // Meta
  first_mention_at: string | null;
  last_signal_at: string | null;
  latest_stance: string | null;  // 최신 1건 방향 (bullish/bearish/neutral/calibration · Fable 5)
  latest_reasoning: string | null;

  // Phase 2 · yfinance vs prior close
  vs_prior_close_pct: number | null;
  // Phase L10 · gain since first mention
  gain_since_first_mention_pct: number | null;
  // Phase L13 · yfinance sector/industry
  sector: string | null;
  industry: string | null;
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

export type MethodologyResponse = {
  source: string;
  text: string;
  bytes: number;
};

export type BacktestBucket = {
  key: string;
  count: number;
  avg_return_5d: number | null;
  avg_return_10d: number | null;
  avg_return_30d: number | null;
  avg_return_60d: number | null;
  avg_return_180d: number | null;
};

export type BacktestSummary = {
  total_backtests: number;
  overall: BacktestBucket;
  by_sentiment: BacktestBucket[];
  by_financing_tier: BacktestBucket[];
  top_tickers_60d: BacktestBucket[];
};
