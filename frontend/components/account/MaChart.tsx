"use client";

// 1110-02 · 평균선 그림 부품 (계좌 카드 · VIP 탭 공용). 단추 두 개:
//  「일봉 1년 · 20·50·200일」(기본) / 「주봉 5년 · 40주」(Week40Chart).
// 사실로 보이는 것만 — 선 상태를 문장으로 말하지 않는다. 선은 범례와 선 끝 글자로 구별(색만 쓰지 않음).
// 색: 종가 검정 · 20일 호박 · 50일 보라 · 200일 틸 (상승 빨강 · 하락 파랑과 겹치지 않음). 숫자는 tabular-nums.

import { useMemo, useState } from "react";
import { CartesianGrid, ComposedChart, Customized, Line, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CrossList, crossShape } from "@/components/account/CrossMarks";
import { Week40Chart } from "@/components/account/Week40Chart";
import {
  Chart,
  CrossPoint,
  DAILY_BASIS_LINE,
  DailyPoint,
  MA_LINES,
  WEEK40_FIRST_LINE,
  WEEK40_LIMIT_LINE,
  crossDirText,
  crossPoints,
  dailySourceText,
  dailyTipText,
  monthTicks,
  spreadLabels,
} from "@/lib/holdings-swing";

type View = "daily" | "week";
type MaKey = "m20" | "m50" | "m200";
const MARK_LINES: { key: MaKey; label: string }[] = [
  { key: "m20", label: "20일선" },
  { key: "m50", label: "50일선" },
  { key: "m200", label: "200일선" },
];

const LINE_COLOR = { m20: "#b45309", m50: "#7c3aed", m200: "hsl(var(--primary))" } as const;

