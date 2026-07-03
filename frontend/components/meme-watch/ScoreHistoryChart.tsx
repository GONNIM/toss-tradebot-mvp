"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";

function formatKstTime(iso: string): string {
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  if (isNaN(d.getTime())) return "";
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(kst.getUTCMonth() + 1)}/${pad(kst.getUTCDate())} ${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())}`;
}

export function ScoreHistoryChart({
  ticker,
  hours = 24,
}: {
  ticker: string;
  hours?: number;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["meme-watch", "history", ticker, hours],
    queryFn: () => api.memeWatch.scoreHistory(ticker, hours),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="text-xs text-zinc-500 dark:text-zinc-400 py-4 text-center">
        로딩 중...
      </div>
    );
  }

  if (!data || data.points.length === 0) {
    return (
      <div className="text-xs text-zinc-500 dark:text-zinc-400 py-4 text-center">
        최근 {hours}시간 이력 없음. Phase 4 이력 저장은 5분마다 누적됩니다.
      </div>
    );
  }

  const chartData = data.points.map((p) => ({
    t: formatKstTime(p.snapshot_at),
    score: Number(p.score.toFixed(3)),
    label: p.label,
  }));

  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid stroke="currentColor" strokeOpacity={0.15} strokeDasharray="3 3" />
          <XAxis
            dataKey="t"
            tick={{ fill: "currentColor", fontSize: 10 }}
            interval="preserveStartEnd"
            minTickGap={40}
          />
          <YAxis
            tick={{ fill: "currentColor", fontSize: 10 }}
            domain={[0, 1.5]}
            ticks={[0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]}
          />
          <Tooltip
            contentStyle={{
              background: "rgba(0,0,0,0.85)",
              border: "1px solid rgba(255,255,255,0.2)",
              borderRadius: "6px",
              color: "white",
              fontSize: "12px",
            }}
            formatter={(v: number) => v.toFixed(3)}
          />
          {/* 라벨 임계선 */}
          <ReferenceLine y={1.0} stroke="rgb(244, 63, 94)" strokeDasharray="4 4" strokeOpacity={0.6} />
          <ReferenceLine y={0.75} stroke="rgb(249, 115, 22)" strokeDasharray="4 4" strokeOpacity={0.5} />
          <ReferenceLine y={0.5} stroke="rgb(245, 158, 11)" strokeDasharray="4 4" strokeOpacity={0.5} />
          <Line
            type="monotone"
            dataKey="score"
            stroke="rgb(34, 211, 238)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
