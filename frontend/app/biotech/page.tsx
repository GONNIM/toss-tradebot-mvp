// Biotech Radar · 통합 대시보드 (WP71-2 · 2026-09-18 · 구조 전환)
// 참조: docs/plans/biotech/FE-RULES.md · FE-DIFF.md · SITE-ANALYSIS.md
// 골격: frontend/app/activist-radar/page.tsx 클래스 문자열 동일
//
// 계약 (WP71-2):
// · 페이지 h1 = text-3xl (1개) · md h1 → text-lg · h2 → text-base · h3 → text-sm
// · p/li/blockquote text-sm leading-5 · 표 text-xs · 사이트 밖 크기 0건
// · 표 = BiotechTable (activist 정합) · 열 ≤ 7 · 숫자 우측 font-mono
// · .biotech-md 삭제 (grep 0건)

"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { BiotechTable, BiotechTableColumn } from "@/components/biotech/BiotechTable";
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

type BiotechDoc = {
  path: string;
  title: string;
  generated_utc: string;
  html: string;
  raw_md_size: number;
  render_mode?: string;
};

type RumorDates = { dates: string[]; latest: string | null };

type TabKey = "radar" | "rumor" | "status" | "glossary" | "final";

const TABS: { key: TabKey; label: string }[] = [
  { key: "radar", label: "레이더" },
  { key: "rumor", label: "소문 확인" },
  { key: "status", label: "상태판" },
  { key: "glossary", label: "용어집" },
  { key: "final", label: "Phase A 최종" },
];

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1/biotech${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const err: Error & { status?: number } = new Error(`API ${path} failed: ${res.status}${body ? " · " + body.slice(0, 200) : ""}`);
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

const RADAR_COLUMNS: BiotechTableColumn<RadarRow>[] = [
  { key: "rank", label: "#", align: "right", render: (r) => r.rank },
  { key: "ticker", label: "티커", render: (r) => r.ticker },
  { key: "name", label: "회사", render: (r) => <span className="text-muted-foreground">{r.name}</span> },
  { key: "mcap_bucket", label: "시총" },
  { key: "state", label: "상태" },
  { key: "score", label: "점수", align: "right", render: (r) => r.score.toFixed(3) },
  { key: "news_window", label: "뉴스 예정" },
];

const RUMOR_COLUMNS: BiotechTableColumn<RumorRow>[] = [
  { key: "table", label: "표" },
  { key: "ticker", label: "티커" },
  { key: "name", label: "회사", render: (r) => <span className="text-muted-foreground">{r.name}</span> },
  { key: "mcap_bucket", label: "시총" },
  { key: "days_hint", label: "시점" },
  { key: "st_24h", label: "ST24", align: "right", render: (r) => r.st_24h ?? "—" },
  { key: "detail", label: "근거" },
];

export default function BiotechPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [active, setActive] = useState<TabKey>("radar");
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [rumor, setRumor] = useState<RumorJson | null>(null);
  const [doc, setDoc] = useState<BiotechDoc | null>(null);
  const [rumorDates, setRumorDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (tab: TabKey, date?: string) => {
    setLoading(true);
    setError(null);
    setDoc(null);
    setRadar(null);
    setRumor(null);
    try {
      if (tab === "radar") {
        setRadar(await apiFetch<RadarJson>("/radar.json"));
      } else if (tab === "rumor") {
        setRumor(await apiFetch<RumorJson>(date ? `/rumor.json?date=${date}` : "/rumor.json"));
      } else {
        setDoc(await apiFetch<BiotechDoc>(`/${tab}`));
      }
    } catch (e) {
      const err = e as Error & { status?: number };
      setError(`${err.message} (status=${err.status ?? "?"})`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active === "rumor" && rumorDates.length === 0) {
      apiFetch<RumorDates>("/rumor/dates")
        .then((r) => {
          setRumorDates(r.dates);
          setSelectedDate(r.latest);
        })
        .catch(() => {});
    }
    load(active, active === "rumor" ? selectedDate ?? undefined : undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, selectedDate]);

  const isAdmin = session?.role === "admin";

  // activist-radar 골격 그대로 · <div className="space-y-4"> 최외곽
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

      <nav className="flex flex-wrap gap-2 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={
              active === t.key
                ? "px-3 py-1.5 text-sm font-bold border-b-2 border-sky-600 text-sky-700 dark:text-sky-300"
                : "px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
            }
          >
            {t.label}
          </button>
        ))}
      </nav>

      {active === "rumor" && rumorDates.length > 0 && (
        <div className="flex items-center gap-2 text-sm">
          <label className="text-muted-foreground">날짜:</label>
          <select
            value={selectedDate ?? ""}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="rounded border border-border bg-background px-2 py-1 text-sm"
          >
            {rumorDates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      )}

      {loading && (
        <div className="rounded border border-border bg-card p-4 text-sm text-muted-foreground">로딩 중…</div>
      )}

      {error && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {!loading && !error && active === "radar" && radar && (
        <>
          <div className="text-xs text-muted-foreground font-mono">
            📁 {radar.source_csv} · 생성 {radar.generated}
          </div>
          <BiotechTable
            columns={RADAR_COLUMNS}
            rows={radar.rows}
            caption="레이더 상위 30 (뉴스 예정일 임박순)"
          />
        </>
      )}

      {!loading && !error && active === "rumor" && rumor && (
        <>
          <div className="text-xs text-muted-foreground font-mono">
            📅 {rumor.date} · 생성 {rumor.generated}
          </div>
          <BiotechTable
            columns={RUMOR_COLUMNS}
            rows={rumor.rows}
            caption="소문 확인 표 1~4 통합 (표1 살 자리 · 표2 통과 · 표3 언급 · 표4 임원 매수)"
          />
        </>
      )}

      {!loading && !error && (active === "status" || active === "glossary" || active === "final") && doc && (
        <article className="space-y-2">
          <div className="text-xs text-muted-foreground font-mono">
            📁 {doc.path} · 생성 UTC {doc.generated_utc} · {doc.raw_md_size.toLocaleString()} B
            {doc.render_mode === "plain_md_fallback" && (
              <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                fallback
              </span>
            )}
          </div>
          <div
            className="rounded border border-border bg-card p-4"
            /* biotech.py 가 python-markdown 로 렌더한 신뢰 가능한 HTML + 프론트에서 계약 클래스 주입 */
            dangerouslySetInnerHTML={{ __html: applyContractToHtml(doc.html) }}
          />
        </article>
      )}
    </div>
  );
}
