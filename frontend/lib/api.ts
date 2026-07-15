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

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API PATCH ${path} failed: ${res.status}`);
  }
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API PUT ${path} failed: ${res.status}`);
  }
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API POST ${path} failed: ${res.status}`);
  }
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API DELETE ${path} failed: ${res.status}`);
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
  entry_price: number | null;      // v2.0: 과열 시 null
  entry_status: string;
  entry_gap_pct: number | null;    // v2.0: 과열 시 null

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

  // v2.0 진입가 근거 (2026-07-08~)
  high_52w: number;
  low_52w: number;
  pos_52w: number;                 // 0.0 ~ 1.0
  atr14: number;
  ma200: number | null;
  ma200_deviation: number | null;
  overheat: boolean;
  entry_method: string;
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
    scoreHistory: (ticker: string, hours = 24) =>
      get<MemeScoreHistoryResponse>(
        `/meme-watch/tickers/${encodeURIComponent(ticker)}/history?hours=${hours}`,
      ),
    vip: {
      status: () => get<VipStatus>(`/meme-watch/vip/status`),
      getConfig: () => get<VipConfig>(`/meme-watch/vip/config`),
      patchConfig: (body: VipConfigPatch) =>
        patch<VipConfigPatchResponse>(`/meme-watch/vip/config`, body),
    },
    activist: {
      status: () => get<ActivistStatusResponse>(`/meme-watch/activist/status`),
      wolfPacks: () => get<ActivistWolfPacksResponse>(`/meme-watch/activist/wolf-packs`),
      universe: () => get<ActivistUniverseResponse>(`/meme-watch/activist/universe`),
      patchUniverse: (entry: ActivistUpsert) =>
        patch<ActivistUniverseMutateResponse>(`/meme-watch/activist/universe`, entry),
      deleteUniverse: async (key: string) => {
        const res = await fetch(`${BASE}/meme-watch/activist/universe/${encodeURIComponent(key)}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`DELETE universe/${key} failed: ${res.status}`);
        return res.json() as Promise<ActivistUniverseMutateResponse>;
      },
    },
  },
  execution: {
    status: () => get<ExecutionStatus>(`/execution/status`),
    killSwitch: {
      status: () => get<KillSwitchStatus>(`/execution/kill-switch/status`),
      activate: (reason: string, actor = "user:manual") =>
        post<{ active: boolean; reason: string; activated_by: string }>(
          `/execution/kill-switch`,
          { reason, actor },
        ),
      deactivate: (actor = "user:manual") =>
        del<{ active: boolean; deactivated_by: string }>(
          `/execution/kill-switch?actor=${encodeURIComponent(actor)}`,
        ),
    },
    params: {
      get: () => get<ExecutionParams>(`/execution/params`),
      put: (body: ExecutionParams) =>
        put<{ ok: boolean; saved: boolean }>(`/execution/params`, body),
    },
    paper: {
      state: () => get<PaperState>(`/execution/paper/state`),
      resync: () =>
        post<{ ok: boolean; synced_from: string; synced_at: string }>(
          `/execution/paper/resync`,
        ),
      reset: (cash_krw?: number) =>
        post<{ ok: boolean; cash_krw: number; synced_from: string }>(
          `/execution/paper/reset`,
          cash_krw !== undefined ? { cash_krw } : {},
        ),
    },
    audit: (opts?: { ticker?: string; broker?: string; signal_source?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (opts?.ticker) q.set("ticker", opts.ticker);
      if (opts?.broker) q.set("broker", opts.broker);
      if (opts?.signal_source) q.set("signal_source", opts.signal_source);
      if (opts?.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<OrderAuditRow[]>(`/execution/audit${qs ? `?${qs}` : ""}`);
    },
    market: {
      status: () => get<MarketStatus>(`/execution/market/status`),
    },
    orders: {
      pending: () => get<{ orders: unknown[]; request_id: string | null }>(
        `/execution/orders/pending`,
      ),
      cancel: (orderId: string) =>
        post<{ ok: boolean; result: unknown; request_id: string | null }>(
          `/execution/orders/${encodeURIComponent(orderId)}/cancel`,
        ),
    },
  },
  superSignals: {
    list: (limit = 30) => get<SuperSignalRow[]>(`/super-signals?limit=${limit}`),
    hits: (opts?: { ticker?: string; days?: number; limit?: number }) => {
      const q = new URLSearchParams();
      if (opts?.ticker) q.set("ticker", opts.ticker);
      if (opts?.days) q.set("days", String(opts.days));
      if (opts?.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<SignalHitRow[]>(`/super-signals/hits${qs ? `?${qs}` : ""}`);
    },
    promote: () =>
      post<{ count: number; results: unknown[] }>(`/super-signals/promote`),
  },
  backtest: {
    run: (opts: {
      days?: number;
      sources?: string[];
      tickers?: string[];
      holding_days?: number;
      take_profit_pct?: number;
      stop_loss_pct?: number;
    }) => post<BacktestReport>(`/backtest/run`, opts),
  },
  sniper: {
    status: () => get<SniperStatus>(`/sniper/status`),
    params: () => get<SniperParams>(`/sniper/params`),
    universe: (opts?: { squeeze_only?: boolean; limit?: number }) => {
      const q = new URLSearchParams();
      if (opts?.squeeze_only) q.set("squeeze_only", "true");
      if (opts?.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<{ size: number; items: SniperUniverseItem[] }>(
        `/sniper/universe${qs ? `?${qs}` : ""}`,
      );
    },
    signals: (opts?: { hours?: number; limit?: number }) => {
      const q = new URLSearchParams();
      if (opts?.hours) q.set("hours", String(opts.hours));
      if (opts?.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<SniperSignalRow[]>(
        `/sniper/signals/recent${qs ? `?${qs}` : ""}`,
      );
    },
    candidates: (top_n = 10) =>
      get<SniperCandidateRow[]>(`/sniper/candidates?top_n=${top_n}`),
    updateParams: (token: string, updates: Partial<SniperParams>) =>
      putWithToken<{ ok: boolean; params: SniperParams }>(
        `/sniper/params`,
        token,
        updates,
      ),
    refreshUniverse: (token: string) =>
      postWithToken<{ total: number; passed: number; squeeze: number; refreshed_at: string }>(
        `/sniper/universe/refresh`,
        token,
      ),
    manualEntry: (token: string, ticker: string, broker: "paper" | "toss" = "paper") =>
      postWithToken<{
        ok: boolean;
        reason: string | null;
        order_uuid: string | null;
        entry_price: number | null;
        filled_qty: number;
        candidate_passed: boolean;
        candidate_reject_reason: string | null;
      }>(`/sniper/entry`, token, { ticker, broker }),
  },
  watchlist: {
    list: (trade_date?: string) => {
      const qs = trade_date ? `?trade_date=${encodeURIComponent(trade_date)}` : "";
      return get<{ trade_date: string; size: number; items: WatchlistItem[] }>(
        `/watchlist${qs}`,
      );
    },
    signals: (opts: { trade_date?: string; hours?: number; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (opts.trade_date) q.set("trade_date", opts.trade_date);
      if (opts.hours) q.set("hours", String(opts.hours));
      if (opts.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<{ count: number; items: WatchlistSignal[] }>(
        `/watchlist/signals${qs ? `?${qs}` : ""}`,
      );
    },
    dates: () => get<string[]>(`/watchlist/dates`),
    finalize: (token: string, opts: { trade_date?: string; top_n?: number } = {}) =>
      postWithToken<{
        trade_date: string;
        signals_read: number;
        candidates_scored: number;
        locked_kept: number;
        auto_picked: number;
        written: number;
        top_n: number;
      }>(`/watchlist/finalize`, token, opts),
    addManual: (
      token: string,
      opts: { ticker: string; trade_date?: string; name?: string },
    ) =>
      postWithToken<{ id: number; ticker: string; trade_date: string; locked: boolean }>(
        `/watchlist/manual`,
        token,
        opts,
      ),
    toggleLock: (token: string, id: number, locked: boolean) =>
      patchWithToken<{ id: number; locked: boolean }>(
        `/watchlist/${id}/lock`,
        token,
        { locked },
      ),
    remove: (token: string, id: number) =>
      delWithToken<{ deleted: boolean; id: number }>(`/watchlist/${id}`, token),
    report: (days = 30) =>
      get<WatchlistReport>(`/watchlist/report?days=${days}`),
  },
  powderkeg: {
    disclaimer: () => get<{ disclaimer: string }>(`/powderkeg/disclaimer`),
    list: (opts: { run_id?: string; status?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (opts.run_id) q.set("run_id", opts.run_id);
      if (opts.status) q.set("status", opts.status);
      if (opts.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<PowderKegListResponse>(`/powderkeg/list${qs ? `?${qs}` : ""}`);
    },
    events: (opts: { ticker?: string; event_type?: string; hours?: number; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (opts.ticker) q.set("ticker", opts.ticker);
      if (opts.event_type) q.set("event_type", opts.event_type);
      if (opts.hours) q.set("hours", String(opts.hours));
      if (opts.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<PowderKegEventsResponse>(`/powderkeg/events${qs ? `?${qs}` : ""}`);
    },
    report: (event_type: string) =>
      get<PowderKegReport>(`/powderkeg/report/${event_type}`),
    tickets: (opts: { status?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (opts.status) q.set("status", opts.status);
      if (opts.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return get<PowderKegTicketsResponse>(`/powderkeg/tickets${qs ? `?${qs}` : ""}`);
    },
    runScreener: (token: string, tickers: string[], year = 2026) =>
      postWithToken<{ run_id: string; total: number; passed: number; rejected: number }>(
        `/powderkeg/screener/run`, token, { tickers, year },
      ),
    processTriggers: (token: string) =>
      postWithToken<Record<string, number>>(`/powderkeg/triggers/process`, token),
    runBacktest: (token: string, event_type: string) =>
      postWithToken<PowderKegReport>(`/powderkeg/backtest/${event_type}`, token),
    approveTicket: (token: string, id: number, approver: string) =>
      patchWithToken<{ id: number; status: string }>(
        `/powderkeg/ticket/${id}/approve`, token, { approver },
      ),
    rejectTicket: (token: string, id: number, reason: string) =>
      patchWithToken<{ id: number; status: string }>(
        `/powderkeg/ticket/${id}/reject`, token, { reason },
      ),
  },
};

async function putWithToken<T>(path: string, token: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-API-Token": token },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API PUT ${path} failed: ${res.status} · ${await res.text()}`);
  return res.json();
}

async function patchWithToken<T>(path: string, token: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-API-Token": token },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API PATCH ${path} failed: ${res.status} · ${await res.text()}`);
  return res.json();
}

async function delWithToken<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json", "X-API-Token": token },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API DELETE ${path} failed: ${res.status} · ${await res.text()}`);
  return res.json();
}

