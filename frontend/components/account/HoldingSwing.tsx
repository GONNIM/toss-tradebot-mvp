"use client";

// 1108-02 · /account 보유 종목마다 「보유 종목 사실」 칸 + 보유 성격 고르기.
// 사실만 보인다 — 규칙 이름 · 규칙 조건까지 거리 · 수량 · 명령문을 쓰지 않는다 (계획 5절 「쓰지 않을 것」).
// 상승(평균 위) 빨강 · 하락(평균 아래) 파랑 · 숫자는 tabular-nums.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AccountHolding, api } from "@/lib/api";
import {
  HORIZON_OPTIONS,
  STATE_MARK,
  SwingCard,
  SwingResponse,
  GoalLong,
  GoalShort,
  daysLeftText,
  deadlineText,
  diffText,
  distanceText,
  drawdownText,
  gapText,
  goalBasisText,
  longSeriesText,
  needText,
  ratioText,
  peakNote,
  sourceText,
  toneOf,
} from "@/lib/holdings-swing";
import { pctText } from "@/lib/holdings-display";

const TONE_CLASS = { up: "text-up", down: "text-down", flat: "text-muted-foreground" } as const;

function HorizonPicker({ card }: { card: SwingCard }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (value: "long" | "short" | "unset") => api.account.setHorizon(card.market, card.symbol, { horizon: value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", "swing"] }),
  });
  const current = card.horizon ?? "unset";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground">보유 성격</span>
      <div role="group" aria-label="보유 성격" className="inline-flex overflow-hidden rounded-lg border border-border">
        {HORIZON_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={current === o.value}
            disabled={save.isPending}
            onClick={() => current !== o.value && save.mutate(o.value)}
            className={`min-h-[44px] min-w-[56px] border-r border-border px-3 text-sm last:border-r-0 disabled:opacity-60 ${
              current === o.value ? "bg-slate-800 font-semibold text-white" : "bg-background hover:bg-muted"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {save.error && <span className="text-xs text-warn">저장하지 못했습니다. 다시 눌러 주십시오.</span>}
    </div>
  );
}

function Facts({ card }: { card: SwingCard }) {
  const bc = card.blue_chip;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs text-muted-foreground">종가와 평균의 거리 ({sourceText(card)})</div>
        <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-3">
          {card.ma.map((m) => (
            <li key={m.days} className="flex items-baseline justify-between gap-2 rounded-md bg-muted/40 px-2 py-1">
              <span className="text-xs text-muted-foreground">{m.days}일 평균</span>
              <span className={`font-semibold tabular-nums ${TONE_CLASS[toneOf(m.distance_pct)]}`}>{distanceText(m)}</span>
            </li>
          ))}
        </ul>
      </div>
      {card.peak && card.peak.from_peak_pct !== null && (
        <div>
          <div className="text-xs text-muted-foreground">{peakNote(card.peak)}</div>
          <div className={`font-semibold tabular-nums ${TONE_CLASS[toneOf(card.peak.from_peak_pct)]}`}>
            대비 {pctText(card.peak.from_peak_pct)}
          </div>
        </div>
      )}
      {card.source_gap && (
        <div className="text-xs">
          <span className="text-muted-foreground">토스 종가와 공식 종가 차이 · </span>
          <span className={`tabular-nums ${card.source_gap.flag ? "font-semibold text-warn" : ""}`}>
            {gapText(card.source_gap)}
            {card.source_gap.flag ? " · 출처 차이 (2% 는 근거 없는 값)" : ""}
          </span>
        </div>
      )}
      {bc && (
        <div>
          <div className="font-semibold tabular-nums">
            대형·대표 기준 {bc.met}/{bc.total} 충족
          </div>
          <ul className="mt-1 space-y-0.5 text-xs">
            {bc.items.map((i) => (
              <li key={i.key} className="flex flex-wrap gap-x-2">
                <span className="w-12 shrink-0 text-muted-foreground">{i.label}</span>
                <span className="font-medium">{STATE_MARK[i.state]}</span>
                {i.state !== "none" && (
                  <span className="tabular-nums text-muted-foreground">
                    {i.text}
                    {i.as_of ? ` · ${i.as_of}` : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="text-xs">
        <span className="text-muted-foreground">실질 평단 · </span>
        {card.real_avg.text}
      </div>
      {card.goal && <GoalBox goal={card.goal} />}
      {card.profit_turn && <ProfitTurn card={card} />}
    </div>
  );
}

// 3단계 · 목표까지 거리 — 추정값 칸. 결론 · 명령문 없이 숫자와 한계만 보인다.
function GoalBox({ goal }: { goal: NonNullable<SwingCard["goal"]> }) {
  return (
    <section className="space-y-2 rounded-md border border-border p-3" aria-label="목표까지 거리">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h4 className="text-xs font-semibold">목표까지 거리</h4>
        <span className="text-[11px] text-muted-foreground">추정 포함 · 보장 아님</span>
      </div>
      <div className="text-[11px] text-muted-foreground">
        기준 가격: {goalBasisText(goal.basis)} · 팔 때 비용 {goal.cost_pct}% 반영
      </div>
      {goal.kind === "short" ? <GoalShortBody g={goal} /> : <GoalLongBody g={goal} />}
      <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
        {goal.limits.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
      <div className="text-[11px] text-muted-foreground">{goal.disclaimer}</div>
    </section>
  );
}

function GoalShortBody({ g }: { g: GoalShort }) {
  return (
    <div className="space-y-2 text-sm">
      <div className={`font-semibold tabular-nums ${g.above_breakeven ? "text-up" : ""}`}>{needText(g)}</div>
      <div className="text-xs">
        <span className="tabular-nums">{deadlineText(g)}</span>
        <span className="text-muted-foreground"> · </span>
        <span className="tabular-nums">{daysLeftText(g)}</span>
      </div>
      <div className="text-[11px] text-muted-foreground">
        기간 안에 한 번이라도 필요 상승률에 닿을 가능성 · 두 방법을 나란히 보이며 평균 내지 않습니다 · {longSeriesText(g.long_series)}
        {g.sigma120_pct !== null ? ` · 최근 120일 변동성 ${g.sigma120_pct.toFixed(2)}%` : ""}
      </div>
      {g.above_breakeven && <div className="text-[11px] text-muted-foreground">이미 본전 위라 닿을 가능성은 계산하지 않았습니다.</div>}
      {g.past_deadline && !g.above_breakeven && (
        <div className="text-[11px] text-muted-foreground">기한이 지나 「기한까지」 기간은 계산하지 않았습니다.</div>
      )}
      {g.windows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[19rem] text-xs tabular-nums">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-1 pr-2 font-normal">기간</th>
                <th className="py-1 pr-2 text-right font-normal">자기 이력</th>
                <th className="py-1 pr-2 text-right font-normal">변동성 모형</th>
                <th className="py-1 text-right font-normal">차이</th>
              </tr>
            </thead>
            <tbody>
              {g.windows.map((w) => (
                <tr key={w.label} className="border-b border-border align-top last:border-0">
                  <td className="py-1 pr-2">
                    {w.label}
                    <div className="text-[11px] text-muted-foreground">{w.days}일</div>
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <div className="font-semibold">{ratioText(w.own.pct)}</div>
                    <div className="text-[11px] text-muted-foreground">표본 {w.own.n.toLocaleString("ko-KR")}개</div>
                    {w.own.note && <div className="text-[11px] text-muted-foreground">{w.own.note}</div>}
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <div className="font-semibold">{ratioText(w.model.pct)}</div>
                    {w.model.note && <div className="text-[11px] text-muted-foreground">{w.model.note}</div>}
                  </td>
                  <td className="py-1 text-right font-semibold">{diffText(w.diff_pp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GoalLongBody({ g }: { g: GoalLong }) {
  const d = g.drawdowns;
  return (
    <div className="space-y-2 text-sm">
      <div className="tabular-nums">
        <span className="text-xs text-muted-foreground">평단까지 여유 </span>
        <span className={`font-semibold ${TONE_CLASS[toneOf(g.cushion_pct)]}`}>{pctText(g.cushion_pct)}</span>
      </div>
      {g.ath ? (
        <div className="text-xs tabular-nums">
          <span className="text-muted-foreground">역대 최고 대비 </span>
          <span className={`font-semibold ${TONE_CLASS[toneOf(g.ath.from_ath_pct)]}`}>{pctText(g.ath.from_ath_pct)}</span>
          <span className="text-muted-foreground">
            {" "}
            (최고 종가 {g.ath.close.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} · {g.ath.date})
          </span>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">역대 최고 대비: 자료 없음</div>
      )}
      <div className="text-xs">
        <div className="text-[11px] text-muted-foreground">같은 종목의 과거 하락 · {longSeriesText(g.long_series)}</div>
        {d ? (
          <>
            <div className="tabular-nums">{drawdownText(d)}</div>
            {d.ongoing && (
              <div className="tabular-nums text-muted-foreground">
                진행 중: {d.ongoing.start} 시작 · 깊이 {pctText(d.ongoing.depth_pct)}
              </div>
            )}
          </>
        ) : (
          <div className="text-muted-foreground">자료 없음</div>
        )}
      </div>
    </div>
  );
}

// 3단계 · 기한 날짜(단기일 때) + 사용자 메모. 메모는 글자 그대로만 보인다 (HTML 해석 없음).
const MEMO_MAX = 200;

function DeadlineMemo({ card }: { card: SwingCard }) {
  const qc = useQueryClient();
  const [deadline, setDeadline] = useState(card.deadline ?? "");
  const [memo, setMemo] = useState(card.memo ?? "");
  const refresh = () => qc.invalidateQueries({ queryKey: ["account", "swing"] });
  const horizon = card.horizon ?? "unset";
  const saveDeadline = useMutation({
    mutationFn: (value: string | null) => api.account.setHorizon(card.market, card.symbol, { horizon, deadline: value }),
    onSuccess: refresh,
  });
  const saveMemo = useMutation({
    mutationFn: (value: string) => api.account.setHorizon(card.market, card.symbol, { horizon, memo: value }),
    onSuccess: refresh,
  });
  const isShort = card.horizon === "short";
  return (
    <div className="space-y-3 text-sm">
      {isShort && (
        <div className="space-y-1">
          <label htmlFor={`dl-${card.market}-${card.symbol}`} className="text-xs text-muted-foreground">
            기한 날짜 (비우고 저장하면 기본값{card.goal?.kind === "short" && card.goal.deadline_source === "default" && card.goal.deadline ? ` · 지금 ${card.goal.deadline}` : ""})
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id={`dl-${card.market}-${card.symbol}`}
              type="date"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              className="min-h-[44px] rounded-lg border border-border bg-background px-3 tabular-nums"
            />
            <button
              type="button"
              disabled={saveDeadline.isPending}
              onClick={() => saveDeadline.mutate(deadline === "" ? null : deadline)}
              className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted disabled:opacity-60"
            >
              기한 저장
            </button>
            {saveDeadline.error && (
              <span className="text-xs text-warn">기한을 저장하지 못했습니다. 기준일보다 앞선 날짜는 받지 않습니다.</span>
            )}
          </div>
        </div>
      )}
      <div className="space-y-1">
        <label htmlFor={`memo-${card.market}-${card.symbol}`} className="text-xs text-muted-foreground">
          사용자 메모 (내가 적은 글 그대로 보이며, 위 숫자에는 영향이 없습니다)
        </label>
        <textarea
          id={`memo-${card.market}-${card.symbol}`}
          value={memo}
          maxLength={MEMO_MAX}
          rows={3}
          onChange={(e) => setMemo(e.target.value)}
          className="w-full rounded-lg border border-border bg-background p-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs tabular-nums text-muted-foreground">
            {memo.length}/{MEMO_MAX}자
          </span>
          <button
            type="button"
            disabled={saveMemo.isPending}
            onClick={() => saveMemo.mutate(memo)}
            className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted disabled:opacity-60"
          >
            메모 저장
          </button>
          {saveMemo.error && <span className="text-xs text-warn">메모를 저장하지 못했습니다. 다시 눌러 주십시오.</span>}
          {saveMemo.isSuccess && !saveMemo.error && <span className="text-xs text-muted-foreground">저장했습니다.</span>}
        </div>
      </div>
    </div>
  );
}

function ProfitTurn({ card }: { card: SwingCard }) {
  const t = card.profit_turn!;
  const l = t.layer;
  const [, m, d] = t.turn_date.split("-");
  return (
    <div className="space-y-1 rounded-md border border-border p-3">
      <div className="text-xs font-semibold">
        비용을 뺀 손익이 {Number(m)}/{Number(d)} 에 0 을 넘었습니다 · 지금 <span className={`tabular-nums ${TONE_CLASS[toneOf(t.net_pnl_pct)]}`}>{pctText(t.net_pnl_pct)}</span> ({t.cost_note})
      </div>
      <div className="text-xs text-muted-foreground">{l.title}</div>
      <ul className="text-xs tabular-nums">
        <li>{l.mean} <span className="text-muted-foreground">(본전에 팔기 / 계속 들고 가기)</span></li>
        <li>{l.median_diff}</li>
        <li>{l.bottom5} <span className="text-muted-foreground">(본전에 팔기 / 계속 들고 가기)</span></li>
        <li>{l.sample}</li>
      </ul>
      <div className="text-[11px] text-muted-foreground">{l.caveat}</div>
      <div className="text-[11px] text-muted-foreground">{l.source}</div>
    </div>
  );
}

export function HoldingSwing({ holdings, isAdmin }: { holdings: AccountHolding[]; isAdmin: boolean }) {
  const q = useQuery<SwingResponse>({ queryKey: ["account", "swing"], queryFn: api.account.swing, enabled: isAdmin, retry: false });
  if (!isAdmin) return null;
  if (q.isLoading) return <p className="text-sm text-muted-foreground">보유 종목 사실 불러오는 중…</p>;
  if (q.error || !q.data) return <p className="text-sm text-muted-foreground">보유 종목 사실을 불러오지 못했습니다.</p>;
  const byKey = new Map(q.data.cards.map((c) => [`${c.market}-${c.symbol}`, c]));
  return (
    <section className="space-y-2" aria-label="보유 종목 사실">
      <h3 className="text-sm font-semibold">보유 종목 사실</h3>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {holdings.map((h) => {
          const card = byKey.get(`${h.market}-${h.symbol}`);
          return (
            <article key={`${h.market}-${h.symbol}`} className="space-y-3 rounded-lg border border-border bg-card p-3">
              <header>
                <div className="font-medium">{h.name ?? h.symbol}</div>
                <div className="font-mono text-xs text-muted-foreground">{h.symbol} · {h.market === "KR" ? "국내" : "미국"}</div>
              </header>
              {!card ? (
                <p className="text-sm text-muted-foreground">보류 · 보유 기록이 쌓이면 보여 드립니다 (국내 15:50 · 미국 07:10 기록).</p>
              ) : (
                <>
                  <HorizonPicker card={card} />
                  <DeadlineMemo key={`${card.deadline ?? ""}|${card.memo ?? ""}|${card.horizon ?? ""}`} card={card} />
                  {card.status === "hold" ? (
                    <p className="text-sm text-muted-foreground">보류 · {card.hold_reason}</p>
                  ) : (
                    <Facts card={card} />
                  )}
                  <p className="text-[11px] text-muted-foreground">{card.disclaimer} · 평단 대비 손익은 위 표(토스 값 그대로)를 보십시오.</p>
                </>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
