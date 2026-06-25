"use client";

/**
 * 섹터별 주도주 Top 3 — 산업통상부 월간 수출입동향 ↔ KRX 주도주 매핑.
 *
 * 동선:
 *   ① 좌측 사이드에서 17 품목 중 1개 선택
 *   ② 메인 상단: 수출 13M+ 차트 + 주도주 Top 3 카드 (selector)
 *   ③ 카드 클릭 → 하단 AnalysisPanel 이 해당 종목으로 전환
 *      - 메인 차트 (가격×수출 동행) · 통계 · 백테스트 · 월별 표 · 최근 시그널
 *
 * 설계: docs/plans/sector-leaders/01-mvp-design.md  +  02-progress-2026-06-24.md (B-2f)
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AnalysisPanel } from "@/components/sector-leaders/AnalysisPanel";
import { api, type SectorItemSummary, type SectorLeader } from "@/lib/api";
import {
  confidenceBadgeClass,
  confidenceStars,
  formatKRW,
  formatPct,
  lagDescription,
} from "@/lib/utils";

export default function SectorLeadersPage() {
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const itemsQuery = useQuery({
    queryKey: ["sector-leaders", "items"],
    queryFn: () => api.sectorLeaders.items(),
  });

  const items = itemsQuery.data ?? [];
  const activeItem = selectedItem ?? (items.length > 0 ? items[0].item : null);

  // 품목 전환 시 종목 선택 초기화 — Top 1 자동 선택은 ItemDetail 내부에서
  const handleSelectItem = (item: string) => {
    setSelectedItem(item);
    setSelectedTicker(null);
  };

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-3xl font-bold">🇰🇷 섹터별 주도주 Top 3</h1>
        <p className="text-sm text-muted-foreground">
          산업통상부 월간 수출입동향 ↔ KRX 주도주 ·{" "}
          매월 1일 발표 자료 자동 갱신 · 24개월 Pearson 상관 + lead/lag 시그널
        </p>
      </header>

      <div className="grid grid-cols-12 gap-4">
        {/* 좌측 사이드 — 17 품목 */}
        <aside className="col-span-12 md:col-span-3">
          {itemsQuery.isLoading && <Loading />}
          {itemsQuery.error && <ErrBox />}
          {itemsQuery.data && (
            <ItemList
              items={items}
              activeItem={activeItem}
              onSelect={handleSelectItem}
            />
          )}
        </aside>

        {/* 메인 — 선택 품목 상세 + 분석 패널 */}
        <section className="col-span-12 md:col-span-9 space-y-4">
          {activeItem ? (
            <ItemDetail
              item={activeItem}
              selectedTicker={selectedTicker}
              onSelectTicker={setSelectedTicker}
            />
          ) : (
            <Empty msg="품목을 선택하세요" />
          )}
        </section>
      </div>
    </div>
  );
}

// ─── 좌측 사이드 ──────────────────────────────────────────────────