async function postWithToken<T>(path: string, token: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Token": token },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API POST ${path} failed: ${res.status} · ${await res.text()}`);
  return res.json();
}

// ─────────────────────────────────────────────
// Execution Layer 타입 (v2 트랙 C · Phase 1)
// ─────────────────────────────────────────────

export interface ThresholdSet {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  trailing_arm_pct: number | null;
  trailing_giveback_pct: number | null;
}

export interface RiskBudget {
  per_ticker_max_pct: number;
  daily_loss_limit: number;
  ticker_dd_limit: number;
}

export interface ExecutionParams {
  global: ThresholdSet;
  risk_budget: RiskBudget;
  tickers: Record<string, ThresholdSet>;
  signals: Record<string, ThresholdSet>;
}

export interface KillSwitchStatus {
  active: boolean;
  reason: string | null;
  activated_at: string | null;
  activated_by: string | null;
  deactivated_at: string | null;
  deactivated_by: string | null;
}

export interface ExecutionStatus {
  execution_enabled: boolean;
  broker: string;
  kill_switch: KillSwitchStatus;
}

export interface PaperPosition {
  qty: number;
  avg_price: number;
  currency: string;
}

export interface PaperState {
  cash_krw: number;
  cash_usd: number;
  fx_usd_krw: number;
  positions: Record<string, PaperPosition>;
  pending_orders: Record<string, unknown>;
  filled_orders: Record<string, unknown>;
  idempotency: Record<string, unknown>;
  order_seq: number;
  synced_at: string | null;
  synced_from: string;
}

