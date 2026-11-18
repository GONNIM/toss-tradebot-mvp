"use client";

// 1022-10 3단계 · 종목 하나 보기 — 이 사이트가 모은 이 종목의 자료를 한 화면에.
// 서버(/api/v1/stock/{ticker})는 저장된 자료만 읽는다. 사이트는 주문을 넣지 않는다.
// 1119-01 · 비로그인에게도 자체 계산 신호 · 일정 · 계속기업(공개 자료)을 보인다. 야후 자료(가격 · 전문가 의견)는 로그인만 (자료 제공처 약관).
// 로그인 상태는 쿠키로 서버가 판별 · 서버 컴포넌트에서 쿠키를 읽지 않고 클라이언트에서만 불러온다.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, StockCatalyst, StockGoingConcern, StockJudgment, StockOverview, StockSignal } from "@/lib/api";
import { QuoteDetails } from "@/components/biotech/QuotePanel";
import {
  GOING_CONCERN_LABEL,
  GOING_CONCERN_NOTE,
  goingConcernParts,
  goingConcernSuffix,
  isSecUrl,
} from "@/lib/biotech-display";
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
        {j.strategy && <span className="rounded-lg border border-border px-2 py-0.5 text-xs">{j.strategy}</span>}
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

const PRICE_LOGIN_NOTE = "가격 · 전문가 의견은 로그인하면 보입니다 (자료 제공처 약관상 공개 게시 불가)";
const PRICE_NONE_NOTE = "이 사이트는 이 종목의 가격 자료를 모으지 않습니다";
const PRICE_KR_NOTE = "국내 종목 가격 · 전문가 의견은 이 화면에 아직 없습니다 · 토스에서 보실 수 있습니다";
const NO_CATALYST_NOTE = "등록된 일정이 없습니다";

