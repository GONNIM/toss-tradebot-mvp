// BiotechTable · WP71-2 · activist-radar 표 클래스 정합 · 단일 컴포넌트
// 계약: 열 ≤ 7 · 숫자 우측 font-mono · 표 안 이모지·bold 금지 · 빈 표 = 빈 상태
"use client";

import { ReactNode } from "react";

export type BiotechTableColumn<Row> = {
  key: string;
  label: string;
  align?: "left" | "right";
  render?: (row: Row) => ReactNode;
};

type Props<Row> = {
  columns: BiotechTableColumn<Row>[];
  rows: Row[];
  emptyLabel?: string;
  caption?: string;
};

export function BiotechTable<Row extends Record<string, unknown>>({
  columns,
  rows,
  emptyLabel = "표시할 행이 없습니다.",
  caption,
}: Props<Row>) {
  if (columns.length > 7) {
    // 계약 · 열 ≤ 7 (개발자 실수 방지 · 콘솔 경고)
    // eslint-disable-next-line no-console
    console.warn("BiotechTable: 열 수가 7을 초과합니다.", columns.length);
  }

  if (rows.length === 0) {
    return (
      <div className="rounded border border-border bg-card p-4 text-sm text-muted-foreground">
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-border">
      {caption && (
        <div className="border-b border-border bg-muted/50 px-3 py-2 text-xs font-semibold text-muted-foreground">
          {caption}
        </div>
      )}
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="bg-slate-50 dark:bg-slate-900">
            {columns.map((c) => (
              <th
                key={c.key}
                className={
                  "border-b border-border p-2 font-semibold" +
                  (c.align === "right" ? " text-right" : " text-left")
                }
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-muted/30">
              {columns.map((c) => {
                const raw = row[c.key];
                const content = c.render ? c.render(row) : (raw as ReactNode);
                return (
                  <td
                    key={c.key}
                    className={
                      "p-2" +
                      (c.align === "right" ? " text-right font-mono" : "")
                    }
                  >
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
