"use client";

// 1125-02 · 계획 상세 「이 종목이 계획에 오른 까닭 · 가격 흐름 · 위험 확인」 카드 + 목록 한 줄.
// 표시 전용 — 서버 `why` 값(자료가 없으면 null)과 기존 시세 API 를 그대로 보여 준다. 점수 · 순위 · 주문 · 승인 값에 쓰이지 않는다.
// 낱말 규칙: 방향은 「후보 방향 · 자동 낱말 표시 · 확정 전」 · 날짜는 「1차 완료 예정일 · 결과 발표일 아님 · 등록부 · 추정」 · 매매 지시 문장 없음.
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { MaChart } from "@/components/account/MaChart";
import type { HLine } from "@/components/account/Week40Chart";
import { Chip } from "@/components/plans/ui";
import { BIOTECH_BASIS_LINE, QuoteView, md, ratioPct, usd } from "@/lib/biotech-quote";
import type { Plan, PlanWhy, WhyBrief, WhyRisk } from "@/lib/plans";
import { num } from "@/lib/plans";
import { parseServerIso } from "@/lib/time";

const CARD_BOX = "space-y-3 rounded-xl border border-border bg-card p-4";
export const WHY_TITLE = "이 종목이 계획에 오른 까닭";
export const RULE_TEXT =
  "초안을 만든 날 기준으로, 바이오 레이더 목록에 있고, 임상시험 등록부의 1차 완료 예정일이 진입 창 안이며, 빼는 조건(상장폐지 · 합병 · 계속기업 의문 · 30일 안 증자)이 없고, 같은 종목의 열린 계획이 없습니다.";
export const PCD_NOTE = "1차 완료 예정일 · 결과 발표일 아님 · 등록부 · 추정";
export const DIRECTION_NOTE = "자동 낱말 표시 · 확정 전";
export const ASOF_NOTE = "승인한 날의 값과 다를 수 있습니다 (오늘 자료 기준).";
export const RADAR_NOTE = "검증 중 · 추정 · 보장 아님";

function f2(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(2);
}

function MiniCell({ label, value, note, testid }: { label: string; value: ReactNode; note?: string; testid?: string }) {
  return (
    <div data-testid={testid} className="min-w-0 rounded-lg border border-border p-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-bold tabular-nums">{value}</p>
      {note && <p className="text-xs leading-snug text-muted-foreground">{note}</p>}
    </div>
  );
}

function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:opacity-75">
      {children}
    </a>
  );
}

/** 목록 카드 한 줄 · 방향은 넣지 않는다. 자료가 없으면 null (줄을 그리지 않음). */
export function whyBriefLine(w: WhyBrief | null | undefined): string | null {
  if (!w) return null;
  const parts: string[] = [];
  if (w.rank !== null) parts.push(`바이오 레이더 ${w.rank}위${w.asof ? `(${md(w.asof)} 자료)` : ""}`);
  else parts.push(`오늘 레이더에 없음${w.asof ? `(${md(w.asof)} 자료)` : ""}`);
  if (w.pcd) parts.push(`다음 임상 1차 완료 예정 ${md(w.pcd)}(등록부 · 추정)`);
  return `오른 까닭: ${parts.join(" · ")}`;
}

/** 초안 만든 날 · 한국 시각 MM/DD (계획 응답의 created_at · 없으면 빈 문자열) */
export function createdMd(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "";
  const parts = new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit", timeZone: "Asia/Seoul" }).formatToParts(d);
  const g = (t: string) => parts.find((x) => x.type === t)?.value ?? "";
  return `${g("month")}/${g("day")}`;
}

/** 8-K 소제목 · 사용자 대표 확정이 있으면 그 내용에 맞게 바꾼다 (없으면 「임상 발표인지 확인 전」 그대로) */
export function eightKTitle(dec: { clinical: boolean } | null | undefined): string {
  if (!dec) return "최근 8-K (임상 발표인지 확인 전)";
  return dec.clinical ? "최근 8-K (대표가 임상 발표로 확정)" : "최근 8-K (대표가 임상 발표 아님으로 확정)";
}

function dDay(n: number | null): string {
  if (n === null) return "";
  return n >= 0 ? ` (D-${n})` : ` (D+${-n})`;
}

