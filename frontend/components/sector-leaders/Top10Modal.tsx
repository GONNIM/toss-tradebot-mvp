"use client";

/**
 * 🏆 투자 종목 Top 10 모달 (B-2j).
 *
 * 매력도 점수(Confluence 0.5 + 신뢰도 0.3 + R/R 0.2) 상위 10 종목.
 * 진입가 v2.0 (2026-07-08~): 52W 위치 + ATR14 완충 + 200MA 이격도 기반 과열 판정.
 *   - 과열 (52W ≥85% or MA200 ≥+25%): 🔴 관망
 *   - 정상: 현재가 − 1.0 × ATR14 → 🟢 지금 or 🟡 조정 대기
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Top10Item } from "@/lib/api";
import { formatPct } from "@/lib/utils";

export function Top10Modal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["sector-leaders", "top10", 10],
    queryFn: () => api.sectorLeaders.top10(10),
    enabled: open,
  });

  // ESC 키로 닫기
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-2"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[96vw] max-h-[96vh] flex flex-col overflow-hidden rounded-xl border border-cyan-500/50 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 (고정) */}
        <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2.5">
          <div>
            <h2 className="text-xl font-bold text-foreground">🏆 투자 종목 Top 10</h2>
            <p className="text-xs text-zinc-300 mt-1">
              매력도 = Confluence 0.5 + 신뢰도 0.3 + R/R 0.2 · horizon = 종목별 best_lag
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm text-foreground hover:bg-muted/50"
            aria-label="Close"
          >
            ✕ 닫기 (Esc)
          </button>
        </div>

        {/* 본문 (남은 영역 채움, 내부 표 자체는 가로 스크롤 가능) */}
        <div className="flex-1 overflow-auto p-3">
          {q.isLoading && (
            <div className="rounded-lg border border-border bg-background p-6 text-muted-foreground">
              Top 10 산출 중... (51 종목 매력도 계산)
            </div>
          )}
          {q.error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
              Top 10 호출 실패
            </div>
          )}
          {q.data && <Top10Table items={q.data.items} computedAt={q.data.computed_at} />}
        </div>
      </div>
    </div>
  );
}

function PriceSourceBadge({
  source,
  marketStatus,
  priceAt,
}: {
  source: "live" | "fallback";
  marketStatus: string | null;
  priceAt: string | null;
}) {
  if (source === "fallback") {
    return (
      <div
        className="text-xs text-amber-400 leading-tight mt-0.5"
        title="네이버 실시간 가격 fetch 실패 — 최근 종가 표시"
      >
        ⚠️ 종가 (fallback)
      </div>
    );
  }
  const isOpen = marketStatus === "OPEN";
  const label = isOpen ? "🟢 LIVE" : "⚪ 종가";
  const kstTime = priceAt ? formatKstTime(priceAt) : null;
  return (
    <div className="text-xs text-emerald-300 leading-tight mt-0.5">
      {label}
      {kstTime && <span className="text-zinc-400 ml-1">{kstTime}</span>}
    </div>
  );
}

