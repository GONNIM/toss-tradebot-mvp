"use client";

/**
 * 헤더 관리자 로그인 · 1022-10 1단계 (2026-10-29).
 *
 * 사이트 전체의 로그인 칸 하나. 로그인·로그아웃 때와 창으로 돌아왔을 때 상태가
 * 바뀌면 emitSessionChange 로 화면(AdminSessionBar·BiotechSessionControl)에 알린다.
 * 인증은 lib/auth (httpOnly 쿠키) 그대로 · 토큰은 저장하지 않는다.
 */

import { useEffect, useRef, useState } from "react";
import { emitSessionChange, login, logout, migrateLegacyToken, whoami } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";

export function HeaderSession() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const roleRef = useRef<SessionInfo["role"] | null>(null);

  function apply(info: SessionInfo, force = false) {
    setSession(info);
    if (force || roleRef.current !== info.role) {
      roleRef.current = info.role;
      emitSessionChange(info);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await migrateLegacyToken();
      const info = await whoami();
      if (!cancelled) apply(info);
    })();
    // 세션 만료(12시간)·다른 탭 로그아웃 뒤 표시를 맞춘다
    const onFocus = () => {
      whoami().then((info) => apply(info));
    };
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  async function run(fn: () => Promise<SessionInfo>) {
    setError(null);
    setBusy(true);
    try {
      const info = await fn();
      setDraft("");
      setOpen(false);
      apply(info, true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "요청 실패");
    } finally {
      setBusy(false);
    }
  }

  const isAdmin = session?.role === "admin";

  if (isAdmin) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="inline-block h-2 w-2 rounded-full bg-teal-600" aria-hidden />
        <span className="text-foreground">관리자</span>
        <button
          type="button"
          onClick={() => run(logout)}
          disabled={busy}
          className="min-h-[44px] rounded-lg px-3 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          로그아웃
        </button>
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="min-h-[44px] rounded-lg px-3 text-sm text-muted-foreground hover:text-foreground"
      >
        관리자 로그인
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-[14px] border border-border bg-card p-3 text-sm">
          <div className="flex gap-2">
            <input
              type="password"
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draft.trim() && !busy) run(() => login(draft.trim()));
                if (e.key === "Escape") setOpen(false);
              }}
              placeholder="관리자 토큰"
              aria-label="관리자 토큰"
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2 py-2 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => run(() => login(draft.trim()))}
              disabled={busy || !draft.trim()}
              className="rounded-lg bg-teal-600 px-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              {busy ? "확인 중…" : "로그인"}
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
          <p className="mt-2 text-xs text-muted-foreground">
            편집·실주문·관리 화면 보기에 필요합니다. 로그인은 이 브라우저에서 12시간 유지됩니다.
          </p>
        </div>
      )}
    </div>
  );
}
