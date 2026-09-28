// WP74 3단계 · Biotech 문서 3개 (상태판 · 용어집 · 최종 리포트) · /biotech 첫 화면에서 분리
// 기존 /biotech 하단 글 탭 코드 이동 · applyContractToHtml 계약 유지 · API 무변경
"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BiotechSessionControl } from "@/components/biotech/BiotechSessionControl";
import type { SessionInfo } from "@/lib/auth";

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
  { key: "final", label: "최종 리포트" },
];

function isDocTab(v: string | null): v is DocTabKey {
  return v === "status" || v === "glossary" || v === "final";
}

async function fetchDoc(key: DocTabKey): Promise<BiotechDoc> {
  const res = await fetch(`/api/v1/biotech/${key}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) throw new Error(`API /${key} failed: ${res.status}`);
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

export default function BiotechDocsPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [active, setActive] = useState<DocTabKey>("status");
  const [doc, setDoc] = useState<BiotechDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = session?.role === "admin";

  // ?tab= 쿼리로 첫 탭 선택 (첫 화면 링크 3개 연결)
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (isDocTab(t)) setActive(t);
  }, []);

  const load = useCallback(async (key: DocTabKey) => {
    setError(null);
    setDoc(null);
    try {
      setDoc(await fetchDoc(key));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load(active);
  }, [isAdmin, active, load]);

  function select(key: DocTabKey) {
    setActive(key);
    window.history.replaceState(null, "", `/biotech/docs?tab=${key}`);
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">🧬 Biotech 문서</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            <Link href="/biotech" className="text-sky-700 hover:underline dark:text-sky-300">← 레이더로 돌아가기</Link>
          </p>
        </div>
        <BiotechSessionControl onSessionChange={setSession} />
      </header>

      {!isAdmin && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          🔒 관리자 로그인이 필요합니다. 오른쪽 위 입력칸에 관리자 토큰을 넣어 로그인하세요.
        </div>
      )}

      {isAdmin && (
        <div className="space-y-2">
          <nav className="flex flex-wrap gap-2 border-b border-border">
            {DOC_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => select(t.key)}
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
          {error && (
            <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">{error}</div>
          )}
          {!doc && !error && <div className="text-sm text-muted-foreground">불러오는 중…</div>}
          {doc && (
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
                dangerouslySetInnerHTML={{ __html: applyContractToHtml(doc.html) }}
              />
            </article>
          )}
        </div>
      )}
    </div>
  );
}