function formatKstTime(iso: string): string {
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  if (isNaN(d.getTime())) return "";
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())} KST`;
}

function formatComputedAt(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function Top10Table({ items, computedAt }: { items: Top10Item[]; computedAt: string }) {
  return (
    <div className="space-y-2">
      <div className="text-xs text-zinc-300 font-mono">
        산출 시점: {formatComputedAt(computedAt)} · {items.length} 종목
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="border-b border-cyan-500/40 bg-cyan-500/10 sticky top-0">
            <tr className="text-left whitespace-nowrap text-cyan-200 font-semibold">
              <th className="px-2.5 py-2 w-10">#</th>
              <th className="px-2.5 py-2">종목 / 품목</th>
              <th className="px-2.5 py-2 text-right">현재가</th>
              <th className="px-2.5 py-2 text-right">진입가</th>
              <th className="px-2.5 py-2 text-right">예측수익가</th>
              <th className="px-2.5 py-2 text-right">Stop</th>
              <th className="px-2.5 py-2 text-right">Take</th>
              <th className="px-2.5 py-2 text-right">Conf · ★</th>
              <th className="px-2.5 py-2 text-right">매력도</th>
            </tr>
          </thead>
          <tbody className="text-zinc-100">
            {items.map((it) => (
              <Row key={`${it.ticker}-${it.item}`} it={it} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-zinc-200 rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 space-y-3">
        <div className="font-semibold text-cyan-200 text-sm">💡 사용 가이드 — 처음 보시는 분도 이해할 수 있게</div>

        {/* ── 1. 진입 상태 3분류 ── */}
        <div>
          <div className="font-semibold text-cyan-200 mb-1">🎯 진입 상태 3분류 (진입가 컬럼)</div>
          <ul className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <li className="rounded border border-rose-500/30 bg-rose-500/5 p-2">
              <div className="font-semibold text-rose-300">🔴 과열 관망</div>
              <div className="text-zinc-300 mt-0.5">이미 가격이 너무 높이 올라와 있음. <strong>지금 매수하면 물릴 위험 큼</strong> — 조정될 때까지 기다리는 게 안전</div>
            </li>
            <li className="rounded border border-amber-500/30 bg-amber-500/5 p-2">
              <div className="font-semibold text-amber-300">🟡 조정 대기</div>
              <div className="text-zinc-300 mt-0.5">지금 사기엔 조금 비쌈. <strong>표시된 진입가까지 내려오면 매수</strong> 검토. 몇 % 조정 대기인지도 함께 표시</div>
            </li>
            <li className="rounded border border-emerald-500/30 bg-emerald-500/5 p-2">
              <div className="font-semibold text-emerald-300">🟢 지금 매수 가능</div>
              <div className="text-zinc-300 mt-0.5">현재가가 이미 진입가 근처. <strong>바로 매수 검토 가능</strong>한 구간</div>
            </li>
          </ul>
        </div>

        {/* ── 2. 근거 배지 읽는 법 ── */}
        <div>
          <div className="font-semibold text-cyan-200 mb-1">🔍 근거 배지 읽는 법 (진입가 아래 회색 작은 글씨)</div>
          <ul className="space-y-1">
            <li>
              <strong className="text-cyan-100">52W xx%</strong> —{" "}
              <span className="text-zinc-300">최근 1년(52주) 최저가~최고가 사이에서 현재가가 어디쯤인지. <strong>0% = 1년 최저가, 100% = 1년 신고가</strong>. 85% 넘으면 과열로 판정</span>
            </li>
            <li>
              <strong className="text-cyan-100">MA200 +xx%</strong> —{" "}
              <span className="text-zinc-300">최근 200거래일(약 10개월) 평균 주가 대비 지금 얼마나 비싼가. <strong>+119%면 10개월 평균의 2배 넘게 오른 것</strong>. +25% 넘으면 과열 판정</span>
            </li>
            <li>
              <strong className="text-cyan-100">ATR xx,xxx원</strong> —{" "}
              <span className="text-zinc-300">이 종목이 <strong>하루 평균 얼마씩 위아래로 흔들리는지</strong>. 종목 <strong>변동성 크기</strong>를 원 단위로 표시. 진입가는 &quot;현재가 − ATR&quot;로 계산 (하루 변동성만큼 아래에서 대기)</span>
            </li>
          </ul>
        </div>

        {/* ── 3. 컬럼 설명 ── */}
        <div>
          <div className="font-semibold text-cyan-200 mb-1">📊 컬럼별 의미</div>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 list-disc list-inside">
            <li><strong className="text-cyan-100">현재가</strong>: 지금 실시간 시장 가격</li>
            <li><strong className="text-cyan-100">진입가</strong>: 매수 대기 가격 (변동성 조정 반영)</li>
            <li><strong className="text-cyan-100">예측수익가</strong>: X개월 뒤 예상 가격 (수출 데이터 기반 통계 추정)</li>
            <li><strong className="text-cyan-100">Stop</strong>: 손절선 — 이 밑으로 떨어지면 매도 검토</li>
            <li><strong className="text-cyan-100">Take</strong>: 익절선 — 이 위로 올라가면 매도 검토</li>
            <li><strong className="text-cyan-100">매력도</strong>: 종합 점수 0~1, <strong>0.6 이상이면 강한 시그널</strong></li>
          </ul>
        </div>

        {/* ── 4. 실전 예시 ── */}
        <div>
          <div className="font-semibold text-cyan-200 mb-1">📖 실전 예시 — 두 종목 비교</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div className="rounded border border-rose-500/30 bg-rose-500/5 p-2">
              <div className="font-semibold text-zinc-100 mb-1">SK하이닉스 · 현재 2,076,000원</div>
              <ul className="text-zinc-300 space-y-0.5">
                <li>• 52W 68% → 1년 범위 위쪽 68% 지점</li>
                <li>• MA200 <strong className="text-rose-300">+119%</strong> → 10개월 평균의 2배 넘음</li>
                <li>• ATR 225,786원 → 하루 평균 22.6만원씩 흔들림</li>
                <li className="text-rose-300 pt-1">→ 🔴 과열 관망 (매수 자제 권장)</li>
              </ul>
            </div>
            <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2">
              <div className="font-semibold text-zinc-100 mb-1">원익IPS · 현재 102,700원</div>
              <ul className="text-zinc-300 space-y-0.5">
                <li>• 52W 49% → 정확히 1년 범위 중간</li>
                <li>• MA200 +13% → 정상 범위 안</li>
                <li>• ATR 22,986원 → 하루 평균 2.3만원 흔들림</li>
                <li className="text-amber-300 pt-1">→ 🟡 22.4% 조정 대기 (약 79,700원까지 내려오면 매수 검토)</li>
              </ul>
            </div>
          </div>
        </div>

        {/* ── 5. 면책 ── */}
        <div className="text-amber-300 pt-1 border-t border-cyan-500/20">
          ⚠️ <strong>보조 신호일 뿐 투자 권유가 아닙니다.</strong> 최종 매수·매도 결정은 본인 판단·책임하에 진행하세요.
        </div>
      </div>
    </div>
  );
}

function Row({ it }: { it: Top10Item }) {
  const formatKRW = (n: number) => Math.round(n).toLocaleString("ko-KR");
  const confColor =
    it.confluence_score > 0.4 ? "text-emerald-400" :
    it.confluence_score > -0.4 ? "text-amber-400" : "text-rose-400";
  const starColor =
    it.confidence_label === "strong" ? "text-emerald-400" :
    it.confidence_label === "medium" ? "text-cyan-400" : "text-muted-foreground";

  // v2.0 진입가 상태 3분기
  const isOverheat = it.overheat;
  const isReady = !isOverheat && it.entry_status.startsWith("🟢");
  const entryPriceLabel = it.entry_price !== null ? formatKRW(it.entry_price) : "—";
  const entryStatusShort = isOverheat
    ? "🔴 과열 관망"
    : isReady
      ? "🟢 지금"
      : `🟡 ${it.entry_gap_pct !== null ? it.entry_gap_pct.toFixed(1) : "?"}%`;
  const entryStatusColor = isOverheat
    ? "text-rose-300"
    : isReady
      ? "text-emerald-300"
      : "text-amber-300";
  // 근거 배지 + hover tooltip — 초보자용 자연어 설명
  const pos52wPct = Math.round(it.pos_52w * 100);
  const ma200Badge = it.ma200_deviation !== null
    ? `MA200 ${it.ma200_deviation >= 0 ? "+" : ""}${(it.ma200_deviation * 100).toFixed(1)}%`
    : null;
  const atrBadge = `ATR ${formatKRW(it.atr14)}원`;
  const rationale = isOverheat
    ? [`52W ${pos52wPct}%`, ma200Badge].filter(Boolean).join(" · ")
    : `52W ${pos52wPct}% · ${atrBadge}`;
  // hover 툴팁 — 각 배지 자연어 풀이
  const tooltipParts: string[] = [];
  tooltipParts.push(
    `52W ${pos52wPct}%: 최근 1년 최저→최고 사이에서 ${pos52wPct}% 지점 (0=1년 최저가, 100=1년 신고가)`
  );
  if (it.ma200_deviation !== null) {
    const sign = it.ma200_deviation >= 0 ? "위" : "아래";
    const abs = Math.abs(it.ma200_deviation * 100).toFixed(1);
    tooltipParts.push(
      `MA200: 최근 200거래일(약 10개월) 평균가 대비 ${abs}% ${sign}`
    );
  }
  if (!isOverheat) {
    tooltipParts.push(
      `ATR ${formatKRW(it.atr14)}원: 하루 평균 이만큼 위아래로 흔들림 (변동성). 진입가 = 현재가 − ATR`
    );
  }
  const rationaleTooltip = tooltipParts.join("\n\n");

  return (
    <tr className="border-b border-border/40 hover:bg-muted/30 whitespace-nowrap">
      <td className="px-2.5 py-2 font-bold text-cyan-300 text-base">#{it.rank}</td>
      <td className="px-2.5 py-2">
        <div className="font-semibold text-zinc-50 leading-tight">{it.name}</div>
        <div className="text-xs text-zinc-400 font-mono leading-tight mt-0.5">
          {it.ticker} · {it.item}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right whitespace-nowrap">
        <div className="font-mono text-zinc-100 font-semibold leading-tight">
          {formatKRW(it.current_price)}
        </div>
        <PriceSourceBadge
          source={it.price_source}
          marketStatus={it.price_market_status}
          priceAt={it.price_at}
        />
      </td>
      <td className="px-2.5 py-2 text-right">
        <div
          className={`font-mono font-semibold leading-tight ${isOverheat ? "text-zinc-500" : "text-zinc-50"}`}
          title={
            isOverheat
              ? "과열 종목은 진입가를 계산하지 않습니다 (지금 매수하면 물릴 위험이 큼)"
              : `진입가 = 현재가 − ATR14 (하루 평균 변동성만큼 아래에서 매수 대기)\n\n현재 상태: ${it.entry_status}`
          }
        >
          {entryPriceLabel}
        </div>
        <div
          className={`text-xs leading-tight mt-0.5 ${entryStatusColor}`}
          title={it.entry_status}
        >
          {entryStatusShort}
        </div>
        <div
          className="text-[10px] text-zinc-400 font-mono leading-tight mt-0.5 cursor-help"
          title={rationaleTooltip}
        >
          {rationale}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right">
        <div
          className="font-mono text-emerald-300 font-semibold leading-tight cursor-help"
          title={`예측수익가 = ${it.horizon_months}개월 뒤 예상 가격\n\n산출: 산업통상부 수출 데이터와 이 종목의 과거 상관관계로 통계 추정\n예상 수익률: ${formatPct(it.point_pct, 1)}`}
        >
          {formatKRW(it.point_price)}
        </div>
        <div className="text-xs text-zinc-400 leading-tight mt-0.5">
          {formatPct(it.point_pct, 1)} · +{it.horizon_months}M
        </div>
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono text-rose-300 leading-tight">
          {it.stop_price !== null ? formatKRW(it.stop_price) : "—"}
        </div>
        {it.stop_pct !== null && (
          <div className="text-xs text-zinc-400 leading-tight mt-0.5">
            {formatPct(it.stop_pct, 1)}
          </div>
        )}
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className="font-mono text-emerald-300 leading-tight">
          {it.take_price !== null ? formatKRW(it.take_price) : "—"}
        </div>
        {it.take_pct !== null && (
          <div className="text-xs text-zinc-400 leading-tight mt-0.5">
            {formatPct(it.take_pct, 1)}
          </div>
        )}
      </td>
      <td className="px-2.5 py-2 text-right">
        <div className={`font-mono font-semibold leading-tight ${confColor}`}>
          {it.confluence_score >= 0 ? "+" : ""}
          {it.confluence_score.toFixed(2)}
        </div>
        <div className={`text-xs leading-tight mt-0.5 ${starColor}`}>
          {it.confidence_stars}
        </div>
      </td>
      <td className="px-2.5 py-2 text-right font-bold font-mono text-cyan-300 text-base">
        {it.attractiveness.toFixed(3)}
      </td>
    </tr>
  );
}
