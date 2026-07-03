/**
 * API 클라이언트 (FastAPI 백엔드).
 * next.config.ts rewrites 로 /api/v1/* → http://localhost:8000/api/v1/* 프록시.
 */

const BASE = "/api/v1";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json();
}

// ─────────────────────────────────────────────
// 타입
// ─────────────────────────────────────────────

export type RiskLevel = "HIGH" | "MED" | "LOW";

export interface CrazyPick {
  id: number;
  pick_date: string;
  rank: number;
  ticker: string;
  company_name: string | null;
  sector: string | null;
  close_price: number | null;
  market_cap: number | null;          // USD (millions 단위 아님 — 일관성 위해 USD)
  composite_score: number | null;
  thesis: string | null;
  catalysts: string | null;            // JSON string
  risks: string | null;
  news_summary: string | null;
  created_at: string;
}

export interface MoonshotPick {
  id: number;
  pick_date: string;
  rank: number;
  ticker: string;
  company_name: string | null;
  sector: string | null;
  market_cap: number | null;
  current_price: number | null;
  risk_level: RiskLevel | null;
  market_cap_category: string | null;
  manipulation_risk: number | null;
  composite_score: number | null;
  // 9 인자 점수
  score_volatility: number | null;
  score_catalyst: number | null;
  score_squeeze: number | null;
  score_social: number | null;
  score_news: number | null;
  score_technical: number | null;
  score_gap_volume: number | null;
  score_low_rebound: number | null;
  score_insider: number | null;
  // 매수 3 가격대 (Decision 33)
  buy_price_a: number | null;          // 시장가
  buy_price_b: number | null;          // -5% drop
  buy_price_c: number | null;          // +8% breakout
  // 매도 정책 (Decision 34)
  target_sell_multiplier: number | null;
  stop_loss_multiplier: number | null;
  time_stop_days: number | null;
  // LLM 콘텐츠
  thesis: string | null;
  catalysts: string | null;
  risks: string | null;
  news_summary: string | null;
  high_52w: number | null;
  low_52w: number | null;
  created_at: string;
}

export interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number | null;
  unrealized_pnl_pct: number | null;
  risk_level: RiskLevel;
}

export interface DashboardSummary {
  total_value_usd: number;
  total_cost_usd: number;
  realized_pnl_usd: number;
  unrealized_pnl_usd: number;
  open_positions: number;
  last_trade_at: string | null;
  engine_status: string;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  module: string;
  message: string;
  context: string | null;
}

export interface Setting {
  key: string;
  value: string;
  description: string | null;
}

// ─── Sector Leaders (B-2e) ────────────────────────────────────

export type Confidence = "strong" | "medium" | "weak";

export interface SectorLeader {
  item: string;
  ticker: string;
  name: string;
  rank: number;
  score: number;
  market_cap_krw: number | null;
  export_ratio_hint: number | null;
  pearson_r0: number | null;
  best_r: number | null;
  best_lag_months: number | null;
  sample_n: number | null;
  confidence: Confidence;
  computed_at: string;
}

export interface ExportSeriesPoint {
  month: string;
  value_musd: number;
  yoy_pct: number | null;
}

export interface PriceSeriesPoint {
  date: string;
  close: number;
  return_pct: number | null;
}

export interface SectorItemSummary {
  item: string;
  latest_value_musd: number | null;
  latest_yoy_pct: number | null;
  top_confidence: Confidence;
  leader_count: number;
}

export interface SectorItemDetail {
  item: string;
  description: string | null;
  export_series: ExportSeriesPoint[];
  leaders: SectorLeader[];
}

export interface TickerDetail {
  leader: SectorLeader;
  price_series: PriceSeriesPoint[];
  export_series: ExportSeriesPoint[];
}

// ─── Sector Leader Analysis Panel (B-2f) ─────────────────────

export interface BacktestBucket {
  label: string;
  threshold_low: number | null;
  threshold_high: number | null;
  n_months: number;
  mean_return_pct: number;
  cumulative_return_pct: number;
}

export type JoinSignal =
  | "agree_up"
  | "agree_down"
  | "disagree"
  | "neutral"
  | "no_data";

export interface MonthlyJoinRow {
  month: string;
  export_value_musd: number | null;
  export_yoy_pct: number | null;
  price_close: number | null;
  return_pct: number | null;
  signal: JoinSignal;
}

export interface LatestSignalHint {
  month: string;
  export_yoy_pct: number | null;
  bucket_label: string;
  expected_window: string;
  regime: string;
  direction: "up" | "down";
  based_on_lag: number;
}

