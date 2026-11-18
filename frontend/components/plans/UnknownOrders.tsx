"use client";

// 결과를 모르는 주문 (서버 GET /plans/{id}/unknown-orders · POST .../resolve) · 사람이 토스 앱 주문 내역과 맞춰 확정한다.
// 확인 코드 흐름은 재개와 같다(CodeDialog 재사용 · 실전 · 시험 계획만 코드). 영어 내부 이름은 한국어 이름표로만 보인다.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { plansApi, ORDER_KIND_LABEL, ORDER_ROLE_LABEL, ORDER_SIDE_LABEL, errText, kst, num, shares, usd } from "@/lib/plans";
import type { UnknownOrder } from "@/lib/plans";
import { CodeDialog } from "@/components/plans/CodeDialog";
import { BTN_LINE, Field, INPUT, Notice } from "@/components/plans/ui";

type Decision = "filled" | "not_created" | "open";
const ORDER_STATE_LABEL: Record<string, string> = { sent_unknown: "결과 모름", needs_human: "사람 확인 필요" };

const DECISION_TEXT: Record<Decision, string> = {
  filled: "체결됨으로 확정하면 입력한 수량을 보유로 보고 그 수량에 손절을 겁니다.",
  not_created: "만들어지지 않음으로 확정하면 묶여 있던 수량을 풀고 손절을 다시 겁니다.",
  open: "아직 열려 있음으로 확정하면 입력한 토스 주문 번호의 주문이 살아 있다고 보고 그대로 이어서 관리합니다.",
};

function lineText(o: UnknownOrder): string {
  const role = ORDER_ROLE_LABEL[o.role] ?? "기타";
  const kind = ORDER_KIND_LABEL[o.kind] ?? "기타 주문";
  const sideRaw = ORDER_SIDE_LABEL[o.side] ?? "";
  const side = sideRaw === role ? "" : sideRaw;
  const price = o.price != null ? ` · 주문가 ${usd(o.price, 4)}` : "";
  const watch = o.watch != null ? ` · 감시가 ${usd(o.watch, 4)}` : "";
  return `${role} ${side} ${kind} ${shares(o.qty)}${price}${watch} · ${kst(o.sent_at)} 보냄${o.replaces_id != null ? " · 기존 주문을 고치려고 보낸 주문" : ""}`;
}