export interface MarketWindow {
  start: string;
  end: string;
}

export interface MarketWindowSet {
  state: "closed" | "pre_market" | "regular" | "after_hours" | "halt";
  pre_market: MarketWindow | null;
  regular_market: MarketWindow | null;
  after_market: MarketWindow | null;
}

export interface MarketStatus {
  KR: MarketWindowSet;
  US: MarketWindowSet;
}

// ─────────────────────────────────────────────
// Sniper 타입 (Sprint 1)
// ─────────────────────────────────────────────
export interface SniperParams {
  seed_cap_krw: number;
  per_order_krw: number;
  max_concurrent_positions: number;
  trailing_giveback_pct: number;
  hard_stop_loss_pct: number;
  daily_loss_limit_pct: number;
  weekly_loss_limit_pct: number;
  active_start_kst: string;
  active_end_kst: string;
  force_close_enabled: boolean;
  force_close_kst: string;
  universe_market_cap_min_krw: number;
  universe_market_cap_max_krw: number;
  universe_adv_20d_min_krw: number;
  universe_float_max_shares: number;
  universe_price_min_krw: number;
  universe_squeeze_float_max: number;
  tape_score_threshold: number;
  rank_velocity_z_min: number;
  trades_intensity_z_min: number;
  orderbook_z_min: number;
  score_weight_rank: number;
  score_weight_trades: number;
  score_weight_orderbook: number;
  entry_return_min_pct: number;
  entry_return_max_pct: number;
  sustained_rise_min_sec: number;
  same_ticker_daily_limit: number;
  rank_target_min: number;
  rank_target_max: number;
  poll_rankings_sec: number;
  poll_trades_sec: number;
  poll_orderbook_sec: number;
  poll_trailing_price_sec: number;
  enabled: boolean;
}

