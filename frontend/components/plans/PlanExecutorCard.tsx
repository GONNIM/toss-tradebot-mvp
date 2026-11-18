"use client";

/**
 * 관리자 설정 「계획 실행기」 칸 (계획서 11절 · 4절)
 * 두 스위치 · 상태 · 마지막 변경(누가 · 언제 · 까닭) · 실거래 켜기 확인 코드. 로그아웃이면 칸이 보이지 않는다.
 * 켜기/끄기는 쿠키 로그인으로만 된다 (서버가 헤더 토큰이면 403).
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSessionListener } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";
import { plansApi, errText, kst, heartbeatText } from "@/lib/plans";
import { CodeDialog } from "@/components/plans/CodeDialog";
import { usePlanStatus } from "@/components/plans/ModeBand";
import { BTN_LINE, BTN_PRIMARY, BTN_WARN, Field, INPUT, Notice, Row } from "@/components/plans/ui";

export function PlanExecutorCard() {
  const [role, setRole] = useState<SessionInfo["role"] | null>(null);
  useSessionListener((i) => setRole(i.role));
  const qc = useQueryClient();
  const admin = role === "admin";
  const { data: st, error } = usePlanStatus(admin);
  const [reasonLive, setReasonLive] = useState("");
  const [reasonPaper, setReasonPaper] = useState("");
  const [liveDlg, setLiveDlg] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!admin) return null;

  const refresh = () => qc.invalidateQueries({ queryKey: ["plans"] });

  async function offLive() {
    setErr(null);
    try {
      await plansApi.setLive({ on: false, reason: reasonLive });
      setMsg("실거래 주문을 껐습니다. 토스에 걸린 매수 조건주문은 실행기가 취소합니다.");
      await refresh();
    } catch (e) { setErr(errText(e)); }
  }
  async function setPaper(on: boolean) {
    setErr(null);
    try {
      await plansApi.setPaper({ on, reason: reasonPaper });
      setMsg(on ? "모의 시험을 켰습니다." : "모의 시험을 껐습니다. 남은 모의 계획은 가상으로 정리됩니다.");
      await refresh();
    } catch (e) { setErr(errText(e)); }
  }

  const lc = st?.last_change;
  return (
    <section aria-label="계획 실행기" data-testid="plan-executor-card" className="space-y-3 rounded-[14px] border border-border bg-card p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">계획 실행기</h2>
        <a href="/plans" aria-label="계획 화면으로" data-testid="link-plans" className="text-sm text-primary underline">계획 화면 →</a>
      </header>
      {error && <Notice tone="warn" testid="pe-error">{errText(error)}</Notice>}
      {st && (
        <dl>
          <Row k="실거래 주문" v={st.switches.live ? "켜짐" : "꺼짐"} testid="pe-live" />
          <Row k="모의 시험" v={st.switches.paper ? "켜짐" : "꺼짐"} testid="pe-paper" />
          <Row k="Kill Switch" v={st.kill_switch.active ? (st.kill_switch.sell_allowed ? "작동 중 · 새 주문 멈춤" : "작동 중 · 매도도 멈춤") : "꺼짐"} testid="pe-kill" />
          <Row k="실행기 마지막 응답" v={heartbeatText(st.heartbeat_age_sec)} testid="pe-heartbeat" />
          <Row
            k="마지막 변경"
            v={lc ? `${lc.switch === "live" ? "실거래" : "모의"} ${lc.new ? "켬" : "끔"} · ${lc.actor} · ${kst(lc.ts)} · 까닭 ${lc.reason || "—"}` : "기록 없음"}
            testid="pe-last-change"
          />
        </dl>
      )}
      <p className="text-xs text-muted-foreground">실거래 켜기는 휴대폰 텔레그램으로 온 6자리 코드가 필요합니다. Kill Switch 해제는 이 칸에서 하지 않습니다.</p>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2" aria-label="실거래 스위치">
          <Field label="실거래 주문 · 까닭 (켤 때 필수)">
            <input value={reasonLive} onChange={(e) => setReasonLive(e.target.value)} aria-label="실거래 스위치 까닭" data-testid="pe-live-reason" className={INPUT} maxLength={200} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!reasonLive.trim() || st?.switches.live === true} onClick={() => setLiveDlg(true)} aria-label="실거래 주문 켜기" data-testid="pe-live-on" className={BTN_PRIMARY}>
              실거래 켜기
            </button>
            <button type="button" disabled={st?.switches.live === false} onClick={offLive} aria-label="실거래 주문 끄기" data-testid="pe-live-off" className={BTN_WARN}>
              실거래 끄기
            </button>
          </div>
        </div>
        <div className="space-y-2" aria-label="모의 시험 스위치">
          <Field label="모의 시험 · 까닭 (켤 때 필수)">
            <input value={reasonPaper} onChange={(e) => setReasonPaper(e.target.value)} aria-label="모의 시험 스위치 까닭" data-testid="pe-paper-reason" className={INPUT} maxLength={200} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!reasonPaper.trim() || st?.switches.paper === true} onClick={() => setPaper(true)} aria-label="모의 시험 켜기" data-testid="pe-paper-on" className={BTN_PRIMARY}>
              모의 켜기
            </button>
            <button type="button" disabled={st?.switches.paper === false} onClick={() => setPaper(false)} aria-label="모의 시험 끄기" data-testid="pe-paper-off" className={BTN_LINE}>
              모의 끄기
            </button>
          </div>
        </div>
      </div>
      {msg && <Notice testid="pe-msg">{msg}</Notice>}
      {err && <Notice tone="warn" testid="pe-action-error">{err}</Notice>}

      <CodeDialog
        testid="dlg-live-on"
        open={liveDlg}
        onClose={() => setLiveDlg(false)}
        title="실거래 주문 켜기"
        requestCode={() => plansApi.liveChallenge()}
        confirmLabel="켜기"
        onConfirm={async (c) => {
          await plansApi.setLive({ on: true, reason: reasonLive, challenge_id: c.challenge_id, code: c.code });
          setMsg("실거래 주문을 켰습니다.");
          setReasonLive("");
          await refresh();
        }}
      >
        <p className="text-sm">까닭: {reasonLive || "—"}</p>
        <p className="text-sm text-warn">켜면 승인된 계획이 실제 주문을 냅니다. 추정 · 보장 아님.</p>
      </CodeDialog>
    </section>
  );
}
