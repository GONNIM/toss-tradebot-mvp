"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  VipStatus,
  VipConfig,
  VipConfigPatch,
  VipMarketStats,
  VipQuote,
} from "@/lib/api";

// ─────────────────────────────────────────────
// Format helpers
// ─────────────────────────────────────────────

function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

function fmtUsd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toFixed(digits)}`;
}

function fmtKrw(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(Math.round(v));
  return `${sign}₩${abs.toLocaleString("ko-KR")}`;
}

function classPnL(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  if (v > 0) return "text-emerald-500";
  if (v < 0) return "text-rose-500";
  return "text-muted-foreground";
}

function relTime(unixSec: number): string {
  const now = Date.now() / 1000;
  const diff = now - unixSec;
  if (diff < 60) return `${Math.floor(diff)}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

function fmtKst(unixSec: number): string {
  const d = new Date(unixSec * 1000);
  const kst = new Date(d.getTime() + 9 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${kst.getUTCFullYear()}-${p(kst.getUTCMonth() + 1)}-${p(kst.getUTCDate())} ${p(kst.getUTCHours())}:${p(kst.getUTCMinutes())} KST`;
}

// ─────────────────────────────────────────────
// Section 1. Hero
// ─────────────────────────────────────────────

function HeroCard({ s }: { s: VipStatus }) {
  const q = s.quote;
  const fx = s.usd_krw;
  const krwPrice = q && fx ? q.close_price * fx.rate : null;

  const marketBadge = () => {
    if (s.is_us_regular_hours)
      return { text: "🟢 정규장", className: "bg-emerald-500/20 text-emerald-400" };
    if (q?.market_status === "OPEN")
      return { text: "🟡 개장 중", className: "bg-amber-500/20 text-amber-400" };
    if (q?.over_market_ratio !== null && q?.over_market_ratio !== undefined)
      return { text: "🌙 AH/PM", className: "bg-indigo-500/20 text-indigo-400" };
    return { text: "📴 마감", className: "bg-muted text-muted-foreground" };
  };
  const badge = marketBadge();

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start gap-4">
        {q?.item_logo_url && (
          <img
            src={q.item_logo_url}
            alt={s.company_name}
            className="h-14 w-14 rounded-full bg-white p-1"
          />
        )}
        <div className="flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <h1 className="text-2xl font-bold">{s.company_name}</h1>
            <span className="text-sm font-mono text-muted-foreground">
              ({s.ticker})
            </span>
            <span
              className={`ml-auto rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}
            >
              {badge.text}
            </span>
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {s.market_stats?.industry_group_kor && (
              <span>{s.market_stats.industry_group_kor}</span>
            )}
            {q?.exchange_name && (
              <span> · {q.exchange_name}</span>
            )}
          </div>
        </div>
      </div>

      {q && (
        <div className="mt-4 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-baseline gap-3">
              <span className="text-4xl font-bold">${q.close_price.toFixed(2)}</span>
              <span className={`text-lg font-semibold ${classPnL(q.fluctuations_ratio / 100)}`}>
                {q.fluctuations_ratio >= 0 ? "▲" : "▼"}{" "}
                {Math.abs(q.fluctuations_ratio).toFixed(2)}%
              </span>
              {q.compare_to_prev_close !== null && (
                <span className={`text-sm ${classPnL(q.compare_to_prev_close)}`}>
                  ({fmtUsd(q.compare_to_prev_close)})
                </span>
              )}
            </div>
            {krwPrice !== null && (
              <div className="mt-1 text-sm text-muted-foreground">
                {fmtKrw(krwPrice)}{" "}
                <span className="text-xs">
                  (환율 {fmtKrw(fx!.rate)} · {fx!.source})
                </span>
              </div>
            )}
            {s.market_stats?.base_price && (
              <div className="mt-1 text-xs text-muted-foreground">
                전일 종가 ${s.market_stats.base_price}
              </div>
            )}
          </div>
          {q.over_market_ratio !== null && q.over_market_ratio !== undefined && (
            <div className="text-right">
              <div className="text-xs text-muted-foreground">시간외</div>
              <div className={`text-sm font-semibold ${classPnL(q.over_market_ratio / 100)}`}>
                {q.over_market_ratio >= 0 ? "▲" : "▼"} {Math.abs(q.over_market_ratio).toFixed(2)}%
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Section 2. My Position
// ─────────────────────────────────────────────

function PositionCard({ s }: { s: VipStatus }) {
  const q = s.quote;
  const fx = s.usd_krw;
  if (!q || s.qty <= 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        보유 수량이 없어 포지션 정보를 표시하지 않습니다.
      </div>
    );
  }
  const cost = s.avg_price * s.qty;
  const eval_ = q.close_price * s.qty;
  const pnlUsd = eval_ - cost;
  const pnlPct = cost > 0 ? pnlUsd / cost : 0;
  const rate = fx?.rate ?? 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-lg font-semibold">💼 내 포지션</h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div>
          <div className="text-xs text-muted-foreground">진입가 · 수량</div>
          <div className="mt-0.5 text-base">
            ${s.avg_price.toFixed(2)} × {s.qty}주
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">매입액</div>
          <div className="mt-0.5 text-base">
            {fmtUsd(cost)}{" "}
            {rate > 0 && (
              <span className="text-xs text-muted-foreground">({fmtKrw(cost * rate)})</span>
            )}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">현재 평가액</div>
          <div className="mt-0.5 text-base">
            {fmtUsd(eval_)}{" "}
            {rate > 0 && (
              <span className="text-xs text-muted-foreground">({fmtKrw(eval_ * rate)})</span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 border-t border-border pt-3">
        <div className="text-xs text-muted-foreground">평가 손익</div>
        <div className="mt-1 flex items-baseline gap-3 flex-wrap">
          <span className={`text-2xl font-bold ${classPnL(pnlUsd)}`}>
            {fmtUsd(pnlUsd)}
          </span>
          {rate > 0 && (
            <span className={`text-lg font-semibold ${classPnL(pnlUsd)}`}>
              {fmtKrw(pnlUsd * rate)}
            </span>
          )}
          <span className={`text-base font-semibold ${classPnL(pnlPct)}`}>
            {pnlUsd >= 0 ? "▲" : "▼"} {pct(pnlPct)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Section 3. Trigger Prices
// ─────────────────────────────────────────────

interface Trigger {
  key: string;
  icon: string;
  label: string;
  triggerPrice: number;
  targetPnlPct: number;
  reached: boolean;
  reachedDirection: "up" | "down";
  alreadySent: boolean;
}

function computeTriggers(s: VipStatus): Trigger[] {
  const q = s.quote;
  if (!q) return [];
  const cur = q.close_price;
  const avg = s.avg_price;
  const t = s.thresholds;
  const sent = s.sent_events || {};
  const triggers: Omit<Trigger, "reached" | "reachedDirection" | "alreadySent">[] = [
    {
      key: "TP1",
      icon: "🎯",
      label: `TP1 (+${(t.tp1_pct * 100).toFixed(0)}%)`,
      triggerPrice: avg * (1 + t.tp1_pct),
      targetPnlPct: t.tp1_pct,
    },
    {
      key: "TP2",
      icon: "🎯🎯",
      label: `TP2 (+${(t.tp2_pct * 100).toFixed(0)}%)`,
      triggerPrice: avg * (1 + t.tp2_pct),
      targetPnlPct: t.tp2_pct,
    },
    {
      key: "STOP_APPROACH",
      icon: "🛑",
      label: `STOP (${(t.stop_pct * 100).toFixed(0)}%)`,
      triggerPrice: avg * (1 + t.stop_pct),
      targetPnlPct: t.stop_pct,
    },
    {
      key: "TRAIL_ARMED",
      icon: "🔒",
      label: `TRAIL_ARM (+${(t.trail_arm_pct * 100).toFixed(0)}%)`,
      triggerPrice: avg * (1 + t.trail_arm_pct),
      targetPnlPct: t.trail_arm_pct,
    },
  ];
  return triggers.map((tr) => ({
    ...tr,
    reached:
      tr.targetPnlPct >= 0 ? cur >= tr.triggerPrice : cur <= tr.triggerPrice,
    reachedDirection: tr.targetPnlPct >= 0 ? "up" : "down",
    alreadySent: !!sent[tr.key],
  }));
}

function TriggerCard({ s }: { s: VipStatus }) {
  const triggers = computeTriggers(s);
  const q = s.quote;
  if (!q || triggers.length === 0) return null;
  const rate = s.usd_krw?.rate ?? 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-lg font-semibold">🎯 다음 트리거 가격</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="pb-2 text-left">이벤트</th>
              <th className="pb-2 text-right">트리거가</th>
              <th className="pb-2 text-right">현재 대비</th>
              <th className="pb-2 text-right">도달 시 손익</th>
              <th className="pb-2 text-center">상태</th>
            </tr>
          </thead>
          <tbody>
            {triggers.map((t) => {
              const distancePct = (t.triggerPrice - q.close_price) / q.close_price;
              const pnlAtTrigger = (t.triggerPrice - s.avg_price) * s.qty;
              return (
                <tr key={t.key} className="border-b border-border/50">
                  <td className="py-2">
                    <span className="mr-1">{t.icon}</span>
                    {t.label}
                  </td>
                  <td className="py-2 text-right font-mono">
                    ${t.triggerPrice.toFixed(2)}
                  </td>
                  <td className={`py-2 text-right ${classPnL(distancePct)}`}>
                    {distancePct >= 0 ? "▲" : "▼"} {Math.abs(distancePct * 100).toFixed(1)}%
                  </td>
                  <td className={`py-2 text-right ${classPnL(t.targetPnlPct)}`}>
                    {fmtUsd(pnlAtTrigger)}
                    {rate > 0 && (
                      <div className="text-xs">{fmtKrw(pnlAtTrigger * rate)}</div>
                    )}
                  </td>
                  <td className="py-2 text-center">
                    {t.alreadySent ? (
                      <span className="rounded bg-rose-500/20 px-2 py-0.5 text-xs text-rose-400">
                        발송됨
                      </span>
                    ) : t.reached ? (
                      <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-400">
                        도달
                      </span>
                    ) : (
                      <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        대기
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        ※ 매수가 {fmtUsd(s.avg_price)} 기준. 각 트리거 도달 시 Telegram 으로 알림 발송 (24h cooldown).
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────
// Section 4. Market Stats
// ─────────────────────────────────────────────

function MarketCard({ s }: { s: VipStatus }) {
  const ms = s.market_stats;
  const q = s.quote;
  if (!ms || !q) return null;

  // 52주 밴드 위치 계산
  const high52 = ms.high_52w ? parseFloat(ms.high_52w) : null;
  const low52 = ms.low_52w ? parseFloat(ms.low_52w) : null;
  const bandPct =
    high52 && low52 && high52 > low52
      ? Math.min(100, Math.max(0, ((q.close_price - low52) / (high52 - low52)) * 100))
      : null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-lg font-semibold">📊 시장 통계</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* 오늘 시세 */}
        <div>
          <div className="mb-2 text-xs font-medium text-muted-foreground">오늘의 시세</div>
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <StatRow label="시가" value={ms.open_price ? `$${ms.open_price}` : "—"} />
            <StatRow label="고가" value={ms.high_price ? `$${ms.high_price}` : "—"} />
            <StatRow label="저가" value={ms.low_price ? `$${ms.low_price}` : "—"} />
            <StatRow label="종가" value={`$${q.close_price.toFixed(2)}`} />
            <StatRow label="거래량" value={ms.accumulated_trading_volume ?? "—"} />
            <StatRow label="대금" value={ms.accumulated_trading_value ?? "—"} />
            <StatRow label="시가총액" value={ms.market_value ?? "—"} />
          </dl>
        </div>

        {/* 밸류에이션 · 배당 */}
        <div>
          <div className="mb-2 text-xs font-medium text-muted-foreground">밸류에이션 & 배당</div>
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <StatRow label="PER" value={ms.per ?? "—"} />
            <StatRow label="EPS" value={ms.eps ? `$${ms.eps}` : "—"} />
            <StatRow label="PBR" value={ms.pbr ?? "—"} />
            <StatRow label="BPS" value={ms.bps ? `$${ms.bps}` : "—"} />
            <StatRow label="주당배당" value={ms.dividend ? `$${ms.dividend}` : "—"} />
            <StatRow label="배당수익률" value={ms.dividend_yield_ratio ?? "—"} />
            <StatRow label="배당락일" value={ms.ex_dividend_at ?? "—"} />
            <StatRow label="배당일" value={ms.dividend_at ?? "—"} />
          </dl>
        </div>
      </div>

      {high52 !== null && low52 !== null && bandPct !== null && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-muted-foreground">52주 밴드</span>
            <span className="font-medium">
              밴드 내 {bandPct.toFixed(0)}%{" "}
              <span className="text-muted-foreground">
                {bandPct < 30 ? "· 저점 부근" : bandPct > 70 ? "· 고점 부근" : ""}
              </span>
            </span>
          </div>
          <div className="relative h-2 rounded-full bg-muted">
            <div
              className="absolute top-0 h-2 w-1 rounded-full bg-primary shadow"
              style={{ left: `calc(${bandPct}% - 2px)` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-xs text-muted-foreground">
            <span>저 ${low52.toFixed(2)}</span>
            <span>현재 ${q.close_price.toFixed(2)}</span>
            <span>고 ${high52.toFixed(2)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </>
  );
}

// ─────────────────────────────────────────────
// Section 5. Alerts (sent history + upcoming)
// ─────────────────────────────────────────────

const EVENT_LABEL: Record<string, { icon: string; kor: string; desc: string }> = {
  TP1: { icon: "🎯", kor: "TP1 (1차 익절)", desc: "매수가 +7% 도달" },
  TP2: { icon: "🎯🎯", kor: "TP2 (2차 익절)", desc: "매수가 +15% 도달" },
  STOP_APPROACH: {
    icon: "🛑",
    kor: "STOP (손절 접근)",
    desc: "매수가 -5% 접근 · 손절 검토 신호",
  },
  TRAIL_ARMED: {
    icon: "🔒",
    kor: "TRAIL_ARMED (추적 시작)",
    desc: "매수가 +10% 도달 · 최고점 추적 개시",
  },
  TRAIL_GIVEBACK: {
    icon: "📉",
    kor: "TRAIL_GIVEBACK (수익 반납)",
    desc: "TRAIL 활성 후 최고점 대비 -3% 반납",
  },
};

const COOLDOWN_SEC = 24 * 3600;

function AlertsCard({ s }: { s: VipStatus }) {
  const sent = s.sent_events || {};
  const sentKeys = Object.keys(sent).sort((a, b) => sent[b] - sent[a]);
  const now = Date.now() / 1000;

  const eventOrder = ["TP1", "TP2", "STOP_APPROACH", "TRAIL_ARMED", "TRAIL_GIVEBACK"];
  const pending = eventOrder.filter((k) => !sent[k]);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-lg font-semibold">📬 알림 이력</h2>

      {sentKeys.length > 0 ? (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">최근 발송</div>
          {sentKeys.map((k) => {
            const ts = sent[k];
            const info = EVENT_LABEL[k] || { icon: "📣", kor: k, desc: "" };
            const nextAt = ts + COOLDOWN_SEC;
            const cooldownLeft = Math.max(0, nextAt - now);
            return (
              <div key={k} className="rounded border border-border/60 p-2 text-sm">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span>{info.icon}</span>
                  <span className="font-medium">{info.kor}</span>
                  <span className="text-xs text-muted-foreground">
                    {fmtKst(ts)} ({relTime(ts)})
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{info.desc}</div>
                {cooldownLeft > 0 ? (
                  <div className="mt-1 text-xs text-amber-400">
                    다음 발송 가능: {fmtKst(nextAt)} ({Math.ceil(cooldownLeft / 3600)}h 남음)
                  </div>
                ) : (
                  <div className="mt-1 text-xs text-emerald-400">쿨다운 종료 · 재발송 대기</div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">아직 발송된 알림이 없습니다.</div>
      )}

      {pending.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">대기 중 이벤트</div>
          <ul className="space-y-1 text-sm">
            {pending.map((k) => {
              const info = EVENT_LABEL[k] || { icon: "📣", kor: k, desc: "" };
              return (
                <li key={k} className="flex justify-between">
                  <span>
                    <span className="mr-1">{info.icon}</span>
                    {info.kor}
                  </span>
                  <span className="text-xs text-muted-foreground">{info.desc}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Section 6. Activist
// ─────────────────────────────────────────────

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={
        "inline-block rounded-full px-2 py-0.5 text-xs font-medium " +
        (active
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-muted text-muted-foreground")
      }
    >
      {active ? "ACTIVE" : "INACTIVE"}
    </span>
  );
}

function ActivistCard({ s, onEdit }: { s: VipStatus; onEdit: () => void }) {
  const a = s.activist;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">🕵️ Activist 감시</h2>
        <div className="flex items-center gap-2">
          <StatusBadge active={s.activist_active} />
          <button
            onClick={onEdit}
            className="rounded border border-border bg-background px-3 py-1 text-xs hover:bg-muted"
          >
            편집
          </button>
        </div>
      </div>

      {a.enabled && (
        <div className="mb-3 rounded bg-muted/50 p-2 text-xs text-muted-foreground">
          💡 <strong>Activist 란?</strong> 상장사 지분을 5% 이상 보유한 활동주주가 SEC 에
          제출하는 <strong>SC 13D/G</strong> 필링을 실시간 감시합니다. 지분 증가·감소·
          경영권 요구 등이 담기며, 통상 주가 급등락의 선행 신호입니다.
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">이름</div>
          <div>{a.name || "—"}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">CIK</div>
          <div className="font-mono">{a.cik || "—"}</div>
        </div>
        <div className="sm:col-span-2">
          <div className="text-xs text-muted-foreground">대상 키워드</div>
          <div className="flex flex-wrap gap-1">
            {a.keywords.length ? (
              a.keywords.map((k) => (
                <span
                  key={k}
                  className="rounded bg-muted px-2 py-0.5 text-xs font-mono"
                >
                  {k}
                </span>
              ))
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
        </div>
      </div>

      {a.latest_target ? (
        <div className="mt-4 rounded-lg border-2 border-cyan-500/60 bg-slate-950 p-3 text-sm shadow-lg">
          <div className="mb-2 flex items-baseline gap-2 flex-wrap">
            <span className="text-xs font-bold uppercase tracking-wider text-cyan-300">
              🎯 최신 대상 필링
            </span>
            <span className="ml-auto text-[10px] font-mono text-slate-400">
              Filing {a.latest_target.filing_date}
            </span>
          </div>

          {/* 폼 배지 · 힌트 */}
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="rounded bg-amber-500 px-2 py-0.5 font-mono text-xs font-bold text-slate-900 shadow">
              {a.latest_target.form}
            </span>
            {a.latest_target.form_hint && (
              <span className="text-xs font-medium text-amber-200">
                {a.latest_target.form_hint}
              </span>
            )}
          </div>

          {/* 이슈어 (SC 13D XML 파싱 결과) */}
          {a.latest_target.details?.issuer_name && (
            <div className="mt-2 flex items-baseline gap-2 flex-wrap">
              <span className="text-lg font-bold text-white">
                {a.latest_target.details.issuer_name}
              </span>
              {a.latest_target.details.issuer_cik && (
                <span className="text-[10px] font-mono text-slate-400">
                  issuer CIK {a.latest_target.details.issuer_cik}
                  {a.latest_target.details.issuer_cusip &&
                    ` · CUSIP ${a.latest_target.details.issuer_cusip}`}
                </span>
              )}
            </div>
          )}

          {/* 지분 grid — 지분율/보유주식/수정차수/이벤트일 */}
          {a.latest_target.details &&
           (a.latest_target.details.percent_of_class != null ||
            a.latest_target.details.aggregate_amount_owned != null) && (
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {a.latest_target.details.percent_of_class != null && (
                <div className="rounded-lg border border-cyan-400/50 bg-cyan-500/15 p-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">
                    지분율
                  </div>
                  <div className="mt-0.5 text-3xl font-black leading-none text-cyan-100">
                    {a.latest_target.details.percent_of_class.toFixed(1)}
                    <span className="text-xl">%</span>
                  </div>
                </div>
              )}
              {a.latest_target.details.aggregate_amount_owned != null && (
                <div className="rounded-lg border border-emerald-400/50 bg-emerald-500/15 p-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                    보유 주식
                  </div>
                  <div className="mt-0.5 text-base font-bold font-mono text-emerald-100">
                    {a.latest_target.details.aggregate_amount_owned.toLocaleString()}
                  </div>
                </div>
              )}
              {a.latest_target.details.amendment_no != null && (
                <div className="rounded-lg border border-fuchsia-400/50 bg-fuchsia-500/15 p-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-fuchsia-300">
                    수정 차수
                  </div>
                  <div className="mt-0.5 text-base font-bold text-fuchsia-100">
                    Amendment #{a.latest_target.details.amendment_no}
                  </div>
                </div>
              )}
              {a.latest_target.details.date_of_event && (
                <div className="rounded-lg border border-indigo-400/50 bg-indigo-500/15 p-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-indigo-300">
                    이벤트 발생일
                  </div>
                  <div className="mt-0.5 text-base font-bold text-indigo-100">
                    {a.latest_target.details.date_of_event}
                  </div>
                </div>
              )}
            </div>
          )}

          {a.latest_target.details?.securities_class_title && (
            <div className="mt-3 rounded bg-slate-800 px-2 py-1 text-xs text-slate-200">
              <span className="font-semibold text-slate-400">증권 클래스:</span>{" "}
              {a.latest_target.details.securities_class_title}
            </div>
          )}

          {/* primary_desc (XML issuer_name 없을 때 fallback) */}
          {!a.latest_target.details?.issuer_name && a.latest_target.primary_desc && (
            <div className="mt-2 text-sm font-medium text-white">
              {a.latest_target.primary_desc}
            </div>
          )}

          {a.latest_target.details?.transaction_purpose && (
            <details className="mt-3 rounded border border-slate-700 bg-slate-900">
              <summary className="cursor-pointer px-2 py-1 text-xs font-semibold text-amber-300 hover:bg-slate-800">
                📝 Item 4 — 거래 목적/사유 (원문 발췌 · 클릭 펼치기)
              </summary>
              <div className="whitespace-pre-wrap border-t border-slate-700 p-2 font-mono text-[11px] text-slate-100">
                {a.latest_target.details.transaction_purpose}
              </div>
            </details>
          )}

          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {a.latest_target.filing_detail_url && (
              <a
                href={a.latest_target.filing_detail_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1 font-medium text-slate-100 hover:bg-slate-700 hover:text-white"
              >
                📄 원문 필링 ↗
              </a>
            )}
            {a.filer_search_url && (
              <a
                href={a.filer_search_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1 font-medium text-slate-100 hover:bg-slate-700 hover:text-white"
              >
                🔍 {a.name.split(" ")[0]} 다른 필링 ↗
              </a>
            )}
            {a.latest_target.details?.issuer_name && (
              <a
                href={`https://www.google.com/search?q=${encodeURIComponent(a.latest_target.details.issuer_name + " SEC filing")}`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1 font-medium text-slate-100 hover:bg-slate-700 hover:text-white"
              >
                🌐 웹 검색 ↗
              </a>
            )}
            <span className="ml-auto text-[10px] font-mono text-slate-500">
              Accession {a.latest_target.accession}
            </span>
          </div>
        </div>
      ) : a.enabled ? (
        <div className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
          대상 매치 필링 없음. 아래 최근 이력에서 수동 확인 가능.
        </div>
      ) : null}

      {a.recent_forms && a.recent_forms.length > 0 && (
        <details className="mt-3 rounded border border-slate-700 bg-slate-900/60">
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800/50">
            📋 {a.name || "Activist"} 최근 필링 10건 (activist 관점 전체 · 클릭 펼치기)
          </summary>
          <ul className="divide-y divide-slate-800">
            {a.recent_forms.map((f) => (
              <li key={f.accession} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                <span className="w-24 shrink-0 font-mono text-slate-400">{f.date}</span>
                <span className="w-32 shrink-0 truncate rounded bg-slate-800 px-1.5 py-0.5 font-mono font-medium text-slate-100">
                  {f.form}
                </span>
                <span className="flex-1 truncate text-slate-300">
                  {f.form_hint || f.desc || "—"}
                </span>
                {f.filing_detail_url && (
                  <a
                    href={f.filing_detail_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-slate-100 hover:bg-slate-700"
                  >
                    📄 ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Section 7. Glossary
// ─────────────────────────────────────────────

function GlossaryCard() {
  return (
    <details className="rounded-lg border border-border bg-card p-4">
      <summary className="cursor-pointer text-lg font-semibold">
        📖 용어 · 알림 사용법
      </summary>
      <div className="mt-3 space-y-3 text-sm">
        <div>
          <div className="font-medium">TP1 / TP2 (Take Profit · 익절)</div>
          <p className="text-muted-foreground">
            매수가 대비 각각 +7% / +15% 상승 도달 시 부분 익절 검토 신호. 자동 매도는
            하지 않음. Telegram 알림 1회 발송 후 24h cooldown.
          </p>
        </div>
        <div>
          <div className="font-medium">STOP_APPROACH (손절 접근)</div>
          <p className="text-muted-foreground">
            매수가 대비 -5% 도달 시 손절 검토 신호. 이 알림 자체는 매매를 실행하지 않고
            사용자에게 결정을 맡깁니다.
          </p>
        </div>
        <div>
          <div className="font-medium">TRAIL_ARMED (트레일링 활성)</div>
          <p className="text-muted-foreground">
            매수가 대비 +10% 도달 시 최고점 추적 개시. 활성화 이후엔 최고점 P&L 을 계속
            갱신하며 giveback 감지 대기.
          </p>
        </div>
        <div>
          <div className="font-medium">TRAIL_GIVEBACK (수익 반납)</div>
          <p className="text-muted-foreground">
            TRAIL 활성 후 최고점 대비 -3% 반납 시 "수익 잠금" 검토 알림. 상승분을 잃기
            전에 부분 청산할지 판단하도록 도움.
          </p>
        </div>
        <div>
          <div className="font-medium">Activist (SEC 필링)</div>
          <p className="text-muted-foreground">
            <strong>SC 13D/G</strong> — 지분 5% 이상 보유 주주 신고서. Trian Partners 처럼
            이사회 영향력을 행사하는 활동주주의 지분 변동은 통상 주가 급등락의 선행 신호로
            해석됩니다.
          </p>
        </div>
        <div className="rounded border border-amber-500/50 bg-amber-500/10 p-2 text-xs text-amber-400">
          ⚠️ 이 페이지는 <strong>참고 신호 알림</strong>이며 자동 매매를 수행하지 않습니다.
          모든 매매 결정은 사용자 본인의 판단입니다.
        </div>
      </div>
    </details>
  );
}

// ─────────────────────────────────────────────
// Section 8. External Links
// ─────────────────────────────────────────────

function LinksCard({ s }: { s: VipStatus }) {
  const yahooTicker = s.ticker.split(".")[0];
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-lg font-semibold">🔗 외부 참조</h2>
      <div className="flex flex-wrap gap-2 text-sm">
        <ExtLink
          href={`https://finance.yahoo.com/quote/${yahooTicker}`}
          label="Yahoo Finance"
        />
        <ExtLink
          href={`https://m.stock.naver.com/worldstock/stock/${s.ticker}/total`}
          label="네이버 금융"
        />
        <ExtLink
          href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000030697&type=&dateb=&owner=include&count=40`}
          label="SEC EDGAR (회사)"
        />
        {s.activist.cik && (
          <ExtLink
            href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${s.activist.cik}&type=SC+13&owner=include&count=40`}
            label={`SEC EDGAR (${s.activist.name || "Activist"})`}
          />
        )}
      </div>
    </div>
  );
}

function ExtLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="rounded border border-border bg-background px-3 py-1.5 hover:bg-muted"
    >
      {label} ↗
    </a>
  );
}

// ─────────────────────────────────────────────
// Section 9. Page Meta
// ─────────────────────────────────────────────

function MetaCard({ s }: { s: VipStatus }) {
  const fx = s.usd_krw;
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>
          폴링: {s.is_us_regular_hours ? "정규장 30초" : "AH/PM 5분"}
        </span>
        <span>데이터: 네이버 금융 API (delayTime 0)</span>
        {s.quote?.local_traded_at && (
          <span>US 거래시각: {s.quote.local_traded_at.slice(0, 16)}</span>
        )}
        {fx && (
          <span>
            환율: {fmtKrw(fx.rate)} ({fx.source}) · {relTime(fx.fetched_at)}
          </span>
        )}
        <span>페이지 자동 새로고침: 30초</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Activist Editor Modal (기존 유지)
// ─────────────────────────────────────────────

function ActivistEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: VipConfig;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(initial.activist.enabled);
  const [cik, setCik] = useState(initial.activist.cik);
  const [name, setName] = useState(initial.activist.name);
  const [keywords, setKeywords] = useState(initial.activist.keywords.join(", "));
  const [saveError, setSaveError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (body: VipConfigPatch) => api.memeWatch.vip.patchConfig(body),
    onSuccess: () => {
      onSaved();
    },
    onError: (err: Error) => {
      setSaveError(err.message);
    },
  });

  const submit = () => {
    setSaveError(null);
    const kw = keywords
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    mut.mutate({
      activist: { enabled, cik: cik.trim(), name: name.trim(), keywords: kw },
    });
  };

  const reset = () => {
    mut.mutate({
      activist: { enabled: false, cik: "", name: "", keywords: [] },
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Activist 설정 편집</h3>
          <button
            onClick={onClose}
            className="rounded border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            닫기
          </button>
        </div>

        <div className="space-y-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>Activist tracker 활성</span>
          </label>

          <div>
            <label className="text-xs text-muted-foreground">CIK</label>
            <input
              type="text"
              value={cik}
              onChange={(e) => setCik(e.target.value)}
              placeholder="예: 0001345471 (Trian)"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              SEC EDGAR CIK · 10자리 zero-padding 자동 · 편집 후 저장 즉시 반영 (재시작 X).
            </p>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">이름 (알림 표기용)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: Trian Partners"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">
              대상 키워드 (콤마 구분)
            </label>
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="예: WEN, WENDY"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              SEC 필링 description 에 이 문자열이 포함되면 매치.
            </p>
          </div>

          {saveError && (
            <div className="rounded border border-rose-500/50 bg-rose-500/10 p-2 text-xs text-rose-400">
              저장 실패: {saveError}
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-between gap-2">
          <button
            onClick={reset}
            disabled={mut.isPending}
            className="rounded border border-rose-500/50 px-3 py-1.5 text-xs text-rose-400 hover:bg-rose-500/10 disabled:opacity-50"
          >
            override 초기화 (env 기본값 복귀)
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              취소
            </button>
            <button
              onClick={submit}
              disabled={mut.isPending}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {mut.isPending ? "저장 중…" : "저장"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────

export default function VipPage() {
  const qc = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);

  const statusQ = useQuery({
    queryKey: ["vip", "status"],
    queryFn: () => api.memeWatch.vip.status(),
    refetchInterval: 30_000,
  });

  const configQ = useQuery({
    queryKey: ["vip", "config"],
    queryFn: () => api.memeWatch.vip.getConfig(),
    enabled: editorOpen,
  });

  useEffect(() => {
    if (editorOpen) qc.invalidateQueries({ queryKey: ["vip", "config"] });
  }, [editorOpen, qc]);

  const s = statusQ.data;

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold">🕵️ VIP 개별 감시</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            실 매수 종목 심층 감시 · 매수가 기반 알림 + Activist SEC 필링 추적
          </p>
        </div>
        {s && <StatusBadge active={s.active} />}
      </header>

      {statusQ.isLoading && (
        <div className="rounded border border-border bg-card p-4 text-sm text-muted-foreground">
          로딩 중…
        </div>
      )}

      {statusQ.isError && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-400">
          상태 조회 실패: {(statusQ.error as Error).message}
        </div>
      )}

      {s && !s.active && (
        <div className="rounded border border-amber-500/50 bg-amber-500/10 p-4 text-sm">
          <div className="font-medium text-amber-400">감시 비활성</div>
          <p className="mt-1 text-muted-foreground">
            서버 <code>backend/.env.sops.yaml</code> 에{" "}
            <code>VIP_ENABLED=true</code> 와 <code>VIP_AVG_PRICE</code> ({">"}0) 설정 후 커밋·push.
            (2분 내 자동 반영)
          </p>
        </div>
      )}

      {s && s.active && (
        <>
          <HeroCard s={s} />
          <PositionCard s={s} />
          <TriggerCard s={s} />
          <MarketCard s={s} />
          <AlertsCard s={s} />
          <ActivistCard s={s} onEdit={() => setEditorOpen(true)} />
          <GlossaryCard />
          <LinksCard s={s} />
          <MetaCard s={s} />
        </>
      )}

      {editorOpen && configQ.data && (
        <ActivistEditor
          initial={configQ.data}
          onClose={() => setEditorOpen(false)}
          onSaved={() => {
            setEditorOpen(false);
            qc.invalidateQueries({ queryKey: ["vip", "status"] });
            qc.invalidateQueries({ queryKey: ["vip", "config"] });
          }}
        />
      )}
    </div>
  );
}
