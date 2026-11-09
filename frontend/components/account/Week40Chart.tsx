"use client";

// 1108-02 4단계 · 40주 평균선 그림 (계획 7절). 사실로 보이는 것만 — 매매 규칙 적용이 아니다.
// 검은 선 = 끝난 주 종가 · 틸 선 = 40주 단순평균 · 선 아래 주는 옅은 바탕. 숫자는 tabular-nums.

import { useMemo } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  WEEK40_BASIS_LINE,
  WEEK40_FIRST_LINE,
  WEEK40_LIMIT_LINE,
  Week40,
  Week40Point,
  week40CheckText,
  week40FactText,
  week40TipText,
} from "@/lib/holdings-swing";

/** 선 아래 주(종가 < 선)가 이어진 구간 [처음 주, 끝 주]. */
function belowRuns(series: Week40Point[]): [string, string][] {
  const runs: [string, string][] = [];
  let start: string | null = null;
  let prev: string | null = null;
  for (const p of series) {
    const below = p.m !== null && p.c < p.m;
    if (below && start === null) start = p.w;
    if (!below && start !== null && prev !== null) {
      runs.push([start, prev]);
      start = null;
    }
    prev = p.w;
  }
  if (start !== null && prev !== null) runs.push([start, prev]);
  return runs;
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Week40Point }[] }) {
  if (!active || !payload?.length) return null;
  const lines = week40TipText(payload[0].payload);
  return (
    <div className="rounded-md border border-border bg-background p-2 text-xs tabular-nums shadow-none">
      {lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </div>
  );
}

export function Week40Chart({ week40 }: { week40: Week40 | null }) {
  const runs = useMemo(() => (week40 ? belowRuns(week40.series) : []), [week40]);
  if (!week40) {
    return (
      <div className="space-y-1 rounded-md border border-border p-3" data-testid="week40">
        <div className="text-xs font-semibold">40주 평균선</div>
        <p className="text-xs text-muted-foreground">자료 없음 · 긴 일봉을 받으면 그림을 보여 드립니다.</p>
      </div>
    );
  }
  const first = week40.series[0]?.w;
  return (
    <div className="space-y-2 rounded-md border border-border p-3" data-testid="week40">
      <div className="text-[11px] text-muted-foreground">{WEEK40_FIRST_LINE}</div>
      <div className="text-xs font-semibold tabular-nums">{week40FactText(week40)}</div>
      {week40.series.length === 0 ? (
        <p className="text-xs text-muted-foreground">그릴 주 자료가 없습니다.</p>
      ) : (
        <div className="h-[180px] w-full sm:h-[220px]" role="img" aria-label="최근 5년 주 종가와 40주 평균선">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={week40.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              {runs.map(([a, b]) => (
                <ReferenceArea key={a} x1={a} x2={b} fill="hsl(var(--muted-foreground))" fillOpacity={0.12} ifOverflow="visible" />
              ))}
              <XAxis dataKey="w" tickFormatter={(v: string) => v.slice(2, 7)} interval="preserveStartEnd" minTickGap={40}
                tick={{ fontSize: 11 }} />
              <YAxis domain={["auto", "auto"]} width={58} tick={{ fontSize: 11 }} tickFormatter={(v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
              <Tooltip content={<Tip />} isAnimationActive={false} />
              <Line type="linear" dataKey="c" stroke="hsl(var(--foreground))" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              <Line type="linear" dataKey="m" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-foreground align-middle" />주 종가</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-primary align-middle" />40주 평균선</span>
        <span><span className="mr-1 inline-block h-3 w-4 bg-muted-foreground/20 align-middle" />선 아래 주</span>
        {first && <span className="tabular-nums">{first.slice(0, 7)} ~ {week40.as_of_week.slice(0, 7)}</span>}
      </div>
      {week40.check && <p className="text-[11px] tabular-nums">{week40CheckText(week40.check)}</p>}
      <p className="text-[11px] text-muted-foreground">{WEEK40_LIMIT_LINE}</p>
      <p className="text-[11px] text-muted-foreground">{WEEK40_BASIS_LINE}</p>
    </div>
  );
}
