"use client";

// 1025-06 · 종목 옆 「토스증권에서 열기 ↗」 — 새 탭으로 토스증권 웹 주문 화면. 사이트는 주문을 넣지 않는다.
// 미국 종목 중 서버가 확인하지 않은 것은 토스증권 첫 화면을 열고 티커를 복사해 둔다 (다른 종목이 열리지 않게).

import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { BROKER_LABEL, BrokerLinkInfo, SEARCH_LABEL, TOSS_HOME, isKrCode, krOrderUrl, usSymbolChunks } from "@/lib/broker-link";

/** 한 화면의 미국 종목을 50개씩 묶어 묻는다 (국내는 묻지 않음). 다시 묻는 동안 지난 결과를 유지해 글자가 깜빡이지 않게. */
export function useBrokerLinks(symbols: (string | null | undefined)[]): Record<string, BrokerLinkInfo> {
  const chunks = usSymbolChunks(symbols);
  const results = useQueries({
    queries: chunks.map((chunk) => ({
      queryKey: ["broker-links", chunk.join(",")],
      queryFn: () => api.brokerLinks.get(chunk),
      staleTime: 60 * 60 * 1000,
      retry: 1,
      placeholderData: keepPreviousData,
    })),
  });
  const out: Record<string, BrokerLinkInfo> = {};
  for (const r of results) for (const l of r.data?.links ?? []) out[l.symbol] = l;
  return out;
}

export function brokerLinkFor(symbol: string, links: Record<string, BrokerLinkInfo>): BrokerLinkInfo {
  const s = symbol.trim().toUpperCase();
  if (isKrCode(s)) return { symbol: s, kind: "order", url: krOrderUrl(s), verified: true };
  return links[s] ?? { symbol: s, kind: "search", url: TOSS_HOME, verified: false };
}

export function BrokerLink({ symbol, links, className = "" }: { symbol: string; links: Record<string, BrokerLinkInfo>; className?: string }) {
  const l = brokerLinkFor(symbol, links);
  const search = l.kind === "search";
  return (
    <a
      href={l.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => {
        if (search) navigator.clipboard?.writeText(l.symbol).catch(() => undefined);
      }}
      title={search ? `${l.symbol} 를 복사했습니다 · 토스증권 검색창에 붙여 넣으십시오` : `${l.symbol} 토스증권 주문 화면`}
      className={`inline-flex items-center rounded-md border border-border px-2 py-1 text-xs font-medium hover:bg-muted ${className}`}
    >
      {search ? SEARCH_LABEL : BROKER_LABEL}
    </a>
  );
}
