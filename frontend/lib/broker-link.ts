// 1025-06 · 「토스증권에서 열기」 규칙 (docs/plans/site-roadmap/broker-link.md).
// 사이트는 주문을 넣지 않는다. 종목 → 토스증권 웹 주문 화면으로 새 탭 이동만. 권유 문구 없음.
// 국내는 코드로 바로 · 미국은 서버가 확인한 토스 코드만 (`/api/v1/broker-links`).

export const TOSS_HOME = "https://www.tossinvest.com/";
export const TOSS_ACCOUNT = "https://www.tossinvest.com/account";
export const BROKER_LABEL = "토스증권에서 열기 ↗";
export const SEARCH_LABEL = "토스증권 검색에서 찾기 ↗";

export interface BrokerLinkInfo {
  symbol: string;
  kind: "order" | "search";
  url: string;
  verified: boolean;
}

/** 국내 6자리 (숫자 1개 이상 · 영문 섞인 ETF 코드 포함 예: 0101N0). */
export function isKrCode(sym: string): boolean {
  return /^(?=.*\d)[0-9A-Z]{6}$/.test(sym);
}

export function krOrderUrl(code: string): string {
  return `${TOSS_HOME}stocks/A${code}/order`;
}

export function uniqueSymbols(raw: (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const r of raw) {
    const s = (r ?? "").trim().toUpperCase();
    if (s && !out.includes(s)) out.push(s);
  }
  return out;
}

export const LINKS_PER_REQUEST = 50; // 서버 /api/v1/broker-links 상한과 같게

/** 서버에 물을 미국 종목 묶음 · 정렬해서 (화면 정렬이 바뀌어도 같은 조회) 50개씩 (뒤쪽이 빠지지 않게). */
export function usSymbolChunks(raw: (string | null | undefined)[]): string[][] {
  const us = uniqueSymbols(raw).filter((s) => !isKrCode(s)).sort();
  const out: string[][] = [];
  for (let i = 0; i < us.length; i += LINKS_PER_REQUEST) out.push(us.slice(i, i + LINKS_PER_REQUEST));
  return out;
}
