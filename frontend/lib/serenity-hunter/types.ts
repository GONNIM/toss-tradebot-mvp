// Serenity Hunter API 타입 · Phase L14 v6 · 2026-08-04
// Backend contract: backend/api/routes/serenity_hunter.py

export type PredictiveStatus = "insufficient_n" | "fail" | "pass";

export type HealthReason = {
  code: string;
  message: string;
  since: string | null;
};

export type HealthResponse = {
  warn: boolean;
  reasons: HealthReason[];
  last_crawl_at: string | null;
  last_signal_at: string | null;
  last_backtest_at: string | null;
  last_price_snapshot_at: string | null;
  benchmark_fresh: boolean;
};

export type WindowMap = Record<string, number | null>;

export type ConfidencePredictiveCheck = {
  top_hit_rate: number | null;
  bottom_hit_rate: number | null;
  diff_pp: number | null;
  top_n: number;
  bottom_n: number;
  min_n_ok: boolean;
  predictive_status: PredictiveStatus;
};

export type VerificationHero = {
  total_events: number;
  valid_events: number;
  benchmark_rows_iwm: number;
  benchmark_rows_spy: number;
  hit_rate_10pct_1d: number | null;
  hit_rate_10pct_3d: number | null;
  hit_rate_10pct_1d_delisting_as_minus100: number | null;
  hit_rate_10pct_3d_delisting_as_minus100: number | null;
  avg_raw_return_1d: number | null;
  avg_raw_return_3d: number | null;
  avg_return_by_window: WindowMap;
  avg_gap_next_open_pct: number | null;
  avg_slippage_adjusted_return_1d: number | null;
  avg_slippage_adjusted_return_3d: number | null;
  avg_cost_adjusted_return_1d: number | null;
  avg_cost_adjusted_return_3d: number | null;
  benchmark_iwm_avg: WindowMap;
  benchmark_spy_avg: WindowMap;
  excess_return_primary_raw: WindowMap;
  excess_return_primary_adjusted: WindowMap;
  excess_return_reference_raw: WindowMap;
  excess_return_reference_adjusted: WindowMap;
  gate_open: boolean;
  gate_events_needed: number;
  gate_events_have: number;
  gate_close_reasons: string[];
  deprecation_triggered: boolean;
  mid_gate_excess_warning: boolean;
  warning_text: string | null;
};

export type BucketRow = {
  key: string;
  n: number;
  hit_rate_10pct_3d: number | null;
  avg_return_3d: number | null;
  excess_iwm_3d: number | null;
  is_masked: boolean;
};

export type BucketGroup = {
  name: string;
  rows: BucketRow[];
};

export type VerificationResponse = {
  hero: VerificationHero;
  buckets: BucketGroup[];
  confidence_predictive_check: ConfidencePredictiveCheck;
};

export type HunterRow = {
  ticker: string;
  industry: string | null;
  sector: string | null;
  first_mention_at: string | null;
  latest_signal_at: string | null;
  mentions_today: number;
  mentions_7d: number;
  mentions_28d: number;
  mentions_90d: number;
  // avg_confidence_recent 삭제 (v6 L14+ · predictive_status=fail 확정 · 2026-08-04)
  latest_thesis: string | null;
  bull_pct_90d: number;
  market_cap: number | null;
  market_cap_tier: string;
  avg_dollar_volume_20d: number | null;
  order_pct_of_adv_1M: number | null;
  passes_liquidity: boolean;
  vs_prior_close_pct: number | null;
  gain_since_first_mention_pct: number | null;
  stance: string;
  is_new: boolean;
  is_avoid_new: boolean;
};

export type HunterResponse = {
  gate_open: boolean;
  deprecation_triggered: boolean;
  mid_gate_warning: boolean;
  gate_close_reasons: string[];
  deprecation_recommended: boolean;
  rows: HunterRow[];
};

// ─── Action Cards (L14+ · 지시서 2026-08-05) ───────────────────

export type ActionCard = {
  ticker: string;
  tier: string | null;
  tier_rank: number;
  financing_tier: string | null;
  bull_pct: number;
  mentions_7d: number;
  mentions_90d: number;
  industry: string | null;
  sector: string | null;
  sector_overlap: boolean;
  last_close: number;
  vs_prior_pct: number | null;
  price_verification_failed: boolean;
  market_cap_sanity_warning: boolean;
  first_mention_at: string | null;
  entry_limit: number;
  entry_krw: number;
  qty: number;
  sl_price: number;
  sl_days: number;
  tp_trigger_price: number;
  trail_pct: number;
  min_rr: number;
  min_rr_warning: boolean;
};

export type WatchOnlyItem = {
  ticker: string;
  industry: string | null;
  bull_pct: number;
  mentions_7d: number;
  mentions_90d: number;
  reason: string;
};

export type ExcludedItem = {
  ticker: string;
  reason: string;
};

export type ActionCardFilters = {
  bull_pct_min: number;
  mentions_90d_min: number;
  mentions_7d_min: number;
  shell_industries: string[];
};

export type ActionRiskParams = {
  slippage_limit_pct: number;
  sl_pct: number;
  sl_days: number;
  tp_trigger_pct: number;
  trail_pct: number;
  position_krw: number;
  min_rr_warning: number;
};

export type ActionCardsResponse = {
  as_of: string;
  fx_rate: number;
  fx_source: string;
  cards: ActionCard[];
  cards_hidden: ActionCard[];
  rest_count: number;
  watch_only: WatchOnlyItem[];
  excluded: ExcludedItem[];
  filters: ActionCardFilters;
  risk: ActionRiskParams;
};