export function UnknownOrdersPanel({
  planId, count, isPaper, guard, onChanged,
}: {
  planId: number;
  count: number;
  isPaper: boolean;
  /** 409 stale 처리를 입힌다(재시도 없이 다시 읽고 안내) */
  guard: (fn: () => Promise<void>) => Promise<void>;
  onChanged: () => Promise<void> | void;
}) {
  const q = useQuery({ queryKey: ["plans", "unknown", planId, count], queryFn: () => plansApi.unknownOrders(planId), enabled: count > 0, retry: false, staleTime: 0 });
  const [sel, setSel] = useState<{ line: UnknownOrder; decision: Decision } | null>(null);
  const [qtyIn, setQtyIn] = useState("");
  const [tossId, setTossId] = useState("");
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (sel) {
      setQtyIn("");
      setTossId(sel.line.candidates.length === 1 ? sel.line.candidates[0].toss_id : "");
    }
  }, [sel]);

  if (count <= 0 && !done) return null;
  const orders = q.data?.orders ?? [];
  const fq = num(qtyIn);
  const ready = !sel ? false
    : sel.decision === "filled" ? fq !== null && Number.isInteger(fq) && fq >= 1 && fq <= sel.line.qty
      : sel.decision === "open" ? tossId.trim().length > 0
        : true;

  return (
    <section aria-label="결과를 모르는 주문" className="space-y-2" data-testid="unknown-orders">
      {count > 0 && (
        <Notice tone="warn" testid="unknown-warn">
          결과를 모르는 주문 {count}건 · 이 수량에는 손절이 걸리지 않을 수 있습니다 · 토스 앱 주문 내역과 맞춰 확정해 주십시오
        </Notice>
      )}
      {count > 0 && (
        <Notice testid="unknown-pause-note">
          확정 전까지 이 계획은 정지 상태라 시간 손절 · 고점 따라 손절 올림 · 1차 익절이 돌지 않습니다. 손절 다리는 그대로 걸려 있습니다.
        </Notice>
      )}
      {done && <Notice testid="unknown-done">{done}</Notice>}
      {q.error && <Notice tone="warn" testid="unknown-error">{errText(q.error)}</Notice>}
      {q.data && !q.data.list_searchable && (
        <Notice testid="unknown-nosearch">토스 주문 목록에서 자동으로 찾지 못하는 상태입니다. 토스 앱 주문 내역을 보고 직접 확정해 주십시오.</Notice>
      )}
      <ul className="divide-y divide-border rounded-[14px] border border-warn/40 bg-card" data-testid="unknown-list">
        {orders.map((o) => (
          <li key={o.id} className="space-y-2 px-3 py-3 text-sm" data-testid={`unknown-${o.id}`}>
            <p className="font-semibold tabular-nums">{lineText(o)}</p>
            <p className="text-muted-foreground">
              상태: {ORDER_STATE_LABEL[o.state] ?? "기타"} · 왜 모르는지: {o.reason && /[가-힣]/.test(o.reason) ? o.reason : "기록된 까닭이 없습니다"}
            </p>
            {o.reason && !/[가-힣]/.test(o.reason) && (
              <details className="text-xs text-muted-foreground"><summary className="cursor-pointer" aria-label="까닭 원문 펼치기">자세히</summary><p className="break-all">{o.reason}</p></details>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setSel({ line: o, decision: "filled" })} aria-label={`주문 ${o.id} 체결됨으로 확정`} data-testid={`unknown-${o.id}-filled`} className={BTN_LINE}>
                체결됨 (수량 입력 · 주문 수량 {o.qty}주 이하)
              </button>
              <button type="button" onClick={() => setSel({ line: o, decision: "not_created" })} aria-label={`주문 ${o.id} 만들어지지 않음으로 확정`} data-testid={`unknown-${o.id}-none`} className={BTN_LINE}>
                만들어지지 않음
              </button>
              <button type="button" onClick={() => setSel({ line: o, decision: "open" })} aria-label={`주문 ${o.id} 아직 열려 있음으로 확정`} data-testid={`unknown-${o.id}-open`} className={BTN_LINE}>
                아직 열려 있음
              </button>
            </div>
          </li>
        ))}
      </ul>

      <CodeDialog
        testid="dlg-unknown"
        open={sel !== null}
        onClose={() => setSel(null)}
        title={sel ? `결과 모르는 주문 확정 · ${sel.decision === "filled" ? "체결됨" : sel.decision === "not_created" ? "만들어지지 않음" : "아직 열려 있음"}` : "결과 모르는 주문 확정"}
        requireCode={!isPaper}
        requestCode={() => plansApi.confirmChallenge("resume", planId)}
        confirmLabel="확정하기"
        extraReady={ready}
        onConfirm={async (c) => {
          if (!sel) return;
          const s = sel;
          await guard(async () => {
            await plansApi.resolveOrder(planId, s.line.id, {
              decision: s.decision,
              ...(s.decision === "filled" ? { filled_qty: fq ?? undefined } : {}),
              ...(s.decision === "open" ? { toss_id: tossId.trim() } : {}),
              ...c,
            });
            setDone(`주문 ${s.line.id}번 줄을 확정했습니다. 손절은 실행기가 다음 걸음에 겁니다.`);
            await onChanged();
          });
        }}
      >
        {sel && (
          <>
            <p className="text-sm" data-testid="dlg-unknown-effect">{DECISION_TEXT[sel.decision]}</p>
            <p className="text-xs tabular-nums text-muted-foreground">{lineText(sel.line)}</p>
            {sel.decision === "filled" && (
              <Field label={`체결된 수량 (1 ~ ${sel.line.qty}주)`}>
                <input inputMode="numeric" value={qtyIn} onChange={(e) => setQtyIn(e.target.value)} aria-label="체결된 수량" data-testid="in-unknown-qty" className={INPUT} />
              </Field>
            )}
            {sel.decision === "open" && (
              <>
                {sel.line.candidates.length > 0 ? (
                  <Field label="후보 목록에서 고르기">
                    <select value={tossId} onChange={(e) => setTossId(e.target.value)} aria-label="후보 주문 고르기" data-testid="in-unknown-cand" className={INPUT}>
                      <option value="">고르십시오</option>
                      {sel.line.candidates.map((c) => (
                        <option key={c.toss_id} value={c.toss_id}>{`${c.toss_id} · ${shares(c.qty)} · 감시 ${usd(c.watch, 4)} · 주문 ${usd(c.order, 4)}`}</option>
                      ))}
                    </select>
                  </Field>
                ) : (
                  <Field label="토스 앱에서 본 주문 번호를 입력하십시오" hint="후보가 없어 직접 입력합니다.">
                    <input value={tossId} onChange={(e) => setTossId(e.target.value)} aria-label="토스 주문 번호" data-testid="in-unknown-tossid" className={INPUT} autoComplete="off" />
                  </Field>
                )}
              </>
            )}
          </>
        )}
      </CodeDialog>
    </section>
  );
}
