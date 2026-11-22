// WP74 3단계 · Biotech 문서 3개 (상태판 · 용어집 · 최종 리포트) · /biotech 첫 화면에서 분리
// 1120-01 단계 3 · 문서 보기는 components/biotech/BiotechDocsViewer.tsx 로 떼어 냄 (/biotech 맨 아래 접기와 같이 씀)
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BiotechSessionControl } from "@/components/biotech/BiotechSessionControl";
import { BiotechDocsViewer, isDocTab, type DocTabKey } from "@/components/biotech/BiotechDocsViewer";
import type { SessionInfo } from "@/lib/auth";

export default function BiotechDocsPage() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [initial, setInitial] = useState<DocTabKey>("status");
  const isAdmin = session?.role === "admin";

  // ?tab= 쿼리로 첫 탭 선택 (첫 화면 링크 3개 연결)
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (isDocTab(t)) setInitial(t);
  }, []);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">🧬 Biotech 문서</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            <Link href="/biotech" className="text-primary hover:underline">← 레이더로 돌아가기</Link>
          </p>
        </div>
        <BiotechSessionControl onSessionChange={setSession} />
      </header>

      {!isAdmin && (
        <div className="rounded-lg border border-warn/50 bg-warn/10 p-4 text-sm text-warn">
          🔒 관리자 로그인이 필요합니다. 오른쪽 위 「로그인」 에서 로그인하십시오.
        </div>
      )}

      <BiotechDocsViewer isAdmin={isAdmin} initial={initial} />
    </div>
  );
}
