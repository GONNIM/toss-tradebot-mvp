// WP72-2b · 표1 (소문에 살 자리) 카드 · activist-radar EventRow 톤 정합
"use client";

type Props = {
  ticker: string;
  name: string;
  mcap_bucket: string;
  days_hint: string;   // D-N or 매수일
  detail: string;      // 한 줄 이유
  score?: number;      // 있으면 우측 표기
};

export function RumorCard({ ticker, name, mcap_bucket, days_hint, detail, score }: Props) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="rounded bg-sky-600 px-2 py-0.5 font-mono text-xs font-bold text-white">
          {ticker}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {mcap_bucket}
        </span>
        <span className="rounded bg-amber-500 px-2 py-0.5 font-mono text-[10px] font-bold text-slate-900">
          {days_hint}
        </span>
        {typeof score === "number" && (
          <span className="ml-auto rounded bg-slate-100 px-2 py-0.5 text-xs font-mono font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            score {score.toFixed(3)}
          </span>
        )}
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">{name}</div>
      <div className="mt-1.5 text-xs text-slate-700 dark:text-slate-200">{detail}</div>
    </div>
  );
}