function Tip({ active, payload, marks, line }: {
  active?: boolean; payload?: { payload: DailyPoint }[]; marks?: Map<string, CrossPoint>; line?: string;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const mark = marks?.get(p.d);
  const lines = mark && line ? [crossDirText(line, mark.dir), ...dailyTipText(p)] : dailyTipText(p);
  return (
    <div className="rounded-md border border-border bg-background p-2 text-xs tabular-nums shadow-none">
      {lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </div>
  );
}

type AxisProps = {
  yAxisMap?: Record<string, { scale: (v: number) => number }>;
  offset?: { left: number; width: number };
};

function DailyChart({ chart, basisLine }: { chart: Chart; basisLine: string }) {
  const data = chart.daily;
  // 넘은 지점은 고른 선 하나만 (기본 200일 · 지점이 가장 적음). 선 값이 없는 날은 건너뜀.
  const [markKey, setMarkKey] = useState<MaKey>("m200");
  const markLine = MARK_LINES.find((l) => l.key === markKey)!.label;
  const marks = useMemo(() => crossPoints(data.map((p) => ({ date: p.d, c: p.c, m: p[markKey] }))), [data, markKey]);
  const markMap = useMemo(() => new Map(marks.map((m) => [m.date, m])), [marks]);
  const lastPt = data[data.length - 1];
  // 선 끝 글자: 마지막 점 오른쪽에 선 이름을 쓴다. 값이 가까워 글자가 겹치면 12px 간격으로 벌린다.
  const ends: { text: string; color: string; value: number | null }[] = [
    { text: "종가", color: "hsl(var(--foreground))", value: lastPt?.c ?? null },
    ...MA_LINES.map((l) => ({ text: l.key.slice(1) + "일", color: LINE_COLOR[l.key], value: lastPt?.[l.key] ?? null })),
  ];
  function EndLabels(props: AxisProps) {
    const y = props.yAxisMap ? Object.values(props.yAxisMap)[0] : undefined;
    if (!y || !props.offset) return <g />;
    const x = props.offset.left + props.offset.width + 4;
    const shown = ends.filter((e): e is { text: string; color: string; value: number } => e.value !== null);
    const ys = spreadLabels(shown.map((e) => y.scale(e.value)), 12);
    return (
      <g data-testid="end-labels">
        {shown.map((e, i) => (
          <text key={e.text} x={x} y={ys[i]} dy={4} fontSize={10} fill={e.color}>
            {e.text}
          </text>
        ))}
      </g>
    );
  }
  return (
    <div className="space-y-2" data-testid="daily-chart">
      <div className="text-[11px] text-muted-foreground">{WEEK40_FIRST_LINE}</div>
      <div role="group" aria-label="넘은 지점을 표시할 선" className="flex flex-wrap items-center gap-1 text-[11px]">
        <span className="text-muted-foreground">표시할 선:</span>
        {MARK_LINES.map((l) => (
          <button
            key={l.key}
            type="button"
            aria-pressed={markKey === l.key}
            onClick={() => setMarkKey(l.key)}
            className={`min-h-[36px] rounded-md border border-border px-2 ${
              markKey === l.key ? "bg-slate-800 font-semibold text-white" : "bg-background hover:bg-muted"
            }`}
          >
            {l.label.replace("선", "")}
          </button>
        ))}
      </div>
      <div className="h-[200px] w-full sm:h-[240px]" role="img" aria-label={`최근 1년 일봉 종가와 20일 50일 200일 평균선 · ${markLine}을 넘은 날 표시`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 38, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis dataKey="d" ticks={monthTicks(data.map((p) => p.d))} tickFormatter={(v: string) => v.slice(2, 7)}
              interval="preserveStartEnd" minTickGap={24}
              tick={{ fontSize: 11 }} />
            <YAxis domain={["auto", "auto"]} width={58} tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
            <Tooltip content={<Tip marks={markMap} line={markLine} />} isAnimationActive={false} />
            <Line type="linear" dataKey="c" stroke="hsl(var(--foreground))" strokeWidth={1.25} dot={false}
              isAnimationActive={false} />
            {MA_LINES.map((l) => (
              <Line key={l.key} type="linear" dataKey={l.key} stroke={LINE_COLOR[l.key]} strokeWidth={l.width}
                strokeDasharray={l.dash} dot={false} connectNulls={false} isAnimationActive={false} />
            ))}
            {marks.map((m) => (
              <ReferenceDot key={m.date} x={m.date} y={m.c} r={0} ifOverflow="visible" shape={crossShape(m.dir)} />
            ))}
            <Customized component={EndLabels} />
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
        <span><span className="text-up">▲</span>/<span className="text-down">▼</span> {markLine}을 넘은 날</span>
      </div>
      <CrossList points={marks} line={markLine} scope="최근 1년" />
      {chart.daily_note && <p className="text-[11px] text-muted-foreground">200일선: {chart.daily_note} (긴 일봉이 200개 미만)</p>}
      <p className="text-[11px] text-muted-foreground tabular-nums">{dailySourceText(chart)}</p>
      <p className="text-[11px] text-muted-foreground">{WEEK40_LIMIT_LINE}</p>
      <p className="text-[11px] text-muted-foreground">{basisLine}</p>
    </div>
  );
}

// 1111-01 · initialView 로 처음 보일 그림을 고른다 (바이오 칸은 주봉 5년·40주가 기본 · 계좌 카드·VIP 는 그대로 일봉)
// 1112-01 · basisLine: 그림 아래 출처 설명 줄 (계좌 카드·VIP 는 기본값 그대로 · 바이오 칸은 「카드 글자 줄」이 없어 따로 줌)
export function MaChart({ chart, initialView = "daily", basisLine = DAILY_BASIS_LINE }: {
  chart: Chart | null; initialView?: View; basisLine?: string;
}) {
  const [view, setView] = useState<View>(initialView);
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
          <DailyChart chart={chart} basisLine={basisLine} />
        </div>
      ) : (
        <Week40Chart week40={chart.week40} />
      )}
    </div>
  );
}