export interface SniperStatus {
  live_enabled: boolean;
  sniper_enabled: boolean;
  kill_switch_active: boolean;
  universe_size: number;
  seed_cap_krw: number;
  per_order_krw: number;
  max_concurrent_positions: number;
  trailing_giveback_pct: number;
  hard_stop_loss_pct: number;
  active_window_kst: { start: string; end: string };
  force_close_enabled: boolean;
  force_close_kst: string;
  watchlist_execute?: {
    enabled: boolean;
    start_kst: string;
    end_kst: string;
    gap_min_pct: number;
    gap_max_pct: number;
    min_composite_score: number;
    use_rankings_confirm: boolean;
  };
}

export interface SniperUniverseItem {
  ticker: string;
  name: string;
  close_price: number | null;
  market_cap_krw: number | null;
  shares: number | null;
  amount_today: number | null;
  is_squeeze: boolean;
}

export interface SniperSignalRow {
  id: number;
  ticker: string;
  detected_at: string | null;
  tape_score: number | null;
  rank_velocity: number | null;
  trades_intensity: number | null;
  orderbook_imbalance: number | null;
  entry_order_uuid: string | null;
  entry_price: number | null;
  exit_order_uuid: string | null;
  exit_price: number | null;
  peak_price: number | null;
  pnl_pct: number | null;
  reason: string | null;
}

export interface SniperCandidateRow {
  ticker: string;
  name: string;
  tape_score: number;
  rank_velocity_score: number;
  trades_intensity_score: number;
  orderbook_score: number;
  last_price: number;
  return_pct: number | null;
  candidate: boolean;
  reject_reason: string | null;
}

export interface BacktestSourceStats {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_return_pct: number;
  total_return_pct: number;
}

export interface BacktestTrade {
  ticker: string;
  source: string;
  signal_id: string;
  entry_at: string | null;
  entry_price: number;
  exit_at: string | null;
  exit_price: number | null;
  pnl_pct: number | null;
  reason: string;
}

