"use client";

// 1114-04 · 1114-05 · 표 아래 접힌 두 목록 · 「순위에서 뺀 종목 (상장폐지)」 · 「합병 진행 중」 (표시 전용 · 사실만)
import { EXCLUDED_TITLE, GOING_CONCERN_NOTE, LISTING_NOTE, MERGING_TITLE, formsText, isSecUrl, mergingLabel } from "@/lib/biotech-display";
import type { ListingRow } from "@/lib/biotech-display";

function Links({ row }: { row: ListingRow }) {
  const links = row.forms.filter((f) => isSecUrl(f.url));
  if (links.length === 0) return <span className="text-muted-foreground">원문 주소 없음</span>;
  return (
    <span className="flex flex-wrap gap-x-2">
      {links.map((f) => (
        <a key={f.url} href={f.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
          {f.form} 원문 ↗
        </a>
      ))}
    </span>
  );
}

function Block({ title, rows, kind }: { title: string; rows: ListingRow[]; kind: "excluded" | "merging" }) {
  if (rows.length === 0) return null;
  return (
    <details className="rounded-lg border border-border bg-card px-3 py-2 text-xs">
      <summary className="cursor-pointer font-semibold">
        {title} · {rows.length}종목
      </summary>
      <ul className="mt-2 space-y-2">
        {rows.map((r) => (
          <li key={`${r.ticker}-${r.status}-${r.name}`} className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0 last:pb-0">
            <div>
              <span className="font-mono font-semibold">{r.ticker || "코드 없음"}</span>
              <span className="ml-2 text-muted-foreground">{r.name}</span>
            </div>
            <div className="text-muted-foreground">
              {kind === "excluded" ? r.reason : mergingLabel(r.status)}
              {r.forms.length > 0 && <> · {formsText(r.forms)}</>}
              {r.status_date && <> · 기준일 {r.status_date}</>}
            </div>
            <Links row={r} />
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ExcludedList({ excluded, merging }: { excluded: ListingRow[]; merging: ListingRow[] }) {
  return (
    <div className="mt-3 space-y-2">
      <Block title={EXCLUDED_TITLE} rows={excluded} kind="excluded" />
      <Block title={MERGING_TITLE} rows={merging} kind="merging" />
      <p className="text-xs text-muted-foreground">{LISTING_NOTE}</p>
      <p className="text-xs text-muted-foreground">{GOING_CONCERN_NOTE}</p>
    </div>
  );
}
