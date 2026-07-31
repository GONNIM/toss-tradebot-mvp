/**
 * 프론트 관측성 초기화 · Phase D 주 8 · 2026-07-31.
 *
 * Sentry (@sentry/nextjs) 와 PostHog (posthog-js) 클라이언트 통합.
 * 환경변수:
 *   NEXT_PUBLIC_SENTRY_DSN       · 미설정 시 Sentry 비활성 (no-op)
 *   NEXT_PUBLIC_POSTHOG_KEY      · 미설정 시 PostHog 비활성 (no-op)
 *   NEXT_PUBLIC_POSTHOG_HOST     · 기본 https://us.i.posthog.com
 *   NEXT_PUBLIC_APP_ENV          · 환경 라벨 (local·staging·production)
 *
 * 설계:
 * - 브라우저 (window 존재)에서만 실행.
 * - 초기화 실패해도 앱 렌더링 막지 않음 (조용히 warn).
 * - useEffect 로 mount 시 1회만 호출 (idempotent).
 */

let sentryReady = false;
let posthogReady = false;

function env(name: string): string | undefined {
  const v = process.env[name];
  return v && v.length > 0 ? v : undefined;
}

export async function initObservability(): Promise<void> {
  if (typeof window === "undefined") return;
  await Promise.allSettled([initSentry(), initPostHog()]);
}

async function initSentry(): Promise<void> {
  if (sentryReady) return;
  const dsn = env("NEXT_PUBLIC_SENTRY_DSN");
  if (!dsn) return;
  try {
    const Sentry = await import("@sentry/nextjs");
    Sentry.init({
      dsn,
      environment: env("NEXT_PUBLIC_APP_ENV") || "local",
      // 성능 트레이스는 기본 0. 필요 시 env 로 승격.
      tracesSampleRate: Number(env("NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE") || "0"),
      // 세션 리플레이는 기본 0 (개인정보·비용). 향후 상품화 시 검토.
      replaysSessionSampleRate: 0,
      replaysOnErrorSampleRate: 0,
    });
    sentryReady = true;
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn("[observability] Sentry init 실패", e);
  }
}

async function initPostHog(): Promise<void> {
  if (posthogReady) return;
  const key = env("NEXT_PUBLIC_POSTHOG_KEY");
  if (!key) return;
  try {
    const posthog = (await import("posthog-js")).default;
    posthog.init(key, {
      api_host: env("NEXT_PUBLIC_POSTHOG_HOST") || "https://us.i.posthog.com",
      // 판정 저장 등 명시 capture 만 사용 · autocapture 는 노이즈 감소를 위해 off
      autocapture: false,
      // 페이지 방문은 별도 capturePageview() 로 라우터 이벤트에서 호출
      capture_pageview: true,
      capture_pageleave: true,
      persistence: "localStorage+cookie",
    });
    posthogReady = true;
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn("[observability] PostHog init 실패", e);
  }
}

/** 판정 저장·주요 상호작용 event capture · PostHog 미init 시 no-op. */
export async function capture(event: string, props?: Record<string, unknown>): Promise<void> {
  if (typeof window === "undefined") return;
  if (!posthogReady) return;
  try {
    const posthog = (await import("posthog-js")).default;
    posthog.capture(event, props);
  } catch {
    // ignore
  }
}
