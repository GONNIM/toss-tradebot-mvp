// Biotech Radar · 통합 대시보드 (WP70 · 2026-09-18 · FE-RULES 정합 재스타일)
// 참조: docs/plans/biotech/SITE-ANALYSIS.md §2
//       docs/plans/biotech/FE-RULES.md (기존 /activist-radar · /powderkeg 정합)
//       docs/plans/biotech/README.md §1 (격리 원칙)
//
// 좌측 탭 5개 = radar · rumor · status · glossary · final
// 백엔드 API: /api/v1/biotech/{radar|rumor|status|glossary|final} · docs md → HTML
// 인증: 기존 admin 세션 재사용 (require_sniper_token)

"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import type { SessionInfo } from "@/lib/auth";

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

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "radar", label: "📡 레이더 순위표", hint: "오늘 상위 30 (뉴스 예정일 임박순)" },
  { key: "rumor", label: "🗣️ 소문 확인", hint: "표 1~4 · 날짜 선택" },
  { key: "status", label: "🗺️ 상태판", hint: "오늘 알아낸 것 5줄 (자동 갱신)" },
  { key: "glossary", label: "📖 용어집", hint: "코드·상태·가설 뜻" },
  { key: "final", label: "📄 Phase A 최종", hint: "2026-09-14 종결본 (동결)" },
];

