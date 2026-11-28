"use client";

// 1128-01 · 국내 종목 가격 칸 자료 불러오기 (관리자 전용 · 서버가 10분 보관 · 여기서도 60초 보관)
import { useQuery } from "@tanstack/react-query";
import type { KrQuote } from "@/lib/stock-display";

export class KrQuoteError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function useKrQuote(code: string | null, enabled: boolean) {
  return useQuery<KrQuote, KrQuoteError>({
    queryKey: ["stock", "kr-quote", code],
    enabled: enabled && !!code,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const res = await fetch(`/api/v1/stock/${encodeURIComponent(code as string)}/quote`, { credentials: "include", cache: "no-store" });
      if (!res.ok) throw new KrQuoteError(res.status, `status ${res.status}`);
      return (await res.json()) as KrQuote;
    },
  });
}
