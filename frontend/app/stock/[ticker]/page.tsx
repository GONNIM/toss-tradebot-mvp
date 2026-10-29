"use client";

// 1022-10 3단계 · 종목 하나 보기 — 이 사이트가 모은 이 종목의 자료를 한 화면에.
// 서버(/api/v1/stock/{ticker})는 저장된 자료만 읽는다. 사이트는 주문을 넣지 않는다.
// 로그인 상태는 쿠키로 서버가 판별 · 서버 컴포넌트에서 쿠키를 읽지 않고 클라이언트에서만 불러온다.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, StockJudgment, StockOverview, StockSignal } from "@/lib/api";
import { useSessionListener } from "@/lib/auth";
import { BROKER_LABEL, SEARCH_LABEL } from "@/lib/broker-link";
import { priceText } from "@/lib/holdings-display";
import { outcomeText } from "@/lib/outcome-display";
import { normalizeTicker } from "@/components/stock/StockLink";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function dateText(ts: string | null): string {
  return ts ? ts.slice(0, 10) : "-";
}

function JudgmentRow({ j }: { j: StockJudgment }) {
  const parts: string[] = [];
  if (j.invalidation_price != null) parts.push(`손절 ${j.invalidation_price.toLocaleString("ko-KR")}`);
  if (j.target_price != null) parts.push(`목표 ${j.target_price.toLocaleString("ko-KR")}`);
  parts.push(`시한 T+${j.horizon_days}일`);
  return (
    <li className="space-y-1 border-b border-border py-2 last:border-0">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="tabular-nums text-muted-foreground">{dateText(j.ts)}</span>
        {j.strategy && <span className="rounded-md border border-border px-2 py-0.5 text-xs">{j.strategy}</span>}
      </div>
      {j.thesis_md && <p className="whitespace-pre-wrap text-sm">{j.thesis_md}</p>}
      <p className="text-xs tabular-nums text-muted-foreground">{parts.join(" · ")}</p>
      <p className="text-xs tabular-nums text-muted-foreground">{outcomeText(j.result_at_horizon, j.horizon_days)}</p>
    </li>
  );
}

function MineCard({ d }: { d: StockOverview }) {
  if (!d.is_admin) {
    return (
      <Card title="내 것">
        <p className="text-sm text-muted-foreground">로그인하면 보유와 판단 기록이 보입니다</p>
      </Card>
    );
  }
  const h = d.holding;
  const js = d.judgments ?? [];
  return (
    <Card title="내 것">
      {h ? (
        h.sold ? (
          <p className="text-sm">팔림 <span className="text-xs text-muted-foreground">· 토스 기준 {h.as_of ?? "-"} · 실시간 아님</span></p>
        ) : (
          <div className="space-y-1">
            <p className="text-sm tabular-nums">
              {h.qty.toLocaleString("ko-KR")}주 · 평균 {h.avg_price != null ? priceText(h.avg_price, h.currency ?? "KRW") : "-"}
            </p>
            <p className="text-xs text-muted-foreground">토스 기준 · {h.as_of ?? "-"} · 실시간 아님</p>
          </div>
        )
      ) : (
        <p className="text-sm text-muted-foreground">보유 기록이 없습니다</p>
      )}
      <div>
        <h3 className="mb-1 text-sm font-medium">판단 기록</h3>
        {js.length === 0 ? (
          <p className="text-sm text-muted-foreground">이 종목에 남긴 판단이 없습니다</p>
        ) : (
          <ul>{js.map((j) => <JudgmentRow key={j.id} j={j} />)}</ul>
        )}
      </div>
      <Link
        href={`/journal?ticker=${encodeURIComponent(d.ticker)}`}
        className="inline-flex min-h-[44px] items-center rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted"
      >
        판단 기록하기
      </Link>
    </Card>
  );
}

function SignalRow({ s }: { s: StockSignal }) {
  return (
    <li className="space-y-1 border-b border-border py-2 last:border-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium">{s.label}</span>
        {s.as_of && <span className="text-xs tabular-nums text-muted-foreground">{s.as_of}</span>}
      </div>
      <p className={`text-sm tabular-nums ${s.locked ? "text-muted-foreground" : ""}`}>{s.summary}</p>
      {!s.locked && s.link && (
        <Link href={s.link} className="inline-flex min-h-[44px] items-center text-sm text-primary underline">
          자세히
        </Link>
      )}
    </li>
  );
}

export default function StockPage() {
  const params = useParams<{ ticker: string }>();
  const raw = decodeURIComponent(String(params?.ticker ?? ""));
  const ticker = normalizeTicker(raw);
  const qc = useQueryClient();

  // 로그인·로그아웃이 바뀌면 다시 불러온다 (보유·판단 칸이 달라짐)
  useSessionListener(() => {
    qc.invalidateQueries({ queryKey: ["stock", "overview"] });
  });

  const q = useQuery<StockOverview>({
    queryKey: ["stock", "overview", ticker],
    queryFn: () => api.stock.overview(ticker as string),
    enabled: !!ticker,
    retry: false,
  });

  if (!ticker) {
    return <p className="text-sm text-muted-foreground">종목 코드 형식이 아닙니다</p>;
  }
  if (q.error) {
    const status = (q.error as Error & { status?: number }).status;
    return (
      <p className="text-sm text-muted-foreground">
        {status === 400 ? "종목 코드 형식이 아닙니다" : "종목 정보를 불러오지 못했습니다. 잠시 뒤 다시 열어 주십시오"}
      </p>
    );
  }
  if (!q.data) return <p className="text-sm text-muted-foreground">불러오는 중…</p>;

  const d = q.data;
  const bl = d.broker_link;
  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{d.name ?? d.ticker}</h1>
        <p className="text-sm text-muted-foreground">
          <span className="font-mono">{d.ticker}</span> · {d.market === "KR" ? "국내" : "미국"}
        </p>
        {bl && (
          <a
            href={bl.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-[44px] items-center text-sm underline"
          >
            {bl.kind === "order" ? BROKER_LABEL : SEARCH_LABEL}
          </a>
        )}
      </header>

      <MineCard d={d} />

      <Card title="신호">
        {d.signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">이 사이트가 모은 신호가 없습니다</p>
        ) : (
          <ul>{d.signals.map((s) => <SignalRow key={s.source} s={s} />)}</ul>
        )}
      </Card>
    </div>
  );
}