export function WhyCard({ plan, why }: { plan: Plan; why: PlanWhy | null | undefined }) {
  const draft = plan.state === "DRAFT";
  if (!why) {
    return (
      <section aria-label={WHY_TITLE} data-testid="why-card" className={CARD_BOX}>
        <h3 className="text-base font-bold">{WHY_TITLE}</h3>
        <p className="text-sm text-muted-foreground" data-testid="why-empty">자료 없음 · 까닭 자료를 읽지 못했습니다. 계획 값에는 영향이 없습니다.</p>
      </section>
    );
  }
  const r = why.radar;
  const k = why.eight_k;
  const t = why.trial;
  return (
    <section aria-label={WHY_TITLE} data-testid="why-card" className={CARD_BOX}>
      <h3 className="text-base font-bold">{WHY_TITLE}</h3>
      {plan.source === "draft" ? (
        <div className="space-y-1 rounded-lg bg-primary/5 px-3 py-2 text-sm" data-testid="why-rule">
          <p>자동 초안 규칙: {RULE_TEXT}</p>
          {createdMd(plan.created_at) && <p className="text-xs text-muted-foreground tabular-nums" data-testid="why-created">초안 만든 날 {createdMd(plan.created_at)} (한국 시각)</p>}
        </div>
      ) : (
        <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm" data-testid="why-rule">직접 만든 계획이라 자동 초안 규칙은 해당 없습니다. 아래는 오늘 자료입니다.</p>
      )}

      {r ? (
        <div className="space-y-2" data-testid="why-radar">
          <h4 className="text-sm font-semibold text-muted-foreground">바이오 레이더{why.asof ? ` · ${md(why.asof)} 자료 기준` : ""}</h4>
          <p className="text-xs text-muted-foreground">
            화면을 열 때 가장 최근 자료를 읽습니다.{!draft && ` ${ASOF_NOTE}`}
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MiniCell testid="why-rank" label="순위" value={<>{r.rank} <span className="text-sm font-normal text-muted-foreground">/ {r.total}</span></>} note={`점수 ${f2(r.score)}`} />
            {r.factors.map((fa) => (
              <MiniCell key={fa.key} testid={`why-f-${fa.key}`} label={fa.label} value={f2(fa.value)} note={fa.meaning} />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">레이더 점수는 {RADAR_NOTE}.</p>
        </div>
      ) : (
        <p className="rounded-lg border border-border px-3 py-2 text-sm" data-testid="why-not-in-radar">
          오늘 레이더에 없음{draft ? " · 초안은 진입 창이 닫히면 만료" : ""}
          {why.asof ? <span className="text-muted-foreground"> ({md(why.asof)} 자료 기준)</span> : null}
          {!draft && <span className="block text-xs text-muted-foreground" data-testid="why-asof-note">{ASOF_NOTE}</span>}
        </p>
      )}

      <div className="space-y-1" data-testid="why-8k">
        <h4 className="text-sm font-semibold text-muted-foreground">{eightKTitle(k?.decision)}</h4>
        {k ? (
          <>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span className="tabular-nums">{md(k.date)}</span>
              <span>· {k.items_text || "서류 종류 없음"} 서류(8-K)</span>
              {k.has_body_tag ? (
                <Chip testid="why-direction">후보 방향: {k.direction_ko ?? "분류 안 됨"} · {DIRECTION_NOTE}</Chip>
              ) : (
                <Chip testid="why-direction">후보 방향: 본문 확인 전</Chip>
              )}
              {k.url && <ExtLink href={k.url}>SEC 원문 ↗</ExtLink>}
            </p>
            {k.quote && <p lang="en" className="border-l-[3px] border-border pl-3 text-sm italic text-muted-foreground" data-testid="why-quote">“{k.quote}”</p>}
            <p className="text-xs text-muted-foreground" data-testid="why-decision">
              {k.has_body_tag && k.keywords.length > 0 ? `후보 방향은 글 속 낱말(${k.keywords.slice(0, 3).join(" · ")})로 자동으로 붙인 표시입니다. ` : ""}
              대표 확정:{" "}
              {k.decision
                ? k.decision.clinical ? `임상 발표 · ${k.decision.direction_ko ?? "방향 없음"}` : "임상 발표 아님"
                : "아직 없음"}
              {k.items.includes("2.02") ? " · 실적 서류라 예전 결과를 다시 적었을 수 있습니다(추정)" : ""}
              {" · 새 결과인지는 원문에서 볼 수 있습니다."}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">자료 없음 · 최근 8-K 기록이 없습니다.</p>
        )}
      </div>

      <div className="space-y-1" data-testid="why-trial">
        <h4 className="text-sm font-semibold text-muted-foreground">다음 임상 일정</h4>
        {t ? (
          <>
            <p className="flex flex-wrap items-baseline gap-x-2 text-sm tabular-nums">
              <span>{t.nct_id}</span>
              <span>· {t.phase_ko}</span>
              <span>· 1차 완료 예정 <b>{t.pcd}</b>{dDay(t.days_to)}</span>
              <ExtLink href={t.url}>등록부 원문 ↗</ExtLink>
            </p>
            <p className="text-xs text-muted-foreground">{t.note}</p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">자료 없음 · 등록부 일정을 찾지 못했습니다.</p>
        )}
      </div>
    </section>
  );
}

const TONE: Record<WhyRisk["tone"], "plain" | "on" | "warn"> = { ok: "on", mid: "plain", bad: "warn", none: "plain" };

export function RiskCard({ why }: { why: PlanWhy | null | undefined }) {
  if (!why) return null;
  return (
    <section aria-label="위험 확인" data-testid="risk-card" className={CARD_BOX}>
      <h3 className="text-base font-bold">위험 확인 (공개 자료)</h3>
      <ul className="divide-y divide-border">
        {why.risks.map((x) => (
          <li key={x.key} data-testid={`risk-${x.key}`} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2 text-sm">
            <span className="min-w-0">{x.label}</span>
            <span className="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
              <Chip tone={TONE[x.tone]}>{x.value}</Chip>
              {x.note && <span className="text-xs text-muted-foreground tabular-nums">{x.note}</span>}
              {x.url && <ExtLink href={x.url}>원문 ↗</ExtLink>}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">SEC 공개 서류에서 낱말로 뽑은 값이며 {RADAR_NOTE}.</p>
    </section>
  );
}

/** 1125-02 · 가로선 값 · 매수 감시가는 계획 값 · 손절 첫 값은 (평균 매수가 있으면 그 값, 없으면 매수 감시가) × (1 − 첫 손절 폭) 로 보인 추정. */
export function priceLines(plan: Plan): { buy: number | null; stop: number | null; stopPct: number | null; stopBase: "avg" | "watch" | null } {
  const buy = num(plan.params.buy_watch);
  const raw = plan.params.ladder_pcts;
  const first = Array.isArray(raw) ? raw.map((x) => num(x)).find((x): x is number => x !== null && x > 0) ?? null : null;
  const pct = first ?? 0.03;
  const avg = num(plan.avg_price);
  const base = avg !== null && avg > 0 ? avg : buy;
  const stop = base !== null && base > 0 ? Math.round(base * (1 - pct) * 100) / 100 : null;
  return { buy: buy !== null && buy > 0 ? buy : null, stop, stopPct: pct, stopBase: base === null ? null : avg !== null && avg > 0 ? "avg" : "watch" };
}

async function fetchQuote(ticker: string): Promise<QuoteView | null> {
  const res = await fetch(`/api/v1/biotech/quote/${encodeURIComponent(ticker)}`, { credentials: "include", cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`불러오지 못했습니다 (status ${res.status}).`);
  return (await res.json()) as QuoteView;
}

export function PriceCard({ plan }: { plan: Plan }) {
  const q = useQuery({ queryKey: ["plans", "quote", plan.symbol], queryFn: () => fetchQuote(plan.symbol), staleTime: 60_000, retry: false });
  const pl = priceLines(plan);
  const v = q.data ?? null;
  const b = v?.basics ?? null;
  const hLines: HLine[] = [];
  if (pl.buy !== null) hLines.push({ value: pl.buy, label: "매수 감시가", color: "hsl(var(--warn))" });
  if (pl.stop !== null) hLines.push({ value: pl.stop, label: "손절 첫 값", color: "hsl(var(--down))", dash: "2 3" });
  return (
    <section aria-label="가격 흐름 40주" data-testid="price-card" className={CARD_BOX}>
      <h3 className="text-base font-bold">가격 흐름 · 40주</h3>
      {q.isLoading && <p className="text-sm text-muted-foreground">불러오는 중입니다</p>}
      {q.error && <p className="text-sm text-warn" data-testid="price-error">{(q.error as Error).message}</p>}
      {q.data === null && <p className="text-sm text-muted-foreground" data-testid="price-none">자료 없음 · 오늘 후보 목록에 없음</p>}
      {v && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniCell label={`종가${v.asof ? ` ${md(v.asof)}` : ""}`} value={usd(b?.price_close)} />
            <MiniCell label="52주 범위" value={b && b.low_52w != null && b.high_52w != null ? `${b.low_52w.toFixed(2)} ~ ${b.high_52w.toFixed(2)}` : "자료 없음"} note="달러" />
            <MiniCell label="시가총액 (야후)" value={usd(b?.market_cap)} />
            <MiniCell label="공매도 비율" value={ratioPct(b?.short_pct_float)} note="유통 주식 대비" />
          </div>
          <MaChart chart={v.chart} initialView="week" basisLine={BIOTECH_BASIS_LINE} hLines={hLines} />
        </>
      )}
      <div className="grid grid-cols-2 gap-2" data-testid="price-lines">
        <MiniCell label="매수 감시가" value={pl.buy !== null ? pl.buy.toFixed(2) : "—"} note="계획 값" />
        <MiniCell
          label="손절 첫 값"
          value={pl.stop !== null ? pl.stop.toFixed(2) : "—"}
          note={pl.stopPct !== null ? `${pl.stopBase === "avg" ? "평균 매수가" : "매수 감시가"} −${(pl.stopPct * 100).toFixed(0)}% 기준 · 추정 · 보장 아님` : undefined}
        />
      </div>
      <p className="text-xs text-muted-foreground">종가 · 52주 · 시가총액 · 공매도 비율은 야후 자료라 로그인 화면에만 보입니다. 선 이름은 그림 아래 범례에 있습니다.</p>
    </section>
  );
}
