import { redirect } from "next/navigation";

/**
 * 화약고 스크리너 · 사용자 가이드 리다이렉트 페이지.
 *
 * v1.25 (2026-07-16 · 사용자 지적):
 *   "https://optimus8.cafe24.com/docs/powderkeg-user-guide 404"
 *
 * 이 페이지는 서버 사이드 리다이렉트 · GitHub 원본 문서로 즉시 이동.
 * (앱 내 markdown 렌더링은 v2 · 지금은 GitHub 링크만 유지)
 */
export default function PowderKegUserGuideRedirect() {
  redirect("https://github.com/GONNIM/toss-tradebot-mvp/blob/main/docs/plans/powderkeg-screener/user-guide.md");
}
