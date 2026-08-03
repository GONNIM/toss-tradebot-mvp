"use client";

// Backtest 수익률 차트 · Phase L7 · 2026-08-02
// recharts BarChart · 5/10/30/60/180일 후 % return

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ReturnFields = {
  return_5d: number | null;
  return_10d: number | null;
  return_30d: number | null;
  return_60d: number | null;
  return_180d: number | null;
};

type Props = {
  data: ReturnFields;
  title?: string;
  height?: number;
};

const WINDOWS: { key: keyof ReturnFields; label: string }[] = [
  { key: "return_5d", label: "5d" },
  { key: "return_10d", label: "10d" },
  { key: "return_30d", label: "30d" },
  { key: "return_60d", label: "60d" },
  { key: "return_180d", label: "180d" },
];

export function BacktestChart({ data, title, height = 220 }: Props) {
  const chartData = WINDOWS.map((w) => ({
    window: w.label,
    return: data[w.key] ?? 0,
    hasData: data[w.key] !== null,
  }));
  const allEmpty = chartData.every((d) => !d.hasData);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      {title && <h3 className="mb-2 text-sm font-semibold">{title}</h3>}
      {allEmpty ? (
        <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
          이 티커에 대한 백테스트 결과가 아직 없습니다.
          <br />
          각 신호의 <strong>추출일 종가</strong> 대비 5·10·30·60·180 거래일 후
          종가 변화율을 계산합니다.
          <br />
          매주 월요일 00:00 KST 배치가 미처리 신호를 200건씩 순차 처리하며,
          이 티커 차례가 오면 채워집니다.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
            <XAxis dataKey="window" tick={{ fontSize: 10 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              tickFormatter={(v: number) => `${v}%`}
              width={44}
            />
            <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.4} />
            <Tooltip
              formatter={(v: number) => `${v.toFixed(2)}%`}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                fontSize: 11,
              }}
            />
            <Bar dataKey="return" radius={[4, 4, 0, 0]}>
              {chartData.map((d, i) => (
                <Cell
                  key={i}
                  fill={
                    !d.hasData
                      ? "hsl(var(--muted))"
                      : d.return >= 0
                      ? "#10b981"
                      : "#ef4444"
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}
