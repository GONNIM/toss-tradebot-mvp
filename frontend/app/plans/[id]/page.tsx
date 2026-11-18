"use client";

// /plans/[id] · 계획 상세 (계획서 11절 · v4 8절 · 8-1)
// 현재가 · 평가 손익 · 다음 전환 시각 · 토스에 실제 걸린 다리 · 계좌 보유 · 앱 조건주문 목록은 서버 값(live · actual_legs · adopt)이다.
// 값이 null 이면 지어내지 않고 「확인 못 함」 으로 보인다.
// 실거래 · 모의 스위치와 Kill Switch 해제는 이 화면에 두지 않는다 (관리자 설정 화면).
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  plansApi, MODE_LABEL, STATE_LABEL, STATE_FLOW, TERMINAL_STATES, ROLE_LABEL, LEG_STATUS_LABEL, TAG_LABEL, VALUE_LABEL, PLAN_SOURCE_LABEL,
  errText, kst, num, pct, shares, usd, TP1_MODE_LABEL,
} from "@/lib/plans";
import type { ActualLeg, Leg, Plan, PlanDetail } from "@/lib/plans";
import { upDownText } from "@/lib/updown";
import { AdoptNotice } from "@/components/plans/AdoptNotice";
import { CodeDialog } from "@/components/plans/CodeDialog";
import { BTN_LINE, BTN_PRIMARY, BTN_WARN, Field, INPUT, Notice, Row } from "@/components/plans/ui";

const HALTABLE = ["APPROVED", "ENTRY_ARMED", "ENTRY_RETRY", "HOLDING", "TP1_WAIT", "TRAILING", "ADOPT_PENDING"];
const POSITION_STATES = ["HOLDING", "TP1_WAIT", "TRAILING"];

const TIMESTOP_LABEL: Record<string, string> = { none: "해당 없음", lift: "손절 끌어올림", clean: "정리 중", stopped: "중지됨" };

const EVENT_LABEL: Record<string, string> = {
  state: "단계 바뀜", draft: "초안 만듦", draft_edit: "초안 고침", leg_missing: "다리 안 보임", leg_triggered: "조건 닿음",
  leg_filled: "체결", leg_canceled: "취소", leg_expired: "만료", leg_register_fail: "등록 실패", leg_modify_fail: "수정 실패",
  sanity_reject: "값 점검 막음", sell_qty_capped: "매도 수량 줄임", sell_rejected: "매도 거부", sell_cross: "즉시 매도",
  account_short: "계좌 보유 부족", tp1_watch_sell: "1차 익절 매도", timestop_stopped: "시간 손절 중지",
  switch_off_wait: "스위치 꺼짐 대기", kill_wait: "Kill Switch 대기", confirm_fail: "확인 코드 실패",
  draft_done: "자동 초안 끝", draft_none: "자동 초안 없음",
};

function legName(raw: string): string {
  const m = /^(sl|tp1|buy)(\d+)$/.exec(raw);
  return m ? `${ROLE_LABEL[m[1]] ?? m[1]} ${m[2]}번` : raw;
}

function reasonKo(reason: string): string {
  const m = /^approved by (.+)$/.exec(reason);
  return m ? `${m[1]} 승인` : reason;
}

