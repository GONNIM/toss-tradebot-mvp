// WP74 2단계 · Biotech 헤더 우측 세션 표시 (관리자 세션 카드 대체)
// - 로그인 상태: 초록 점 + 로그아웃 버튼만
// - 로그아웃 상태: 회색 점 + 토큰 입력 + 로그인 (로그인 수단이 사라지지 않도록 유지)
// 인증 로직은 공용 lib/auth (httpOnly 쿠키) 그대로 사용 · 토큰은 저장하지 않음
"use client";

import { useEffect, useRef, useState } from "react";
import { login, logout, migrateLegacyToken, whoami } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";

export function BiotechSessionControl({ onSessionChange }: { onSessionChange?: (info: SessionInfo) => void }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cb = useRef(onSessionChange);
  useEffect(() => {
    cb.current = onSessionChange;
  }, [onSessionChange]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await migrateLegacyToken();
      const info = await whoami();
      if (cancelled) return;
      setSession(info);
      cb.current?.(info);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function run(fn: () => Promise<SessionInfo>) {
    setError(null);
    setBusy(true);
    try {
      const info = await fn();
      setSession(info);
      setDraft("");
      cb.current?.(info);
    } catch (e) {
      setError(e instanceof Error ? e.message : "요청 실패");
    } finally {
      setBusy(false);
    }
  }

  const isAdmin = session?.role === "admin";
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2 text-xs">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${isAdmin ? "bg-emerald-500" : "bg-slate-400"}`}
          aria-label={isAdmin ? "관리자 로그인됨" : "로그인 필요"}
          title={isAdmin ? "관리자 로그인됨" : "로그인 필요"}
        />
        {isAdmin ? (
          <button
            type="button"
            onClick={() => run(logout)}
            disabled={busy}
            className="rounded border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
          >
            로그아웃
          </button>
        ) : (
          <>
            <input
              type="password"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draft.trim() && !busy) run(() => login(draft.trim()));
              }}
              placeholder="관리자 토큰"
              className="w-40 rounded border border-border bg-background px-2 py-1 text-xs font-mono"
            />
            <button
              type="button"
              onClick={() => run(() => login(draft.trim()))}
              disabled={busy || !draft.trim()}
              className="rounded border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
            >
              {busy ? "확인 중…" : "로그인"}
            </button>
          </>
        )}
      </div>
      {error && <p className="text-xs text-red-600 dark:text-red-400">⚠️ {error}</p>}
    </div>
  );
}
