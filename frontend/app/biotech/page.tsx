// Biotech Radar · 통합 대시보드 (WP72-2 · 2026-09-20 · 정보 구조 activist-radar 정합)
// 참조: docs/plans/biotech/FE-RULES.md · FE-DIFF.md · SITE-ANALYSIS.md
// 골격: frontend/app/activist-radar/page.tsx (KPI 4칸 + 색띠 섹션)
//
// 구조:
// - 상단 KPI 4칸 (StatBox 공용 부품)
// - 색띠 섹션 6개: 소문(sky) · 임원매수(emerald) · 급등경보(rose) · 뉴스통과(amber) · 순위표(slate, 접힘) · 언급(slate)
// - 글 탭 3개 (상태판 · 용어집 · Phase A 최종) 는 하단 나란히 배치 · applyContractToHtml 계약 유지
// - 미로그인: 상단 잠금 배너 1개만 · 섹션·글 숨김
"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BiotechSessionControl } from "@/components/biotech/BiotechSessionControl";
import { CatalystTimeline } from "@/components/biotech/CatalystTimeline";
import { StatBox } from "@/components/ui/stat-box";
import { SectionCard } from "@/components/ui/section-card";
import { BiotechTable, BiotechTableColumn } from "@/components/biotech/BiotechTable";
import { RumorCard } from "@/components/biotech/RumorCard";
import type { SessionInfo } from "@/lib/auth";
import { cardText, checkedAtLabel, ctgovUrl, insiderLine, mcapBadge, mentionSentence, multSentence, refreshLabel, rumorReason, shortName, sortFilterCards, sortLabel, summaryStatus, tickerOrUnknown, trialSentence } from "@/lib/biotech-display";
import type { CardSort, ThemeRank, TrialDisplay } from "@/lib/biotech-display";

// 백엔드 스키마
type RadarRow = {
  rank: number;
  ticker: string;
  name: string;
  mcap_bucket: string;
  mcap_asof?: string;
  score: number;
  state: string;
  news_window: string;
  nct_id?: string;
  phase?: string;
  event_date?: string;
  days_to?: number | null;
  trial?: TrialDisplay;
  factors: { expert: number; crowd: number; near: number; unnoticed: number; risk: number };
  tag_bonus: number;
};
type RadarJson = { generated: string; source_csv: string; rows: RadarRow[] };

type RumorRow = {
  table: string;
  ticker: string;
  name: string;
  mcap_bucket: string;
  days_hint: string;
  detail: string;
  st_24h?: number | null;
  baseline_n?: number | null;
  mcap_asof?: string;
  nct_id?: string;
  phase?: string;
  event_date?: string;
  days_to?: number | null;
  stage?: string;
  trial?: TrialDisplay;
  theme_rank?: ThemeRank;
  mult?: string;
  cik?: string;
  baseline_mean?: number | null;
};

// WP77 · 급등 브리핑 (수집 사실 + 자동 요약)
type AlertBrief = {
  ticker: string;
  name: string;
  note: string;
  brief_date?: string;
  mentions: { yesterday: number | null; today: number | null; mult: string; mean?: number | null; reddit_today: number; history: { date: string; apewisdom_24h: number; reddit_matches: number }[] };
  reddit: { title: string; link: string; updated: string }[];
  reddit_time_checked?: boolean;
  sec_8k: { filing_date: string; items: string; description: string; url: string; ex99_1_title: string }[];
  sec_status: string;
  form4: { available: boolean; n?: number };
  schedule: string;
  summary?: { ok: boolean; model?: string; lines?: string[]; error?: string };
};
type RumorJson = { date: string; generated: string; rows: RumorRow[] };

