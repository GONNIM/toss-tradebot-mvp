"use client";

// 1110-02 · 평균선 그림 부품 (계좌 카드 · VIP 탭 공용). 단추 두 개:
//  「일봉 1년 · 20·50·200일」(기본) / 「주봉 5년 · 40주」(Week40Chart).
// 사실로 보이는 것만 — 선 상태를 문장으로 말하지 않는다. 선은 범례와 선 끝 글자로 구별(색만 쓰지 않음).
// 색: 종가 검정 · 20일 호박 · 50일 보라 · 200일 틸 (상승 빨강 · 하락 파랑과 겹치지 않음). 숫자는 tabular-nums.

import { useState } from "react";
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Week40Chart } from "@/components/account/Week40Chart";
import {
  Chart,
  DAILY_BASIS_LINE,
  DailyPoint,
  MA_LINES,
  WEEK40_FIRST_LINE,
  WEEK40_LIMIT_LINE,
  dailySourceText,
  dailyTipText,
} from "@/lib/holdings-swing";

type View = "daily" | "week";

const LINE_COLOR = { m20: "#b45309", m50: "#7c3aed", m200: "hsl(var(--primary))" } as const;

function Tip({ active, payload }: { active?: boolean; payload?: { payload: DailyPoint }[] }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-background p-2 text-xs tabular-nums shadow-none">
      {dailyTipText(payload[0].payload).map((l) => (
        <div key={l}>{l}</div>
      ))}
    </div>
  );
}

function DailyChart({ chart }: { chart: Chart }) {
  const data = chart.daily;
  const last = data.length - 1;
  const endLabel = (text: string, color: string) =>
    // 선 끝 글자: 마지막 점 오른쪽에 선 이름을 쓴다
    function EndLabel(p: { x?: number; y?: number; index?: number; value?: number | null }) {
      if (p.index !== last || p.value === null || p.value === undefined || p.x === undefined || p.y === undefined) return <g />;
      return (
        <text x={p.x + 4} y={p.y} dy={4} fontSize={10} fill={color}>
          {text}
        </text>
      );
    };
  return (
    <div className="space-y-2" data-testid="daily-chart">
      <div className="text-[11px] text-muted-foreground">{WEEK40_FIRST_LINE}</div>
      <div className="h-[200px] w-full sm:h-[240px]" role="img" aria-label="최근 1년 일봉 종가와 20일 50일 200일 평균선">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 38, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis dataKey="d" tickFormatter={(v: string) => v.slice(2, 7)} interval="preserveStartEnd" minTickGap={40}
              tick={{ fontSize: 11 }} />
            <YAxis domain={["auto", "auto"]} width={58} tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
            <Tooltip content={<Tip />} isAnimationActive={false} />
            <Line type="linear" dataKey="c" stroke="hsl(var(--foreground))" strokeWidth={1.25} dot={false}
              isAnimationActive={false} label={endLabel("종가", "hsl(var(--foreground))")} />
            {MA_LINES.map((l) => (
              <Line key={l.key} type="linear" dataKey={l.key} stroke={LINE_COLOR[l.key]} strokeWidth={l.width}
                strokeDasharray={l.dash} dot={false} connectNulls={false} isAnimationActive={false}
                label={endLabel(l.key.slice(1) + "일", LINE_COLOR[l.key])} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-foreground align-middle" />종가</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: LINE_COLOR.m20 }} />20일 평균선</span>
        <span>
          <span className="mr-1 inline-block h-0 w-4 border-t-2 border-dashed align-middle" style={{ borderColor: LINE_COLOR.m50 }} />
          50일 평균선
        </span>
        <span><span className="mr-1 inline-block h-1 w-4 align-middle" style={{ background: LINE_COLOR.m200 }} />200일 평균선(≈40주)</span>
      </div>
      {chart.daily_note && <p className="text-[11px] text-muted-foreground">200일선: {chart.daily_note} (긴 일봉이 200개 미만)</p>}
      <p className="text-[11px] text-muted-foreground tabular-nums">{dailySourceText(chart)}</p>
      <p className="text-[11px] text-muted-foreground">{WEEK40_LIMIT_LINE}</p>
      <p className="text-[11px] text-muted-foreground">{DAILY_BASIS_LINE}</p>
    </div>
  );
}

export function MaChart({ chart }: { chart: Chart | null }) {
  const [view, setView] = useState<View>("daily");
  if (!chart || chart.daily.length === 0) {
    return (
      <div className="space-y-1 rounded-md border border-border p-3" data-testid="ma-chart-empty">
        <div className="text-xs font-semibold">평균선 그림</div>
        <p className="text-xs text-muted-foreground">자료 없음 · 긴 일봉을 받으면 그림을 보여 드립니다.</p>
      </div>
    );
  }
  const options: { v: View; label: string }[] = [
    { v: "daily", label: "일봉 1년 · 20·50·200일" },
    { v: "week", label: "주봉 5년 · 40주" },
  ];
  return (
    <div className="space-y-2" data-testid="ma-chart">
      <div role="group" aria-label="그림 종류" className="inline-flex overflow-hidden rounded-lg border border-border">
        {options.map((o) => (
          <button
            key={o.v}
            type="button"
            aria-pressed={view === o.v}
            onClick={() => setView(o.v)}
            className={`min-h-[44px] border-r border-border px-3 text-xs last:border-r-0 sm:text-sm ${
              view === o.v ? "bg-slate-800 font-semibold text-white" : "bg-background hover:bg-muted"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {view === "daily" ? (
        <div className="rounded-md border border-border p-3">
          <DailyChart chart={chart} />
        </div>
      ) : (
        <Week40Chart week40={chart.week40} />
      )}
    </div>
  );
}
