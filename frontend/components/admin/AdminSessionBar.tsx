"use client";

/**
 * 관리자 세션 안내 줄 · Phase D 주 7 · 2026-07-31 → 1022-10 1단계 (2026-10-29).
 *
 * 로그인 칸은 헤더(HeaderSession) 하나로 합쳤다. 이 부품은 화면마다 남아
 * 세션 상태를 받아 부모의 onSessionChange 를 그대로 부른다 (isAdmin·다시 읽기 유지).
 * 로그인 전에는 「헤더에서 로그인」 안내 한 줄만 보인다.
 */

import { useCallback, useState } from "react";
import { useSessionListener } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";

interface Props {
  /** 세션 상태 변경(로그인·로그아웃·마운트 확인) 때 부모에 알림. */
  onSessionChange?: (info: SessionInfo) => void;
  /** 옛 화면별 도움말 구분 · 1022-10 1단계부터 쓰지 않음 (호출부 호환용). */
  scope?: string;
}

export function AdminSessionBar({ onSessionChange }: Props) {
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
  return (
    <p className="rounded border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
      편집하려면 오른쪽 위 「관리자 로그인」 에서 로그인하십시오.
    </p>
  );
}
