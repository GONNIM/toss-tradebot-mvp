// 1128-01 · 종목 화면의 「하는 일」 칸. 지금은 증권사 이동 링크(㉡ 주문 화면 그대로)만 있다.
//
// 앞으로 「계획으로 옮기기」를 여기에 붙인다 (사용자 결정 11/28 ㉠ · 지금은 만들지 않음 · 보이는 단추 없음):
//  - planHints 는 서버(/api/v1/stock/{code}/quote 의 plan_hints)가 준 표시용 값이다: 마지막 종가 · 40주 평균선 · 52주 낮음/높음.
//    미리 채워 보여 주기만 하고, 이 값으로 계획을 만들거나 바꾸지 않는다.
//  - onMoveToPlan 을 넘기는 날 단추가 켜진다. 계획 만들기 호출은 사용자가 단추를 눌러 승인한 뒤에만 한다 (주문 · 계획 생성은 되돌리기 어려움).
//  - 지금은 어느 곳도 onMoveToPlan 을 넘기지 않으므로 아무 것도 그려지지 않는다.
import type { StockOverview } from "@/lib/api";
import { BROKER_LABEL, SEARCH_LABEL } from "@/lib/broker-link";
import type { PlanHints } from "@/lib/stock-display";

/** 「계획으로 옮기기」 처리기 (아직 아무도 넘기지 않음). 호출 시 미리 채울 값을 받는다. */
export type MoveToPlanHandler = (args: { ticker: string; market: "KR" | "US"; hints: PlanHints }) => void;

export function StockActions({
  d,
  planHints,
  onMoveToPlan,
}: {
  d: StockOverview;
  /** 국내 종목 가격 자료가 있을 때만 값이 있다 (관리자 · 로그인 화면) */
  planHints?: PlanHints | null;
  /** 아직 연결하지 않음 — 연결하면 「계획으로 옮기기」 단추가 켜진다 */
  onMoveToPlan?: MoveToPlanHandler;
}) {
  const bl = d.broker_link;
  const canMove = !!onMoveToPlan && !!planHints; // 지금은 항상 false
  if (!bl && !canMove) return null;
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="stock-actions">
      {bl && (
        <a href={bl.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary hover:text-primary/70">
          {bl.kind === "order" ? BROKER_LABEL : SEARCH_LABEL}
        </a>
      )}
      {canMove && (
        <button
          type="button"
          onClick={() => onMoveToPlan!({ ticker: d.ticker, market: d.market, hints: planHints! })}
          className="inline-flex min-h-[44px] items-center rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted"
        >
          계획으로 옮기기
        </button>
      )}
    </div>
  );
}
