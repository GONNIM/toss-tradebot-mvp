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
  ticker: string;
  rank: number;
  company_name: string;
  sector: string | null;
  current_price: number;
  market_cap_usd: number | null;
  total_score: number;
  thesis: string;
  catalysts: string[];
  risks: string[];
  news_summary: string;
  manipulation_risk: number;
  created_at: string;
}

export interface MoonshotPick {
  id: number;
  ticker: string;
  rank: number;
  company_name: string;
  sector: string | null;
  current_price: number;
  market_cap_usd: number | null;
  risk_level: RiskLevel;
  total_score: number;
  thesis: string;
  catalysts: string[];
  risks: string[];
  news_summary: string;
  manipulation_risk: number;
  buy_price_market: number;
  buy_price_limit_3pct: number;
  buy_price_limit_7pct: number;
  risk_warning: string;
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
  level: string;
  category: string;
  message: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Setting {
  key: string;
  value: string;
  description: string | null;
}

// ─────────────────────────────────────────────
// 메소드
// ─────────────────────────────────────────────

export const api = {
  crazy: {
    list: (limit = 10) => get<CrazyPick[]>(`/crazy?limit=${limit}`),
    byTicker: (ticker: string) => get<CrazyPick>(`/crazy/${ticker}`),
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
    list: (limit = 50, hours = 24) =>
      get<LogEntry[]>(`/logs?limit=${limit}&hours=${hours}`),
  },
};
