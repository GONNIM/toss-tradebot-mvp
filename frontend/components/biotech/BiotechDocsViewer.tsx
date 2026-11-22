"use client";

// 1120-01 단계 3 (2026-11-22) · /biotech/docs 의 문서 보기(상태판 · 용어집 · 최종 리포트)를 부품으로 떼어 냄.
// - /biotech/docs 는 이 부품을 그대로 쓴다 (탭을 바꾸면 주소 ?tab= 도 바꿈 · 예전과 같음).
// - /biotech 맨 아래 접기 안에서는 embedded 로 쓴다: 주소를 바꾸지 않고, 로그인 칸은 /biotech 의 세션 값을 받는다.
// - 문서는 관리자일 때만 받는다 (API 무변경 · applyContractToHtml 계약 유지).

import { useCallback, useEffect, useState } from "react";

type BiotechDoc = {
  path: string;
  title: string;
  generated_utc: string;
  html: string;
  raw_md_size: number;
  render_mode?: string;
};

export type DocTabKey = "status" | "glossary" | "final";
const DOC_TABS: { key: DocTabKey; label: string }[] = [
  { key: "status", label: "상태판" },
  { key: "glossary", label: "용어집" },
  { key: "final", label: "최종 리포트" },
];

export function isDocTab(v: string | null): v is DocTabKey {
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
  out = out.replace(/<h2(\s[^>]*)?>/gi, '<h2 class="text-base font-semibold mt-3 mb-1">');
  out = out.replace(/<h3(\s[^>]*)?>/gi, '<h3 class="text-sm font-medium mt-2 mb-1">');
  // 1120-01 단계 4 · 문서 속 h1 은 h2 로 낮춘다 (화면의 큰 제목은 화면마다 하나 · 모양은 예전 h1 그대로).
  out = out.replace(/<h1(\s[^>]*)?>/gi, '<h2 class="text-lg font-bold mt-3 mb-1">').replace(/<\/h1>/gi, "</h2>");
  out = out.replace(/<p(\s[^>]*)?>/gi, '<p class="text-sm leading-5 my-1">');
  out = out.replace(/<li(\s[^>]*)?>/gi, '<li class="text-sm leading-5">');
  out = out.replace(/<blockquote(\s[^>]*)?>/gi, '<blockquote class="border-l-2 border-border pl-2 text-sm leading-5 text-muted-foreground my-1">');
  out = out.replace(/<table(\s[^>]*)?>/gi, '<table class="w-full border-collapse text-xs my-2">');
  out = out.replace(/<th(\s[^>]*)?>/gi, '<th class="border-b border-border bg-slate-50 p-1.5 text-left font-semibold">');
  out = out.replace(/<td(\s[^>]*)?>/gi, '<td class="border-b border-border p-1.5">');
  out = out.replace(/<code(\s[^>]*)?>/gi, '<code class="rounded-lg bg-slate-100 px-1 py-0.5 font-mono text-xs">');
  out = out.replace(/<pre(\s[^>]*)?>/gi, '<pre class="rounded-lg bg-slate-100 p-2 overflow-x-auto text-xs my-2">');
  out = out.replace(/<a(\s[^>]*)?>/gi, '<a class="text-primary hover:underline"$1>');
  out = out.replace(/<ul(\s[^>]*)?>/gi, '<ul class="list-disc pl-5 my-1">');
  out = out.replace(/<ol(\s[^>]*)?>/gi, '<ol class="list-decimal pl-5 my-1">');
  return out;
}

export function BiotechDocsViewer({
  isAdmin,
  initial = "status",
  embedded = false,
}: {
  isAdmin: boolean;
  initial?: DocTabKey;
  embedded?: boolean;
}) {
  const [active, setActive] = useState<DocTabKey>(initial);
  const [doc, setDoc] = useState<BiotechDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setActive(initial), [initial]);

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
    if (!embedded) window.history.replaceState(null, "", `/biotech/docs?tab=${key}`);
  }

  return (
    <>
      {isAdmin && (
        <div className="space-y-2">
          <nav className="flex flex-wrap gap-2 border-b border-border">
            {DOC_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => select(t.key)}
                className={
                  active === t.key
                    ? "px-3 py-1.5 text-sm font-bold border-b-2 border-primary text-primary"
                    : "px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
          {error && (
            <div className="rounded-lg border border-warn/50 bg-warn/10 p-4 text-sm text-warn">{error}</div>
          )}
          {!doc && !error && <div className="text-sm text-muted-foreground">불러오는 중…</div>}
          {doc && (
            <article className="space-y-2">
              <div className="text-xs text-muted-foreground font-mono">
                📁 {doc.path} · 생성 UTC {doc.generated_utc} · {doc.raw_md_size.toLocaleString()} B
                {doc.render_mode === "plain_md_fallback" && (
                  <span className="ml-2 rounded-lg bg-warn/20 px-1.5 py-0.5 text-xs font-semibold text-warn">
                    fallback
                  </span>
                )}
              </div>
              <div
                className="overflow-x-auto rounded-lg border border-border bg-card p-4"
                dangerouslySetInnerHTML={{ __html: applyContractToHtml(doc.html) }}
              />
            </article>
          )}
        </div>
      )}
    </>
  );
}
