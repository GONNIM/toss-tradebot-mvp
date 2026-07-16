"use client";

import { useEffect } from "react";

/**
 * 화약고 스크리너 · 사용자 가이드 리다이렉트 페이지.
 *
 * v1.26 · Client-side 안정적 리다이렉트 + fallback 안내.
 *   · useEffect · 마운트 즉시 GitHub 이동
 *   · meta refresh · JS 비활성 fallback (layout head 활용 어려움 · JS 우선)
 *   · 명시 안내 · 링크 · 사용자 클릭 fallback
 */
const TARGET_URL =
  "https://github.com/GONNIM/toss-tradebot-mvp/blob/main/docs/plans/powderkeg-screener/user-guide.md";

export default function PowderKegUserGuideRedirect() {
  useEffect(() => {
    window.location.replace(TARGET_URL);
  }, []);
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="max-w-md rounded border-2 border-purple-300 bg-white p-6 text-center shadow-lg dark:bg-slate-900">
        <h1 className="mb-3 text-2xl font-bold">📖 사용자 가이드</h1>
        <p className="mb-4 text-sm text-slate-700 dark:text-slate-300">
          GitHub 원본 문서로 이동 중입니다...
        </p>
        <a
          href={TARGET_URL}
          className="inline-block rounded bg-sky-600 px-4 py-2 text-sm font-bold text-white hover:bg-sky-700"
        >
          📄 지금 이동
        </a>
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
          자동 이동이 안 될 경우 · 위 버튼 클릭
        </p>
      </div>
    </div>
  );
}
