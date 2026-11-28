// 1022-10 3단계 · 종목 코드 → /stock/코드 (종목 하나 보기). 코드 모양이 아니면 글자만 보인다.
// 1128-01 · 밑줄 없음 — 글자색(강조 틸) + 보통 굵기(medium) + 마우스를 올리면 옅어짐으로 링크임을 알린다.
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
      className={`font-medium text-primary transition-colors hover:text-primary/70 ${className}`}
      title={`${t} 종목 하나 보기`}
    >
      {label}
    </Link>
  );
}
