"use client";

// 50 <= valid < 150 구간에서 초과수익 음수 시 리스트 상단 적색 경고 (v6 §2.9)

export function MidGateWarning({ valid, needed }: { valid: number; needed: number }) {
  return (
    <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">
      ⚠ 검증 데이터 축적 중 (N={valid}/{needed}). 현재까지 IWM 대비 비용 차감 초과수익 음수.
      폐기 판정 대기 · <strong>매수 지양</strong>.
    </div>
  );
}