export interface TickerAnalysis {
  leader: SectorLeader;
  correlation_sign: number;       // +1 / -1
  export_series: ExportSeriesPoint[];
  monthly_close: PriceSeriesPoint[];
  backtest_lag0: BacktestBucket[];
  backtest_best_lag: BacktestBucket[];
  monthly_join: MonthlyJoinRow[];
  latest_signal: LatestSignalHint | null;
}

// ─── Forecast (B-2g) ──────────────────────────────────────────

export interface HorizonForecast {
  horizon_months: number;
  n_samples: number;
  alpha: number;
  beta: number;
  r_squared: number;
  p_value_approx: number;
  rmse: number;
  hit_rate: number;
  latest_input_yoy: number;
  point_estimate_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
  sample_warning: boolean;
}

export interface FanChartPoint {
  month_offset: number;
  target_month: string;
  point_estimate_pct: number;
  sigma_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
}

export interface OOSMetrics {
  train_n: number;
  test_n: number;
  mae: number;
  rmse: number;
  hit_rate: number;
  directional_accuracy: number | null;
}

export interface HistoricalBand {
  horizon_months: number;
  n_windows: number;
  p10_pct: number;
  p50_pct: number;
  p90_pct: number;
}

export interface Verdict {
  color: "green" | "amber" | "red";
  label: string;
  context: string;
  action_hint: string;
}

export interface RiskReward {
  ratio: number;
  grade: "excellent" | "good" | "weak" | "too_high";
  grade_label: string;
  upside_pct: number;
  downside_pct: number;
}

export interface StopTakeProfit {
  stop_price: number;
  stop_pct: number;
  stop_basis: string;
  take_price: number;
  take_pct: number;
  take_basis: string;
}

export interface HorizonAdvice {
  horizon_months: number;
  verdict: Verdict;
  risk_reward: RiskReward | null;
  stop_take: StopTakeProfit | null;
}

// ─── Confluence (B-2i-a) ──────────────────────────────────────

export interface SignalContribution {
  name: string;
  label: string;
  raw_value: number | null;
  raw_label: string;
  normalized: number;
  weight: number;
  contribution: number;
  detail: string;
  direction: "bullish" | "bearish" | "neutral";
}

export interface Confluence {
  score: number;          // -1 ~ +1
  score_pct: number;      // 0 ~ 100
  direction: "bullish" | "bearish" | "neutral";
  agreement_count: number;
  disagreement_count: number;
  total_signals: number;
  contributions: SignalContribution[];
  grade: string;
  grade_label: string;
  grade_color: "green" | "amber" | "red";
  interpretation: string;
}

export interface TickerConfluence {
  leader: SectorLeader;
  correlation_sign: number;
  latest_data_month: string;
  confluence: Confluence;
}

// ─── Top 10 (B-2j) ────────────────────────────────────────────

export interface Top10Item {
  rank: number;
  ticker: string;
  name: string;
  item: string;
  market_cap_krw: number | null;

  current_price: number;
  entry_price: number;
  entry_status: string;
  entry_gap_pct: number;

  point_price: number;
  point_pct: number;
  stop_price: number | null;
  stop_pct: number | null;
  take_price: number | null;
  take_pct: number | null;

  confluence_score: number;
  confidence_stars: string;
  confidence_label: string;
  attractiveness: number;

  horizon_months: number;
  best_r: number | null;
  sample_warning: boolean;

  price_source: "live" | "fallback";
  price_at: string | null;
  price_market_status: string | null;
}

export interface Top10Response {
  items: Top10Item[];
  total_candidates: number;
  computed_at: string;
}

export interface ForecastDisclaimer {
  method: string;
  ci_method: string;
  sample_window: string;
  limitations: string[];
}

export interface TickerForecast {
  leader: SectorLeader;
  correlation_sign: number;
  latest_data_month: string;
  latest_input_yoy: number;
  latest_close_krw: number | null;
  latest_close_date: string | null;
  horizons: HorizonForecast[];
  fan_chart: FanChartPoint[];
  historical_bands: HistoricalBand[];
  advice_by_horizon: HorizonAdvice[];
  oos_metrics: OOSMetrics | null;
  disclaimer: ForecastDisclaimer;

  price_source: "live" | "fallback";
  price_at: string | null;
  price_market_status: string | null;
}

// ─────────────────────────────────────────────
// 메소드
// ─────────────────────────────────────────────

