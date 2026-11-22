// 1120-01 단계 4 d · 오늘 화면 「보유 경보」 기한 문구 (경보 규칙은 그대로 · 문구만).
// 기한 경보는 「기한 ≤ 오늘」이면 보유가 남아 있는 동안 계속 나온다. 며칠 지났는지 함께 적어 오래된 경보임을 알린다.

/** YYYY-MM-DD 두 날짜의 일수 차이 (today - deadline). 모양이 틀리면 null. */
export function daysPast(deadline: string | null | undefined, today: string): number | null {
  const re = /^\d{4}-\d{2}-\d{2}$/;
  if (!deadline || !re.test(deadline) || !re.test(today)) return null;
  const a = Date.UTC(+deadline.slice(0, 4), +deadline.slice(5, 7) - 1, +deadline.slice(8, 10));
  const b = Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10));
  return Math.round((b - a) / 86400000);
}

/** 한국 날짜(YYYY-MM-DD). */
export function todayKst(now: Date = new Date()): string {
  return now.toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
}

/** 「기한 도달 (10/13)」 뒤에 「 · N일 지남」을 붙인다 (오늘이 기한이면 「오늘 기한」). */
export function deadlineFact(deadline: string | null | undefined, today: string): string {
  const md = deadline && deadline.length >= 10 ? `${deadline.slice(5, 7)}/${deadline.slice(8, 10)}` : null;
  const d = daysPast(deadline, today);
  const base = md ? `기한 도달 (${md})` : "기한 도달";
  if (d === null || d < 0) return base;
  if (d === 0) return `${base} · 오늘이 기한`;
  return `${base} · ${d}일 지남`;
}
