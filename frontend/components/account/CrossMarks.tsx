"use client";

// 1110-03 · 평균선 넘은 지점 — 그림 위 ▲▼ 표시와 그림 아래 「최근 지점」 목록 (주봉 · 일봉 공용).
// 지난 사실만 보인다. 방향은 모양(▲▼)과 글자로 쓰고 색은 보조(상승 빨강 · 하락 파랑).

import { CROSS_NOTE, CrossPoint, crossRowText, recentCrosses } from "@/lib/holdings-swing";

const MARK_COLOR = { up: "hsl(var(--up))", down: "hsl(var(--down))" } as const;

/** recharts ReferenceDot shape — ▲ 는 종가 아래, ▼ 는 종가 위에 그린다. 바깥 테두리는 바탕색. */
export function crossShape(dir: CrossPoint["dir"]) {
  function Shape(props: { cx?: number; cy?: number }) {
    const { cx, cy } = props;
    if (cx === undefined || cy === undefined) return <g />;
    const s = 6;
    const pts =
      dir === "up"
        ? `${cx},${cy + 3} ${cx - s},${cy + 3 + s * 1.6} ${cx + s},${cy + 3 + s * 1.6}`
        : `${cx},${cy - 3} ${cx - s},${cy - 3 - s * 1.6} ${cx + s},${cy - 3 - s * 1.6}`;
    return (
      <polygon points={pts} fill={MARK_COLOR[dir]} stroke="hsl(var(--background))" strokeWidth={1.5} data-testid={`cross-${dir}`} />
    );
  }
  return Shape;
}

/** 그림 아래 목록 — 최근 지점 5개(최근 것 먼저) · 이 그림 안 전체 개수 · 사실 표시 한 줄. */
export function CrossList({ points, line, scope }: { points: CrossPoint[]; line: string; scope: string }) {
  const rows = recentCrosses(points);
  return (
    <div className="space-y-1" data-testid="cross-list">
      <div className="flex flex-wrap items-baseline gap-x-2 text-[11px]">
        <span className="font-semibold">{line} 넘은 지점</span>
        <span className="text-muted-foreground tabular-nums">
          {scope} 안 {points.length}번 · ▲ 위로 올라섬 · ▼ 아래로 내려감
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">이 그림 안에는 넘은 지점이 없습니다.</p>
      ) : (
        <ul className="space-y-0.5">
          {rows.map((p) => {
            const t = crossRowText(p, line);
            return (
              <li key={p.date} className="flex flex-wrap gap-x-2 text-[11px] tabular-nums">
                <span>{t.date}</span>
                <span className={p.dir === "up" ? "text-up" : "text-down"}>{t.dir}</span>
                <span>{t.close}</span>
                <span className="text-muted-foreground">{t.line}</span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-[11px] text-muted-foreground">{CROSS_NOTE}</p>
    </div>
  );
}
