"use client";

// 계획 실행기 화면 공통 · 맨 위 모드 띠 + 로그아웃이면 안내만 (모든 계획 API 가 401)
import Link from "next/link";
import { useState } from "react";
import { useSessionListener } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";
import { ModeBand } from "@/components/plans/ModeBand";

export default function PlansLayout({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<SessionInfo["role"] | null>(null);
  useSessionListener((i) => setRole(i.role));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">
          <Link href="/plans" aria-label="계획 목록으로" data-testid="plans-home">
            계획
          </Link>
        </h1>
        <p className="text-xs text-muted-foreground">숫자는 규칙으로 계산한 값입니다 · 추정 · 수익 보장 아님</p>
      </div>
      {role === null && <p className="text-sm text-muted-foreground">로그인 상태를 확인하는 중입니다</p>}
      {role !== null && role !== "admin" && (
        <p data-testid="plans-login-required" role="alert" className="rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-sm text-warn">
          계획 화면은 관리자만 볼 수 있습니다. 오른쪽 위 「관리자 로그인」 에서 로그인하십시오.
        </p>
      )}
      {role === "admin" && (
        <>
          <ModeBand />
          {children}
        </>
      )}
    </div>
  );
}