function BrokerLink({ d }: { d: StockOverview }) {
  const bl = d.broker_link;
  if (!bl) return null;
  return (
    <a href={bl.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-[44px] items-center text-sm underline">
      {bl.kind === "order" ? BROKER_LABEL : SEARCH_LABEL}
    </a>
  );
}

// 2 · 가격 · 전문가 의견 — 로그인 + 후보면 /biotech 와 같은 칸, 아니면 한 줄
function PriceCard({ d }: { d: StockOverview }) {
  if (d.quote_available == null) return null; // 후보 파일을 못 읽음 → 칸 숨김
  if (!d.quote_available) {
    return (
      <Card title="가격 · 전문가 의견">
        <p className="text-sm text-muted-foreground">{d.market === "KR" ? PRICE_KR_NOTE : PRICE_NONE_NOTE}</p>
        {d.market === "KR" && <BrokerLink d={d} />}
      </Card>
    );
  }
  if (!d.is_admin) {
    return (
      <Card title="가격 · 전문가 의견">
        <p className="text-sm text-muted-foreground" data-testid="price-login-note">{PRICE_LOGIN_NOTE}</p>
        <BrokerLink d={d} />
      </Card>
    );
  }
  return (
    <Card title="가격 · 전문가 의견">
      <QuoteDetails
        ticker={d.ticker}
        name={d.name ?? undefined}
        errorText={{ 401: "다시 로그인하면 보입니다", 404: "후보에서 빠진 종목입니다" }}
      />
    </Card>
  );
}

function catalystLine(c: StockCatalyst): string {
  const when = c.past ? `지난 일정 (D+${Math.abs(c.days_to)})` : c.days_to === 0 ? "오늘" : `D-${c.days_to}`;
  return `임상 완료 예정일 ${c.event_date} · ${when} · ${c.nct_id}${c.phase ? ` · ${c.phase}` : ""}`;
}

// 4 · 다가오는 일정
function CatalystCard({ list }: { list: StockCatalyst[] | null | undefined }) {
  if (list == null) return null;
  return (
    <Card title="다가오는 일정">
      {list.length === 0 ? (
        <p className="text-sm text-muted-foreground">{NO_CATALYST_NOTE}</p>
      ) : (
        <ul className="space-y-1">
          {list.map((c) => (
            <li key={`${c.nct_id}-${c.event_date}`} className={`text-sm tabular-nums ${c.past ? "text-muted-foreground" : ""}`}>{catalystLine(c)}</li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">임상 완료 예정일은 결과 발표일이 아닙니다.</p>
    </Card>
  );
}

// 5 · 위험 (공개 자료) — 표시 문장은 /biotech 와 같은 규칙 (lib/biotech-display)
function RiskCard({ g }: { g: StockGoingConcern | null | undefined }) {
  if (g == null) return null;
  const det = g.detail;
  const { head, tail } = det ? goingConcernParts(det) : { head: "", tail: "" };
  const suffix = det ? goingConcernSuffix(det) : "";
  return (
    <Card title="위험 (공개 자료)">
      {g.scope !== "checked" || !det ? (
        <p className="text-sm text-muted-foreground">
          {GOING_CONCERN_LABEL}:{" "}
          {g.scope === "unreadable"
            ? "자료를 읽지 못했습니다"
            : g.scope === "no_cik"
              ? "회사 번호를 찾지 못해 확인하지 못했습니다"
              : "확인 대상 밖 (이 회사는 확인 목록에 없습니다)"}
        </p>
      ) : (
        <p className="text-sm">
          {GOING_CONCERN_LABEL}: {head && <strong className="font-semibold">{head}</strong>}
          {tail}
          {suffix && <> · {suffix}</>}
          {isSecUrl(det.url) && (
            <> · <a href={det.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">원문 ↗</a></>
          )}
        </p>
      )}
      <p className="text-xs text-muted-foreground">{GOING_CONCERN_NOTE}</p>
    </Card>
  );
}

// 7 · 출처 — 칸마다 자료 날짜와 출처 이름
function SourceCard({ d }: { d: StockOverview }) {
  const lines: string[] = [];
  for (const s of d.signals) lines.push(`${s.label}: ${s.as_of ?? "날짜 없음"} · 이 사이트가 저장한 자료`);
  if (d.catalysts != null) lines.push("일정: ClinicalTrials.gov 등록부 주간 사본");
  const det = d.going_concern?.detail;
  if (d.going_concern != null) lines.push(`계속기업 문구: SEC 제출 서류${det?.filed ? ` · ${det.filed} 제출` : ""}`);
  if (d.is_admin && d.quote_available) lines.push("가격 · 전문가 의견: 위 칸에 적힌 출처와 조회일");
  return (
    <Card title="출처">
      <ul className="space-y-1 text-xs text-muted-foreground tabular-nums">
        {lines.map((l, i) => <li key={i}>{l}</li>)}
        <li>이 페이지는 {d.fetched_at.slice(0, 10)} 에 읽은 저장 자료입니다 · 실시간 아님</li>
      </ul>
    </Card>
  );
}

// 1119-01 · 「자세히」 링크가 가는 화면이 관리자 전용이면 비로그인에게는 링크를 숨긴다 (열면 로그인 안내만 나옴).
// 근거 (코드로 확인 11/19 · 시험 test_signal_link_pages_api_guard):
//   /lab/crazy · /lab/moonshot : 라우터 전체 dependencies=[Depends(require_sniper_token)] (routes/crazy.py:16 · moonshot.py:16)
//   /biotech : 자료 API 12개 중 12개가 Depends(require_sniper_token) (routes/biotech.py:105-125 …) · 화면도 비로그인 잠금 배너 (app/biotech/page.tsx:460)
// 나머지 10곳(/lab/meme-watch · /activist-radar · /influencer/serenity/* · /powderkeg · /rulebook · /principles/screener ·
//   /sector-leaders · /watchlist · /sniper)은 읽기 API 가 공개 (편집 버튼만 관리자). 새 신호 출처를 더하면 여기도 확인.
const ADMIN_ONLY_LINKS = new Set<string>(["/lab/crazy", "/lab/moonshot", "/biotech"]);

function SignalRow({ s, isAdmin }: { s: StockSignal; isAdmin: boolean }) {
  return (
    <li className="space-y-1 border-b border-border py-2 last:border-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium">{s.label}</span>
        {s.as_of && <span className="text-xs tabular-nums text-muted-foreground">{s.as_of}</span>}
      </div>
      <p className="text-sm tabular-nums">{s.summary}</p>
      {s.explain && <p className="text-xs text-muted-foreground">{s.explain}</p>}
      {s.link && (isAdmin || !ADMIN_ONLY_LINKS.has(s.link)) && (
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
  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{d.name ?? d.ticker}</h1>
        <p className="text-sm text-muted-foreground">
          <span className="font-mono">{d.ticker}</span> · {d.market === "KR" ? "국내" : "미국"}
        </p>
        <BrokerLink d={d} />
      </header>

      <PriceCard d={d} />

      <Card title="왜 올라왔나">
        {d.signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">이 사이트가 모은 신호가 없습니다</p>
        ) : (
          <ul>{d.signals.map((s) => <SignalRow key={s.source} s={s} isAdmin={d.is_admin} />)}</ul>
        )}
      </Card>

      <CatalystCard list={d.catalysts} />
      <RiskCard g={d.going_concern} />
      <MineCard d={d} />
      <SourceCard d={d} />
    </div>
  );
}
