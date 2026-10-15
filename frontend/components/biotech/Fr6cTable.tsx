"use client";

// P4-3 · FR-6c 과거 기록 표 (봉인 설계 fr6c_design_v1.md 4절 · 표시 행만 · 잔여 칸 비표시)
import { FR6C_METRIC, FR6C_MIN_N, FR6C_NOTICE, FR6C_PENDING, FR6C_SURVIVOR, fr6cHeader, fr6cRowText, fr6cRows } from "@/lib/biotech-fr6c";
import type { Fr6cCells } from "@/lib/biotech-fr6c";

export function Fr6cTable({ data }: { data: Fr6cCells | null }) {
  if (!data || !data.ready) {
    return <div className="text-xs text-muted-foreground">{FR6C_PENDING}</div>;
  }
  const rows = fr6cRows(data.cells).map(fr6cRowText);
  return (
    <div className="space-y-2 text-xs">
      <div className="rounded border-l-4 border-slate-400 bg-slate-50 p-2 dark:border-slate-600 dark:bg-slate-900/60">{FR6C_NOTICE}</div>
      <div className="text-muted-foreground">
        지표: {FR6C_METRIC} · {fr6cHeader(data)} · {FR6C_MIN_N}건 미만 칸은 숫자 없이 표본 수만 적습니다.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs">
          <caption className="sr-only">과거 기록 · 칸별 분포</caption>
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="p-1">세밀도</th>
              <th className="p-1">칸</th>
              <th className="p-1 text-right">n</th>
              <th className="p-1 text-right">중앙값</th>
              <th className="p-1 text-right">사분위(25~75)</th>
              <th className="p-1 text-right">최솟값 ~ 최댓값</th>
              <th className="p-1">기간</th>
              <th className="p-1">가격 없음</th>
              <th className="p-1">방향 출처</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.level}-${r.label}`} className="border-b border-border last:border-0">
                <td className="p-1 text-muted-foreground">{r.level}</td>
                <td className="p-1 font-semibold">{r.label}</td>
                <td className="p-1 text-right">{r.n}</td>
                <td className="p-1 text-right font-mono">{r.median}</td>
                <td className="p-1 text-right font-mono">{r.iqr}</td>
                <td className="p-1 text-right font-mono">{r.range}</td>
                <td className="p-1">{r.period}</td>
                <td className="p-1">{r.missing}</td>
                <td className="p-1">{r.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-muted-foreground">{FR6C_SURVIVOR}</div>
    </div>
  );
}
