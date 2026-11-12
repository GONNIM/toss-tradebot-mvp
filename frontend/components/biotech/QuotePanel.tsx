// 1111-01 · 「가격·전문가 의견 보기」 접힘 칸 (순위표·소문 목록 종목 칸 전용 · 과거 기록 표에는 넣지 않음)
// 순서: ① 현재가 ② 그림(주봉 5년·40주 기본) ③ 기본 칸 ④ 전문가 의견(원자료) ⑤ AI 요약 ⑥ 출처
// 표시 전용 — 점수·순위·경보에 쓰지 않는다. 자체 계산(목표가까지 몇 %)은 하지 않는다. 명령문을 쓰지 않는다.
"use client";

import { useEffect, useState } from "react";
import { MaChart } from "@/components/account/MaChart";
import {
  BIOTECH_BASIS_LINE,
  NO_DATA,
  QUOTE_TOGGLE_CLOSE,
  QUOTE_TOGGLE_OPEN,
  QuoteView,
  changeLine,
  countLine,
  distLine,
  liveLine,
  md,
  ratioPct,
  shares,
  sourceLine,
  targetLine,
  usd,
} from "@/lib/biotech-quote";

const CACHE_MS = 60_000;
const cache = new Map<string, { at: number; view: QuoteView }>();

function Cell({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-md border border-border bg-background p-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      {note && <div className="text-[11px] text-muted-foreground tabular-nums">{note}</div>}
    </div>
  );
}

function Body({ v }: { v: QuoteView }) {
  const b = v.basics;
  const o = v.opinion;
  const tl = o ? targetLine(o) : null;
  return (
    <div className="space-y-3 text-xs">
      <div className="text-sm font-semibold tabular-nums" data-testid="quote-live">{liveLine(v)}</div>
      <MaChart chart={v.chart} initialView="week" basisLine={BIOTECH_BASIS_LINE} />
      {b ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Cell label="거래량" value={shares(b.volume)} />
          <Cell label="평균 거래량" value={shares(b.avg_volume)} />
          <Cell label="시가총액 (야후)" value={usd(b.market_cap)} note={`${md(v.asof)} 조회`} />
          <Cell label="52주 범위" value={b.low_52w != null && b.high_52w != null ? `${b.low_52w.toFixed(2)} ~ ${b.high_52w.toFixed(2)}` : NO_DATA} note="달러" />
          <Cell label="보유 현금" value={usd(b.total_cash)} note="최근 보고 기준" />
          <Cell label="공매도 비율 (유통 주식 대비)" value={ratioPct(b.short_pct_float)} note={b.short_asof ? `${md(b.short_asof)} 기준 · 한 달 두 번 갱신` : undefined} />
        </div>
      ) : (
        <p className="text-muted-foreground">기본 시세 자료가 아직 없습니다. 하루 한 번(화~토 08:45) 받습니다.</p>
      )}
      {o && (
        <div className="space-y-1 rounded-md border border-border p-2" data-testid="quote-opinion">
          <div className="font-semibold">{o.head}</div>
          <div className="tabular-nums">{countLine(o)}</div>
          {tl && <div className="tabular-nums">{tl}</div>}
          <div className="tabular-nums">
            의견 분포 · {distLine(o)} <span className="text-muted-foreground">({o.grade_note})</span>
          </div>
          {o.changes.length > 0 && (
            <div>
              <div className="text-muted-foreground">최근 등급·목표가 변경 ({o.grade_note})</div>
              <ul className="list-disc pl-5 tabular-nums">
                {o.changes.map((c, i) => (
                  <li key={i}>{changeLine(c)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {v.summary && (
        <div className="space-y-1 rounded-md border border-primary/40 bg-primary/5 p-2" data-testid="quote-summary">
          <div className="text-[11px] font-bold text-primary">
            {v.summary.head}
            {v.summary.model ? ` · ${v.summary.model}` : ""}
            {v.summary.made_at ? ` · ${md(v.summary.made_at)}` : ""}
          </div>
          {v.summary.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
          <details>
            <summary className="cursor-pointer text-muted-foreground">요약에 넣은 자료 보기</summary>
            <ol className="list-decimal pl-5 text-muted-foreground">
              {v.summary.sources.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </details>
        </div>
      )}
      {v.sec8k?.url && (
        <div>
          회사 공시 원문:{" "}
          <a href={v.sec8k.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
            SEC 8-K {md(v.sec8k.filing_date)} ↗
          </a>
          {v.sec8k.title ? <span className="text-muted-foreground"> · {v.sec8k.title}</span> : null}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground tabular-nums">{sourceLine(v)}</p>
      <p className="text-[11px] text-muted-foreground">{v.use_note}</p>
    </div>
  );
}

/** 1112-02 · 카드·표 행의 단추 모양 (토스증권 단추와 같은 모양 · 터치 44px). */
export const ROW_BUTTON_CLASS =
  "inline-flex min-h-[44px] items-center gap-1 rounded-lg border border-border bg-white px-3 text-xs font-medium hover:bg-muted";

/** 1112-02 · 「가격·전문가 의견 ▼/▲」 단추. 펼친 내용은 QuoteDetails 가 그 카드·행 안에 따로 그린다. */
export function QuoteToggleButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      onKeyDown={(e) => e.stopPropagation()}
      className={`${ROW_BUTTON_CLASS} text-primary`}
    >
      {open ? `${QUOTE_TOGGLE_CLOSE} ▲` : `${QUOTE_TOGGLE_OPEN} ▼`}
    </button>
  );
}

/** 1112-02 · 펼친 칸. 머리에 종목 기호·이름을 적어 어느 종목 칸인지 바로 알게 한다. 열릴 때 한 번 불러온다(60초 캐시). */
export function QuoteDetails({ ticker, name }: { ticker: string; name?: string }) {
  const [view, setView] = useState<QuoteView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    const hit = cache.get(ticker);
    if (hit && Date.now() - hit.at < CACHE_MS) {
      setView(hit.view);
      return;
    }
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const res = await fetch(`/api/v1/biotech/quote/${encodeURIComponent(ticker)}`, { credentials: "include", cache: "no-store" });
        if (res.status === 401) throw new Error("로그인이 필요합니다.");
        if (res.status === 404) throw new Error("후보 종목이 아니어서 자료가 없습니다.");
        if (!res.ok) throw new Error(`불러오지 못했습니다 (status ${res.status}).`);
        const j = (await res.json()) as QuoteView;
        cache.set(ticker, { at: Date.now(), view: j });
        if (alive) setView(j);
      } catch (e) {
        if (alive) setErr((e as Error).message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [ticker]);

  return (
    <div
      className="rounded-lg border border-primary/30 bg-white"
      data-testid={`quote-panel-${ticker}`}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <div className="flex flex-wrap items-baseline gap-2 border-b border-border bg-primary/5 px-3 py-2">
        <span className="rounded-lg bg-primary px-2 py-0.5 font-mono text-xs font-bold text-white">{ticker}</span>
        <span className="text-xs font-semibold">가격·전문가 의견</span>
        {name && <span className="text-xs text-muted-foreground">{name}</span>}
      </div>
      <div className="p-3">
        {loading && <p className="text-xs text-muted-foreground">불러오는 중입니다.</p>}
        {err && <p className="text-xs text-warn">{err}</p>}
        {view && !loading && <Body v={view} />}
      </div>
    </div>
  );
}
