"use client";

// 게이트 닫힘 or 폐기 발동 시 리스트 대체 안내 (v6 §2.8)

export function HunterEmptyGate({
  deprecated,
  reasons,
}: {
  deprecated: boolean;
  reasons: string[];
}) {
  if (deprecated) {
    return (
      <section className="rounded-lg border border-red-500/40 bg-red-500/5 p-6 text-center">
        <div className="text-lg font-bold text-red-500">🚨 발굴 리스트 폐기</div>
        <p className="mt-2 text-sm text-muted-foreground">
          이 페이지는 <strong>검증 결과 알파 부재로 자동 폐기</strong>되었습니다.
          <br />
          IWM 벤치마크 대비 비용 차감 초과수익 (3d) ≤ 0 · 유효 이벤트 150+ 축적 후 판정.
        </p>
        <p className="mt-3 text-[11px] text-muted-foreground">
          다시 켜려면 위험 원칙 문서에 재개 이유를 남기고, 코드의 재개 표시(상수)를 바꿔 다시 배포해야 합니다 (두 단계 확인).
        </p>
      </section>
    );
  }
  return (
    <section className="rounded-lg border border-slate-500/40 bg-slate-500/5 p-6 text-center">
      <div className="text-lg font-bold text-slate-400">⏸ 게이트 닫힘 · 데이터 축적 중</div>
      <p className="mt-2 text-sm text-muted-foreground">
        발굴 리스트 노출 조건 미충족.
      </p>
      {reasons.length > 0 && (
        <ul className="mt-3 text-[11px] text-muted-foreground">
          {reasons.map((r, i) => (
            <li key={i}>· {r}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