export interface BacktestReport {
  config: Record<string, unknown>;
  generated_at: string;
  summary: {
    total_trades: number;
    win_rate: number;
    avg_return_pct: number;
    total_return_pct: number;
    max_drawdown_pct: number;
    sharpe: number;
  };
  by_source: Record<string, BacktestSourceStats>;
  by_ticker: Record<string, BacktestSourceStats>;
  trades: BacktestTrade[];
}

export interface SuperSignalRow {
  id: number;
  ticker: string;
  intensity: number;
  sources: string;
  hit_count: number;
  first_hit_at: string | null;
  last_hit_at: string | null;
  promoted_at: string | null;
  order_uuid: string | null;
  oco_id: string | null;
  oco_status: string | null;
  metadata: {
    hits?: Array<{ source: string; signal_id: string; score: number; at: string | null }>;
    oco?: {
      tp_price: string;
      sl_price: string;
      tp_pct: number;
      sl_pct: number;
      entry_price: number;
      request_id: string | null;
    };
  };
}

export interface SignalHitRow {
  id: number;
  ticker: string;
  source: string;
  signal_id: string;
  score: number;
  action: string;
  hit_at: string | null;
}

export interface OrderAuditRow {
  order_uuid: string;
  broker_kind: string;
  broker_order_id: string | null;
  ticker: string;
  side: string;
  order_type: string;
  qty: number;
  price: number | null;
  signal_source: string | null;
  signal_id: string | null;
  status: string;
  filled_qty: number;
  avg_fill_price: number | null;
  total_fee: number;
  error_code: string | null;
  error_message: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface ActivistUpsert {
  key: string;
  name?: string;
  country?: string;
  tier?: number;
  cik?: string;
  corp_code?: string;
  keywords?: string[];
  enabled?: boolean;
}

export interface ActivistUniverseMutateResponse {
  overrides: Record<string, unknown>;
  universe: ActivistUniverseResponse;
}

// ─── Wolf Pack 그룹 ──────────────────────

export interface WolfPackEntry {
  filer_key: string;
  filer_name: string;
  tier: number;
  form: string;
  filing_date: string;
  detected_at: number;
  accession: string;
  intensity_label: string;
}

export interface WolfPackGroup {
  target_ticker: string;
  target_desc: string;
  target_cik: string | null;
  country: string;
  activist_count: number;
  tier1_count: number;
  days_span: number;
  first_entry_at: number;
  latest_entry_at: number;
  intensity_score: number;
  intensity_label: "CRITICAL_PACK" | "STRONG_PACK" | "PACK";
  entries: WolfPackEntry[];
}

export interface ActivistWolfPacksResponse {
  total: number;
  critical_count: number;
  strong_count: number;
  groups: WolfPackGroup[];
}

// ─── Activist Radar ──────────────────────────────────

export type ActivistIntensity =
  | "REGIME_CHANGE"   // Phase D · 13G→13D 태세 전환
  | "CRITICAL"
  | "STRONG"
  | "INSIDER"          // Phase E · 임원 매매
  | "WATCH"
  | "NOTE";

export interface ActivistEventItem {
  id: string;
  country: string;
  filer_key: string;
  filer_name: string;
  filer_cik?: string | null;
  filer_tier?: number | null;
  form: string;
  form_hint?: string;
  action_hint?: string;
  accession: string;
  filing_date: string;
  target_desc: string;
  target_ticker: string | null;
  score: number;
  wolf_pack: string[];
  detected_at: number;
  event_type?: "ACTIVIST" | "REGIME_CHANGE" | "INSIDER";
  filing_detail_url?: string;
  filer_search_url?: string;
  details?: {
    issuer_name?: string;
    issuer_cik?: string;
    issuer_cusip?: string;
    securities_class_title?: string;
    percent_of_class?: number | null;
    aggregate_amount_owned?: number | null;
    amendment_no?: number | null;
    date_of_event?: string;
    transaction_purpose?: string;
    reporting_persons_count?: number;
  };
}

export interface UsInsiderWatchEntry {
  ticker: string;
  cik: string;
  name: string;
}

export interface ActivistStatusResponse {
  universe_size: number;
  universe_us: number;
  universe_kr: number;
  events_total: number;
  insider_watchlist_kr?: string[];
  insider_watchlist_us?: UsInsiderWatchEntry[];
  buckets: Record<ActivistIntensity, ActivistEventItem[]>;
}

export interface ActivistEntry {
  key: string;
  name: string;
  country: string;
  tier: number;
  cik: string | null;
  corp_code: string | null;
  keywords: string[];
  enabled: boolean;
}

export interface ActivistUniverseResponse {
  activists: ActivistEntry[];
  overrides: Record<string, unknown>;
}

// ─── VIP (P-A) ─────────────────────────────────────────────

export interface VipThresholds {
  tp1_pct: number;
  tp2_pct: number;
  stop_pct: number;
  trail_arm_pct: number;
  trail_giveback_pct: number;
}

export interface VipQuote {
  close_price: number;
  fluctuations_ratio: number;
  compare_to_prev_close: number | null;
  market_status: string;
  over_market_ratio: number | null;
  local_traded_at: string | null;
  stock_name_kor: string | null;
  stock_name_eng: string | null;
  item_logo_url: string | null;
  exchange_name: string | null;
}

export interface VipMarketStats {
  base_price?: string;
  open_price?: string;
  high_price?: string;
  low_price?: string;
  accumulated_trading_volume?: string;
  accumulated_trading_value?: string;
  market_value?: string;
  industry_group_kor?: string;
  high_52w?: string;
  low_52w?: string;
  per?: string;
  eps?: string;
  pbr?: string;
  bps?: string;
  dividend?: string;
  dividend_yield_ratio?: string;
  dividend_at?: string;
  ex_dividend_at?: string;
}

export interface VipUsdKrw {
  rate: number;
  fluctuations_ratio: number;
  source: string;
  fetched_at: number;
}

export interface VipActivistFilingDetails {
  issuer_name?: string;
  issuer_cik?: string;
  issuer_cusip?: string;
  securities_class_title?: string;
  percent_of_class?: number | null;
  aggregate_amount_owned?: number | null;
  amendment_no?: number | null;
  date_of_event?: string;
  transaction_purpose?: string;
  reporting_persons_count?: number;
}

export interface VipActivistFiling {
  accession: string;
  form: string;
  form_hint?: string;
  filing_date: string;
  primary_desc: string;
  primary_doc: string;
  filing_detail_url?: string;
  details?: VipActivistFilingDetails;
}

export interface VipActivistRecent {
  form: string;
  form_hint?: string;
  date: string;
  accession: string;
  desc: string;
  filing_detail_url?: string;
}

export interface VipActivistSection {
  enabled: boolean;
  cik: string;
  name: string;
  keywords: string[];
  filer_search_url?: string;
  latest_target?: VipActivistFiling | null;
  recent_forms?: VipActivistRecent[];
}

export interface VipStatus {
  active: boolean;
  activist_active: boolean;
  ticker: string;
  company_name: string;
  tag: string;
  avg_price: number;
  qty: number;
  thresholds: VipThresholds;
  trail_armed_at: number | null;
  trail_peak_pnl: number | null;
  sent_events: Record<string, number>;
  activist_last_accession: string | null;
  is_us_regular_hours: boolean;
  quote?: VipQuote;
  market_stats?: VipMarketStats;
  usd_krw?: VipUsdKrw;
  pnl?: number;
  activist: VipActivistSection;
}

export interface VipConfig {
  ticker: string;
  company_name: string;
  tag: string;
  activist: {
    enabled: boolean;
    cik: string;
    name: string;
    keywords: string[];
  };
  overrides: Record<string, unknown>;
}

export interface VipConfigPatch {
  activist?: {
    enabled?: boolean;
    cik?: string;
    name?: string;
    keywords?: string[];
  };
}

export interface VipConfigPatchResponse {
  overrides: Record<string, unknown>;
  config: VipConfig;
}

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
  score_delta_24h: number | null;
  time_in_blazing_7d: number;
  mention_velocity_30m: number | null;    // Phase 5
  sample_days: number;
}

