// WP72-2b · 표1 (소문에 살 자리) 카드 · activist-radar EventRow 톤 정합
// WP74 2단계 · 문장형 본문 (sentence) · NCT 번호는 원문 링크로 숨김 · 문장에 일수가 있으면 D-day 배지 생략
"use client";

type Props = {
  ticker: string;
  name: string;
  mcap_bucket: string; // 빈 값이면 배지 미표시
  days_hint: string;   // D-N or 매수일
  detail: string;      // 한 줄 이유 (sentence 없을 때 원문)
  score?: number;      // 있으면 우측 표기
  sentence?: string | null; // 쉬운 말 본문
  sourceUrl?: string | null; // ClinicalTrials.gov 원문
  order?: number;            // WP74 3단계 · 목록 안 순서 (정렬이 눈에 보이게)
};

export function RumorCard({ ticker, name, mcap_bucket, days_hint, detail, score, sentence, sourceUrl, order }: Props) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
      <div className="flex items-baseline gap-2 flex-wrap">
        {typeof order === "number" && (
          <span className="w-6 text-right font-mono text-xs text-muted-foreground">{order}</span>
        )}
        <span className="rounded bg-sky-600 px-2 py-0.5 font-mono text-xs font-bold text-white">
          {ticker}
        </span>
        {mcap_bucket && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {mcap_bucket}
          </span>
        )}
        {!sentence && (
          <span className="rounded bg-amber-500 px-2 py-0.5 font-mono text-[10px] font-bold text-slate-900">
            {days_hint}
          </span>
        )}
        {typeof score === "number" && (
          <span className="ml-auto rounded bg-slate-100 px-2 py-0.5 text-xs font-mono font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            score {score.toFixed(3)}
          </span>
        )}
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">{name}</div>
      <div className="mt-1.5 text-sm text-slate-700 dark:text-slate-200">
        {sentence ?? detail}
        {sentence && sourceUrl && (
          <>
            {" "}
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-xs text-sky-700 hover:underline dark:text-sky-300"
            >
              임상 원문 보기 ↗
            </a>
          </>
        )}
      </div>
    </div>
  );
}
