"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { MemeSignalContribution } from "@/lib/api";

const SIGNAL_ORDER = ["short", "social", "volume", "oversold", "catalyst"];
const SIGNAL_LABELS: Record<string, string> = {
  short: "공매도",
  social: "소셜",
  volume: "거래량",
  oversold: "Oversold",
  catalyst: "Catalyst",
};

export function MemeRadarChart({
  contributions,
}: {
  contributions: MemeSignalContribution[];
}) {
  const byName: Record<string, MemeSignalContribution> = {};
  for (const c of contributions) byName[c.name] = c;

  const data = SIGNAL_ORDER.map((name) => {
    const c = byName[name];
    return {
      signal: SIGNAL_LABELS[name],
      normalized: c ? Number(c.normalized.toFixed(2)) : 0,
      available: c !== undefined,
    };
  });

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data}>
          <PolarGrid stroke="currentColor" opacity={0.2} />
          <PolarAngleAxis
            dataKey="signal"
            tick={{ fill: "currentColor", fontSize: 12 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 1.5]}
            tick={{ fill: "currentColor", fontSize: 10, opacity: 0.6 }}
          />
          <Tooltip
            contentStyle={{
              background: "rgba(0,0,0,0.85)",
              border: "1px solid rgba(255,255,255,0.2)",
              borderRadius: "6px",
              color: "white",
              fontSize: "12px",
            }}
            formatter={(v: number) => v.toFixed(2)}
          />
          <Radar
            name="시그널 강도"
            dataKey="normalized"
            stroke="rgb(34, 211, 238)"
            fill="rgb(34, 211, 238)"
            fillOpacity={0.4}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
