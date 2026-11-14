"use client";

/**
 * 1114-03 · 알림 뒤 결과 (밈 알림 성적판).
 * 알림마다 「알림 뒤 처음 열린 봉의 시가」에서 N거래일 뒤 종가까지 잰 지난 값을 모아 보여 준다.
 * 모든 값은 지난 값 · 추정 · 보장 아님. 수익률은 왕복 비용 0.25% 를 뺀 값. 30건 미만 칸은 서버가 숫자를 비운다.
 * 계획: docs/plans/meme-stock-discovery/08-alert-outcomes-plan-1114-03.md
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { isUnauthorized, LoginNotice, PicksSessionBar } from "@/components/lab/PickResults";
import { api, type MemeOutcomeCell, type MemeOutcomeItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { upDownText } from "@/lib/updown";

const HORIZONS = [1, 3, 5, 10] as const;

const STATUS_LABEL: Record<string, string> = {
  ok: "끝남",
  pending: "진행 중",
  not_buyable: "살 수 없었음(상한가 시가)",
  no_trade: "거래 없음",
  broken: "봉 끊김",
  unavailable: "계산 불가",
};

function pct(v: number | null | undefined, digits = 1, sign = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const x = v * 100;
  return `${sign && x >= 0 ? "+" : ""}${x.toFixed(digits)}%`;
}

function share(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`;
}

function Num({ v, digits = 1 }: { v: number | null | undefined; digits?: number }) {
  return <span className={cn("tabular-nums", upDownText(v))}>{pct(v, digits)}</span>;
}

function Tile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-bold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}

function BreakdownTable({ title, cells }: { title: string; cells: MemeOutcomeCell[] }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-2 text-left font-medium">구분</th>
              <th className="px-2 py-1 text-right font-medium">건수</th>
              <th className="px-2 py-1 text-right font-medium">순 수익률 중앙값</th>
              <th className="px-2 py-1 text-right font-medium">오른 비율</th>
              <th className="pl-2 py-1 text-right font-medium">중앙 최대 하락</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => (
              <tr key={c.label} className="border-t border-border/60">
                <td className="py-1.5 pr-2">{c.label}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">{c.n}</td>
                <td className="px-2 py-1.5 text-right">
                  <Num v={c.median} />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{share(c.up_share)}</td>
                <td className="pl-2 py-1.5 text-right">
                  <Num v={c.median_max_down} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RecentTable({ items }: { items: MemeOutcomeItem[] }) {
  if (items.length === 0) {
    return <div className="text-sm text-muted-foreground">아직 쌓인 알림 결과가 없습니다.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="py-1 pr-2 text-left font-medium">기준일</th>
            <th className="px-2 py-1 text-left font-medium">종목</th>
            <th className="px-2 py-1 text-left font-medium">시장</th>
            <th className="px-2 py-1 text-left font-medium">종류</th>
            <th className="px-2 py-1 text-right font-medium">점수</th>
            <th className="px-2 py-1 text-right font-medium">그날 등락</th>
            <th className="px-2 py-1 text-right font-medium">산 가격(시가)</th>
            <th className="px-2 py-1 text-right font-medium">1일</th>
            <th className="px-2 py-1 text-right font-medium">3일</th>
            <th className="px-2 py-1 text-right font-medium">5일</th>
            <th className="px-2 py-1 text-right font-medium">10일</th>
            <th className="px-2 py-1 text-right font-medium">최대 상승</th>
            <th className="px-2 py-1 text-right font-medium">최대 하락</th>
            <th className="pl-2 py-1 text-left font-medium">상태</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={`${r.ticker}-${r.signal_date}`} className="border-t border-border/60">
              <td className="py-1.5 pr-2 tabular-nums">{r.signal_date.slice(5)}</td>
              <td className="px-2 py-1.5 font-mono">{r.ticker}</td>
              <td className="px-2 py-1.5">{r.market === "KR" ? "국내" : "미국"}</td>
              <td className="px-2 py-1.5">{r.alert_type === "ERUPTING" ? "상승 강도" : r.alert_type === "BLAZING" ? "급등 전 단계" : "—"}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{r.score === null ? "—" : r.score.toFixed(2)}</td>
              <td className="px-2 py-1.5 text-right"><Num v={r.signal_day_ret} /></td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {r.entry_open === null ? "—" : r.entry_open.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </td>
              <td className="px-2 py-1.5 text-right"><Num v={r.ret_1d} /></td>
              <td className="px-2 py-1.5 text-right"><Num v={r.ret_3d} /></td>
              <td className="px-2 py-1.5 text-right"><Num v={r.ret_5d} /></td>
              <td className="px-2 py-1.5 text-right"><Num v={r.ret_10d} /></td>
              <td className="px-2 py-1.5 text-right"><Num v={r.max_up} /></td>
              <td className="px-2 py-1.5 text-right"><Num v={r.max_down} /></td>
              <td className="pl-2 py-1.5" title={r.status_note ?? undefined}>
                {STATUS_LABEL[r.status] ?? r.status}
                {r.status === "pending" ? ` (${r.bars_after}/10)` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AlertOutcomes() {
  const [horizon, setHorizon] = useState<number>(5);
  const summary = useQuery({
    queryKey: ["meme-outcomes", "summary", horizon],
    queryFn: () => api.memeWatch.outcomes.summary(horizon),
    retry: false,
  });
  const recent = useQuery({
    queryKey: ["meme-outcomes", "recent"],
    queryFn: () => api.memeWatch.outcomes.recent(50),
    retry: false,
  });

  const unauthorized = isUnauthorized(summary.error) || isUnauthorized(recent.error);
  const s = summary.data;
  const v = s?.verdict;

  return (
    <section className="space-y-3 rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">알림 뒤 결과</h2>
        <div className="flex gap-1" role="group" aria-label="보는 기간">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              className={cn(
                "min-h-[44px] min-w-[44px] rounded-lg border px-3 text-sm tabular-nums",
                horizon === h ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground",
              )}
            >
              {h}일
            </button>
          ))}
        </div>
      </div>

      <PicksSessionBar queryRoot="meme-outcomes" />
      {unauthorized && <LoginNotice />}
      {summary.isLoading && <div className="text-sm text-muted-foreground">불러오는 중...</div>}
      {summary.error && !unauthorized && (
        <div className="text-sm text-warn">결과를 불러오지 못했습니다. 잠시 뒤 다시 열어 주십시오.</div>
      )}

      {s && v && (
        <>
          {/* 판정 줄 */}
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
            <div className="font-semibold">
              국내 알림 · 순 {v.horizon}일 · 코스닥과 비교한 판정: <span className="text-primary">{v.label}</span>
            </div>
            <div className="mt-1 space-y-0.5 text-xs text-muted-foreground tabular-nums">
              <div>
                기간 {s.period.start ?? "—"} ~ {s.period.end ?? "—"} · 서로 다른 기준일 {s.period.distinct_dates}일 · 알림 {s.period.alerts}건
              </div>
              <div>
                짝지어 비교한 {v.n_paired}건(기준 {v.min_n}건 이상)
                {v.net_median !== null && v.kosdaq_median !== null && (
                  <>
                    {" "}· 순 중앙값 {pct(v.net_median)} · 같은 기간 코스닥 {pct(v.kosdaq_median)} · 오른 비율 {share(v.up_share)}
                  </>
                )}
              </div>
              <div>
                계산 불가·봉 끊김 {v.missing}건 / 대상 {v.denominator}건 = {share(v.missing_share)}
                (기준 {share(v.missing_max)} 넘으면 판정 보류)
              </div>
              <div>
                상태별:{" "}
                {Object.entries(s.status_counts)
                  .map(([k, n]) => `${STATUS_LABEL[k] ?? k} ${n}`)
                  .join(" · ")}
              </div>
              <div>
                수익률은 왕복 비용 {(s.cost * 100).toFixed(2)}% 를 뺀 값 · 지난 값 · 추정 · 보장 아님
              </div>
            </div>
          </div>

          {/* 요약 타일 5 */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <Tile label={`${horizon}일 값이 있는 알림`} value={`${s.overall.n}건`} sub={`짝지은 코스닥 ${s.overall.n_paired ?? 0}건`} />
            <Tile label="순 수익률 중앙값" value={<Num v={s.overall.median} />} sub={s.overall.median === null ? `${s.overall.n}건 · 30건부터 표시` : undefined} />
            <Tile label="오른 비율" value={share(s.overall.up_share)} />
            <Tile label="중앙 최대 하락(10봉 안)" value={<Num v={s.overall.median_max_down} />} />
            <Tile
              label="코스닥과의 차이(중앙값)"
              value={<Num v={s.overall.diff_vs_kosdaq ?? null} />}
              sub={s.kosdaq.median !== null ? `같은 기간 코스닥 ${pct(s.kosdaq.median)}` : "국내 알림만 비교"}
            />
          </div>

          {/* 나눠 본 값 · 설명용 */}
          <div>
            <h3 className="text-base font-semibold">나눠 본 값 · 설명용</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              나눠 볼수록 칸당 건수가 줄어 우연에 흔들립니다. 30건 미만 칸은 숫자를 숨깁니다. 보내지 않은(건너뜀·대기) 알림도 포함합니다.
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-2">
              {s.breakdowns.map((b) => (
                <BreakdownTable key={b.key} title={b.title} cells={b.cells} />
              ))}
            </div>
          </div>
        </>
      )}

      {/* 최근 알림 */}
      <div>
        <h3 className="text-base font-semibold">최근 알림 {recent.data ? `${recent.data.items.length}건` : ""}</h3>
        <div className="mt-2">{recent.data && <RecentTable items={recent.data.items} />}</div>
      </div>

      <p className="text-xs text-muted-foreground">
        알림 뒤 처음 열린 봉의 시가에서 잰 지난 값입니다. 앞으로의 수익을 뜻하지 않으며 · 추정 · 보장 아님.
        알림 기준일은 알림에 적힌 종가 날짜이고, 1114-02 이전 알림은 기준일을 추정했습니다.
      </p>
    </section>
  );
}
