"use client";

// Serenity Ticker Card · Fable 5 재설계 (2026-08-14):
// 정보 위계 4행 (모바일 375px 유지):
//   1행 · 티커 + Financing/Serenity tier + Bull%(90d) 정체성
//   2행 · 🕐 마지막 언급 (신선도 · 최신 1건 stance) — 카드의 새 주인공
//   3행 · 📈 7d/28d/90d + 추세 배지 (🔥/→/❄) — 언급이 늘고 있나 계산 없이 읽기
//   4행 · vs prior close (또는 관찰 전용 배지) + 도메인 태그
// today mentions/stance 는 표시 강등 (백엔드 보존 · 실시간 크롤 시 부활)

import Link from "next/link";
import type { TickerCardItem } from "@/lib/serenity/types";

const TIER_STYLE: Record<string, string> = {
  S: "bg-purple-500/20 text-purple-400 border-purple-500/40",
  A: "bg-blue-500/20 text-blue-400 border-blue-500/40",
  B: "bg-emerald-500/20 text-emerald-500 border-emerald-500/40",
  C: "bg-amber-500/20 text-amber-500 border-amber-500/40",
  D: "bg-orange-500/20 text-orange-500 border-orange-500/40",
  F: "bg-red-500/20 text-red-500 border-red-500/40",
};

const STANCE_META: Record<string, { label: string; icon: string; cls: string }> = {
  bullish: { label: "bullish", icon: "▲", cls: "text-emerald-500" },
  bearish: { label: "bearish", icon: "▼", cls: "text-red-500" },
  neutral: { label: "neutral", icon: "●", cls: "text-slate-400" },
  calibration: { label: "cal", icon: "◆", cls: "text-amber-500" },
  mixed: { label: "mixed", icon: "◆", cls: "text-amber-500" },
};

function _fmtSignedPct(v: number | null): { txt: string; cls: string } {
  if (v === null || v === undefined) return { txt: "—", cls: "text-muted-foreground" };
  const sign = v >= 0 ? "+" : "";
  const cls = v >= 0 ? "text-emerald-500" : "text-red-500";
  return { txt: `${sign}${v.toFixed(1)}%`, cls };
}

// 상대 시간 (한국어) · Fable 5: 타임존 무관 · 크롤 지연에 강건
function relTime(iso: string | null): { txt: string; days: number | null; silent: boolean } {
  if (!iso) return { txt: "언급 없음", days: null, silent: true };
  const dt = new Date(iso);
  const diffMs = Date.now() - dt.getTime();
  const diffMin = diffMs / 60000;
  const diffH = diffMs / 3_600_000;
  const diffD = diffMs / 86_400_000;
  let txt: string;
  if (diffMin < 1) txt = "방금";
  else if (diffH < 1) txt = `${Math.round(diffMin)}분 전`;
  else if (diffH < 24) txt = `${Math.round(diffH)}시간 전`;
  else if (diffD < 30) txt = `${Math.round(diffD)}일 전`;
  else if (diffD < 365) txt = `${Math.round(diffD / 30)}개월 전`;
  else txt = `${(diffD / 365).toFixed(1)}년 전`;
  return { txt, days: diffD, silent: diffD >= 7 };
}

// 추세 배지 · (7d/7) ÷ (28d/28) 비율
function trendBadge(m7: number, m28: number): { icon: string; ratio: number; cls: string } | null {
  if (m28 === 0) return null; // 계산 불가
  const rate7 = m7 / 7;
  const rate28 = m28 / 28;
  const ratio = rate7 / rate28;
  if (ratio >= 1.5) return { icon: "🔥", ratio, cls: "text-red-500" };
  if (ratio <= 0.5) return { icon: "❄", ratio, cls: "text-sky-400" };
  return { icon: "→", ratio, cls: "text-muted-foreground" };
}

