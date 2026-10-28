// WP74 2단계 · Biotech 헤더 우측 세션 표시 → 1022-10 1단계 (2026-10-29)
// 로그인 칸은 사이트 헤더(HeaderSession) 하나로 합쳤다. 이 부품은 세션 상태를 받아
// 부모의 onSessionChange 를 그대로 부르고, 로그인 전에는 안내 한 줄만 보인다.
"use client";

import { useCallback, useState } from "react";
import { useSessionListener } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";

export function BiotechSessionControl({ onSessionChange }: { onSessionChange?: (info: SessionInfo) => void }) {
  const [role, setRole] = useState<SessionInfo["role"] | null>(null);
  const handle = useCallback(
    (info: SessionInfo) => {
      setRole(info.role);
      onSessionChange?.(info);
    },
    [onSessionChange],
  );
  useSessionListener(handle);

  if (role === null || role === "admin") return null;
  return <p className="text-xs text-muted-foreground">관리자 기능은 오른쪽 위에서 로그인한 뒤 보입니다.</p>;
}
