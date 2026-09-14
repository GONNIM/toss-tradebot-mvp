// Biotech Radar · 통합 대시보드 (WP69-1 · 2026-09-14 · admin 전용)
// 참조: docs/plans/biotech/SITE-ANALYSIS.md §2
//       docs/plans/biotech/README.md §1 (격리 원칙)
//
// 좌측 탭 5개 = radar (레이더) · rumor (소문) · status (상태판) · glossary (용어집) · final (Phase A 최종)
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
    // rumor 탭 전환 시 날짜 목록 로드
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
    <main className="mx-auto max-w-6xl px-4 py-6 space-y-4">
      <AdminSessionBar onSessionChange={setSession} />

      <div className="rounded-md bg-amber-50 border-l-4 border-amber-500 p-3 text-sm">
        ⚠️ <b>알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님</b> ·
        자동매매 없음 · 반자동 티켓도 Phase C 1순위 보류함
      </div>

      <h1 className="text-2xl font-bold">🧬 Biotech Catalyst Radar</h1>
      <p className="text-sm text-gray-600">
        급등 이전 바이오 종목 사전 감지 · 9 가설 검증 · Phase A 종결 (2026-09-14) · Fable 최종 검수 통과
      </p>

      {!isAdmin && (
        <div className="rounded-md bg-red-50 border-l-4 border-red-500 p-3 text-sm">
          🔒 <b>admin 세션 필요</b> · 상단 로그인 바에서 관리자 토큰으로 로그인 후 이용
        </div>
      )}

      <nav className="flex flex-wrap gap-2 border-b pb-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            title={t.hint}
            className={`px-3 py-1.5 rounded-t text-sm transition-colors ${
              active === t.key
                ? "bg-indigo-600 text-white"
                : "bg-gray-100 hover:bg-gray-200 text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {active === "rumor" && rumorDates.length > 0 && (
        <div className="text-sm">
          <label className="mr-2">날짜:</label>
          <select
            value={selectedDate ?? ""}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="border rounded px-2 py-1"
          >
            {rumorDates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      )}

      {loading && <p className="text-sm text-gray-500">로딩 중…</p>}

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-800">
          <b>오류</b>: {error}
        </div>
      )}

      {doc && !loading && !error && (
        <article className="space-y-2">
          <div className="text-xs text-gray-500">
            📁 {doc.path} · 생성 UTC {doc.generated_utc} · {doc.raw_md_size.toLocaleString()} B
          </div>
          <div
            className="biotech-md prose prose-sm max-w-none"
            // 백엔드는 python-markdown 로 렌더한 신뢰 가능한 HTML (사용자 입력 아님 · 리포트 md)
            dangerouslySetInnerHTML={{ __html: doc.html }}
          />
        </article>
      )}

      <style jsx global>{`
        .biotech-md h1 { font-size: 1.5rem; font-weight: 700; margin: 1rem 0 0.5rem; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.25rem; }
        .biotech-md h2 { font-size: 1.25rem; font-weight: 600; margin: 1rem 0 0.5rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.25rem; }
        .biotech-md h3 { font-size: 1.1rem; font-weight: 600; margin: 0.75rem 0 0.4rem; }
        .biotech-md p { margin: 0.4rem 0; line-height: 1.6; }
        .biotech-md ul, .biotech-md ol { padding-left: 1.5rem; margin: 0.4rem 0; }
        .biotech-md table { border-collapse: collapse; width: 100%; margin: 0.8rem 0; font-size: 0.9rem; }
        .biotech-md th, .biotech-md td { border: 1px solid #e5e7eb; padding: 0.4rem 0.6rem; text-align: left; }
        .biotech-md th { background: #f9fafb; font-weight: 600; }
        .biotech-md code { background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.85em; }
        .biotech-md pre { background: #f3f4f6; padding: 0.6rem; border-radius: 4px; overflow-x: auto; font-size: 0.85em; }
        .biotech-md blockquote { border-left: 4px solid #d1d5db; padding: 0 0.8rem; color: #6b7280; margin: 0.4rem 0; }
        .biotech-md a { color: #4f46e5; text-decoration: none; }
        .biotech-md a:hover { text-decoration: underline; }
      `}</style>
    </main>
  );
}