function ItemList({
  items,
  activeItem,
  onSelect,
}: {
  items: SectorItemSummary[];
  activeItem: string | null;
  onSelect: (item: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card divide-y divide-border">
      {items.map((it) => {
        const active = it.item === activeItem;
        const yoy = it.latest_yoy_pct ?? 0;
        const yoyColor =
          yoy > 0
            ? "text-emerald-400"
            : yoy < 0
              ? "text-rose-400"
              : "text-muted-foreground";
        return (
          <button
            key={it.item}
            onClick={() => onSelect(it.item)}
            className={`w-full text-left px-3 py-2.5 text-sm transition ${
              active
                ? "bg-cyan-500/10 border-l-2 border-cyan-500"
                : "hover:bg-muted/30 border-l-2 border-transparent"
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium truncate">{it.item}</span>
              <span
                className={`shrink-0 text-xs ${confidenceBadgeClass(
                  it.top_confidence,
                )} rounded-full border px-1.5 py-0.5`}
              >
                {confidenceStars(it.top_confidence)}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {it.leader_count}종목
              </span>
              <span className={yoyColor}>
                {it.latest_yoy_pct === null
                  ? "—"
                  : formatPct(it.latest_yoy_pct, 1)}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── 메인 패널 ────────────────────────────────────────────────────

function ItemDetail({
  item,
  selectedTicker,
  onSelectTicker,
}: {
  item: string;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["sector-leaders", "item", item],
    queryFn: () => api.sectorLeaders.itemDetail(item, 5),
  });

  // 품목 전환 시 Top 1 자동 선택 (디폴트)
  useEffect(() => {
    if (detailQuery.data?.leaders.length && !selectedTicker) {
      onSelectTicker(detailQuery.data.leaders[0].ticker);
    }
  }, [detailQuery.data, selectedTicker, onSelectTicker]);

  if (detailQuery.isLoading) return <Loading />;
  if (detailQuery.error) return <ErrBox />;
  const d = detailQuery.data;
  if (!d) return <Empty msg="데이터 없음" />;

  return (
    <>
      {/* 품목 헤더 + 수출 차트 */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <h2 className="text-xl font-bold">{d.item}</h2>
          <span className="text-xs text-muted-foreground">
            {d.description ?? "—"}
          </span>
        </div>
        <ExportChart data={d.export_series} />
        <p className="text-xs text-muted-foreground">
          *데이터: 산업통상부 월간 수출입동향 (motir.go.kr) · 13~25개월 누적
          시계열 · 잠정→확정 BACKFILL 자동 적용
        </p>
      </div>

      {/* 주도주 카드 */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <h3 className="font-semibold">
          주도주 Top {d.leaders.length}{" "}
          <span className="text-xs text-muted-foreground">
            (score = log10(시총) × 수출비중 · 카드 클릭 시 하단 분석 패널 갱신)
          </span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {d.leaders.map((l) => (
            <LeaderCard
              key={l.ticker}
              leader={l}
              active={l.ticker === selectedTicker}
              onSelect={() => onSelectTicker(l.ticker)}
            />
          ))}
        </div>
      </div>

      {/* 분석 패널 (B-2f) */}
      {selectedTicker && (
        <AnalysisPanel ticker={selectedTicker} item={d.item} />
      )}
    </>
  );
}

function ExportChart({
  data,
}: {
  data: { month: string; value_musd: number; yoy_pct: number | null }[];
}) {
  const chartData = data.map((d) => ({
    month: d.month.slice(2),
    value: d.value_musd,
    yoy: d.yoy_pct ?? 0,
  }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
          <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <YAxis
            yAxisId="value"
            orientation="left"
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v) => `${(v / 1000).toFixed(0)}억$`}
          />
          <YAxis
            yAxisId="yoy"
            orientation="right"
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              fontSize: "12px",
            }}
          />
          <Legend wrapperStyle={{ fontSize: "12px" }} />
          <Line
            yAxisId="value"
            type="monotone"
            dataKey="value"
            name="수출액(백만$)"
            stroke="#06b6d4"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="yoy"
            type="monotone"
            dataKey="yoy"
            name="YoY(%)"
            stroke="#f97316"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function LeaderCard({
  leader,
  active,
  onSelect,
}: {
  leader: SectorLeader;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`text-left rounded-lg border bg-background p-3 transition ${
        active
          ? "border-cyan-500/60 ring-1 ring-cyan-500/30 bg-cyan-500/5"
          : "border-border hover:border-muted-foreground/40"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="font-semibold">{leader.name}</span>
        <span className="text-xs text-muted-foreground">{leader.ticker}</span>
      </div>
      <div className="text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">시총</span>
          <span className="font-mono">{formatKRW(leader.market_cap_krw)}원</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">수출비중*</span>
          <span className="font-mono">
            {leader.export_ratio_hint !== null
              ? `${(leader.export_ratio_hint * 100).toFixed(0)}%`
              : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Pearson r</span>
          <span className="font-mono">
            {leader.best_r !== null
              ? `${leader.best_r >= 0 ? "+" : ""}${leader.best_r.toFixed(3)}`
              : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">lead/lag</span>
          <span className="font-mono">{lagDescription(leader.best_lag_months)}</span>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span
          className={`text-xs ${confidenceBadgeClass(
            leader.confidence,
          )} rounded-full border px-2 py-0.5`}
        >
          {confidenceStars(leader.confidence)} {leader.confidence}
        </span>
        <span className="text-xs text-muted-foreground">rank #{leader.rank}</span>
      </div>
      <div className="mt-2 text-xs text-cyan-400">
        {active ? "✓ 선택됨 (아래 패널)" : "클릭 → 분석 패널 ▾"}
      </div>
    </button>
  );
}

// ─── 상태 컴포넌트 ────────────────────────────────────────────────

function Loading() {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
      로딩 중...
    </div>
  );
}

function ErrBox() {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
      API 호출 실패. backend (포트 8001) 가동 여부를 확인하세요.
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
      {msg}
    </div>
  );
}