async function fetchDoc(path: string): Promise<BiotechDoc> {
  const res = await fetch(`/api/v1/biotech${path}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const err: Error & { status?: number } = new Error(
      `API ${path} failed: ${res.status}${body ? " · " + body.slice(0, 200) : ""}`,
    );
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function fetchRumorDates(): Promise<RumorDates> {
  const res = await fetch("/api/v1/biotech/rumor/dates", {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`rumor dates failed: ${res.status}`);
  return res.json();
}

export default function BiotechPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [active, setActive] = useState<TabKey>("radar");
  const [doc, setDoc] = useState<BiotechDoc | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rumorDates, setRumorDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const load = useCallback(async (tab: TabKey, date?: string) => {
    setLoading(true);
    setError(null);
    setDoc(null);
    try {
      let path: string;
      if (tab === "rumor") {
        path = date ? `/rumor?date=${date}` : "/rumor";
      } else {
        path = `/${tab}`;
      }
      const result = await fetchDoc(path);
      setDoc(result);
    } catch (e) {
      const err = e as Error & { status?: number };
      setError(`${err.message} (status=${err.status ?? "?"})`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active === "rumor" && rumorDates.length === 0) {
      fetchRumorDates()
        .then((r) => {
          setRumorDates(r.dates);
          setSelectedDate(r.latest);
        })
        .catch(() => {
          /* 별도 처리 안 함 · 문서 로드에서 오류 표시 */
        });
    }
    load(active, active === "rumor" ? selectedDate ?? undefined : undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, selectedDate]);

  const isAdmin = session?.role === "admin";

  return (
    <main className="container mx-auto px-4 py-6 space-y-4">
      <AdminSessionBar onSessionChange={setSession} />

      {/* 페이지 헤더 · 제목+배지 · 기존 activist-radar 정합 */}
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-bold">🧬 Biotech Catalyst Radar</h1>
        <span className="rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-semibold text-sky-700 dark:text-sky-300">
          Phase A 종결 · 2026-09-14
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        급등 이전 바이오 종목 사전 감지 · 9 가설 검증 · Fable 최종 검수 통과 · admin 전용
      </p>

      {/* 경고 배너 · amber 좌측 4px · 라이트+다크 쌍 */}
      <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-3 text-sm dark:border-amber-600 dark:bg-amber-950/40">
        ⚠️ <b>알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님</b> ·
        자동매매 없음 · 반자동 티켓도 Phase C 1순위 보류함
      </div>

      {/* 인증 안내 · red · 라이트+다크 */}
      {!isAdmin && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
          🔒 <b>admin 세션 필요</b> · 상단 로그인 바에서 관리자 토큰으로 로그인 후 이용
        </div>
      )}

      {/* 탭 · sky 활성 border-b-2 (기존 powderkeg 정합) */}
      <nav className="flex flex-wrap gap-2 border-b border-border pb-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            title={t.hint}
            className={
              active === t.key
                ? "rounded-t border-b-2 border-sky-600 px-3 py-1.5 text-sm font-bold text-sky-700 dark:text-sky-300"
                : "rounded-t bg-slate-100 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            }
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* 날짜 드롭다운 · rumor 탭 전용 · 기존 filter 스타일 */}
      {active === "rumor" && rumorDates.length > 0 && (
        <div className="flex items-center gap-2 text-sm">
          <label className="text-slate-600 dark:text-slate-400">날짜:</label>
          <select
            value={selectedDate ?? ""}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            {rumorDates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* 로딩 · muted */}
      {loading && <p className="text-sm text-muted-foreground">로딩 중…</p>}

      {/* 오류 · red 인라인 배너 */}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
          <b>오류</b>: {error}
        </div>
      )}

      {/* 콘텐츠 · md HTML · 기존 스타일 정합 (slate · sky) */}
      {doc && !loading && !error && (
        <article className="space-y-2">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
            📁 {doc.path} · 생성 UTC {doc.generated_utc} ·{" "}
            {doc.raw_md_size.toLocaleString()} B
            {doc.render_mode === "plain_md_fallback" && (
              <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                fallback
              </span>
            )}
          </div>
          <div
            className="biotech-md"
            /* 백엔드는 python-markdown 로 렌더한 신뢰 가능한 HTML (사용자 입력 아님 · 리포트 md) */
            dangerouslySetInnerHTML={{ __html: doc.html }}
          />
        </article>
      )}

      {/* Markdown 렌더 스타일 · Tailwind 색상 (slate · sky) · dark 지원 */}
      <style jsx global>{`
        .biotech-md h1 {
          font-size: 1.5rem;
          font-weight: 700;
          margin: 1rem 0 0.5rem;
          padding-bottom: 0.25rem;
          border-bottom: 2px solid rgb(226 232 240); /* slate-200 */
        }
        .dark .biotech-md h1 { border-bottom-color: rgb(51 65 85); /* slate-700 */ }
        .biotech-md h2 {
          font-size: 1.25rem;
          font-weight: 600;
          margin: 1rem 0 0.5rem;
          padding-bottom: 0.25rem;
          border-bottom: 1px solid rgb(226 232 240);
        }
        .dark .biotech-md h2 { border-bottom-color: rgb(51 65 85); }
        .biotech-md h3 { font-size: 1.05rem; font-weight: 600; margin: 0.75rem 0 0.4rem; }
        .biotech-md p { margin: 0.4rem 0; line-height: 1.6; }
        .biotech-md ul, .biotech-md ol { padding-left: 1.5rem; margin: 0.4rem 0; }
        .biotech-md li { margin: 0.15rem 0; }
        .biotech-md strong { font-weight: 600; }
        .biotech-md table {
          border-collapse: collapse;
          width: 100%;
          margin: 0.8rem 0;
          font-size: 0.85rem;
          display: block;
          overflow-x: auto;
        }
        .biotech-md th, .biotech-md td {
          border: 1px solid rgb(226 232 240);
          padding: 0.4rem 0.6rem;
          text-align: left;
          vertical-align: top;
        }
        .dark .biotech-md th, .dark .biotech-md td { border-color: rgb(51 65 85); }
        .biotech-md th { background: rgb(248 250 252); font-weight: 600; } /* slate-50 */
        .dark .biotech-md th { background: rgb(15 23 42); } /* slate-900 */
        .biotech-md code {
          background: rgb(241 245 249); /* slate-100 */
          padding: 1px 5px;
          border-radius: 3px;
          font-size: 0.85em;
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        }
        .dark .biotech-md code { background: rgb(30 41 59); } /* slate-800 */
        .biotech-md pre {
          background: rgb(241 245 249);
          padding: 0.6rem;
          border-radius: 4px;
          overflow-x: auto;
          font-size: 0.85em;
        }
        .dark .biotech-md pre { background: rgb(30 41 59); }
        .biotech-md blockquote {
          border-left: 4px solid rgb(203 213 225); /* slate-300 */
          padding: 0.25rem 0.8rem;
          color: rgb(71 85 105); /* slate-600 */
          margin: 0.5rem 0;
        }
        .dark .biotech-md blockquote {
          border-left-color: rgb(51 65 85);
          color: rgb(148 163 184); /* slate-400 */
        }
        .biotech-md a { color: rgb(2 132 199); text-decoration: none; } /* sky-600 */
        .dark .biotech-md a { color: rgb(125 211 252); } /* sky-300 */
        .biotech-md a:hover { text-decoration: underline; }
      `}</style>
    </main>
  );
}
