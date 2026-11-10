"use client";

// 1110-02 · 탭 본문: ① 포지션(토스 원장) ② 평균선 그림 ③ 목표까지 거리 ④ (설정 종목 탭만) 기존 VIP 칸.
// 사실만 보인다 — 규칙 이름 · 명령문 없음. 상승 빨강 · 하락 파랑 · 숫자는 tabular-nums.
import { GoalBox } from "@/components/account/HoldingSwing";
import { MaChart } from "@/components/account/MaChart";
import { VipConfigPanels } from "@/components/vip/VipConfigPanels";
import { distanceText, longMaSourceText, sourceText, splitMa, toneOf } from "@/lib/holdings-swing";
import { POSITION_SOURCE_LINE, VipTab, pnlLines, priceText } from "@/lib/vip-tabs";

const TONE = { up: "text-up", down: "text-down", flat: "text-muted-foreground" } as const;

function reasonLine(t: VipTab): string {
  switch (t.reason) {
    case "loss":
      return "가장 최근 하루 1회 보유 기록에서 매도 비용을 뺀 손익이 0 아래인 종목입니다.";
    case "turned":
      return "손익이 0 위로 바뀐 뒤 보유 기록 5행 이내인 종목입니다.";
    case "config":
      return "설정 종목입니다.";
    default:
      return "설정 종목이고 지금 보유 수량이 없습니다.";
  }
}

function Position({ t }: { t: VipTab }) {
  const p = t.position;
  if (!p) {
    return (
      <section className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground" data-testid="vip-position-empty">
        보유 없음 · 토스 보유 목록에 이 종목이 없습니다.
      </section>
    );
  }
  const { pct, amount } = pnlLines(p);
  const tone = TONE[toneOf(p.pnl_pct)];
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="포지션" data-testid="vip-position">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h3 className="text-base font-semibold">포지션 · 토스 원장</h3>
        <span className="text-[11px] text-muted-foreground">{POSITION_SOURCE_LINE}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <div className="text-xs text-muted-foreground">평단</div>
          <div className="tabular-nums">{priceText(p.avg_price, p.currency)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">수량</div>
          <div className="tabular-nums">{p.qty.toLocaleString("ko-KR")}주</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">현재가</div>
          <div className="tabular-nums">{priceText(p.current_price, p.currency)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">손익</div>
          <div className={`text-lg font-bold tabular-nums ${tone}`}>{pct}</div>
          <div className={`text-sm tabular-nums ${tone}`}>{amount}</div>
        </div>
      </div>
    </section>
  );
}

export function VipTabBody({ t }: { t: VipTab }) {
  const { base, long } = splitMa(t.ma_text);
  const closeSource = sourceText({ close_source: t.market === "KR" ? "krx" : "toss", as_of: null });
  return (
    <div className="space-y-4" data-testid={`vip-body-${t.market}:${t.symbol}`}>
      <p className="text-xs text-muted-foreground">{reasonLine(t)}</p>
      <Position t={t} />
      <MaChart chart={t.chart} />
      {base.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-4" aria-label="종가와 평균의 거리">
          <div className="text-xs text-muted-foreground">종가와 평균의 거리 ({closeSource})</div>
          <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-3">
            {base.map((m) => (
              <li key={m.days} className="flex items-baseline justify-between gap-2 rounded-md bg-muted/40 px-2 py-1">
                <span className="text-xs text-muted-foreground">{m.days}일 평균</span>
                <span className={`font-semibold tabular-nums ${TONE[toneOf(m.distance_pct)]}`}>{distanceText(m)}</span>
              </li>
            ))}
          </ul>
          {long && (
            <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-2 rounded-md bg-muted/40 px-2 py-1">
              <span className="text-xs text-muted-foreground">200일 평균 · {longMaSourceText(long)}</span>
              <span className={`font-semibold tabular-nums ${TONE[toneOf(long.distance_pct)]}`}>{distanceText(long)}</span>
            </div>
          )}
        </section>
      )}
      {t.goal ? (
        <GoalBox goal={t.goal} />
      ) : (
        <section className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground" aria-label="목표까지 거리">
          {t.goal_hold_reason ?? "목표 칸은 지금 보이지 않습니다."}
        </section>
      )}
      {t.is_vip_config && <VipConfigPanels />}
    </div>
  );
}
