"use client";

// 1025-06 · 종목 옆 「토스증권에서 열기 ↗」 — 새 탭으로 토스증권 웹 주문 화면. 사이트는 주문을 넣지 않는다.
// 미국 종목 중 서버가 확인하지 않은 것은 토스증권 첫 화면을 열고 티커를 복사해 둔다 (다른 종목이 열리지 않게).

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { BROKER_LABEL, BrokerLinkInfo, SEARCH_LABEL, TOSS_HOME, isKrCode, krOrderUrl, uniqueSymbols } from "@/lib/broker-link";

/** 한 화면의 종목들을 한 번에 묻는다 (국내는 묻지 않음 · 최대 50 씩). */
export function useBrokerLinks(symbols: (string | null | undefined)[]): Record<string, BrokerLinkInfo> {
  const us = uniqueSymbols(symbols).filter((s) => !isKrCode(s)).slice(0, 50);
  const q = useQuery({
    queryKey: ["broker-links", us.join(",")],
    queryFn: () => api.brokerLinks.get(us),
    enabled: us.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
  const out: Record<string, BrokerLinkInfo> = {};
  for (const l of q.data?.links ?? []) out[l.symbol] = l;
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
