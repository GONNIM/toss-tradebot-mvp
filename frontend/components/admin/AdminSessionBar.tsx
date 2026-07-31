"use client";

/**
 * 관리자 세션 바 · Phase D 주 7 · 2026-07-31.
 *
 * 3개 관리자 페이지(sniper·watchlist·powderkeg) 공용 UI.
 * 토큰 입력 → POST /api/v1/admin/session → httpOnly 쿠키 발급.
 * 이후 편집·실주문 요청은 자격증명 자동 전송(credentials: "include") 으로 통과.
 *
 * localStorage 는 저장하지 않는다 (XSS 취약). 페이지 전환·새로고침 후에도
 * 쿠키가 살아있으면 세션 유지 · 세션 만료(12h) 시 재로그인.
 */

import { useEffect, useState } from "react";
import { login, logout, migrateLegacyToken, whoami } from "@/lib/auth";
import type { SessionInfo } from "@/lib/auth";

interface Props {
  /** 세션 상태 변경(login/logout) 완료 시 부모에 알림. isAdmin 로컬 캐싱 갱신용. */
  onSessionChange?: (info: SessionInfo) => void;
  /** 페이지 컨텍스트 · 도움말 문구에만 사용 (인증 로직 무관). */
  scope?: "sniper" | "watchlist" | "powderkeg";
}

const SCOPE_HINT: Record<NonNullable<Props["scope"]>, string> = {
  sniper: "파라미터 편집·자동매매 On/Off·실주문 요청 시 필요.",
  watchlist: "확정·수동 편입·잠금·삭제 등 편집 작업 시 필요.",
  powderkeg: "런 실행·리스트 편집 등 관리 작업 시 필요.",
};

export function AdminSessionBar({ onSessionChange, scope = "sniper" }: Props) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await migrateLegacyToken();
      const info = await whoami();
      if (cancelled) return;
      setSession(info);
      onSessionChange?.(info);
    })();
    return () => {
      cancelled = true;
    };
  }, [onSessionChange]);

  const isAdmin = session?.role === "admin";

  async function handleLogin() {
    setError(null);
    setBusy(true);
    try {
      const info = await login(draft.trim());
      setSession(info);
      setDraft("");
      onSessionChange?.(info);
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setError(null);
    setBusy(true);
    try {
      const info = await logout();
      setSession(info);
      onSessionChange?.(info);
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그아웃 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          🔐 관리자 세션
          {isAdmin ? (
            <span className="ml-2 rounded bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
              admin · 활성 (httpOnly 쿠키)
            </span>
          ) : (
            <span className="ml-2 rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-950 dark:text-red-300">
              anon · 편집·실주문 불가
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={() => setShowHelp(!showHelp)}
          className="text-xs text-sky-600 hover:underline"
        >
          {showHelp ? "설명 닫기" : "❓ 이게 뭐예요?"}
        </button>
      </div>
      {showHelp && (
        <div className="mb-3 rounded bg-slate-50 p-2 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">
          <p className="mb-1">
            <strong>왜 필요한가?</strong> 이 백엔드는 로그인 시스템이 없습니다. {SCOPE_HINT[scope]}
          </p>
          <p className="mb-1">
            <strong>어디서 발급받나?</strong> 최초 1회 터미널에서{" "}
            <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">openssl rand -base64 32</code> 실행 →
            SOPS 편집(<code className="rounded bg-slate-200 px-1 dark:bg-slate-800">sops edit backend/.env.sops.yaml</code>) 에{" "}
            <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">SNIPER_API_TOKEN</code> 저장.
          </p>
          <p>
            <strong>저장 방식?</strong> 서버가 httpOnly 쿠키(<code className="rounded bg-slate-200 px-1 dark:bg-slate-800">sniper_session</code>)로 응답 · 브라우저 JS 접근 불가 (XSS 방어).
            세션 유지 12시간 · 이후 재로그인 필요.
          </p>
        </div>
      )}
      {isAdmin ? (
        <div className="flex items-center gap-2">
          <p className="flex-1 text-xs text-slate-600 dark:text-slate-400">
            세션 활성 · 이 브라우저에서 편집·실주문 요청 허용.
          </p>
          <button
            type="button"
            onClick={handleLogout}
            disabled={busy}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
          >
            로그아웃
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draft.trim().length > 0 && !busy) handleLogin();
            }}
            placeholder="SNIPER_API_TOKEN 입력"
            className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm font-mono"
          />
          <button
            type="button"
            onClick={handleLogin}
            disabled={busy || draft.trim().length === 0}
            className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? "확인 중…" : "로그인"}
          </button>
        </div>
      )}
      {error && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">⚠️ {error}</p>
      )}
    </section>
  );
}
