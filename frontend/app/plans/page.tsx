"use client";

// /plans · 계획 목록 (계획서 11절 · v4 8절)
// 맨 위 한 줄(주문 나감/안 나감)과 상태 칩은 ModeBand(자세히). 걸린 조건주문 수 · 1차 익절 방식 · 마지막 현재가는 서버 값이고 null 이면 「확인 못 함」.
// 카드 맨 위는 「언제」 칩(발표 · 매수 마감 · 시간 손절 시작 · 서버 when 값만 읽음). 카드는 종목 · 살 값 · 팔 값 · 손절 값 · 수량 다섯 줄 (1116-01 B). 손절은 계획의 손절 폭이 있으면 그 값, 없을 때만 기본 규칙.
import Link from "next/link";

import { StockLabel } from "@/components/stock/StockLabel";
import { useQuery } from "@tanstack/react-query";
import { plansApi, MODE_LABEL, STATE_LABEL, TERMINAL_STATES, TP1_MODE_LABEL, errText, kst, num, shares, usd } from "@/lib/plans";
import { usePlanStatus } from "@/components/plans/ModeBand";
import { ADOPT_NAME, PRICE_NOTE, ladderLine } from "@/components/plans/planView";
import { BTN_LINE, BTN_PRIMARY, Notice } from "@/components/plans/ui";
import { WhenChips } from "@/components/plans/WhenCard";

export default function PlansPage() {
  const status = usePlanStatus();
  const q = useQuery({ queryKey: ["plans", "list"], queryFn: () => plansApi.list(), refetchInterval: 20_000, staleTime: 0, retry: false });
  const st = status.data;
  const paperOk = st?.paper_test_enabled === true; // 서버가 true 일 때만 모의 만들기를 보인다

  const rows = q.data?.plans ?? [];
  const open = rows.filter((p) => !TERMINAL_STATES.includes(p.state));
  const closed = rows.filter((p) => TERMINAL_STATES.includes(p.state));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Link href="/plans/new" aria-label="새 계획 만들기" data-testid="btn-new-plan" className={BTN_PRIMARY}>
          새 계획
        </Link>
        <Link href="/plans/adopt" aria-label="보유 종목 인수하기" data-testid="btn-adopt-plan" className={BTN_LINE}>
          {ADOPT_NAME}
        </Link>
        {paperOk && (
          <Link href="/plans/new?mode=paper" aria-label="모의 시험 계획 만들기" data-testid="btn-new-paper" className={BTN_LINE}>
            모의 시험 계획 만들기
          </Link>
        )}
      </div>

      {q.isLoading && <p className="text-sm text-muted-foreground">계획을 읽는 중입니다</p>}
      {q.error && <Notice tone="warn" testid="plans-error">{errText(q.error)}</Notice>}
      {q.data && rows.length === 0 && <Notice testid="plans-empty">아직 계획이 없습니다. 「새 계획」 으로 초안을 만들 수 있습니다.</Notice>}

      {open.length > 0 && <PlanList title="진행 중 계획" rows={open} testid="plans-open" />}
      {closed.length > 0 && <PlanList title="끝난 계획" rows={closed} testid="plans-closed" />}
    </div>
  );
}

function PlanList({ title, rows, testid }: { title: string; rows: import("@/lib/plans").PlanRow[]; testid: string }) {
  return (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-base font-bold">
        {title} <span className="text-sm font-normal tabular-nums text-muted-foreground">{rows.length}건</span>
      </h2>
      <ul data-testid={testid} className="divide-y divide-border rounded-[14px] border border-border bg-card">
        {rows.map((p) => {
          const qty = p.params.qty ?? p.params.adopt?.qty;
          const warn = p.state === "HALTED";
          const adopt = p.source === "adopt";
          const lad = ladderLine(p.params);
          return (
            <li key={p.id}>
              <Link
                href={`/plans/${p.id}`}
                aria-label={`계획 ${p.id} ${p.symbol} 상세`}
                data-testid={`plan-row-${p.id}`}
                className="block min-h-[44px] space-y-1 px-3 py-3"
              >
                {!TERMINAL_STATES.includes(p.state) && <WhenChips when={p.when} id={p.id} />}
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm tabular-nums text-muted-foreground">#{p.id}</span>
                  <span className="font-bold" data-testid={`row-symbol-${p.id}`}><StockLabel code={p.symbol} name={p.name} market="US" link={false} /></span>
                  <span className="text-xs text-muted-foreground">{MODE_LABEL[p.mode] ?? "알 수 없는 종류"}</span>
                  {adopt && <span className="text-xs text-muted-foreground">{ADOPT_NAME}</span>}
                  <span className={`ml-auto text-sm ${warn ? "font-semibold text-warn" : "font-semibold"}`}>{STATE_LABEL[p.state] ?? "알 수 없는 단계"}</span>
                </span>
                <span className="block space-y-0.5 text-sm tabular-nums">
                  <span className="block" data-testid={`row-buy-${p.id}`}>
                    {adopt ? `살 값: 평균 단가 ${usd(p.params.adopt?.avg_price ?? p.avg_price)}` : `살 값: 매수 감시가 ${usd(p.params.buy_watch)} · 매수 주문가 ${usd(p.params.buy_order)}`}
                  </span>
                  <span className="block" data-testid={`row-sell-${p.id}`}>팔 값: 1차 익절 감시가 {usd(p.params.tp1_watch)} · 1차 익절 주문가 {usd(p.params.tp1_order)}</span>
                  <span className="block" data-testid={`row-stop-${p.id}`}>{lad.text}</span>
                  <span className="block" data-testid={`row-qty-${p.id}`}>수량: {num(qty) !== null && (num(qty) ?? 0) > 0 ? shares(qty) : "0주 · 빠진 값이 있을 수 있음"}</span>
                </span>
                <span className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                  <span data-testid={`row-conds-${p.id}`}>걸린 조건주문 {p.live_cond_count ?? "확인 못 함"}{typeof p.live_cond_count === "number" ? "건" : ""}</span>
                  <span data-testid={`row-tp1-${p.id}`}>1차 익절 {p.tp1_mode ? TP1_MODE_LABEL[p.tp1_mode] : "정해지지 않음"}</span>
                  <span data-testid={`row-price-${p.id}`}>현재가 {p.price != null ? `${usd(p.price, 4)} · ${kst(p.price_at)}` : "확인 못 함"}</span>
                </span>
                <span className="block text-xs text-muted-foreground" data-testid={`row-note-${p.id}`}>{PRICE_NOTE}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
