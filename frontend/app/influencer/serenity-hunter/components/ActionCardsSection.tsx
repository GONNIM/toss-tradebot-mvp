"use client";

// 🎯 오늘의 실행 카드 · 지시서 §1 · 페이지 최상단 섹션
// 필터 통과 종목만 · 매수/손절/TP 자동 계산 · 저널 프리필 버튼

import Link from "next/link";
import { useState } from "react";
import { JudgmentDialog } from "@/components/journal/JudgmentDialog";
import type { ActionCard, ActionCardsResponse } from "@/lib/serenity-hunter/types";

function _fmtUsd(v: number, digits = 2): string {
  return `$${v.toFixed(digits)}`;
}

function _fmtKrw(v: number): string {
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function ActionCardsSection({ data }: { data: ActionCardsResponse }) {
  const [dialogTicker, setDialogTicker] = useState<string | null>(null);
  const [showRest, setShowRest] = useState(false);
  const [showExcluded, setShowExcluded] = useState(false);

  const activeCard = dialogTicker
    ? [...data.cards, ...data.cards_hidden].find((c) => c.ticker === dialogTicker)
    : null;

  // 검증 실패 카드는 저널 오픈 금지 (렌더 단에서 버튼 자체 숨김 · 2중 방어)
  const activeCardIsValid = activeCard && !activeCard.price_verification_failed;

  return (
    <section>
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">🎯 오늘의 실행 카드</h2>
          <p className="text-[10px] text-muted-foreground">
            필터: bull_pct≥{data.filters.bull_pct_min}% · m90≥{data.filters.mentions_90d_min} ·
            m7≥{data.filters.mentions_7d_min} · Shell/AutoAvoid/AntiPattern 제외 · 가격 있음
          </p>
        </div>
        <div className="text-[10px] text-muted-foreground">
          FX {data.fx_rate.toFixed(0)} ({data.fx_source}) · as of {data.as_of.slice(0, 19)}
        </div>
      </header>

      {/* 동시 보유 한도 배너 · 지시서 §1.2 · 섹션 상단 고정 1줄 */}
      <div className="mb-3 rounded border border-primary/40 bg-primary/10 px-3 py-1.5 text-[11px] text-primary">
        📏 동시 보유 ≤ 3종목 · 건당 {_fmtKrw(data.risk.position_krw)} · 총 노출 ≤ 60% (RISK-PRINCIPLES §1·§2)
      </div>

      {data.cards.length === 0 ? (
        <div className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          조건 통과 카드 없음. 필터 완화·검증 재실행이 아닌 자연 축적 대기.
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {data.cards.map((c) => (
            <ActionCardItem
              key={c.ticker}
              card={c}
              risk={data.risk}
              onOpenJournal={() => setDialogTicker(c.ticker)}
            />
          ))}
        </div>
      )}

      {/* 더 보기 (5+ 카드) */}
      {data.rest_count > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowRest(!showRest)}
            className="text-xs text-sky-500 hover:underline"
          >
            {showRest ? "▲ 접기" : `▼ 더 보기 (+${data.rest_count})`}
          </button>
          {showRest && (
            <div className="mt-2 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {data.cards_hidden.map((c) => (
                <ActionCardItem
                  key={c.ticker}
                  card={c}
                  risk={data.risk}
                  onOpenJournal={() => setDialogTicker(c.ticker)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* excluded 사유 (투명성 · 지시서 §4) */}
      {data.excluded.length > 0 && (
        <details className="mt-3 rounded border border-border/40 bg-background/40 px-3 py-2 text-xs">
          <summary
            className="cursor-pointer text-muted-foreground"
            onClick={(e) => {
              e.preventDefault();
              setShowExcluded(!showExcluded);
            }}
          >
            📋 제외 사유 · {data.excluded.length} 티커
          </summary>
          {showExcluded && (
            <div className="mt-2 space-y-1">
              {data.excluded.map((e, i) => (
                <div key={i} className="flex justify-between gap-2">
                  <span className="font-mono">{e.ticker}</span>
                  <span className="text-muted-foreground">{e.reason}</span>
                </div>
              ))}
            </div>
          )}
        </details>
      )}

      {activeCardIsValid && (
        <JudgmentDialog
          open={!!dialogTicker}
          onOpenChange={(o) => {
            if (!o) setDialogTicker(null);
          }}
          ticker={activeCard.ticker}
          pageSource="serenity-hunter"
          hypothesisId={`serenity-hunter-action-v1-${activeCard.tier ?? "unscored"}`}
          initialThesis={
            activeCard.manual_sl_required
              ? "manual_sl_required=true · 소수점 주문 · 자동 손절 브로커 확인 필요\n\n"
              : ""
          }
          initialEntry={activeCard.entry_limit.toFixed(4)}
          initialInvalidation={activeCard.sl_price.toFixed(4)}
          initialTarget={activeCard.tp_trigger_price.toFixed(4)}
          initialHorizon={activeCard.sl_days * 2}
        />
      )}
    </section>
  );
}

function ActionCardItem({
  card,
  risk,
  onOpenJournal,
}: {
  card: ActionCard;
  risk: ActionCardsResponse["risk"];
  onOpenJournal: () => void;
}) {
  return (
    <article className="rounded-lg border border-border bg-card p-3 text-xs">
      <header className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono text-lg font-bold">{card.ticker}</span>
        {card.tier && (
          <span className="rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
            {card.tier}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          Bull {card.bull_pct.toFixed(0)}% · 90d {card.mentions_90d} · 7d {card.mentions_7d}
        </span>
        {card.sector_overlap && (
          <span
            className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-500"
            title={`같은 thesis 태그 (${card.sector_overlap_tags.join(", ")}) 2+ 카드 · 사실상 같은 베팅 · Serenity 논지 축 기준`}
          >
            ⚠ 논지겹침 {card.sector_overlap_tags.length > 0 ? `(${card.sector_overlap_tags[0]}${card.sector_overlap_tags.length > 1 ? "+" : ""})` : ""}
          </span>
        )}
        {card.price_verification_failed && (
          <span
            className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-red-500"
            title={`prior close 대비 ${card.vs_prior_pct?.toFixed(1)}% 이동 · ±30% 초과 · 실적 발표·이벤트 가능 · 수동 확인 필요`}
          >
            🚨 가격 검증 실패 · 수동 확인
          </span>
        )}
        {card.market_cap_sanity_warning && (
          <span
            className="rounded bg-orange-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-orange-500"
            title="marketCap ≠ shares × close (>10% 편차) · yfinance 데이터 정합성 의심 · 계산 신뢰도 낮음"
          >
            ⚠ 시총 검산 실패
          </span>
        )}
        {card.order_mode === "amount" && (
          <>
            <span
              className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-purple-400"
              title="1주가 예산을 초과 · 금액 주문 (₩200,000 상당) · 소수점 수량 · 지정가 통제 브로커별 제한"
            >
              💰 금액 모드
            </span>
            <span
              className="rounded bg-yellow-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-400"
              title="소수점 주문은 지정가 슬리피지 방어가 약함 · 브로커 매매 방식 실 확인"
            >
              ⚠ 지정가 통제 제한
            </span>
            <span
              className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-red-400"
              title="브로커별 소수점 주문의 자동 손절 지원 상이 · 저널에 manual_sl_required=true 태그 프리필 · 실 손절 반드시 수동 확인"
            >
              🛑 손절 수동 확인
            </span>
          </>
        )}
      </header>

      {card.industry && (
        <div className="mt-1 text-[10px] text-muted-foreground">{card.industry}</div>
      )}

      <div className="mt-2 text-[11px] text-muted-foreground">
        전일 종가 <span className="font-mono font-bold text-foreground">{_fmtUsd(card.last_close)}</span>
      </div>

      {/*
        Fable 5 3차 원칙 (2026-08-13):
        "검증 실패한 입력 위에서는 어떤 계산도 발급하지 않는다."
        price_verification_failed=true → 실행 계획·저널 버튼 발급 X · 대체 안내만.
      */}
      {card.price_verification_failed ? (
        <div className="mt-3 border-t border-red-500/40 pt-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-red-500">
            실행 계획 보류 · 가격 확인 후 진행
          </div>
          <div className="mt-1 space-y-1 font-mono text-[11px] text-muted-foreground">
            <div>
              최근 스냅샷 <span className="font-bold text-foreground">{_fmtUsd(card.last_close)}</span>{" "}
              vs 직전{" "}
              <span className="font-bold text-foreground">
                {_fmtUsd((card.last_close ?? 0) / (1 + (card.vs_prior_pct ?? 0) / 100))}
              </span>{" "}
              (
              <span className={((card.vs_prior_pct ?? 0) > 0 ? "text-emerald-500" : "text-red-500")}>
                {(card.vs_prior_pct ?? 0) > 0 ? "+" : ""}
                {(card.vs_prior_pct ?? 0).toFixed(1)}%
              </span>
              )
            </div>
            <div className="text-[10px]">
              ±30% 초과 · 실적 발표·이벤트·데이터 오염 가능. 다음 정상 스냅샷 시 자동 복원.
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <Link
              href={`/influencer/serenity/${card.ticker}`}
              className="rounded border border-border px-3 py-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground hover:border-foreground"
            >
              📈 가격 수동 확인 후 진행
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-3 border-t border-border/40 pt-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              실행 계획 (RISK-PRINCIPLES 자동 계산)
            </div>
            <div className="mt-1 space-y-1 font-mono text-[11px]">
              <div>
                매수 <span className="text-muted-foreground">·</span> 다음 시가 · 지정가 상한{" "}
                <span className="font-bold">{_fmtUsd(card.entry_limit, 4)}</span>
              </div>
              {card.order_mode === "shares" ? (
                <div>
                  수량 <span className="text-muted-foreground">·</span>{" "}
                  <span className="font-bold">{card.qty}주</span>{" "}
                  <span className="text-muted-foreground">
                    (≈{_fmtKrw(card.total_krw ?? card.entry_krw * card.qty)}
                    {card.remaining_krw !== null && card.remaining_krw !== undefined
                      ? ` · 잔여 ${_fmtKrw(card.remaining_krw)}`
                      : ""}
                    )
                  </span>
                </div>
              ) : (
                <div>
                  주문금액 <span className="text-muted-foreground">·</span>{" "}
                  <span className="font-bold">{_fmtKrw(card.order_krw ?? 0)}</span>{" "}
                  <span className="text-muted-foreground">
                    (예상 수량 ≈ {(card.est_qty_fractional ?? 0).toFixed(3)}주)
                  </span>
                </div>
              )}
              <div className="text-red-500">
                손절 <span className="text-muted-foreground">·</span> −{risk.sl_pct}% ={" "}
                <span className="font-bold">{_fmtUsd(card.sl_price, 4)}</span> or {card.sl_days}거래일
              </div>
              <div className="text-emerald-500">
                TP <span className="text-muted-foreground">·</span> +{risk.tp_trigger_pct}% ={" "}
                <span className="font-bold">{_fmtUsd(card.tp_trigger_price, 4)}</span>{" "}
                <span className="text-muted-foreground">후 트레일링 -{card.trail_pct}%</span>
              </div>
              <div className={card.min_rr_warning ? "text-amber-500" : "text-muted-foreground"}>
                최소 R:R <span className="text-muted-foreground">·</span>{" "}
                <span className="font-bold">{card.min_rr}</span>
                {card.min_rr_warning && ` ⚠ Rulebook ${risk.min_rr_warning} 미달 · 확인 후 진행`}
              </div>
            </div>
          </div>

          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={onOpenJournal}
              className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/80"
            >
              📓 저널에 기록
            </button>
          </div>
        </>
      )}
    </article>
  );
}