export function TickerCard({ item }: { item: TickerCardItem }) {
  const financing = item.financing_tier;
  const serenity = item.serenity_tier;
  const prior = _fmtSignedPct(item.vs_prior_close_pct);
  const rt = relTime(item.last_signal_at);
  const latestStance = STANCE_META[item.latest_stance ?? "neutral"] ?? STANCE_META.neutral;
  const trend = trendBadge(item.mentions_7d, item.mentions_28d);
  const hasPrice = item.vs_prior_close_pct !== null;

  return (
    <Link
      href={`/influencer/serenity/${item.ticker}`}
      className={`block rounded-lg border p-3 transition hover:border-primary/60 ${
        item.auto_avoid ? "border-red-500/40 bg-red-500/5" : "border-border bg-card"
      }`}
    >
      {/* 1행 · 정체성: 티커 + tier + Bull%(90d) */}
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono text-lg font-bold">{item.ticker}</span>
        {financing && (
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
              TIER_STYLE[financing] ?? "border-slate-500/40 bg-slate-500/20 text-slate-400"
            }`}
            title={`Financing tier ${financing}`}
          >
            F:{financing}
          </span>
        )}
        {serenity && (
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
              TIER_STYLE[serenity] ?? "border-slate-500/40 bg-slate-500/20 text-slate-400"
            }`}
            title={`Serenity conviction tier ${serenity}`}
          >
            S:{serenity}
          </span>
        )}
        <span className="ml-auto flex items-baseline gap-1 text-xs">
          <span className="text-emerald-500">▲</span>
          <span className="font-semibold">{item.bullish_pct_90d.toFixed(0)}%</span>
          <span className="text-muted-foreground">bullish (90d)</span>
        </span>
      </div>

      {/* 2행 · 신선도 (카드의 새 주인공): 🕐 마지막 언급 · 최신 1건 방향 */}
      <div className="mt-2 flex flex-wrap items-baseline gap-2 text-[11px]">
        {rt.silent ? (
          <span
            className="text-muted-foreground"
            title={item.last_signal_at ? `마지막 언급 ${new Date(item.last_signal_at).toLocaleString("ko-KR")}` : "언급 없음"}
          >
            🕸 {rt.days === null ? "언급 없음" : `${Math.round(rt.days)}일+ 침묵`}
          </span>
        ) : (
          <>
            <span
              className="text-foreground"
              title={item.last_signal_at ? `마지막 언급 ${new Date(item.last_signal_at).toLocaleString("ko-KR")}` : undefined}
            >
              🕐 마지막 언급: <strong>{rt.txt}</strong>
            </span>
            {item.latest_stance && (
              <span className={`text-[11px] font-semibold ${latestStance.cls}`}>
                {latestStance.icon} {latestStance.label}
              </span>
            )}
          </>
        )}
      </div>

      {/* 3행 · 추세: 7d/28d/90d 한 줄 압축 + 배지 */}
      <div className="mt-1 flex flex-wrap items-baseline gap-1 text-[11px] text-muted-foreground">
        <span>📈 7d <strong className="text-foreground">{item.mentions_7d}</strong></span>
        <span>· 28d <strong className="text-foreground">{item.mentions_28d}</strong></span>
        <span>· 90d <strong className="text-foreground">{item.mention_count_90d}</strong></span>
        {trend && (
          <span className={`ml-1 font-semibold ${trend.cls}`} title={`(7d/7) ÷ (28d/28) = ${trend.ratio.toFixed(2)}`}>
            추세 {trend.icon}×{trend.ratio.toFixed(1)}
          </span>
        )}
      </div>

      {/* 4행 · 가격 또는 관찰 전용 + 태그 */}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
        {hasPrice ? (
          <span className={prior.cls} title="전일 종가 대비">
            vs prior {prior.txt}
          </span>
        ) : (
          <span
            className="rounded bg-slate-500/20 px-1.5 py-0.5 font-semibold text-slate-300"
            title="가격 피드 없음 · 매매 불가"
          >
            👁 관찰 전용
          </span>
        )}
        {item.domain_tags.slice(0, 3).map((tag) => (
          <span
            key={tag}
            className="rounded bg-slate-500/20 px-1.5 py-0.5 text-slate-300"
          >
            {tag}
          </span>
        ))}
        {item.anti_pattern_flags.map((flag) => (
          <span
            key={flag}
            className="rounded bg-red-500/20 px-1.5 py-0.5 text-red-400"
          >
            ⚠ {flag}
          </span>
        ))}
        {item.auto_avoid && <span className="ml-auto font-semibold text-red-500">AVOID</span>}
      </div>
    </Link>
  );
}
