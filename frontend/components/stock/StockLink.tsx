// 1022-10 3단계 · 종목 코드 → /stock/코드 (종목 하나 보기). 코드 모양이 아니면 글자만 보인다.
import Link from "next/link";
import type { ReactNode } from "react";

const TICKER_RE = /^[A-Z0-9.\-]{1,12}$/;

export function normalizeTicker(t: string | null | undefined): string | null {
  const u = (t ?? "").trim().toUpperCase();
  return TICKER_RE.test(u) ? u : null;
}

export function StockLink({
  ticker,
  children,
  className = "",
}: {
  ticker: string;
  children?: ReactNode;
  className?: string;
}) {
  const t = normalizeTicker(ticker);
  const label = children ?? ticker;
  if (!t) return <>{label}</>;
  return (
    <Link
      href={`/stock/${encodeURIComponent(t)}`}
      onClick={(e) => e.stopPropagation()}
      className={`underline-offset-2 hover:underline ${className}`}
      title={`${t} 종목 하나 보기`}
    >
      {label}
    </Link>
  );
}
