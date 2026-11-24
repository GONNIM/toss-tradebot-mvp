"use client";

// /plans/adopt · 이미 산 종목 맡기기 초안 (보이는 이름만 바뀜 · 서버 값 이름 adopt 는 그대로 · 1116-01 F)
// 오류 문구는 「인수 초안 저장」을 누른 뒤에만 보인다 (1116-01 E) (계획서 8-0 · 8-1 · 11절)
// 계좌 보유 수량 · 평균단가를 서버에서 읽어 오는 API 가 없어 직접 입력한다 (보고 「필요한 API」).
// 인수 승인(쿠키 + 확인 코드)은 저장 뒤 상세 화면에서 한다. 예시 TESTA 는 가짜 이름이다.
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { plansApi, MODE_LABEL, errText, num } from "@/lib/plans";
import type { PlanMode } from "@/lib/plans";
import { AdoptNotice } from "@/components/plans/AdoptNotice";
import { BTN_LINE, BTN_PRIMARY, Field, INPUT, Notice } from "@/components/plans/ui";

export default function AdoptPage() {
  const router = useRouter();
  const [symbol, setSymbol] = useState("");
  const [mode, setMode] = useState<PlanMode>("live");
  const [qty, setQty] = useState("");
  const [avg, setAvg] = useState("");
  const [trailing, setTrailing] = useState(false);
  const [peak, setPeak] = useState("");
  const [tp1Watch, setTp1Watch] = useState("");
  const [tp1Order, setTp1Order] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const list = useQuery({ queryKey: ["plans", "list"], queryFn: () => plansApi.list(), staleTime: 0, retry: false });
  const sym = symbol.trim().toUpperCase();
  const dup = list.data?.plans.find((p) => p.symbol === sym && !["CLOSED", "CANCELLED"].includes(p.state));
  const q = num(qty);
  const a = num(avg);
  const pk = num(peak);

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!sym) p.push("종목 이름을 넣어 주십시오.");
    else if (!/^[A-Z0-9.\-]{1,16}$/.test(sym)) p.push("종목 이름은 영문 대문자 · 숫자만 쓸 수 있습니다.");
    if (dup) p.push(`같은 종목에 열린 계획 #${dup.id} 이 이미 있습니다.`);
    if (q === null || q < 1 || !Number.isInteger(q)) p.push("보유 수량은 1 이상의 정수여야 합니다.");
    if (a === null || a <= 0) p.push("평균 단가는 0 보다 커야 합니다.");
    if (trailing && (pk === null || pk <= 0)) p.push("고점을 따라 손절을 올리는 중이면 고점(달러)을 넣어 주십시오.");
    return p;
  }, [sym, dup, q, a, trailing, pk]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (problems.length) return;
    setBusy(true);
    setErr(null);
    try {
      const params: Record<string, unknown> = {
        adopt: { qty: q, avg_price: a, trailing, peak: trailing ? pk : null },
        tp1_watch: num(tp1Watch), tp1_order: num(tp1Order), avg_price: a, qty: q,
      };
      const r = await plansApi.create({ symbol: sym, mode, source: "adopt", params });
      router.push(`/plans/${r.plan.id}`);
    } catch (e2) {
      setErr(errText(e2));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4" aria-label="보유 인수 초안 입력">
      <h2 className="text-xl font-bold">이미 산 종목 맡기기 초안</h2>
      <AdoptNotice />
      <Notice>맡기기를 승인하면 실행기가 그 종목의 앱 조건주문이 없어지기를 10초마다 확인하고, 0건이 되는 즉시 손절 주문을 겁니다. 실거래 스위치가 꺼져 있으면 맡기기를 시작하지 않습니다.</Notice>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="종목 이름 (예 TESTA)">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="종목 이름" data-testid="in-symbol" className={INPUT} placeholder="TESTA" />
        </Field>
        <Field label="계획 종류">
          <select value={mode} onChange={(e) => setMode(e.target.value as PlanMode)} aria-label="계획 종류" data-testid="in-mode" className={INPUT}>
            <option value="live">{MODE_LABEL.live}</option>
            <option value="test">{MODE_LABEL.test}</option>
          </select>
        </Field>
        <Field label="보유 수량 (주)">
          <input inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} aria-label="보유 수량" data-testid="in-adopt-qty" className={INPUT} />
        </Field>
        <Field label="평균 단가 (달러)">
          <input inputMode="decimal" value={avg} onChange={(e) => setAvg(e.target.value)} aria-label="평균 단가" data-testid="in-adopt-avg" className={INPUT} />
        </Field>
        <Field label="1차 익절 감시가 (달러 · 비워도 됨)">
          <input inputMode="decimal" value={tp1Watch} onChange={(e) => setTp1Watch(e.target.value)} aria-label="1차 익절 감시가" data-testid="in-tp1-watch" className={INPUT} />
        </Field>
        <Field label="1차 익절 주문가 (달러 · 비워도 됨)">
          <input inputMode="decimal" value={tp1Order} onChange={(e) => setTp1Order(e.target.value)} aria-label="1차 익절 주문가" data-testid="in-tp1-order" className={INPUT} />
        </Field>
        <label className="flex min-h-[44px] items-center gap-2 text-sm">
          <input type="checkbox" checked={trailing} onChange={(e) => setTrailing(e.target.checked)} aria-label="이미 고점 따라 손절을 올리는 중" data-testid="in-adopt-trailing" className="h-5 w-5" />
          이미 고점을 따라 손절을 올리는 중입니다
        </label>
        {trailing && (
          <Field label="고점 (달러)">
            <input inputMode="decimal" value={peak} onChange={(e) => setPeak(e.target.value)} aria-label="고점" data-testid="in-adopt-peak" className={INPUT} />
          </Field>
        )}
      </div>
      {submitted && problems.length > 0 && (
        <ul data-testid="adopt-problems" role="alert" className="list-disc space-y-1 rounded-lg border border-warn/40 bg-warn/5 py-2 pl-7 pr-3 text-sm text-warn">
          {problems.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      <Notice testid="adopt-server-check-note">앱에서 건 같은 종목 조건주문 수는 서버가 목록을 주는 대로 인수 대기 화면에 보입니다.</Notice>
      {submitted && err && <Notice tone="warn" testid="adopt-error">{err}</Notice>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} aria-label="인수 초안 저장" data-testid="btn-save-adopt" className={BTN_PRIMARY}>
          {busy ? "저장 중" : "맡기기 초안 저장"}
        </button>
        <button type="button" onClick={() => router.push("/plans")} aria-label="목록으로 돌아가기" data-testid="btn-cancel-adopt" className={BTN_LINE}>
          목록으로
        </button>
      </div>
    </form>
  );
}
