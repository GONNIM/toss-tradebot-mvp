/**
 * 관리자 세션 클라이언트 · Phase D 주 7 · 2026-07-31.
 *
 * localStorage 기반 X-API-Token 저장을 httpOnly 쿠키 세션으로 대체.
 * XSS 방어선 완결 (localStorage 는 스크립트 접근 가능 · httpOnly 쿠키는 불가).
 *
 * 서버 계약: backend/api/routes/session.py
 *   POST   /api/v1/admin/session  { token } → SessionInfo + Set-Cookie
 *   DELETE /api/v1/admin/session                → SessionInfo (쿠키 삭제)
 *   GET    /api/v1/admin/session                → SessionInfo (whoami · 예외 없음)
 *
 * 사용:
 *   import { login, logout, whoami, useSession } from "@/lib/auth";
 */

const BASE = "/api/v1/admin/session";

export type Role = "admin" | "subscriber" | "anon";

export interface SessionInfo {
  role: Role;
  live_enabled: boolean;
}

export async function login(token: string): Promise<SessionInfo> {
  const res = await fetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `로그인 실패 (${res.status})`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j?.detail) msg = j.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return (await res.json()) as SessionInfo;
}

export async function logout(): Promise<SessionInfo> {
  const res = await fetch(BASE, {
    method: "DELETE",
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`로그아웃 실패 (${res.status})`);
  return (await res.json()) as SessionInfo;
}

export async function whoami(): Promise<SessionInfo> {
  const res = await fetch(BASE, {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    // 서버 오류여도 UI 는 anon 취급 (whoami 는 예외 없음이 계약)
    return { role: "anon", live_enabled: false };
  }
  return (await res.json()) as SessionInfo;
}

// ─────────────────────────────────────────────
// 레거시 localStorage 정리 유틸 (마이그레이션 1회 실행)
// ─────────────────────────────────────────────

const LEGACY_TOKEN_KEY = "sniper_api_token";

/**
 * Phase D 이관 · 최초 마운트 시 1회 호출.
 * 기존 localStorage 토큰이 있으면 세션으로 승격 후 삭제.
 * XSS 회귀 위험 제거 · 사용자 재로그인 부담 최소.
 */
export async function migrateLegacyToken(): Promise<void> {
  if (typeof window === "undefined") return;
  const legacy = window.localStorage.getItem(LEGACY_TOKEN_KEY);
  if (!legacy) return;
  try {
    await login(legacy);
  } catch {
    // 승격 실패해도 조용히 삭제 · 토큰 잔존이 더 큰 위험
  } finally {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
}
