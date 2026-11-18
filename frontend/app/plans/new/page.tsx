"use client";

// /plans/new · 새 계획 초안 (계획서 11절 · v4 8절)
// 즉시 검증은 화면에서 할 수 있는 것만 한다 (양수 · 수량 · 1차 익절가 위치). 상한 · buying-power · 가격 단위 · sanity ·
// 앱 조건주문 유무는 서버가 검증 값을 아직 주지 않아 못 한다 (보고 「필요한 API」). 초안 저장 뒤 승인 때 서버가 다시 막는다.
// 예시 칸의 TESTA 는 가짜 이름이다.
import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { plansApi, MODE_LABEL, errText, num, shares } from "@/lib/plans";
import type { PlanMode } from "@/lib/plans";
import { usePlanStatus } from "@/components/plans/ModeBand";
import { BTN_LINE, BTN_PRIMARY, Field, INPUT, Notice } from "@/components/plans/ui";

function toKst(v: string): string | null {
  return v ? `${v}:00+09:00` : null;
}

function NewPlanForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const status = usePlanStatus();
  const paperOk = status.data ? status.data.paper_test_enabled !== false : false;
  const [mode, setMode] = useState<PlanMode>(sp.get("mode") === "paper" ? "paper" : "live");
  const [symbol, setSymbol] = useState("");
  const [budget, setBudget] = useState("");
  const [buyWatch, setBuyWatch] = useState("");
  const [buyOrder, setBuyOrder] = useState("");
  const [tp1Watch, setTp1Watch] = useState("");
  const [tp1Order, setTp1Order] = useState("");
  const [announce, setAnnounce] = useState("");
  const [close, setClose] = useState("");
  const [windowEnd, setWindowEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 같은 종목에 열린 계획이 있는지 목록에서 바로 알려 준다 (서버도 막는다)
  const list = useQuery({ queryKey: ["plans", "list"], queryFn: () => plansApi.list(), staleTime: 0, retry: false });
  const sym = symbol.trim().toUpperCase();
  const dup = list.data?.plans.find((p) => p.symbol === sym && !["CLOSED", "CANCELLED"].includes(p.state));

  const b = num(budget);
  const o = num(buyOrder);
  const w = num(buyWatch);
  const t1w = num(tp1Watch);
  const t1o = num(tp1Order);
  const qty = b !== null && o !== null && o > 0 ? Math.floor(b / o) : null;

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!sym) p.push("종목 이름을 넣어 주십시오.");
    else if (!/^[A-Z0-9.\-]{1,16}$/.test(sym)) p.push("종목 이름은 영문 대문자 · 숫자만 쓸 수 있습니다.");
    if (dup) p.push(`같은 종목에 열린 계획 #${dup.id} 이 이미 있습니다.`);
    if (b === null || b <= 0) p.push("예산(달러)은 0 보다 커야 합니다.");
    if (o === null || o <= 0) p.push("매수 주문가는 0 보다 커야 합니다.");
    if (w === null || w <= 0) p.push("매수 감시가는 0 보다 커야 합니다.");
    if (qty !== null && qty < 1) p.push("예산이 매수 주문가 한 주보다 작아 수량이 0 입니다.");
    if (t1w !== null && t1w <= 0) p.push("1차 익절 감시가는 0 보다 커야 합니다.");
    if (t1o !== null && t1o <= 0) p.push("1차 익절 주문가는 0 보다 커야 합니다.");
    return p;
  }, [sym, dup, b, o, w, qty, t1w, t1o]);

  const soft: string[] = [];
  if (o !== null && t1w !== null && t1w <= o) soft.push("1차 익절 감시가가 매수 주문가 이하입니다. 값이 맞는지 확인해 주십시오.");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (problems.length > 0) return;
    setBusy(true);
    setErr(null);
    try {
      const params: Record<string, unknown> = {
        budget_usd: b, buy_watch: w, buy_order: o, qty,
        tp1_watch: t1w, tp1_order: t1o,
        announce_at: toKst(announce), entry_close_at: toKst(close), entry_window_end: toKst(windowEnd),
      };
      const r = await plansApi.create({ symbol: sym, mode, source: "manual", params });
      router.push(`/plans/${r.plan.id}`);
    } catch (e2) {
      setErr(errText(e2));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4" aria-label="새 계획 초안 입력">
      <h2 className="text-xl font-bold">새 계획 초안</h2>
      <Notice>저장하면 초안이 됩니다. 주문은 승인한 뒤에 시작됩니다. 값은 입력한 그대로 저장하며 추정 · 보장 아님.</Notice>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="종목 이름 (예 TESTA)">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="종목 이름" data-testid="in-symbol" className={INPUT} autoCapitalize="characters" placeholder="TESTA" />
        </Field>
        <Field label="계획 종류">
          <select value={mode} onChange={(e) => setMode(e.target.value as PlanMode)} aria-label="계획 종류" data-testid="in-mode" className={INPUT}>
            <option value="live">{MODE_LABEL.live}</option>
            <option value="test">{MODE_LABEL.test}</option>
            {(paperOk || mode === "paper") && <option value="paper">{MODE_LABEL.paper}</option>}
          </select>
        </Field>
        <Field label="예산 (달러)">
          <input inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} aria-label="예산 달러" data-testid="in-budget" className={INPUT} placeholder="100" />
        </Field>
        <Field label="계산된 수량" hint="예산 ÷ 매수 주문가 의 몫(소수점 버림)입니다.">
          <output data-testid="out-qty" aria-label="계산된 수량" className={`${INPUT} flex items-center`}>{qty === null ? "—" : shares(qty)}</output>
        </Field>
        <Field label="매수 감시가 (달러)">
          <input inputMode="decimal" value={buyWatch} onChange={(e) => setBuyWatch(e.target.value)} aria-label="매수 감시가" data-testid="in-buy-watch" className={INPUT} placeholder="1.00" />
        </Field>
        <Field label="매수 주문가 (달러)">
          <input inputMode="decimal" value={buyOrder} onChange={(e) => setBuyOrder(e.target.value)} aria-label="매수 주문가" data-testid="in-buy-order" className={INPUT} placeholder="1.02" />
        </Field>
        <Field label="1차 익절 감시가 (달러)">
          <input inputMode="decimal" value={tp1Watch} onChange={(e) => setTp1Watch(e.target.value)} aria-label="1차 익절 감시가" data-testid="in-tp1-watch" className={INPUT} />
        </Field>
        <Field label="1차 익절 주문가 (달러)">
          <input inputMode="decimal" value={tp1Order} onChange={(e) => setTp1Order(e.target.value)} aria-label="1차 익절 주문가" data-testid="in-tp1-order" className={INPUT} />
        </Field>
        <Field label="발표 시각 (한국 시각 · 비워도 됨)">
          <input type="datetime-local" value={announce} onChange={(e) => setAnnounce(e.target.value)} aria-label="발표 시각" data-testid="in-announce" className={INPUT} />
        </Field>
        <Field label="매수 마감 시각 (한국 시각 · 비워도 됨)">
          <input type="datetime-local" value={close} onChange={(e) => setClose(e.target.value)} aria-label="매수 마감 시각" data-testid="in-close" className={INPUT} />
        </Field>
        <Field label="진입 창 끝 (한국 시각 · 비워도 됨)">
          <input type="datetime-local" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} aria-label="진입 창 끝" data-testid="in-window-end" className={INPUT} />
        </Field>
      </div>

      {problems.length > 0 && (
        <ul data-testid="new-problems" role="alert" className="list-disc space-y-1 rounded-lg border border-warn/40 bg-warn/5 py-2 pl-7 pr-3 text-sm text-warn">
          {problems.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      {soft.map((m) => <Notice key={m} tone="warn" testid="new-soft">{m}</Notice>)}
      <Notice testid="new-server-check-note">
        한도 · 매수 가능 금액 · 가격 단위 · 값 이상 여부 · 앱에서 건 같은 종목 조건주문 확인은 서버 검증 값을 받는 대로 이 자리에 붙입니다. 지금은 승인할 때 서버가 막습니다.
      </Notice>
      {err && <Notice tone="warn" testid="new-error">{err}</Notice>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || problems.length > 0} aria-label="초안 저장" data-testid="btn-save-draft" className={BTN_PRIMARY}>
          {busy ? "저장 중" : "초안 저장"}
        </button>
        <button type="button" onClick={() => router.push("/plans")} aria-label="목록으로 돌아가기" data-testid="btn-cancel-new" className={BTN_LINE}>
          목록으로
        </button>
      </div>
    </form>
  );
}

export default function NewPlanPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">불러오는 중입니다</p>}>
      <NewPlanForm />
    </Suspense>
  );
}
