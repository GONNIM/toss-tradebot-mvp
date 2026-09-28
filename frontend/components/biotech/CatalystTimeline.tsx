// WP74 5단계 · 오늘~90일 가로 타임라인 (점 = 종목 · 위치 = 임상 완료 예정일)
// dataviz 규칙: 단일 계열 (범례 없음 · 제목이 설명) · 점 ≥8px + 2px 표면색 테두리 · 히트 영역 > 점
// · 호버와 키보드 포커스에 같은 툴팁 (양 끝 20% 안쪽 정렬 · 잘림 방지) · 축/격자 약하게 · 색 검증 (validate_palette: light #0284c7 · dark #0c95d6 PASS)
// 표 대체 = 바로 아래 카드 목록 (툴팁 정보는 카드에도 모두 있음)
"use client";

import { useState } from "react";
import { phaseLabel } from "@/lib/biotech-display";

export type TimelineItem = { ticker: string; days_to?: number | null; event_date?: string; phase?: string };

const HORIZON = 90;           // 오늘부터 90일
const LANE_H = 20;            // 겹치는 점을 쌓는 줄 높이 (px)
const MIN_GAP_PCT = 2.2;      // 이 간격보다 가까우면 다른 줄에 배치

function laneLayout(items: TimelineItem[]): { item: TimelineItem; pct: number; lane: number }[] {
  const pts = items
    .filter((r) => typeof r.days_to === "number" && r.days_to >= 0 && r.days_to <= HORIZON)
    .map((r) => ({ item: r, pct: ((r.days_to as number) / HORIZON) * 100 }))
    .sort((a, b) => a.pct - b.pct);
  const laneEnd: number[] = [];
  return pts.map((p) => {
    let lane = laneEnd.findIndex((end) => p.pct - end >= MIN_GAP_PCT);
    if (lane === -1) {
      lane = laneEnd.length;
      laneEnd.push(p.pct);
    } else {
      laneEnd[lane] = p.pct;
    }
    return { ...p, lane };
  });
}

function dateAfter(days: number): string {
  const d = new Date(Date.now() + days * 86_400_000);
  const f = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" }).formatToParts(d);
  const g = (t: string) => f.find((x) => x.type === t)?.value ?? "";
  return `${g("month")}/${g("day")}`;
}

export function CatalystTimeline({ items, onSelect }: { items: TimelineItem[]; onSelect: (ticker: string) => void }) {
  const [tip, setTip] = useState<string | null>(null);
  const pts = laneLayout(items);
  const lanes = Math.max(1, ...pts.map((p) => p.lane + 1));
  const outside = items.length - pts.length;
  const ticks = [0, 30, 60, 90];

  return (
    <figure className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
      <figcaption className="mb-2 text-xs text-muted-foreground">
        앞으로 90일 안에 임상이 끝날 예정인 종목 {pts.length}개입니다. 점을 누르면 해당 카드로 이동합니다.
        {outside > 0 && ` (90일 밖 ${outside}개는 목록에만 있습니다.)`}
      </figcaption>
      <div className="relative mx-3" style={{ height: lanes * LANE_H + 28 }}>
        {/* 격자·축 (약하게) */}
        {ticks.map((t) => (
          <div key={t} className="absolute top-0 bottom-5 border-l border-slate-200 dark:border-slate-700" style={{ left: `${(t / HORIZON) * 100}%` }}>
            <span className="absolute -bottom-5 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground">
              {t === 0 ? "오늘" : `${t}일 (${dateAfter(t)})`}
            </span>
          </div>
        ))}
        {pts.map(({ item, pct, lane }) => {
          const label = `${item.ticker} · ${phaseLabel(item.phase)} · ${item.event_date ?? ""} (${item.days_to}일 뒤)`;
          const top = lane * LANE_H;
          return (
            <button
              key={item.ticker}
              type="button"
              aria-label={`${label} · 카드로 이동`}
              onClick={() => onSelect(item.ticker)}
              onMouseEnter={() => setTip(item.ticker)}
              onMouseLeave={() => setTip((t) => (t === item.ticker ? null : t))}
              onFocus={() => setTip(item.ticker)}
              onBlur={() => setTip((t) => (t === item.ticker ? null : t))}
              className="group absolute flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              style={{ left: `${pct}%`, top }}
            >
              <span className="block h-2.5 w-2.5 rounded-full bg-sky-600 ring-2 ring-white group-hover:scale-125 dark:bg-[#0c95d6] dark:ring-slate-900" />
              {tip === item.ticker && (
                <span
                  role="tooltip"
                  className={`pointer-events-none absolute bottom-full z-10 mb-1 whitespace-nowrap rounded border border-border bg-background px-2 py-1 text-left text-xs shadow ${
                    pct < 20 ? "left-0" : pct > 80 ? "right-0" : "left-1/2 -translate-x-1/2"
                  }`}
                >
                  <strong className="font-mono">{item.ticker}</strong>
                  <span className="text-muted-foreground"> · {phaseLabel(item.phase)} · {item.event_date} ({item.days_to}일 뒤)</span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </figure>
  );
}
