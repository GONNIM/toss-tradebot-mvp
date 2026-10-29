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
 *   import { login, logout, whoami, emitSessionChange, useSessionListener } from "@/lib/auth";
 */

import { useEffect, useRef } from "react";

const BASE = "/api/v1/admin/session";

export type Role = "admin" | "subscriber" | "anon";

// 1028-04 · 편집 API 가 401 이면 영어 일반 문구 대신 로그인 안내
export const LOGIN_REQUIRED_MESSAGE =
  "관리자 로그인이 필요합니다. 오른쪽 위 「관리자 로그인」 에서 로그인한 뒤 다시 누르십시오.";

export function editErrorMessage(err: Error): string {
  return /failed: 401\b/.test(err.message) ? LOGIN_REQUIRED_MESSAGE : err.message;
}

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

// ─────────────────────────────────────────────
// 1022-10 1단계 · 헤더 로그인 하나 → 화면에 알림
// ─────────────────────────────────────────────

const SESSION_EVENT = "admin-session-change";

/** 헤더 로그인·로그아웃·포커스 재확인 때 호출 · 화면의 useSessionListener 가 받는다. */
export function emitSessionChange(info: SessionInfo): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SessionInfo>(SESSION_EVENT, { detail: info }));
}

/**
 * 화면 쪽 세션 구독. 마운트 때 whoami() 로 지금 상태를 한 번 넘기고 (헤더는 layout 에
 * 한 번만 마운트되어 이미 지나간 이벤트를 화면이 못 받기 때문), 그 뒤 헤더 이벤트를 받는다.
 * 이벤트가 먼저 오면 늦게 도착한 마운트 whoami 결과는 버린다 (Fable 1022-10-02 권고).
 */
export function useSessionListener(onChange?: (info: SessionInfo) => void): void {
  const cb = useRef(onChange);
  useEffect(() => {
    cb.current = onChange;
  }, [onChange]);

  useEffect(() => {
    let cancelled = false;
    let gotEvent = false;
    // 1022-10-03 M1 · 하드 로드 중복: 헤더 첫 whoami 이벤트가 화면 마운트 whoami 와 같은 값이면 건너뛴다
    let last: string | null = null;
    const deliver = (info: SessionInfo) => {
      const key = `${info.role}:${info.live_enabled}`;
      if (key === last) return;
      last = key;
      cb.current?.(info);
    };
    const handler = (e: Event) => {
      gotEvent = true;
      deliver((e as CustomEvent<SessionInfo>).detail);
    };
    window.addEventListener(SESSION_EVENT, handler);
    (async () => {
      const info = await whoami();
      if (cancelled || gotEvent) return;
      deliver(info);
    })();
    return () => {
      cancelled = true;
      window.removeEventListener(SESSION_EVENT, handler);
    };
  }, []);
}