export const api = {
  crazy: {
    list: (limit = 10) => get<CrazyPick[]>(`/crazy?limit=${limit}`),
    byTicker: (ticker: string) => get<CrazyPick>(`/crazy/${ticker}`),
    history: (days = 7) => get<CrazyPick[]>(`/crazy/history?days=${days}`),
  },
  moonshot: {
    list: (limit = 3, risk?: RiskLevel) => {
      const q = new URLSearchParams({ limit: String(limit) });
      if (risk) q.set("risk_level", risk);
      return get<MoonshotPick[]>(`/moonshot?${q.toString()}`);
    },
    byTicker: (ticker: string) => get<MoonshotPick>(`/moonshot/${ticker}`),
    history: (days = 7) => get<MoonshotPick[]>(`/moonshot/history?days=${days}`),
  },
  positions: {
    list: () => get<Position[]>(`/positions`),
  },
  dashboard: {
    summary: () => get<DashboardSummary>(`/dashboard`),
  },
  settings: {
    list: () => get<Setting[]>(`/settings`),
  },
  logs: {
    list: (limit = 50, hours = 24, module?: string) => {
      const q = new URLSearchParams({
        limit: String(limit),
        hours: String(hours),
      });
      if (module) q.set("module", module);
      return get<LogEntry[]>(`/logs?${q.toString()}`);
    },
  },
  sectorLeaders: {
    items: () => get<SectorItemSummary[]>(`/sector-leaders/`),
    itemDetail: (item: string, topN = 3) =>
      get<SectorItemDetail>(
        `/sector-leaders/items/${encodeURIComponent(item)}?top_n=${topN}`,
      ),
    tickerDetail: (ticker: string, item?: string) => {
      const q = item ? `?item=${encodeURIComponent(item)}` : "";
      return get<TickerDetail>(`/sector-leaders/tickers/${ticker}${q}`);
    },
    tickerAnalysis: (ticker: string, item?: string) => {
      const q = item ? `?item=${encodeURIComponent(item)}` : "";
      return get<TickerAnalysis>(
        `/sector-leaders/tickers/${ticker}/analysis${q}`,
      );
    },
    tickerForecast: (ticker: string, item?: string, horizons = "1,3,6") => {
      const params = new URLSearchParams({ horizons });
      if (item) params.set("item", item);
      return get<TickerForecast>(
        `/sector-leaders/tickers/${ticker}/forecast?${params.toString()}`,
      );
    },
    tickerConfluence: (ticker: string, item?: string) => {
      const q = item ? `?item=${encodeURIComponent(item)}` : "";
      return get<TickerConfluence>(
        `/sector-leaders/tickers/${ticker}/confluence${q}`,
      );
    },
    top10: (limit = 10) =>
      get<Top10Response>(`/sector-leaders/top10?limit=${limit}`),
  },
  memeWatch: {
    top: (limit = 20, market?: "US" | "KRX") => {
      const q = new URLSearchParams({ limit: String(limit) });
      if (market) q.set("market", market);
      return get<MemeWatchTopResponse>(`/meme-watch/top?${q.toString()}`);
    },
  },
};

// ─── Meme Watch (Phase 1e) ────────────────────────────────────

export interface MemeSignalContribution {
  name: string;          // social / volume / oversold / short / catalyst
  label: string;
  raw_value: number | null;
  raw_label: string;
  normalized: number;
  weight: number;
  contribution: number;
  detail: string;
}

export interface MemeIntensity {
  intensity: number;
  label: string;   // ERUPTING / SURGING / RISING / STABILIZING / FLAT
  emoji: string;   // 🌋 / 🚀 / 📈 / 〰️ / 💤
  return_1d: number | null;
  return_5d: number | null;
  acceleration: number | null;
  volume_ratio: number | null;
  sample_days: number;
}

export interface MemeScoreItem {
  ticker: string;
  name: string | null;
  market: string | null;
  sector: string | null;
  market_cap: number | null;

  score: number;
  label: string;     // BLAZING / HOT / WATCH / OBSERVE / SLEEP
  emoji: string;

  active_signals: number;
  strongest_signal: string;
  confidence_label: string;
  sample_warning: boolean;
  contributions: MemeSignalContribution[];
  current_price: number | null;
  return_1d_pct: number | null;
  intensity: MemeIntensity | null;
}

export interface MemeWatchTopResponse {
  items: MemeScoreItem[];
  total: number;
  computed_at: string;
  sources_status: Record<string, string>;  // {"apewisdom":"ok",...}
}
