// 1025-05 · /journal 판정 결과 문구 — 실현값 (토스 일봉 종가) · 기준가 출처를 숨기지 않는다.

export function outcomeText(result: number | null, horizonDays: number): string {
  if (result === null) return `결과 계산 대기 (T+${horizonDays}일 뒤 · 매일 08:10)`;
  const pct = result * 100;
  return `결과 (T+${horizonDays}일): ${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

// 1026-02 · 대체된 판정 · 청산 행은 자동 계산하지 않는다 (backend/services/outcomes.py _judgment_due).
export function notScoredText(superseded: boolean, pageSource: string): string {
  if (superseded) return "자동 계산 대상 아님 (새 판정으로 대체됨)";
  if (pageSource === "close") return "자동 계산 대상 아님 (청산 기록)";
  return "";
}

export function baseNote(price: number | null | undefined, source: string | null | undefined): string {
  if (price === null || price === undefined || !source) return "";
  const what = source === "entry" ? "적은 진입가" : "판정 시점 종가";
  return `기준가: ${what} ${price.toLocaleString("ko-KR", { maximumFractionDigits: 4 })} · 토스 일봉 종가 기준`;
}
