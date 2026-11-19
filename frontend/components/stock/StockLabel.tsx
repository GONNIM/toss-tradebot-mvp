// 1119-02 · 종목 표시 한 곳. 한국은 `이름(코드)` 한 줄, 미국은 티커(굵게) 아래 줄에 회사명(작게).
// 이름을 모르면 한국은 `코드 (종목명 확인 안 됨)`, 미국은 티커만. 링크가 있던 곳은 StockLink 를 그대로 쓴다.
import type { ReactNode } from "react";

import { isKrCode } from "@/lib/broker-link";

import { StockLink } from "./StockLink";

export type StockLabelLayout = "inline" | "stacked";

/** 표시용 글 만들기 (화면 밖 글 · 시험 · 제목에 쓰기 위함). 이름이 빈칸이거나 코드와 같으면 이름 없음. */
export function stockLabelText(code: string, name?: string | null, market?: "KR" | "US" | null): string {
  const n = cleanName(code, name);
  const kr = market ? market === "KR" : isKrCode(code);
  if (kr) return n ? `${n}(${code})` : `${code} (종목명 확인 안 됨)`;
  return n ? `${code} · ${n}` : code;
}

function cleanName(code: string, name?: string | null): string | null {
  const n = (name ?? "").trim();
  return n && n !== code ? n : null;
}

export function StockLabel({
  code,
  name,
  market,
  link = true,
  layout = "stacked",
  className = "",
  nameClassName = "",
}: {
  code: string;
  name?: string | null;
  market?: "KR" | "US" | null;
  link?: boolean;
  /** stacked: 미국은 티커 아래 줄에 회사명 · inline: 미국도 `티커 · 회사명` 한 줄 (좁은 문장 · 선택 칸). 한국은 늘 한 줄. */
  layout?: StockLabelLayout;
  className?: string;
  nameClassName?: string;
}) {
  const n = cleanName(code, name);
  const kr = market ? market === "KR" : isKrCode(code);
  const wrap = (node: ReactNode) => (link ? <StockLink ticker={code} className={className}>{node}</StockLink> : <span className={className}>{node}</span>);

  if (kr) {
    return n ? (
      <span data-testid="stock-label" data-market="KR">
        {wrap(<>{n}<span className="whitespace-nowrap">({code})</span></>)}
      </span>
    ) : (
      <span data-testid="stock-label" data-market="KR">
        {wrap(<span className="tabular-nums">{code}</span>)}
        <span className="text-muted-foreground"> (종목명 확인 안 됨)</span>
      </span>
    );
  }
  if (!n) return <span data-testid="stock-label" data-market="US">{wrap(code)}</span>;
  if (layout === "inline") {
    return (
      <span data-testid="stock-label" data-market="US">
        {wrap(code)}
        <span className={`text-muted-foreground ${nameClassName}`}> · {n}</span>
      </span>
    );
  }
  return (
    <span data-testid="stock-label" data-market="US" className="inline-flex min-w-0 max-w-full flex-col align-top leading-tight">
      <span className="font-bold">{wrap(code)}</span>
      <span className={`block max-w-[16rem] truncate text-xs font-normal text-muted-foreground ${nameClassName}`} title={n}>{n}</span>
    </span>
  );
}
