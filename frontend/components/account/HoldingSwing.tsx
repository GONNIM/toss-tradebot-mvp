"use client";

// 1108-02 · /account 보유 종목마다 「보유 종목 사실」 칸 + 보유 성격 고르기.
// 사실만 보인다 — 규칙 이름 · 규칙 조건까지 거리 · 수량 · 명령문을 쓰지 않는다 (계획 5절 「쓰지 않을 것」).
// 상승(평균 위) 빨강 · 하락(평균 아래) 파랑 · 숫자는 tabular-nums.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AccountHolding, api } from "@/lib/api";
import {
  HORIZON_OPTIONS,
  STATE_MARK,
  SwingCard,
  SwingResponse,
  distanceText,
  gapText,
  peakNote,
  sourceText,
  toneOf,
} from "@/lib/holdings-swing";
import { pctText } from "@/lib/holdings-display";

const TONE_CLASS = { up: "text-up", down: "text-down", flat: "text-muted-foreground" } as const;

function HorizonPicker({ card }: { card: SwingCard }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (value: "long" | "short" | "unset") => api.account.setHorizon(card.market, card.symbol, value),
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
      {card.profit_turn && <ProfitTurn card={card} />}
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
