"use client";

// /plans/new · 새 계획 초안 (계획서 11절 · v4 8절)
// 화면은 양수 · 1차 익절가 위치만 직접 본다. 수량 · 상한 · 매수 가능 금액 · 가격 단위 · 값 이상 여부 · 앱 조건주문은
// 서버 POST /plans/validate 결과를 보인다 (아무것도 저장하지 않는 읽기 점검). 초안 저장 뒤 승인 때 서버가 다시 막는다.
// 예시 칸의 TESTA 는 가짜 이름이다.
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { plansApi, MODE_LABEL, errText, num, shares } from "@/lib/plans";
import type { PlanMode, ValidateResult } from "@/lib/plans";
import { usePlanStatus } from "@/components/plans/ModeBand";
import { BTN_LINE, BTN_PRIMARY, Field, INPUT, Notice } from "@/components/plans/ui";

function toKst(v: string): string | null {
  return v ? `${v}:00+09:00` : null;
}

function NewPlanForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const status = usePlanStatus();
  const paperOk = status.data?.paper_test_enabled === true;
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
  const [qtyIn, setQtyIn] = useState("");
  const [vr, setVr] = useState<ValidateResult | null>(null);
  const [vErr, setVErr] = useState<string | null>(null);
  const [vBusy, setVBusy] = useState(false);
  // 수량은 서버 한 곳(engine.derive_qty)에서 정한다: 예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림.
  // 서버 점검 values.qty_source 가 "server" 이면 읽기 전용으로 보이고, "given"(예산 · 매수가 없음)일 때만 직접 넣는다.
  const hasBase = b !== null && b > 0 && o !== null && o > 0;
  const given = {
    editable: vr ? vr.values.qty_source === "given" : !hasBase,
    serverQty: vr && vr.values.qty_source === "server" ? vr.values.qty : null,
  };
  const qty = given.editable ? num(qtyIn) : given.serverQty;

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!sym) p.push("종목 이름을 넣어 주십시오.");
    else if (!/^[A-Z0-9.\-]{1,16}$/.test(sym)) p.push("종목 이름은 영문 대문자 · 숫자만 쓸 수 있습니다.");
    if (dup) p.push(`같은 종목에 열린 계획 #${dup.id} 이 이미 있습니다.`);
    if (b !== null && b <= 0) p.push("예산(달러)은 0 보다 커야 합니다.");
    if (o === null || o <= 0) p.push("매수 주문가는 0 보다 커야 합니다.");
    if (w === null || w <= 0) p.push("매수 감시가는 0 보다 커야 합니다.");
    if (given.editable && (qty === null || qty < 1 || !Number.isInteger(qty))) p.push("수량은 1 이상의 정수여야 합니다.");
    if (vr && !vr.ok) p.push("서버 점검에서 막힌 항목이 있습니다. 아래 점검 결과를 확인해 주십시오.");
    if (t1w !== null && t1w <= 0) p.push("1차 익절 감시가는 0 보다 커야 합니다.");
    if (t1o !== null && t1o <= 0) p.push("1차 익절 주문가는 0 보다 커야 합니다.");
    return p;
  }, [sym, dup, b, o, w, qty, given.editable, t1w, t1o, vr]);

  const soft: string[] = [];
  if (o !== null && t1w !== null && t1w <= o) soft.push("1차 익절 감시가가 매수 주문가 이하입니다. 값이 맞는지 확인해 주십시오.");

  function buildParams(q: number | null): Record<string, unknown> {
    return {
      budget_usd: b, buy_watch: w, buy_order: o, qty: q,
      tp1_watch: t1w, tp1_order: t1o,
      announce_at: toKst(announce), entry_close_at: toKst(close), entry_window_end: toKst(windowEnd),
    };
  }

  // 입력이 멈추고 0.6초 뒤 서버 점검을 부른다 · 서버가 정한 수량은 values.qty
  // (예산 · 매수가가 있으면 서버가 수량을 정하고, 없을 때만 직접 넣은 수량을 받는다)
  const valKey = JSON.stringify([sym, mode, qtyIn, b, o, w, t1w, t1o, announce, close, windowEnd]);
  useEffect(() => {
    const qn = num(qtyIn);
    if (!sym || o === null || o <= 0 || (!hasBase && (qn === null || qn < 1 || !Number.isInteger(qn)))) {
      setVr(null); setVErr(null);
      return;
    }
    let dead = false;
    const t = setTimeout(async () => {
      setVBusy(true);
      try {
        const r = await plansApi.validate({ symbol: sym, mode, source: "manual", params: buildParams(qn !== null && Number.isInteger(qn) && qn >= 1 ? qn : null) });
        if (dead) return;
        setVr(r); setVErr(null);
      } catch (e2) {
        if (dead) return;
        setVr(null); setVErr(errText(e2));
      } finally {
        if (!dead) setVBusy(false);
      }
    }, 600);
    return () => { dead = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valKey]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (problems.length > 0) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await plansApi.create({ symbol: sym, mode, source: "manual", params: buildParams(qty) });
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
        {given.editable ? (
          <Field label="수량 (주) · 예산 · 매수가가 없어 직접 넣은 값" hint="예산과 매수 주문가를 넣으면 서버가 수량을 정합니다(예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림).">
            <input inputMode="numeric" value={qtyIn} onChange={(e) => setQtyIn(e.target.value)} aria-label="수량 직접 입력" data-testid="in-qty" className={INPUT} placeholder="6" />
          </Field>
        ) : (
          <Field label="서버가 정한 수량" hint="예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내린 값입니다. 저장할 때 보내는 수량이 달라도 서버가 정한 값이 쓰입니다.">
            <output data-testid="out-qty" aria-label="서버가 정한 수량" className={`${INPUT} flex items-center`}>{given.serverQty === null ? "확인하는 중" : shares(given.serverQty)}</output>
          </Field>
        )}
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
      <section aria-label="서버 점검 결과" data-testid="new-validate" className="space-y-2">
        <h3 className="text-sm font-bold">서버 점검 결과 {vBusy && <span className="font-normal text-muted-foreground">· 확인하는 중</span>}</h3>
        {vErr && <Notice tone="warn" testid="new-validate-error">점검을 하지 못했습니다 · {vErr}</Notice>}
        {!vr && !vErr && !vBusy && <Notice testid="new-validate-empty">종목 · 예산 · 매수 주문가를 넣으면 서버가 한도 · 매수 가능 금액 · 가격 단위 · 값 이상 여부 · 앱 조건주문을 점검합니다.</Notice>}
        {vr && (
          <ul className="divide-y divide-border rounded-[14px] border border-border bg-card">
            {vr.checks.map((c) => (
              <li key={c.key} data-testid={`check-${c.key}`} data-status={c.status} className="px-3 py-2 text-sm">
                <span className={`mr-2 font-semibold ${c.status === "fail" ? "text-warn" : c.status === "ok" ? "text-foreground" : "text-muted-foreground"}`}>
                  {c.status === "ok" ? "통과" : c.status === "fail" ? "막힘" : c.status === "warn" ? "주의" : "확인 못 함"}
                </span>
                {c.label}
                {c.message && <p className="mt-0.5 break-words text-xs text-muted-foreground">{c.message}</p>}
              </li>
            ))}
            <li className="px-3 py-2 text-sm tabular-nums" data-testid="check-values">주문 금액 {vr.values.order_usd.toLocaleString("en-US", { style: "currency", currency: "USD" })} · 수량 {shares(vr.values.qty)}</li>
          </ul>
        )}
      </section>
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
