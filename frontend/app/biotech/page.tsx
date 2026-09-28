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
import { StatBox } from "@/components/ui/stat-box";
import { SectionCard } from "@/components/ui/section-card";
import { BiotechTable, BiotechTableColumn } from "@/components/biotech/BiotechTable";
import { RumorCard } from "@/components/biotech/RumorCard";
import type { SessionInfo } from "@/lib/auth";
import { checkedAtLabel, ctgovUrl, mcapBadge, refreshLabel, trialSentence } from "@/lib/biotech-display";

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
};
type RumorJson = { date: string; generated: string; rows: RumorRow[] };

type BiotechKpi = {
  generated: string;
  candidates_total: number;
  news_a_ready: number;
  insider_buy_20d: number;
  alerts: number;
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
          {mcapBadge(r.mcap_bucket, r.mcap_asof) && (
            <span className="rounded bg-slate-50 px-1 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              {mcapBadge(r.mcap_bucket, r.mcap_asof)}
            </span>
          )}
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
        {mcapBadge(row.mcap_bucket, row.mcap_asof) && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {mcapBadge(row.mcap_bucket, row.mcap_asof)}
          </span>
        )}
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          <StatBox label="후보 (총)" value={`${kpi.candidates_total}`} hint={`관찰 중인 종목 ${kpi.candidates_total}개`} />
          <StatBox label="뉴스 예정 (A)" value={`${kpi.news_a_ready}`} hint="발표 임박 종목" />
          <StatBox
            label="임원·대주주 매수 (20d)"
            value={`${kpi.insider_buy_20d}`}
            hint={`최근 20거래일 임원·대주주 매수 신고 ${kpi.insider_buy_20d}건${radar ? ` (${checkedAtLabel(radar.generated)} 확인)` : ""}`}
          />
          <StatBox label="급등 경보" value={`${kpi.alerts}`} hint="오늘 언급이 급증한 종목" />
        </div>
      )}

      {/* 섹션 1: 소문에 살 자리 · sky · 표1 카드 피드 */}
      {isAdmin && rumor && (
        <SectionCard tone="sky" icon="💡" label="소문에 살 자리" count={t1.length} hint={`발표가 다가오는데 아직 조용한 종목 ${t1.length}개 (임박한 순)`}>
          {t1.length === 0 ? (
            <div className="text-xs text-muted-foreground">해당 종목 없음</div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">임상 완료 예정일이 가까운 순서 ↓ (위가 가장 임박)</div>
              {t1.map((r, i) => (
                <RumorCard
                  key={i}
                  order={i + 1}
                  ticker={r.ticker}
                  name={r.name}
                  mcap_bucket={mcapBadge(r.mcap_bucket, r.mcap_asof) ?? ""}
                  days_hint={r.days_hint}
                  detail={r.detail}
                  sentence={trialSentence(r.phase, r.event_date, r.days_to)}
                  sourceUrl={ctgovUrl(r.nct_id)}
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