type BiotechKpi = {
  generated: string;
  candidates_total: number;
  news_a_ready: number;
  insider_buy_20d: number;
  alerts: number;
  alert_tickers?: string[];
  alert_briefs?: AlertBrief[];
  alerts_collecting?: number;
};

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1/biotech${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) {
    const err: Error & { status?: number } = new Error(`API ${path} failed: ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// ── 순위표 (섹션 5) 컬럼 ────────────────────────────────
const RADAR_COLUMNS: BiotechTableColumn<RadarRow>[] = [
  { key: "rank", label: "#", align: "right", render: (r) => r.rank },
  { key: "ticker", label: "티커", render: (r) => r.ticker },
  { key: "name", label: "회사", render: (r) => <span className="text-muted-foreground">{r.name}</span> },
  { key: "mcap_bucket", label: "시총", render: (r) => mcapBadge(r.mcap_bucket, r.mcap_asof) ?? "" },
  { key: "state", label: "상태" },
  { key: "score", label: "점수", align: "right", render: (r) => r.score.toFixed(3) },
  {
    key: "news_window",
    label: "시험 요약 (결과 발표일 아님)",
    render: (r) => cardText(r.trial, r.phase, r.event_date, r.days_to, undefined, { short: true }).main ?? "대표 시험 정보 없음",
  },
];

// ── WP74 4단계 · 점수 5요소 이름 (쉬운 말) ─────────────────
const FACTOR_KO: { key: keyof RadarRow["factors"]; label: string }[] = [
  { key: "expert", label: "전문가 신호" },
  { key: "crowd", label: "대중 관심" },
  { key: "near", label: "예정일 임박" },
  { key: "unnoticed", label: "덜 알려짐" },
  { key: "risk", label: "위험 감점" },
];
const BASELINE_TARGET_DAYS = 30; // 언급량 기준선 목표 수집 일수 (confirm · 30일 기준선)

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// KPI 버튼 · StatBox 공용 부품을 그대로 감싼다
function KpiButton({ onClick, children, label }: { onClick: () => void; children: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="block w-full rounded-lg text-left transition hover:ring-2 hover:ring-sky-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
    >
      {children}
    </button>
  );
}

// ── WP77 · 급등 브리핑 카드 (펼침) ─────────────────────────
function AlertBriefCard({ b, defaultOpen = false }: { b: AlertBrief; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen); // WP85 · 첫 경보는 펼친 채로 (접혀 있어 요약이 안 보이던 문제)
  const m = b.mentions;
  return (
    <div className="rounded-lg border border-rose-200 bg-white dark:border-rose-900 dark:bg-slate-900">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex w-full items-baseline gap-2 p-3 text-left">
        <span className="rounded bg-rose-600 px-2 py-0.5 font-mono text-xs font-bold text-white">{b.ticker}</span>
        <span className="text-muted-foreground">{shortName(b.name)}</span>
        <span className="ml-auto text-muted-foreground">{open ? "접기 ▲" : "브리핑 보기 ▼"}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-rose-100 p-3 dark:border-rose-900">
          <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-2 dark:border-amber-600 dark:bg-amber-950/40">⚠️ {b.note}</div>
          {summaryStatus(b.summary) && (
            <div className="rounded border border-slate-300 bg-slate-50 p-2 text-muted-foreground dark:border-slate-700 dark:bg-slate-900">
              {summaryStatus(b.summary)} · 아래 수집 자료는 그대로 보여 드립니다.
            </div>
          )}
          {b.summary?.ok && (b.summary.lines ?? []).length > 0 && (
            <div className="rounded border border-sky-300 bg-sky-50 p-2 dark:border-sky-800 dark:bg-sky-950/40">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-sky-800 dark:text-sky-300">
                자동 요약 · 진위 미검증{b.summary.model ? ` · ${b.summary.model}` : ""}
              </div>
              {(b.summary.lines ?? []).map((l, i) => <div key={i}>{l}</div>)}
            </div>
          )}
          <div>
            <div className="font-semibold">(a) 언급량 · apewisdom 24시간</div>
            <div>
              어제 {m.yesterday ?? "기록 없음"} → 오늘 {m.today ?? "기록 없음"} · {multSentence(m.mean, m.today) ?? (m.mult === "collecting" ? "평소 대비 배수: 수집 중 (7일 미만)" : `평소 대비 배수 ${m.mult}`)} · 레딧 매치 오늘 {m.reddit_today}건
            </div>
            <div className="font-mono text-muted-foreground">
              최근 {m.history.length}일 (날짜 언급 수): {m.history.map((h) => `${Number(h.date.slice(4, 6))}/${Number(h.date.slice(6, 8))} ${h.apewisdom_24h}`).join(" · ")}
            </div>
          </div>
          <div>
            <div className="font-semibold">(b) 커뮤니티 · 최근 24시간 매치 레딧 글 (제목만)</div>
            {b.reddit_time_checked === false && b.reddit.length > 0 && (
              <div className="text-muted-foreground">이 날짜 자료에는 게시 시각이 없어 24시간 안의 글인지 확인하지 못했습니다.</div>
            )}
            {b.reddit.length === 0 ? (
              <div className="text-muted-foreground">{b.reddit_time_checked === false ? "매치된 글이 없습니다." : "최근 24시간 매치 글이 없습니다."}</div>
            ) : (
              <ul className="list-disc pl-5">
                {b.reddit.map((p, i) => (
                  <li key={i}><a href={p.link} target="_blank" rel="noopener noreferrer" className="text-sky-700 hover:underline dark:text-sky-300">{p.title}</a></li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="font-semibold">(c) 회사 공시 · 최근 5거래일 8-K</div>
            {b.sec_status !== "ok" ? (
              <div className="text-muted-foreground">SEC 조회 안 됨 ({b.sec_status === "no_cik" ? "SEC 발행사 번호 없음" : "차단으로 중단"})</div>
            ) : b.sec_8k.length === 0 ? (
              <div className="text-muted-foreground">최근 5거래일 8-K 없음</div>
            ) : (
              <ul className="list-disc pl-5">
                {b.sec_8k.map((f, i) => (
                  <li key={i}>
                    <a href={f.url} target="_blank" rel="noopener noreferrer" className="text-sky-700 hover:underline dark:text-sky-300">{f.filing_date} · 항목 {f.items || "-"}</a>
                    {f.description && ` · ${f.description}`}
                    {f.ex99_1_title && ` · 보도자료: ${f.ex99_1_title}`}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="font-semibold">(d) Form 4 · 최근 20거래일</div>
            <div className="text-muted-foreground">{b.form4.available ? `매수·매도 신고 ${b.form4.n ?? 0}건` : "자료 없음"}</div>
          </div>
          <div>
            <div className="font-semibold">(e) 일정</div>
            <div className="text-muted-foreground">{b.schedule}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 압축 목록 (섹션 4·6) 컴포넌트 ────────────────────────
function CompactList({ rows, emptyLabel, kind }: { rows: RumorRow[]; emptyLabel: string; kind: "mentions" | "news" }) {
  if (rows.length === 0) {
    return <div className="text-xs text-muted-foreground">{emptyLabel}</div>;
  }
  return (
    <ul className="space-y-1 text-xs">
      {rows.map((r, i) => (
        <li key={i} className="flex items-baseline gap-2 flex-wrap">
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {r.ticker}
          </span>
          <span className="text-muted-foreground">{shortName(r.name)}</span>
          {mcapBadge(r.mcap_bucket, r.mcap_asof) && (
            <span className="rounded bg-slate-50 px-1 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              {mcapBadge(r.mcap_bucket, r.mcap_asof)}
            </span>
          )}
          <span className="text-slate-700 dark:text-slate-200">
            {kind === "mentions"
              ? mentionSentence(r.stage || r.days_hint, r.baseline_n, r.st_24h, r.mult, r.baseline_mean)
              : trialSentence(r.phase, r.event_date, r.days_to) ?? r.detail}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ── Form4 카드 (섹션 2) ──────────────────────────────────
function Form4Card({ row }: { row: RumorRow }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="rounded bg-emerald-600 px-2 py-0.5 font-mono text-xs font-bold text-white">
          {tickerOrUnknown(row.ticker)}
        </span>
        <span className="text-xs text-muted-foreground">{shortName(row.name)}</span>
        {mcapBadge(row.mcap_bucket, row.mcap_asof) && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {mcapBadge(row.mcap_bucket, row.mcap_asof)}
          </span>
        )}
        <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">
          {row.days_hint}
        </span>
      </div>
      <div className="mt-1.5 text-xs text-slate-700 dark:text-slate-200">{insiderLine(row.detail)}</div>
      {row.cik && (
        <details className="mt-1 text-[11px] text-muted-foreground">
          <summary className="cursor-pointer">자세히</summary>
          SEC 발행사 번호 {row.cik}
        </details>
      )}
    </div>
  );
}

export default function BiotechPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [kpi, setKpi] = useState<BiotechKpi | null>(null);
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [rumor, setRumor] = useState<RumorJson | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // WP74 4단계 · 상호작용 상태 (표시만)
  const [aMode, setAMode] = useState(false);        // 뉴스 예정 KPI 클릭 → A 전체 목록 모드
  const [quietOnly, setQuietOnly] = useState(true); // A 모드 안 "조용한 것만" (= 기존 표1 · 상위 15)
  const [sortBy, setSortBy] = useState<CardSort>("date");
  const [phase3Only, setPhase3Only] = useState(false);
  const [within7, setWithin7] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [openRadar, setOpenRadar] = useState(false);

  const isAdmin = session?.role === "admin";

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [k, r, ru] = await Promise.all([
        apiFetch<BiotechKpi>("/kpi.json"),
        apiFetch<RadarJson>("/radar.json"),
        apiFetch<RumorJson>("/rumor.json"),
      ]);
      setKpi(k);
      setRadar(r);
      setRumor(ru);
    } catch (e) {
      const err = e as Error & { status?: number };
      setError(`${err.message} (status=${err.status ?? "?"})`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) loadAdminData();
  }, [isAdmin, loadAdminData]);

  // rumor 표 분류
  const t1 = rumor?.rows.filter((r) => r.table === "표1") ?? [];  // 소문 살자리
  const t2 = rumor?.rows.filter((r) => r.table === "표2") ?? [];  // 뉴스 통과
  const t3 = rumor?.rows.filter((r) => r.table === "표3") ?? [];  // 언급 있는 종목
  const t4 = rumor?.rows.filter((r) => r.table === "표4") ?? [];  // 임원 매수
  const aAll = rumor?.rows.filter((r) => r.table === "A") ?? [];  // 뉴스 예정 전체 (WP74)

  const radarByTicker = new Map((radar?.rows ?? []).map((r) => [r.ticker, r]));
  const baseCards = aMode && !quietOnly ? aAll : t1;
  const cards = sortFilterCards(baseCards, { sort: sortBy, phase3Only, within7 }, (tk) => radarByTicker.get(tk)?.score);
  const checkedAt = radar ? checkedAtLabel(radar.generated) : "";

  function flash(id: string) {
    scrollToId(id);
    setHighlight(id);
    window.setTimeout(() => setHighlight((h) => (h === id ? null : h)), 2000);
  }
  const ring = (id: string) => (highlight === id ? "rounded-lg ring-2 ring-offset-2 ring-sky-500 transition" : "transition");
  const chip = (on: boolean) =>
    `rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-sky-600 bg-sky-50 font-semibold text-sky-700 dark:bg-sky-950/40 dark:text-sky-300" : "border-border text-muted-foreground hover:bg-muted"}`;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">🧬 Biotech Catalyst Radar</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            급등 이전 바이오 종목 사전 감지 · admin 전용
            {radar && radar.rows.length > 0 && <> · {refreshLabel(radar.generated)}</>}
          </p>
        </div>
        <BiotechSessionControl onSessionChange={setSession} />
      </header>

      <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-3 text-sm dark:border-amber-600 dark:bg-amber-950/40">
        ⚠️ 이 화면은 관찰용입니다. 매수 추천이 아니며 자동으로 주문하지 않습니다. 투자하더라도 소액만 권합니다.
      </div>

      {!isAdmin && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          🔒 관리자 로그인이 필요합니다. 오른쪽 위 입력칸에 관리자 토큰을 넣어 로그인하세요.
        </div>
      )}

      {isAdmin && loading && (
        <div className="rounded border border-border bg-card p-4 text-sm text-muted-foreground">로딩 중…</div>
      )}

      {isAdmin && error && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {/* KPI 4칸 · activist-radar StatBox 공용 부품 · grid grid-cols-1 gap-2 sm:grid-cols-4 */}
      {isAdmin && kpi && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
          <KpiButton label="순위표 전체로 이동" onClick={() => { setOpenRadar(true); flash("sec-radar"); }}>
            <StatBox label="후보 (총)" value={`${kpi.candidates_total}`} hint={`관찰 중인 종목 ${kpi.candidates_total}개`} />
          </KpiButton>
          <KpiButton label="뉴스 예정 종목 전체 펼치기" onClick={() => { setAMode(true); setQuietOnly(true); flash("sec-rumor"); }}>
            <StatBox label="뉴스 예정 (A)" value={`${kpi.news_a_ready}`} hint="발표 임박 종목" />
          </KpiButton>
          <KpiButton label="임원·대주주 매수 섹션으로 이동" onClick={() => flash("sec-insider")}>
            <StatBox
              label="임원·대주주 매수 (20d)"
              value={`${kpi.insider_buy_20d}`}
              hint={`최근 20거래일 임원·대주주 매수 신고 ${kpi.insider_buy_20d}건${checkedAt ? ` (${checkedAt} 확인)` : ""}`}
            />
          </KpiButton>
          <KpiButton label="급등 경보 섹션으로 이동" onClick={() => flash("sec-alerts")}>
            <StatBox label="급등 경보" value={`${kpi.alerts}`} hint="오늘 언급이 급증한 종목" />
          </KpiButton>
        </div>
      )}

      {/* 섹션 1: 소문에 살 자리 · sky · 표1 카드 (뉴스 예정 KPI 클릭 시 A 전체 모드) */}
      {isAdmin && rumor && (
        <div id="sec-rumor" className={ring("sec-rumor")}>
          <SectionCard
            tone="sky"
            icon="💡"
            label={aMode && !quietOnly ? "뉴스 예정 전체" : "소문에 살 자리"}
            count={cards.length}
            hint={aMode && !quietOnly ? `발표가 다가오는 종목 ${aAll.length}개 전체` : `발표가 다가오는데 아직 조용한 종목 ${t1.length}개 (임박한 순)`}
          >
            <div className="flex flex-wrap items-center gap-2">
              {aMode && (
                <button type="button" aria-pressed={quietOnly} onClick={() => setQuietOnly((v) => !v)} className={chip(quietOnly)}>
                  조용한 것만 ({t1.length})
                </button>
              )}
              <button type="button" aria-pressed={phase3Only} onClick={() => setPhase3Only((v) => !v)} className={chip(phase3Only)}>
                3상만
              </button>
              <button type="button" aria-pressed={within7} onClick={() => setWithin7((v) => !v)} className={chip(within7)}>
                D-7 이내
              </button>
              <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                정렬
                <select value={sortBy} onChange={(e) => setSortBy(e.target.value as CardSort)} className="border rounded px-2 py-1 text-sm bg-background">
                  <option value="date">예정일 가까운 순</option>
                  <option value="score">점수 높은 순</option>
                </select>
              </label>
            </div>
            {cards.length > 0 && (
              <CatalystTimeline
                items={cards}
                onSelect={(tk) => { setExpanded(tk); flash(`card-${tk}`); }}
              />
            )}
            {cards.length === 0 ? (
              <div className="text-xs text-muted-foreground">조건에 맞는 종목이 없습니다.</div>
            ) : (
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">
                  <strong className="font-semibold text-slate-700 dark:text-slate-200">{sortLabel(sortBy)}</strong> ↓ · 카드를 누르면 자세히 보입니다.
                </div>
                {cards.map((r, i) => {
                  const rr = radarByTicker.get(r.ticker);
                  const open = expanded === r.ticker;
                  return (
                    <div
                      key={`${r.table}-${r.ticker}-${i}`}
                      id={`card-${r.ticker}`}
                      role="button"
                      tabIndex={0}
                      aria-expanded={open}
                      onClick={() => setExpanded(open ? null : r.ticker)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(open ? null : r.ticker); } }}
                      className={`cursor-pointer rounded-lg ${ring(`card-${r.ticker}`)}`}
                    >
                      <RumorCard
                        order={i + 1}
                        ticker={r.ticker}
                        name={r.name}
                        mcap_bucket={mcapBadge(r.mcap_bucket, r.mcap_asof) ?? ""}
                        days_hint={r.days_hint}
                        detail={r.detail}
                        sentence={cardText(r.trial, r.phase, r.event_date, r.days_to).main ?? trialSentence(r.phase, r.event_date, r.days_to)}
                        subline={cardText(r.trial, r.phase, r.event_date, r.days_to, r.theme_rank).theme}
                        sourceUrl={ctgovUrl(r.nct_id)}
                      />
                      {open && (
                        <div className="mt-1 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-700 dark:bg-slate-900/60">
                          {rr ? (
                            <>
                              <div className="mb-1 font-semibold">점수 {rr.score.toFixed(3)} · 5가지 요소</div>
                              <table className="w-full text-xs">
                                <tbody>
                                  {FACTOR_KO.map((f) => (
                                    <tr key={f.key} className="border-b border-border last:border-0">
                                      <td className="p-1">{f.label}</td>
                                      <td className="p-1 text-right font-mono">{rr.factors[f.key].toFixed(2)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </>
                          ) : (
                            <div className="text-muted-foreground">{rumorReason(r.days_to, r.stage, r.baseline_n)}</div>
                          )}
                          {r.trial?.official_title && (
                            <div className="mt-2">
                              <div className="font-semibold">시험 정식 제목 (원문)</div>
                              <div className="text-muted-foreground">{r.trial.official_title}</div>
                            </div>
                          )}
                          {(r.trial?.conditions ?? []).length > 0 && (
                            <div className="mt-1">
                              대상 질환: {(r.trial?.conditions ?? []).map((c) => (c.ko ? `${c.ko} (${c.en})` : c.en)).join(" · ")}
                            </div>
                          )}
                          <div className="mt-2">
                            근거 원문:{" "}
                            {ctgovUrl(r.nct_id) ? (
                              <a href={ctgovUrl(r.nct_id)!} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-sky-700 hover:underline dark:text-sky-300">
                                ClinicalTrials.gov {r.nct_id} ↗
                              </a>
                            ) : (
                              <span className="text-muted-foreground">{r.detail}</span>
                            )}
                          </div>
                          <div className="mt-1">
                            언급량 수집 진행: {typeof r.baseline_n === "number" ? `${r.baseline_n}/${BASELINE_TARGET_DAYS}일` : "기록 없음"}
                            {r.stage === "collecting" && <span className="text-muted-foreground"> (7일 전까지는 조용함·급증 판단을 보류합니다)</span>}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </SectionCard>
        </div>
      )}

      {/* 섹션 2: 임원·대주주 매수 · emerald · 표4 카드 */}
      {isAdmin && rumor && (
        <div id="sec-insider" className={ring("sec-insider")}>
          <SectionCard tone="emerald" icon="👤" label="임원·대주주 매수 (최근 20일)" count={t4.length} hint="Form 4 · 매수 금액·유형">
            {t4.length === 0 ? (
              <div className="rounded border border-dashed border-emerald-300 p-3 text-sm text-muted-foreground dark:border-emerald-800">
                최근 20거래일 동안 새 매수 신고가 없습니다.{checkedAt && ` (${checkedAt} 확인)`}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {t4.map((r, i) => <Form4Card key={i} row={r} />)}
              </div>
            )}
          </SectionCard>
        </div>
      )}

      {/* 섹션 3: 급등 경보 · rose · 없으면 접힘 */}
      {isAdmin && kpi && (
        <div id="sec-alerts" className={ring("sec-alerts")}>
          <SectionCard tone="rose" icon="🚨" label="급등 경보" count={kpi.alerts} hint="오늘 언급이 급증한 종목" collapsible defaultOpen={kpi.alerts > 0}>
            {kpi.alerts === 0 ? (
              <div className="text-xs text-muted-foreground">
                오늘 언급이 급증한 종목이 없습니다.
                {(kpi.alerts_collecting ?? 0) > 0 && ` 기준선이 7일 미만인 ${kpi.alerts_collecting}개 종목은 수집 중이라 판정에서 뺐습니다.`}
              </div>
            ) : (
              <div className="space-y-2 text-xs">
                <div className="flex flex-wrap gap-2">
                  {(kpi.alert_tickers ?? []).map((tk) => (
                    <span key={tk} className="rounded bg-rose-100 px-2 py-0.5 font-mono font-bold text-rose-800 dark:bg-rose-900/40 dark:text-rose-200">{tk}</span>
                  ))}
                  <span className="text-muted-foreground">기준: 기준선 7일 이상 종목 중 오늘 언급 5건 이상이면서 평소의 5배 이상, 또는 레딧 매치 3건 이상 · 카드를 누르면 브리핑이 펼쳐집니다.</span>
                </div>
                {(kpi.alert_briefs ?? []).map((b, i) => (
                  <AlertBriefCard key={b.ticker} b={b} defaultOpen={i === 0} />
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      )}

      {/* 섹션 4: 뉴스 통과 (팔 자리) · amber · 표2 압축 목록 */}
      {isAdmin && rumor && (
        <SectionCard tone="amber" icon="📰" label="뉴스 통과 (팔 자리)" count={t2.length} hint="B 상태 · 이미 발표 · 관망">
          <CompactList rows={t2} emptyLabel="B 상태 종목 없음" kind="news" />
        </SectionCard>
      )}

      {/* 섹션 5: 순위표 전체 · slate · 접기 · BiotechTable ≤7열 */}
      {isAdmin && radar && (
        <div id="sec-radar" className={ring("sec-radar")}>
        <SectionCard
          key={openRadar ? "radar-open" : "radar-closed"}
          tone="slate"
          icon="📊"
          label="순위표 전체"
          count={radar.rows.length}
          hint="상위 30 (뉴스 예정일 임박순)"
          collapsible
          defaultOpen={openRadar}
        >
          <div className="text-xs text-muted-foreground font-mono mb-2">
            📁 {radar.source_csv} · 생성 {radar.generated}
          </div>
          <BiotechTable columns={RADAR_COLUMNS} rows={radar.rows} caption="레이더 상위 30" />
        </SectionCard>
        </div>
      )}

      {/* 섹션 6: 언급 있는 종목 · slate · 표3 압축 목록 */}
      {isAdmin && rumor && (
        <div id="sec-mentions">
        <SectionCard tone="slate" icon="🔔" label="언급 있는 종목" count={t3.length} hint="24시간 언급 수 · 기준선 수집 일수 · 평소 대비 배수">
          <CompactList rows={t3} emptyLabel="언급 감지 없음" kind="mentions" />
        </SectionCard>
        </div>
      )}

      {/* WP74 3단계 · 문서는 /biotech/docs 로 분리 · 첫 화면에는 링크 3개만 */}
      {isAdmin && (
        <nav className="flex flex-wrap gap-4 border-t border-border pt-3 text-sm">
          <span className="text-muted-foreground">📄 문서</span>
          <Link href="/biotech/docs?tab=status" className="text-sky-700 hover:underline dark:text-sky-300">상태판</Link>
          <Link href="/biotech/docs?tab=glossary" className="text-sky-700 hover:underline dark:text-sky-300">용어집</Link>
          <Link href="/biotech/docs?tab=final" className="text-sky-700 hover:underline dark:text-sky-300">최종 리포트</Link>
        </nav>
      )}
    </div>
  );
}
