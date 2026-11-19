"use client";

// /plans · 계획 목록 (계획서 11절 · v4 8절)
// 걸린 조건주문 수 · 토스 API 마지막 성공 시각 · 1차 익절 방식 · 마지막 현재가는 서버 값이고 null 이면 「확인 못 함」.
import Link from "next/link";

import { StockLabel } from "@/components/stock/StockLabel";
import { useQuery } from "@tanstack/react-query";
import { plansApi, MODE_LABEL, STATE_LABEL, TERMINAL_STATES, TP1_MODE_LABEL, WS_LABEL, errText, kst, shares, usd } from "@/lib/plans";
import { usePlanStatus } from "@/components/plans/ModeBand";
import { BTN_LINE, BTN_PRIMARY, Chip, Notice } from "@/components/plans/ui";

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
      <section aria-label="실행기 상태 칩" className="flex flex-wrap gap-2" data-testid="plans-chips">
        <Chip testid="chip-ws">시세 연결 {WS_LABEL[st?.ws_status ?? "none"] ?? "확인 못 함"}</Chip>
        <Chip testid="chip-resync">토스와 마지막으로 맞춘 시각 {kst(st?.last_resync_at)}</Chip>
        <Chip testid="chip-toss" tone={q.data?.toss?.status === "ok" ? "plain" : "warn"}>
          토스 API 연결 {q.data?.toss?.status === "ok" ? "정상" : q.data?.toss?.status === "error" ? "오류" : "확인 못 함"} · 마지막 성공 {kst(q.data?.toss?.last_ok_at ?? st?.toss?.last_ok_at)}
        </Chip>
      </section>

      <div className="flex flex-wrap gap-2">
        <Link href="/plans/new" aria-label="새 계획 만들기" data-testid="btn-new-plan" className={BTN_PRIMARY}>
          새 계획
        </Link>
        <Link href="/plans/adopt" aria-label="보유 종목 인수하기" data-testid="btn-adopt-plan" className={BTN_LINE}>
          보유 인수
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
          return (
            <li key={p.id}>
              <Link
                href={`/plans/${p.id}`}
                aria-label={`계획 ${p.id} ${p.symbol} 상세`}
                data-testid={`plan-row-${p.id}`}
                className="flex min-h-[44px] flex-col gap-1 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm tabular-nums text-muted-foreground">#{p.id}</span>
                  <span className="font-bold"><StockLabel code={p.symbol} name={p.name} market="US" link={false} /></span>
                  <span className="text-xs text-muted-foreground">{MODE_LABEL[p.mode] ?? "알 수 없는 종류"}</span>
                  {p.source === "adopt" && <span className="text-xs text-muted-foreground">보유 인수</span>}
                </span>
                <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm tabular-nums">
                  <span className={warn ? "font-semibold text-warn" : "font-semibold"}>{STATE_LABEL[p.state] ?? "알 수 없는 단계"}</span>
                  <span>수량 {shares(qty)}</span>
                  <span>매수 주문가 {usd(p.params.buy_order ?? p.avg_price)}</span>
                  <span data-testid={`row-conds-${p.id}`}>걸린 조건주문 {p.live_cond_count ?? "확인 못 함"}{typeof p.live_cond_count === "number" ? "건" : ""}</span>
                  <span data-testid={`row-tp1-${p.id}`} className="text-muted-foreground">1차 익절 {p.tp1_mode ? TP1_MODE_LABEL[p.tp1_mode] : "정해지지 않음"}</span>
                  <span data-testid={`row-price-${p.id}`} className="text-muted-foreground">현재가 {p.price != null ? `${usd(p.price, 4)} · ${kst(p.price_at)}` : "확인 못 함"}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