export interface MemeScoreHistoryPoint {
  snapshot_at: string;   // ISO
  score: number;
  label: string;
  active_signals: number;
}

export interface MemeScoreHistoryResponse {
  ticker: string;
  points: MemeScoreHistoryPoint[];
  hours: number;
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

// ─────────────────────────────────────────────
// Watchlist 타입 (Sprint 2 · 마감후 예측)
// ─────────────────────────────────────────────
export interface WatchlistItem {
  id: number;
  trade_date: string;      // YYYY-MM-DD
  ticker: string;
  name: string | null;
  rank: number;
  composite_score: number;
  news_score: number;
  board_score: number;
  youtube_score: number;
  event_score: number;
  prev_day_score: number;
  source_breakdown: Record<string, { count: number; intensity_sum: number }> | null;
  locked: boolean;
  added_by: string;        // "auto" | "user"
  created_at: string | null;
  updated_at: string | null;
}

export interface WatchlistSignal {
  id: number;
  ticker: string;
  source: string;          // news_yhap · board_naver · youtube_shuka 등
  signal_type: string;     // headline · board_post_velocity · video_upload 등
  intensity: number;
  payload: Record<string, unknown> | null;
  detected_at: string | null;
  trade_date: string;
}

export interface WatchlistReportCheck {
  name: string;
  target: string;
  actual: string;
  passed: boolean;
}

export interface WatchlistReport {
  since: string;
  window_days: number;
  closed_trades: number;
  metrics: {
    total_trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    avg_pnl_pct: number;
    avg_win_pct: number;
    avg_loss_pct: number;
    max_win_pct: number;
    max_loss_pct: number;
    mdd_pct: number;
    r_r_ratio: number;
    reason_breakdown: Record<string, number>;
  };
  checks: WatchlistReportCheck[];
  total_pass: boolean;
}

// ─────────────────────────────────────────────
// Powder Keg 타입 (Phase 7 · 화약고 스크리너)
// ─────────────────────────────────────────────
export interface PowderKegListItem {
  id: number;
  ticker: string;
  name: string | null;
  status: string;                // passed / rejected / cash_suspect
  net_cash_ratio: number | null;
  piotroski_f_score: number | null;
  owner_pct: number | null;
  treasury_pct: number | null;
  pbr: number | null;
  dividend_payout: number | null;
  conditions: Record<string, boolean> | null;
  reject_reasons: string | null;
  created_at: string | null;
}

export interface PowderKegListResponse {
  disclaimer: string;
  run_id: string | null;
  count: number;
  items: PowderKegListItem[];
}

export interface PowderKegEventItem {
  id: number;
  ticker: string;
  event_type: string;            // A1~A6 · B1~B3
  kind: "A" | "B";
  source: string;
  source_id: string | null;
  title: string;
  url: string | null;
  detected_at: string | null;
  release_date: string | null;
  confidence: number | null;
  needs_human_review: boolean;
  action_taken: string | null;
  validated: boolean;
}

export interface PowderKegEventsResponse {
  disclaimer: string;
  count: number;
  items: PowderKegEventItem[];
}

export interface PowderKegWindowStats {
  label: string;
  n: number;
  mean_return: number;
  median_return: number;
  win_rate: number;
  std: number;
  t_stat: number;
  max_return: number;
  min_return: number;
}

export interface PowderKegReport {
  disclaimer: string;
  event_type: string;
  aggregate: {
    event_type: string;
    total_events: number;
    valid_events: number;
    per_window: Record<string, PowderKegWindowStats>;
    error_counts: Record<string, number>;
  };
  decision: {
    event_type: string;
    validated: boolean;
    reasons: string[];
    tested_windows: string[];
    passing_window: string | null;
  };
  updated_rows: number;
}

export interface PowderKegTicket {
  id: number;
  event_id: number;
  ticker: string;
  proposed_qty: number;
  proposed_price: number | null;
  invalidation_price: number;
  invalidation_logic: string;
  status: string;               // pending/approved/rejected/executed
  approver: string | null;
  approved_at: string | null;
  created_at: string | null;
  holding_days_max: number;
  executed_order_uuid: string | null;
}

export interface PowderKegTicketsResponse {
  disclaimer: string;
  count: number;
  items: PowderKegTicket[];
}
