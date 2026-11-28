"use client";

// 1128-01 · 거래량 막대 (가격 그림 아래 작은 그림 · 같은 날짜 칸).
// 올라간 날(주)은 빨강 · 내려간 날은 파랑 (한국식 · 전날 종가 대비) · 첫 점·같은 값은 회색. 막대 위에 숫자는 쓰지 않고 마우스 올림에서만 보인다.
// 거래량이 없는 날(null)은 막대를 그리지 않는다. 가격 그림과 가로 칸이 맞도록 왼쪽 축 너비(58)와 오른쪽 여백을 같게 쓴다.
// 기본은 꺼짐 — 계획 · 계좌 · VIP 화면의 MaChart 는 showVolume 을 넘기지 않는다 (Fable 막음 ㄴ).
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { VolBar, volColor, volumeKo } from "@/lib/stock-display";

function Tip({ active, payload, unit }: { active?: boolean; payload?: { payload: VolBar }[]; unit: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-border bg-background p-2 text-xs tabular-nums shadow-none">
      <div>{p.x.slice(0, 10)}</div>
      <div>{unit} 거래량 {volumeKo(p.v)}</div>
    </div>
  );
}

export function VolumeBars({ bars, rightMargin, unit }: { bars: VolBar[]; rightMargin: number; unit: "일" | "주" }) {
  return (
    <div className="space-y-1" data-testid="volume-bars">
      <div className="h-[64px] w-full" role="img" aria-label={`${unit}별 거래량 · 오른 ${unit} 빨강 · 내린 ${unit} 파랑`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} margin={{ top: 2, right: rightMargin, bottom: 0, left: 0 }} barCategoryGap={0}>
            <XAxis dataKey="x" hide />
            <YAxis width={58} tick={false} axisLine={false} tickLine={false} domain={[0, "auto"]} />
            <Tooltip content={<Tip unit={unit} />} isAnimationActive={false} cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }} />
            <Bar dataKey="v" isAnimationActive={false} minPointSize={0}>
              {bars.map((b) => (
                <Cell key={b.x} fill={volColor(b.up)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span>거래량 ({unit}별)</span>
        <span><span className="mr-1 inline-block h-2 w-3 align-middle" style={{ background: volColor(true) }} />전{unit === "일" ? "날" : "주"}보다 오른 {unit}</span>
        <span><span className="mr-1 inline-block h-2 w-3 align-middle" style={{ background: volColor(false) }} />내린 {unit}</span>
      </div>
    </div>
  );
}
