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

import { useCallback, useEffect, useState } from "react";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { StatBox } from "@/components/ui/stat-box";
import { SectionCard } from "@/components/ui/section-card";
import { BiotechTable, BiotechTableColumn } from "@/components/biotech/BiotechTable";
import { RumorCard } from "@/components/biotech/RumorCard";
import type { SessionInfo } from "@/lib/auth";

// 백엔드 스키마
type RadarRow = {
  rank: number;
  ticker: string;
  name: string;
  mcap_bucket: string;
  score: number;
  state: string;
  news_window: string;
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
};
type RumorJson = { date: string; generated: string; rows: RumorRow[] };

type BiotechKpi = {
  generated: string;
  candidates_total: number;
  news_a_ready: number;
  insider_buy_20d: number;
  alerts: number;
};

type BiotechDoc = {
  path: string;
  title: string;
  generated_utc: string;
  html: string;
  raw_md_size: number;
  render_mode?: string;
};

type DocTabKey = "status" | "glossary" | "final";
const DOC_TABS: { key: DocTabKey; label: string }[] = [
  { key: "status", label: "상태판" },
  { key: "glossary", label: "용어집" },
  { key: "final", label: "Phase A 최종" },
];

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1/biotech${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) {
    const err: Error & { status?: number } = new Error(`API ${path} failed: ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// md HTML → 계약 클래스 주입 (h1/h2/h3/p/li/blockquote/table/th/td)
function applyContractToHtml(html: string): string {
  let out = html;
  out = out.replace(/<h1(\s[^>]*)?>/gi, '<h1 class="text-lg font-bold mt-3 mb-1">');
  out = out.replace(/<h2(\s[^>]*)?>/gi, '<h2 class="text-base font-semibold mt-3 mb-1">');
  out = out.replace(/<h3(\s[^>]*)?>/gi, '<h3 class="text-sm font-medium mt-2 mb-1">');
  out = out.replace(/<p(\s[^>]*)?>/gi, '<p class="text-sm leading-5 my-1">');
  out = out.replace(/<li(\s[^>]*)?>/gi, '<li class="text-sm leading-5">');
  out = out.replace(/<blockquote(\s[^>]*)?>/gi, '<blockquote class="border-l-2 border-border pl-2 text-sm leading-5 text-muted-foreground my-1">');
  out = out.replace(/<table(\s[^>]*)?>/gi, '<table class="w-full border-collapse text-xs my-2">');
  out = out.replace(/<th(\s[^>]*)?>/gi, '<th class="border-b border-border bg-slate-50 dark:bg-slate-900 p-1.5 text-left font-semibold">');
  out = out.replace(/<td(\s[^>]*)?>/gi, '<td class="border-b border-border p-1.5">');
  out = out.replace(/<code(\s[^>]*)?>/gi, '<code class="rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 font-mono text-xs">');
  out = out.replace(/<pre(\s[^>]*)?>/gi, '<pre class="rounded bg-slate-100 dark:bg-slate-800 p-2 overflow-x-auto text-xs my-2">');
  out = out.replace(/<a(\s[^>]*)?>/gi, '<a class="text-sky-700 hover:underline dark:text-sky-300"$1>');
  out = out.replace(/<ul(\s[^>]*)?>/gi, '<ul class="list-disc pl-5 my-1">');
  out = out.replace(/<ol(\s[^>]*)?>/gi, '<ol class="list-decimal pl-5 my-1">');
  return out;
}

// ── 순위표 (섹션 5) 컬럼 ────────────────────────────────
const RADAR_COLUMNS: BiotechTableColumn<RadarRow>[] = [
  { key: "rank", label: "#", align: "right", render: (r) => r.rank },
  { key: "ticker", label: "티커", render: (r) => r.ticker },
  { key: "name", label: "회사", render: (r) => <span className="text-muted-foreground">{r.name}</span> },
  { key: "mcap_bucket", label: "시총" },
  { key: "state", label: "상태" },
  { key: "score", label: "점수", align: "right", render: (r) => r.score.toFixed(3) },
  { key: "news_window", label: "뉴스 예정" },
];

// ── 압축 목록 (섹션 4·6) 컴포넌트 ────────────────────────
function CompactList({ rows, emptyLabel }: { rows: RumorRow[]; emptyLabel: string }) {
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
          <span className="text-muted-foreground">{r.name}</span>
          <span className="rounded bg-slate-50 px-1 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            {r.mcap_bucket}
          </span>
          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
            {r.days_hint}
          </span>
          <span className="text-slate-700 dark:text-slate-200">{r.detail}</span>
          {typeof r.st_24h === "number" && (
            <span className="ml-auto font-mono text-slate-500 dark:text-slate-400">ST24 {r.st_24h}</span>
          )}
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
          {row.ticker}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {row.mcap_bucket}
        </span>
        <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">
          {row.days_hint}
        </span>
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">{row.name}</div>
      <div className="mt-1.5 text-xs text-slate-700 dark:text-slate-200">{row.detail}</div>
    </div>
  );
}

export default function BiotechPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [kpi, setKpi] = useState<BiotechKpi | null>(null);
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [rumor, setRumor] = useState<RumorJson | null>(null);
  const [docs, setDocs] = useState<Record<DocTabKey, BiotechDoc | null>>({ status: null, glossary: null, final: null });
  const [activeDoc, setActiveDoc] = useState<DocTabKey>("status");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = session?.role === "admin";

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [k, r, ru, s, g, fi] = await Promise.all([
        apiFetch<BiotechKpi>("/kpi.json"),
        apiFetch<RadarJson>("/radar.json"),
        apiFetch<RumorJson>("/rumor.json"),
        apiFetch<BiotechDoc>("/status"),
        apiFetch<BiotechDoc>("/glossary"),
        apiFetch<BiotechDoc>("/final"),
      ]);
      setKpi(k);
      setRadar(r);
      setRumor(ru);
      setDocs({ status: s, glossary: g, final: fi });
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

  const activeDocData = docs[activeDoc];

  return (
    <div className="space-y-4">
      <AdminSessionBar onSessionChange={setSession} />

      <header>
        <h1 className="flex items-center gap-2 text-3xl font-bold">
          🧬 Biotech Catalyst Radar
          <span
            className="rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-semibold text-sky-700 dark:text-sky-300"
            title="Phase A 종결 · 2026-09-14 · Fable 최종 검수 통과"
          >
            PHASE A DONE
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          급등 이전 바이오 종목 사전 감지 · 9 가설 검증 · admin 전용 · 화면 데이터 2026-09-14 자 (서버 파이프 배포 후 매일 갱신)
        </p>
      </header>

      <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-3 text-sm dark:border-amber-600 dark:bg-amber-950/40">
        알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님 · 자동매매 없음
      </div>

      {!isAdmin && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          admin 세션 필요 · 상단 로그인 바에서 관리자 토큰으로 로그인 후 이용
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
          <StatBox label="후보 (총)" value={`${kpi.candidates_total}`} hint="candidates v3 전 상태" />
          <StatBox label="뉴스 예정 (A)" value={`${kpi.news_a_ready}`} hint="임박 발표 전" />
          <StatBox label="임원·대주주 매수 (20d)" value={`${kpi.insider_buy_20d}`} hint="Form 4 최근 20 거래일" />
          <StatBox label="급등 경보" value={`${kpi.alerts}`} hint="D+0 이내 급등 감지" />
        </div>
      )}

      {/* 섹션 1: 소문에 살 자리 · sky · 표1 카드 피드 */}
      {isAdmin && rumor && (
        <SectionCard tone="sky" icon="💡" label="소문에 살 자리" count={t1.length} hint="A 상태 · 조용/초기 · 예정일 가까운 순">
          {t1.length === 0 ? (
            <div className="text-xs text-muted-foreground">해당 종목 없음</div>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {t1.map((r, i) => (
                <RumorCard
                  key={i}
                  ticker={r.ticker}
                  name={r.name}
                  mcap_bucket={r.mcap_bucket}
                  days_hint={r.days_hint}
                  detail={r.detail}
                />
              ))}
            </div>
          )}
        </SectionCard>
      )}

      {/* 섹션 2: 임원·대주주 매수 · emerald · 표4 카드 */}
      {isAdmin && rumor && (
        <SectionCard tone="emerald" icon="👤" label="임원·대주주 매수 (최근 20일)" count={t4.length} hint="Form 4 · 매수 금액·유형">
          {t4.length === 0 ? (
            <div className="text-xs text-muted-foreground">최근 20 거래일 신규 매수 없음</div>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {t4.map((r, i) => <Form4Card key={i} row={r} />)}
            </div>
          )}
        </SectionCard>
      )}

      {/* 섹션 3: 급등 경보 · rose · 없으면 접힘 */}
      {isAdmin && kpi && (
        <SectionCard tone="rose" icon="🚨" label="급등 경보" count={kpi.alerts} hint="D+0 이내 · 신호 채널 대기" collapsible defaultOpen={kpi.alerts > 0}>
          <div className="text-xs text-muted-foreground">
            {kpi.alerts === 0
              ? "현재 경보 없음 · 신호 채널 배포 (WP69-3) 후 실시간 반영"
              : `${kpi.alerts} 건`}
          </div>
        </SectionCard>
      )}

      {/* 섹션 4: 뉴스 통과 (팔 자리) · amber · 표2 압축 목록 */}
      {isAdmin && rumor && (
        <SectionCard tone="amber" icon="📰" label="뉴스 통과 (팔 자리)" count={t2.length} hint="B 상태 · 이미 발표 · 관망">
          <CompactList rows={t2} emptyLabel="B 상태 종목 없음" />
        </SectionCard>
      )}

      {/* 섹션 5: 순위표 전체 · slate · 접기 · BiotechTable ≤7열 */}
      {isAdmin && radar && (
        <SectionCard
          tone="slate"
          icon="📊"
          label="순위표 전체"
          count={radar.rows.length}
          hint="상위 30 (뉴스 예정일 임박순)"
          collapsible
          defaultOpen={false}
        >
          <div className="text-xs text-muted-foreground font-mono mb-2">
            📁 {radar.source_csv} · 생성 {radar.generated}
          </div>
          <BiotechTable columns={RADAR_COLUMNS} rows={radar.rows} caption="레이더 상위 30" />
        </SectionCard>
      )}

      {/* 섹션 6: 언급 있는 종목 · slate · 표3 압축 목록 */}
      {isAdmin && rumor && (
        <SectionCard tone="slate" icon="🔔" label="언급 있는 종목" count={t3.length} hint="ST24 원값 표기 · baseline 미확보 포함">
          <CompactList rows={t3} emptyLabel="언급 감지 없음" />
        </SectionCard>
      )}

      {/* 글 탭 3개 · 하단 · applyContractToHtml */}
      {isAdmin && (
        <div className="space-y-2">
          <nav className="flex flex-wrap gap-2 border-b border-border">
            {DOC_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveDoc(t.key)}
                className={
                  activeDoc === t.key
                    ? "px-3 py-1.5 text-sm font-bold border-b-2 border-sky-600 text-sky-700 dark:text-sky-300"
                    : "px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
          {activeDocData && (
            <article className="space-y-2">
              <div className="text-xs text-muted-foreground font-mono">
                📁 {activeDocData.path} · 생성 UTC {activeDocData.generated_utc} · {activeDocData.raw_md_size.toLocaleString()} B
                {activeDocData.render_mode === "plain_md_fallback" && (
                  <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                    fallback
                  </span>
                )}
              </div>
              <div
                className="rounded border border-border bg-card p-4"
                dangerouslySetInnerHTML={{ __html: applyContractToHtml(activeDocData.html) }}
              />
            </article>
          )}
        </div>
      )}
    </div>
  );
}
