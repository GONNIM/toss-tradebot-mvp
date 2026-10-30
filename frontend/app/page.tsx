"use client";

// 1022-10 4단계 · 오늘 (홈) — 지금 확인할 것만 한 화면에.
// 서버(/api/v1/today)는 저장된 자료만 읽는다. 사이트는 주문을 넣지 않는다.
// 관리자 칸은 로그인 여부를 서버가 쿠키로 판별 · 비로그인은 잠금 한 줄만 받는다.
// 문구는 사실만 적는다 (매도·시기 지시 문장 금지).

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  TodayCandidateBlock,
  TodayHoldingAlert,
  TodayJudgmentDue,
  TodayResponse,
  TodaySafety,
} from "@/lib/api";
import { useSessionListener } from "@/lib/auth";
import { StockLink } from "@/components/stock/StockLink";
import { JournalKpiBadge } from "@/components/home/JournalKpiBadge";

const LOCKED = "로그인하면 보입니다";

function Card({ title, children, link }: { title: string; children: React.ReactNode; link?: { href: string; text: string } }) {
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold">{title}</h2>
        {link && (
          <Link href={link.href} className="shrink-0 text-sm text-primary underline-offset-2 hover:underline">
            {link.text}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

// ISO 날짜(YYYY-MM-DD) → MM/DD
function md(d: string | null | undefined): string {
  return d && d.length >= 10 ? `${d.slice(5, 7)}/${d.slice(8, 10)}` : "-";
}

function kstTime(iso: string): string {
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  if (isNaN(t.getTime())) return "-";
  const k = new Date(t.getTime() + 9 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(k.getUTCHours())}:${p(k.getUTCMinutes())}`;
}

function safetyText(s: TodaySafety | null): string {
  // 서버가 이 칸을 못 읽으면 null · 그 칸만 비운다 (Fable 1022-10-11)
  if (!s) return "지금 확인하지 못했습니다";
  const live = s.live_enabled ? "실거래 켜짐" : "실거래 꺼짐";
  const kill = s.kill_switch_active ? "긴급 정지 작동 중" : "긴급 정지 해제";
  const target = s.order_target === "toss" ? "주문 대상 토스" : "주문 대상 모의";
  return `${live} · ${kill} · ${target}`;
}

function SystemBlock({ d }: { d: TodayResponse }) {
  const failures = d.failures ?? [];
  return (
    <div className="space-y-2">
      {failures.length > 0 && (
        <div role="alert" className="space-y-2 rounded-lg border border-red-500/60 bg-red-500/10 p-4">
          <p className="text-sm font-semibold text-red-600 dark:text-red-400">오늘 실패한 작업 {failures.length}건</p>
          <ul className="space-y-1 text-sm">
            {failures.map((f, i) => (
              <li key={`${f.title}-${i}`} className="flex flex-wrap gap-x-2">
                <span>{f.title}</span>
                <span className="tabular-nums text-muted-foreground">
                  {f.count}회 · {kstTime(f.at)}
                </span>
              </li>
            ))}
          </ul>
          {d.failures_scope && <p className="text-xs text-muted-foreground">{d.failures_scope}</p>}
        </div>
      )}
      <p className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <span className="font-semibold">실주문 안전</span>
        <span className="text-muted-foreground"> · {safetyText(d.safety)}</span>
      </p>
    </div>
  );
}

function JudgmentsCard({ d }: { d: TodayResponse }) {
  const rows: TodayJudgmentDue[] | null = d.judgments_due;
  return (
    <Card title="오늘 할 판단" link={d.is_admin ? { href: "/journal", text: "판단 기록 보기" } : undefined}>
      {!d.is_admin || rows == null ? (
        <p className="text-sm text-muted-foreground">{LOCKED}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">오늘 기한인 판단이 없습니다</p>
      ) : (
        <ul>
          {rows.map((j) => (
            <li key={j.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border py-2 text-sm last:border-0">
              <StockLink ticker={j.ticker} className="font-semibold">{j.ticker}</StockLink>
              {j.strategy && <span className="rounded-md border border-border px-2 py-0.5 text-xs">{j.strategy}</span>}
              <span className="tabular-nums text-muted-foreground">기한 {md(j.due_date)}</span>
              {j.overdue && <span className="rounded-md bg-red-500/15 px-2 py-0.5 text-xs text-red-600 dark:text-red-400">기한 지남</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function alertFact(a: TodayHoldingAlert, nearPct: number): string {
  if (a.kind === "stop_hit") return "손절가 도달";
  if (a.kind === "stop_near") {
    const gap = a.gap_pct != null ? ` (손절가와 ${a.gap_pct.toFixed(1)}% 차이)` : "";
    return `손절가까지 ${nearPct}% 이내${gap}`;
  }
  return `기한 도달${a.deadline ? ` (${md(a.deadline)})` : ""}`;
}

function AlertsCard({ d }: { d: TodayResponse }) {
  const rows = d.holding_alerts;
  return (
    <Card title="보유 경보" link={d.is_admin ? { href: "/account#plan", text: "청산 계획 보기" } : undefined}>
      {!d.is_admin || rows == null ? (
        <p className="text-sm text-muted-foreground">{LOCKED}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">경보 없음</p>
      ) : (
        <ul>
          {rows.map((a, i) => (
            <li key={`${a.symbol}-${a.kind}-${i}`} className="space-y-0.5 border-b border-border py-2 text-sm last:border-0">
              <div className="flex flex-wrap items-center gap-x-3">
                <StockLink ticker={a.symbol} className="font-semibold">{a.symbol}</StockLink>
                <span>{alertFact(a, d.near_stop_pct)}</span>
              </div>
              <p className="text-xs tabular-nums text-muted-foreground">
                {md(a.price_date)} {a.price_source === "holding" ? "저장 가격 기준" : "종가 기준"} · 실시간 아님
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CandidateBlock({ b }: { b: TodayCandidateBlock }) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-base font-semibold">
          {b.label}
          {b.as_of && <span className="ml-2 text-xs font-normal tabular-nums text-muted-foreground">{md(b.as_of)} 기준</span>}
        </h3>
        <Link href={b.link} className="shrink-0 text-sm text-primary underline-offset-2 hover:underline">
          자세히 보기
        </Link>
      </div>
      {b.locked ? (
        <p className="text-sm text-muted-foreground">{LOCKED}</p>
      ) : b.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">오늘 없음</p>
      ) : (
        <ul>
          {b.items.map((it, i) => (
            <li key={`${it.ticker}-${i}`} className="flex flex-wrap items-baseline gap-x-2 border-b border-border py-1.5 text-sm last:border-0">
              {it.ticker && <StockLink ticker={it.ticker} className="font-semibold">{it.ticker}</StockLink>}
              {it.name && <span>{it.name}</span>}
              {it.note && <span className="text-muted-foreground">{it.note}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Home() {
  const qc = useQueryClient();
  // 로그인·로그아웃이 바뀌면 관리자 칸이 달라지므로 다시 불러온다
  useSessionListener(() => {
    qc.invalidateQueries({ queryKey: ["today"] });
  });
  const q = useQuery<TodayResponse>({
    queryKey: ["today"],
    queryFn: () => api.today(),
    retry: false,
  });

  return (
    <div className="space-y-6">
      <header className="border-b border-border pb-4">
        <h1 className="text-2xl font-bold">오늘</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {q.data ? `${q.data.today_kst} 기준 · ` : ""}이 사이트가 저장한 자료만 보여 줍니다. 실시간 시세가 아닙니다.
        </p>
      </header>

      {q.isLoading && <p className="text-sm text-muted-foreground">불러오는 중입니다</p>}
      {q.error && <p className="text-sm text-red-600 dark:text-red-400">오늘 화면을 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</p>}

      {q.data && (
        <>
          <SystemBlock d={q.data} />
          {q.data.is_admin && <JournalKpiBadge />}
          <JudgmentsCard d={q.data} />
          <AlertsCard d={q.data} />
          <div className="space-y-3">
            <h2 className="text-base font-semibold">오늘 후보</h2>
            {q.data.candidates.map((b) => (
              <CandidateBlock key={b.source} b={b} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