/** 이벤트 한 줄: 한국어 문장 + (원문이 다르면) 접힌 「자세히」 · 모르는 종류는 「기타 기록」 */
function eventView(kind: string, detail: string): { label: string; text: string; raw: string | null } {
  const label = EVENT_LABEL[kind] ?? "기타 기록";
  const d = detail ?? "";
  let m: RegExpExecArray | null;
  let text: string | null = null;
  if (kind === "state") {
    try {
      const j = JSON.parse(d) as { from?: string; to?: string; reason?: string };
      text = `${STATE_LABEL[j.from ?? ""] ?? "알 수 없는 단계"} → ${STATE_LABEL[j.to ?? ""] ?? "알 수 없는 단계"}${j.reason ? ` · ${reasonKo(j.reason)}` : ""}`;
    } catch { /* 아래 기타 처리 */ }
  } else if (kind === "draft") text = `초안을 만들었습니다 (${PLAN_SOURCE_LABEL[d] ?? "자동"})`;
  else if ((m = /^revision (\d+)$/.exec(d)) && kind === "draft_edit") text = `초안 값을 고쳤습니다 (판 번호 ${m[1]})`;
  else if (kind === "leg_missing") text = `${legName(d)} 다리가 토스에서 보이지 않습니다`;
  else if (kind === "leg_triggered") text = `${legName(d)} 조건에 닿았습니다`;
  else if (kind === "leg_filled") text = `${legName(d)} 체결되었습니다`;
  else if (kind === "leg_canceled") text = `${legName(d)} 취소되었습니다`;
  else if (kind === "leg_expired") text = `${legName(d)} 만료되었습니다`;
  else if ((m = /^(\S+) (\S+)$/.exec(d)) && kind === "leg_register_fail") text = `${legName(m[1])} 조건주문 등록에 실패했습니다`;
  else if ((m = /^(\S+) (\S+) #(\d+)$/.exec(d)) && kind === "leg_modify_fail") text = `${legName(m[1])} 조건주문 수정에 실패했습니다 (연속 ${m[3]}번째)`;
  else if (kind === "sanity_reject") text = `값 점검에서 막았습니다 · ${d}`;
  else if ((m = /^(\S+) (\d+) → (\d+)$/.exec(d)) && kind === "sell_qty_capped") text = `${legName(m[1])} 매도 수량을 ${m[2]}주에서 ${m[3]}주로 줄였습니다`;
  else if ((m = /^(\S+) (\S+)$/.exec(d)) && kind === "sell_rejected") text = `${legName(m[1])} 매도 주문이 거부되었습니다`;
  else if ((m = /^(\S+) qty (\d+)$/.exec(d)) && kind === "sell_cross") text = `${legName(m[1])} 즉시 매도 ${m[2]}주를 요청했습니다`;
  else if ((m = /^plan_qty (\d+) account (\d+)$/.exec(d)) && kind === "account_short") text = `계좌 보유가 계획 수량보다 적습니다 (계획 ${m[1]}주 · 계좌 ${m[2]}주)`;
  else if ((m = /^qty (\d+)$/.exec(d)) && kind === "tp1_watch_sell") text = `1차 익절 감시가에 닿아 ${m[1]}주 매도를 요청했습니다`;
  else if (kind === "timestop_stopped") text = "시간 손절을 중지했습니다";
  else if (["switch_off_wait", "kill_wait", "confirm_fail", "draft_done", "draft_none"].includes(kind)) text = d || label;
  if (text === null) return { label: "기타 기록", text: "자세한 내용은 아래 「자세히」 에서 볼 수 있습니다", raw: `${kind} · ${d}` };
  return { label, text, raw: d && d !== text && !/[가-힣]/.test(d) ? d : null };
}

type Dlg = null | "approve" | "resume" | "stop" | "adopt-cancel" | "timestop";

function legKey(l: { qty: number; watch: number | null; order: number | null }): string {
  return `${l.qty}|${l.watch ?? ""}|${l.order ?? ""}`;
}

function valueText(k: string, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (k === "mode") return MODE_LABEL[String(v)] ?? "알 수 없는 종류";
  if (k === "adopt" && typeof v === "object") {
    const a = v as { qty?: unknown; avg_price?: unknown; trailing?: boolean; peak?: unknown };
    return `수량 ${shares(a.qty)} · 평균 단가 ${usd(a.avg_price, 4)}${a.trailing ? ` · 고점 ${usd(a.peak, 4)}부터 따라 올림` : ""}`;
  }
  if (k === "ladder_pcts" && Array.isArray(v)) return v.map((x) => `${(Number(x) * 100).toFixed(1).replace(/\.0$/, "")}%`).join(" · ");
  if (k.endsWith("_at") || k === "entry_window_end") return kst(String(v));
  if (["budget_usd", "buy_watch", "buy_order", "tp1_watch", "tp1_order"].includes(k)) return usd(v, 4);
  if (k === "qty") return shares(v);
  return typeof v === "object" ? "기타 값" : String(v);
}

function ValuesList({ values }: { values: Record<string, unknown> | undefined }) {
  if (!values) return <p className="text-sm text-muted-foreground">값이 없습니다</p>;
  const label = VALUE_LABEL;

  return (
    <dl>
      {Object.entries(values).map(([k, v]) => (
        <Row
          key={k}
          k={label[k] ?? "기타 값"}
          testid={`val-${k}`}
          v={valueText(k, v)}
        />
      ))}
    </dl>
  );
}

function LegTable({ legs, testid, label }: { legs: { key: string; role: string; qty: number; watch: number | null; order: number | null; extra?: string }[]; testid: string; label: string }) {
  if (legs.length === 0) return <p data-testid={`${testid}-empty`} className="text-sm text-muted-foreground">걸려 있어야 할 다리가 없습니다</p>;
  return (
    <div className="overflow-x-auto" aria-label={label}>
      <table data-testid={testid} className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr><th className="py-1 pr-2">종류</th><th className="pr-2 text-right">수량</th><th className="pr-2 text-right">감시가</th><th className="text-right">주문가</th></tr>
        </thead>
        <tbody className="tabular-nums">
          {legs.map((l) => (
            <tr key={l.key} className="border-t border-border/60">
              <td className="py-1.5 pr-2">{ROLE_LABEL[l.role] ?? "기타"}{l.extra ? <span className="ml-1 text-xs text-muted-foreground">{TAG_LABEL[l.extra] ?? l.extra}</span> : null}</td>
              <td className="pr-2 text-right">{shares(l.qty)}</td>
              <td className="pr-2 text-right">{usd(l.watch, 4)}</td>
              <td className="text-right">{usd(l.order, 4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AdoptList({ adopt }: { adopt: PlanDetail["adopt"] }) {
  if (!adopt) return <Notice testid="adopt-pending-list">확인 못 함 · 앱 조건주문 목록을 실행기가 아직 남기지 않았습니다.</Notice>;
  const conds = adopt.foreign_conds;
  return (
    <div data-testid="adopt-pending-list" className="space-y-2 rounded-[14px] border border-border bg-card p-3">
      <h4 className="text-sm font-semibold">앱에 남은 조건주문 {conds.length}건</h4>
      {conds.length === 0 ? (
        <p data-testid="adopt-conds-empty" className="text-sm text-muted-foreground">남은 앱 조건주문이 없습니다.</p>
      ) : (
        <div className="overflow-x-auto" aria-label="앱에 남은 조건주문">
          <table data-testid="adopt-conds" className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="py-1 pr-2">방향</th><th className="pr-2 text-right">수량</th><th className="pr-2 text-right">감시가</th><th className="text-right">주문가</th></tr>
            </thead>
            <tbody className="tabular-nums">
              {conds.map((c, i) => (
                <tr key={c.toss_id ?? i} className="border-t border-border/60">
                  <td className="py-1.5 pr-2">{c.side === "BUY" ? "매수" : c.side === "SELL" ? "매도" : c.side ?? "—"}</td>
                  <td className="pr-2 text-right">{shares(c.qty)}</td>
                  <td className="pr-2 text-right">{usd(c.watch, 4)}</td>
                  <td className="text-right">{usd(c.order, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p data-testid="adopt-seconds" className="text-sm tabular-nums">
        {adopt.seconds_left != null ? `다음 확인까지 최대 ${adopt.seconds_left}초 (확인 간격 ${adopt.max_gap_sec}초)` : "마지막 확인 시각 확인 못 함"}
        {adopt.checked_at ? ` · 마지막 확인 ${kst(adopt.checked_at)}` : ""}
        {adopt.waiting_minutes != null ? ` · 대기 ${adopt.waiting_minutes}분` : ""}
      </p>
      <p className="text-xs text-muted-foreground">지운 뒤 실행기가 10초마다 확인합니다. 10분이 넘어도 대기를 유지하고 알림이 한 번 갑니다.</p>
    </div>
  );
}

function Progress({ plan }: { plan: Plan }) {
  const side = plan.state === "HALTED" || plan.state === "CANCELLED" || plan.state === "ADOPT_PENDING";
  const idx = STATE_FLOW.indexOf(plan.state);
  return (
    <div aria-label="계획 단계" data-testid="plan-progress">
      <ol className="flex flex-wrap gap-1.5 text-xs">
        {STATE_FLOW.map((s, i) => {
          const on = s === plan.state;
          const done = idx >= 0 && i < idx;
          return (
            <li
              key={s}
              aria-current={on ? "step" : undefined}
              className={`rounded-full border px-2.5 py-1 ${on ? "border-primary bg-primary/10 font-bold text-primary" : done ? "border-border text-foreground" : "border-border text-muted-foreground"}`}
            >
              {STATE_LABEL[s]}
            </li>
          );
        })}
      </ol>
      {side && (
        <p data-testid="plan-side-state" className={`mt-2 text-sm font-semibold ${plan.state === "ADOPT_PENDING" ? "" : "text-warn"}`}>
          지금 단계: {STATE_LABEL[plan.state]}
          {plan.halted_reason ? ` · 까닭: ${plan.halted_reason}` : ""}
        </p>
      )}
    </div>
  );
}

export default function PlanDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plans", "detail", id], queryFn: () => plansApi.detail(id), refetchInterval: 10_000, staleTime: 0, retry: false, enabled: Number.isFinite(id) });
  const [dlg, setDlg] = useState<Dlg>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [editErr, setEditErr] = useState<string | null>(null);
  const [resyncBusy, setResyncBusy] = useState(false);

  // 승인 대화상자 입력
  const [tickerIn, setTickerIn] = useState("");
  const [thesis, setThesis] = useState("");
  const [invalid, setInvalid] = useState("");
  const [target, setTarget] = useState("");
  const [approver, setApprover] = useState("대표");

  const d: PlanDetail | undefined = q.data;
  const p = d?.plan;

  useEffect(() => {
    if (dlg === "approve" && p) {
      setTickerIn("");
      setTarget(String(p.params.tp1_watch ?? ""));
      setApprover("대표");
    }
  }, [dlg, p]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["plans"] });

  if (!Number.isFinite(id)) return <Notice tone="warn">계획 번호가 올바르지 않습니다.</Notice>;
  if (q.isLoading) return <p className="text-sm text-muted-foreground">계획을 읽는 중입니다</p>;
  if (q.error || !d || !p) return <Notice tone="warn" testid="detail-error">{errText(q.error)}</Notice>;

  const isPaper = p.mode === "paper";
  const isAdopt = p.source === "adopt";
  const terminal = TERMINAL_STATES.includes(p.state);
  const expectedLegs = d.legs.filter((l: Leg) => l.status === "WATCHING");
  const actual: ActualLeg[] | null = Array.isArray(d.actual_legs) ? d.actual_legs : null;
  const live = d.live;
  const adopt = d.adopt ?? null;
  const expectedKeys = expectedLegs.map((l) => legKey(l)).sort();
  const actualKeys = actual ? actual.map((l) => legKey(l)).sort() : [];
  const legMismatch = actual !== null && expectedKeys.join(",") !== actualKeys.join(",");
  const invBad = d.invariant.status !== "ok";
  const qty = num(p.qty ?? p.params.qty ?? p.params.adopt?.qty);
  const pnl = live?.pnl ?? null;
  const kstNow = (iso: string | null | undefined) => (iso ? kst(iso) : "확인 못 함");

  async function resync() {
    setResyncBusy(true);
    setEditErr(null);
    try {
      await plansApi.resync(id);
      setMsg("토스와 다시 맞추기를 요청했습니다. 실행기가 처리한 뒤 위 값이 바뀝니다.");
      await refresh();
    } catch (e) {
      setEditErr(errText(e));
    } finally {
      setResyncBusy(false);
    }
  }

  async function saveAnnounce() {
    setEditErr(null);
    try {
      await plansApi.edit(id, { announce_at: announce ? `${announce}:00+09:00` : null });
      setMsg("발표 시각을 저장했습니다. 판 번호가 바뀌었으면 승인 때 새 값으로 확인 코드를 받습니다.");
      setAnnounce("");
      await refresh();
    } catch (e) {
      setEditErr(errText(e));
    }
  }

  async function doApprove(c: { challenge_id?: number; code?: string }) {
    if (!p) return;
    // 판단 3줄은 승인 요청 본문으로 보낸다 · 서버가 승인과 한 번에 저장한다 (둘 중 하나가 실패하면 둘 다 남지 않는다)
    await plansApi.approve(id, {
      ...c, approver: isPaper ? approver : "대표",
      ticker: tickerIn.trim().toUpperCase(), thesis: thesis.trim(), invalidation_price: num(invalid), target_price: num(target),
    });
    setMsg(isAdopt ? "인수를 승인했습니다. 실행기가 앱 조건주문을 확인합니다." : "승인했습니다. 실거래 스위치가 꺼져 있으면 주문은 나가지 않습니다.");
    await refresh();
  }

  const approveReady =
    tickerIn.trim().toUpperCase() === p.symbol &&
    thesis.trim().length > 0 &&
    num(invalid) !== null && (num(invalid) ?? 0) > 0;

  const challengeAction = isAdopt ? "adopt" : "approve";
  const noLiveWarn = "실거래 꺼짐 · 주문 안 냄: 실거래 스위치가 꺼져 있으면 승인은 저장되지만 주문은 나가지 않습니다 (관리자 설정에서 켭니다).";

  return (
    <div className="space-y-4">
      <section aria-label="계획 종류 띠" data-testid="plan-mode-band" className={`rounded-lg border px-3 py-2 text-sm font-semibold ${isPaper ? "border-warn/40 bg-warn/5 text-warn" : "border-primary/40 bg-primary/10 text-primary"}`}>
        {isPaper ? "모의 시험 · 토스 주문 없음" : p.mode === "test" ? "실제 주문 시험" : "실전"}
        {isAdopt ? " · 보유 인수" : ""}
      </section>

      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-bold" data-testid="plan-title">#{p.id} {p.symbol}</h2>
        <span data-testid="plan-state" className="text-sm font-semibold">{STATE_LABEL[p.state] ?? "알 수 없는 단계"}</span>
        <span className="text-xs tabular-nums text-muted-foreground">판 번호 {p.revision} · 내용 확인값 {d.content_hash}</span>
      </header>

      <Progress plan={p} />

      {msg && <Notice testid="detail-msg">{msg}</Notice>}
      {p.state === "ADOPT_PENDING" && (
        <section className="space-y-2" aria-label="인수 대기">
          <AdoptNotice />
          <AdoptList adopt={adopt} />
        </section>
      )}
      {p.state === "DRAFT" && !isPaper && <Notice testid="no-live-warn">{noLiveWarn}</Notice>}

      <section aria-label="계획 값" className="rounded-[14px] border border-border bg-card px-3">
        <dl>
          <Row k="수량" v={shares(qty)} testid="val-qty" />
          <Row k="예산" v={usd(p.params.budget_usd)} testid="val-budget" />
          <Row k="매수 감시가 / 주문가" v={`${usd(p.params.buy_watch, 4)} / ${usd(p.params.buy_order, 4)}`} testid="val-buy" />
          <Row k="1차 익절 감시가 / 주문가" v={`${usd(p.params.tp1_watch, 4)} / ${usd(p.params.tp1_order, 4)}`} testid="val-tp1" />
          <Row k="평균 단가" v={usd(p.avg_price, 4)} testid="val-avg" />
          <Row k="고점" v={usd(p.peak_price, 4)} testid="val-peak" />
          <Row k="발표 시각" v={kst(p.params.announce_at as string | null)} testid="val-announce" />
          <Row k="매수 마감 · 진입 창 끝" v={`${kst(p.params.entry_close_at as string | null)} · ${kst(p.params.entry_window_end as string | null)}`} testid="val-close" />
          <Row k="시간 손절 단계" v={TIMESTOP_LABEL[p.timestop_stage] ?? "알 수 없음"} testid="val-timestop" />
          <Row k="승인한 사람" v={p.approved_by ?? "아직 승인 전"} testid="val-approver" />
        </dl>
      </section>

      <section aria-label="시세 기준 값" className="rounded-[14px] border border-border bg-card px-3">
        <dl>
          <Row k="현재가" v={live?.price != null ? `${usd(live.price, 4)} · ${kstNow(live.price_at)}` : "확인 못 함"} testid="val-price" />
          <Row
            k="계획 평가 손익 (추정 · 보장 아님)"
            v={pnl ? `${pnl.usd > 0 ? "+" : ""}${usd(pnl.usd)} · ${pct(pnl.pct)}` : "확인 못 함"}
            testid="val-pnl"
            tone={upDownText(pnl ? pnl.usd : null)}
          />
          <Row k="다음 시간대 전환 시각 (한국 시각)" v={kstNow(live?.next_swap_at)} testid="val-next-switch" />
          <Row k="1차 익절까지 %" v={live?.tp1_gap_pct != null ? pct(live.tp1_gap_pct) : "확인 못 함"} testid="val-to-tp1" />
          <Row k="1차 익절 방식" v={live?.tp1_mode ? TP1_MODE_LABEL[live.tp1_mode] ?? "알 수 없음" : "아직 정해지지 않음"} testid="val-tp1-mode" />
          {live?.trailing && (
            <Row k="고점 · 따라 올린 손절 감시가" v={`${usd(live.trailing.peak, 4)} · ${usd(live.trailing.stop, 4)}`} testid="val-trailing" />
          )}
          <Row
            k="계획 보유 / 계좌 보유 / 계획 밖 보유"
            v={`${shares(live?.plan_qty)} / ${live?.account_qty != null ? shares(live.account_qty) : "확인 못 함"} / ${live?.outside_qty != null ? shares(live.outside_qty) : "확인 못 함"}`}
            testid="val-holdings"
          />
        </dl>
        <p className="pb-2 text-xs text-muted-foreground">
          값은 규칙 계산이며 추정 · 보장 아님. 현재가와 계좌 보유는 실행기가 마지막으로 남긴 값입니다 (계좌 보유 확인 {kstNow(live?.account_qty_at)}).
        </p>
      </section>

      <section aria-label="다리 비교" className="space-y-2">
        <h3 className="text-base font-bold">걸려 있어야 할 다리와 토스에 실제 걸린 다리</h3>
        {(legMismatch || invBad) && (
          <Notice tone="warn" testid="leg-mismatch">
            {legMismatch ? "불일치: 두 목록이 다릅니다. " : ""}
            {invBad ? `수량 점검 ${d.invariant.status === "shortage" ? "부족" : d.invariant.status === "excess" ? "초과" : "이상"}: 손절 합계 ${shares(d.invariant.sl_sum)} · 목표 ${shares(d.invariant.target)}` : ""}
          </Notice>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          <div className={`rounded-[14px] border bg-card p-3 ${legMismatch || invBad ? "border-warn/60" : "border-border"}`}>
            <h4 className="mb-1 text-sm font-semibold">지금 걸려 있어야 할 다리 (계획 기준)</h4>
            <LegTable testid="legs-expected" label="걸려 있어야 할 다리" legs={expectedLegs.map((l) => ({ key: String(l.id), role: l.role, qty: l.qty, watch: l.watch, order: l.order, extra: l.tag || undefined }))} />
          </div>
          <div className={`rounded-[14px] border bg-card p-3 ${legMismatch ? "border-warn/60" : "border-border"}`}>
            <h4 className="mb-1 text-sm font-semibold">토스에 실제 걸린 다리</h4>
            {actual === null ? (
              <p data-testid="legs-actual-unknown" className="text-sm text-muted-foreground">확인 못 함 · 실행기가 토스에서 읽은 값이 아직 없습니다.</p>
            ) : (
              <>
                <LegTable testid="legs-actual" label="토스에 실제 걸린 다리" legs={actual.map((l, i) => ({ key: l.toss_id ?? String(i), role: l.role ?? "", qty: l.qty, watch: l.watch, order: l.order }))} />
                <p data-testid="legs-actual-at" className="mt-1 text-xs text-muted-foreground">마지막 확인 {kstNow(d.actual_at)}</p>
              </>
            )}
          </div>
        </div>
        <details className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
          <summary className="min-h-[32px] cursor-pointer font-semibold" aria-label="모든 다리 기록 펼치기">모든 다리 기록 {d.legs.length}건</summary>
          <ul data-testid="legs-all" className="mt-2 space-y-1 tabular-nums">
            {d.legs.map((l) => (
              <li key={l.id}>
                {ROLE_LABEL[l.role] ?? "기타"} {l.seq} · {shares(l.qty)} · 감시 {usd(l.watch, 4)} · 주문 {usd(l.order, 4)} · {LEG_STATUS_LABEL[l.status] ?? "기타 상태"}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section aria-label="버튼" className="space-y-2">
        <div className="flex flex-wrap gap-2" data-testid="plan-actions">
          {p.state === "DRAFT" && (
            <button type="button" onClick={() => setDlg("approve")} aria-label={isAdopt ? "보유 인수 승인" : "계획 승인"} data-testid="btn-approve" className={BTN_PRIMARY}>
              {isAdopt ? "보유 인수 승인" : "계획 승인"}
            </button>
          )}
          {p.state === "HALTED" && (
            <button type="button" onClick={() => setDlg("resume")} aria-label="정지 풀고 재개" data-testid="btn-resume" className={BTN_PRIMARY}>
              정지 풀고 재개
            </button>
          )}
          {p.state === "ADOPT_PENDING" && (
            <button type="button" onClick={() => setDlg("adopt-cancel")} aria-label="인수 취소" data-testid="btn-adopt-cancel" className={BTN_LINE}>
              인수 취소
            </button>
          )}
          {POSITION_STATES.includes(p.state) && p.timestop_stage !== "stopped" && (
            <button type="button" onClick={() => setDlg("timestop")} aria-label="시간 손절 중지" data-testid="btn-timestop-stop" className={BTN_LINE}>
              시간 손절 중지
            </button>
          )}
          {HALTABLE.includes(p.state) && (
            <button type="button" onClick={() => setDlg("stop")} aria-label="이 계획 정지" data-testid="btn-stop" className={BTN_WARN}>
              이 계획 정지
            </button>
          )}
          {!terminal && p.state !== "DRAFT" && (
            <button type="button" onClick={resync} disabled={resyncBusy} aria-label="토스와 다시 맞추기" data-testid="btn-resync" className={BTN_LINE}>
              {resyncBusy ? "요청 중" : "토스와 다시 맞추기"}
            </button>
          )}
        </div>
        {p.state === "DRAFT" && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="발표 시각 입력 (한국 시각)">
              <input type="datetime-local" value={announce} onChange={(e) => setAnnounce(e.target.value)} aria-label="발표 시각" data-testid="in-announce" className={INPUT} />
            </Field>
            <button type="button" onClick={saveAnnounce} disabled={!announce} aria-label="발표 시각 저장" data-testid="btn-save-announce" className={BTN_LINE}>
              발표 시각 저장
            </button>
          </div>
        )}
        {editErr && <Notice tone="warn" testid="edit-error">{editErr}</Notice>}
        <p className="text-xs text-muted-foreground">실거래 · 모의 스위치와 Kill Switch 는 이 화면에서 바꾸지 않습니다. 관리자 설정의 「계획 실행기」 칸에서 바꿉니다.</p>
        <p className="text-xs text-muted-foreground">「이 계획 정지」 는 새 등록과 매수를 멈추고 대기 중인 매수를 취소합니다. 걸린 매도 다리는 지우지 않습니다.</p>
      </section>

      <section aria-label="이벤트 기록" className="space-y-2">
        <h3 className="text-base font-bold">이벤트 기록 <span className="text-sm font-normal tabular-nums text-muted-foreground">{d.events.length}건</span></h3>
        {d.events.length === 0 ? (
          <Notice>아직 기록이 없습니다.</Notice>
        ) : (
          <ul data-testid="plan-events" className="divide-y divide-border rounded-[14px] border border-border bg-card">
            {d.events.map((e, i) => (
              <li key={`${e.ts}-${i}`} className="px-3 py-2 text-sm">
                <span className="tabular-nums text-muted-foreground">{kst(e.ts)}</span>
                {(() => {
                  const v = eventView(e.kind, e.detail);
                  return (
                    <>
                      <span className="ml-2 text-xs text-muted-foreground">{v.label}</span>
                      <p className="break-words">{v.text}</p>
                      {v.raw && (
                        <details className="text-xs text-muted-foreground">
                          <summary className="cursor-pointer" aria-label="이 기록의 원문 펼치기">자세히</summary>
                          <p className="break-all tabular-nums">{v.raw}</p>
                        </details>
                      )}
                    </>
                  );
                })()}
              </li>
            ))}
          </ul>
        )}
      </section>

      <CodeDialog
        testid="dlg-approve"
        open={dlg === "approve"}
        onClose={() => setDlg(null)}
        title={isAdopt ? "보유 인수 승인" : "계획 승인"}
        requireCode={!isPaper}
        requestCode={() => plansApi.confirmChallenge(challengeAction, id)}
        renderValues={(v) => <ValuesList values={v} />}
        confirmLabel={isAdopt ? "인수 승인하기" : "승인하기"}
        extraReady={approveReady}
        onConfirm={doApprove}
      >
        {isPaper && <ValuesList values={d.approval_values} />}
        {!isPaper && <Notice testid="dlg-approve-note">{noLiveWarn}</Notice>}
        <Field label={`종목 이름을 직접 입력하십시오 (${p.symbol})`}>
          <input value={tickerIn} onChange={(e) => setTickerIn(e.target.value)} aria-label="승인할 종목 이름 직접 입력" data-testid="in-approve-ticker" className={INPUT} autoComplete="off" />
        </Field>
        <Field label="판단 기록 1 · 이 계획을 세운 근거">
          <input value={thesis} onChange={(e) => setThesis(e.target.value)} aria-label="판단 기록 근거" data-testid="in-approve-thesis" className={INPUT} />
        </Field>
        <Field label="판단 기록 2 · 이 가격(달러)에 닿으면 계획이 틀린 것">
          <input inputMode="decimal" value={invalid} onChange={(e) => setInvalid(e.target.value)} aria-label="판단 기록 무효 가격" data-testid="in-approve-invalid" className={INPUT} />
        </Field>
        <Field label="판단 기록 3 · 목표 가격(달러 · 비워도 됨)">
          <input inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="판단 기록 목표 가격" data-testid="in-approve-target" className={INPUT} />
        </Field>
        {isPaper && (
          <Field label="승인 주체">
            <select value={approver} onChange={(e) => setApprover(e.target.value)} aria-label="승인 주체" data-testid="in-approver" className={INPUT}>
              <option value="대표">대표</option>
              <option value="Aside(대표 지시)">Aside(대표 지시)</option>
            </select>
          </Field>
        )}
      </CodeDialog>

      <CodeDialog
        testid="dlg-resume"
        open={dlg === "resume"}
        onClose={() => setDlg(null)}
        title="정지 풀고 재개"
        requireCode={!isPaper}
        requestCode={() => plansApi.confirmChallenge("resume", id)}
        renderValues={(v) => <ValuesList values={v} />}
        confirmLabel="재개하기"
        onConfirm={async (c) => {
          await plansApi.resume(id, c);
          setMsg("재개를 요청했습니다. 실행기가 토스와 맞춘 뒤 불변식을 통과하면 이어 갑니다.");
          await refresh();
        }}
      >
        <Notice>재개 요청은 실행기가 처리합니다. 정지된 사이에도 손절 다리 다시 걸기는 계속됩니다.</Notice>
      </CodeDialog>

      <CodeDialog
        testid="dlg-stop"
        open={dlg === "stop"}
        onClose={() => setDlg(null)}
        title="이 계획 정지"
        requireCode={false}
        confirmLabel="정지하기"
        onConfirm={async () => {
          await plansApi.stop(id);
          setMsg("계획을 정지했습니다. 대기 중인 매수 취소는 실행기가 처리합니다. 매도 다리는 지우지 않았습니다.");
          await refresh();
        }}
      >
        <p className="text-sm">새 등록과 매수를 멈추고 대기 중인 매수를 취소합니다. 걸린 매도 다리는 지우지 않습니다.</p>
      </CodeDialog>

      <CodeDialog
        testid="dlg-adopt-cancel"
        open={dlg === "adopt-cancel"}
        onClose={() => setDlg(null)}
        title="인수 취소"
        requireCode={false}
        confirmLabel="인수 취소하기"
        onConfirm={async () => {
          await plansApi.adoptCancel(id);
          setMsg("인수 취소를 요청했습니다.");
          await refresh();
        }}
      >
        <p className="text-sm">인수 대기를 끝냅니다. 앱에서 건 조건주문은 이 화면에서 건드리지 않습니다.</p>
      </CodeDialog>

      <CodeDialog
        testid="dlg-timestop"
        open={dlg === "timestop"}
        onClose={() => setDlg(null)}
        title="시간 손절 중지"
        requireCode={false}
        confirmLabel="시간 손절 중지하기"
        onConfirm={async () => {
          await plansApi.timestopStop(id);
          setMsg("시간 손절 중지를 요청했습니다.");
          await refresh();
        }}
      >
        <p className="text-sm">이 계획의 시간 손절 단계를 더 진행하지 않도록 실행기에 요청합니다.</p>
      </CodeDialog>
    </div>
  );
}
