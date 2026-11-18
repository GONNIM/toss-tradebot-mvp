"use client";

import { Notice } from "@/components/plans/ui";

/** 계획서 8-1 · 인수 대기 문구 · 인수 화면과 인수 대기 상세에 늘 보인다 */
export function AdoptNotice() {
  return (
    <Notice tone="warn" testid="adopt-notice">
      앱 조건주문을 지우시면 10초 안에 실행기 손절이 걸립니다 · 그 사이 최대 10초 손절이 없습니다
    </Notice>
  );
}
