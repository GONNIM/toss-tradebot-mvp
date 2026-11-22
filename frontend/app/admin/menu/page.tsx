"use client";

/**
 * 메뉴 보이기 (1120-01 · 2026-11-21) — 메뉴 탭마다 보임/숨김을 고른다.
 * 화면은 지워지지 않는다. 숨겨도 주소 · 알림 링크로 열리고, 자료 수집 · 예약 작업은 그대로 돈다.
 * 잠긴 화면(실주문 · 비상 정지 · 운영 값 · 알림 · 이 화면)은 숨길 수 없다.
 * 비로그인은 읽기만 · 쓰기는 /admin/notifications 와 같은 방식(관리자 쿠키 세션).
 * 토글은 화면을 먼저 바꾸고 저장이 실패하면 되돌린다.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { GROUPS } from "@/components/layout/AppNav";
import { api } from "@/lib/api";
import type { MenuVisibilityResponse } from "@/lib/api";
import type { SessionInfo } from "@/lib/auth";
import { editErrorMessage } from "@/lib/auth";
import { isLocked, RECOMMENDED_HIDE_KEYS, toMenuMap, writeStored } from "@/lib/menu-visibility";
import { MENU_QUERY_KEY } from "@/lib/use-menu-visibility";

type Banner = { kind: "ok" | "error"; text: string } | null;

// 원래 메뉴에 없는 화면 · 숨기고 말고 할 것이 없어 읽기만 · 열어 보기 링크만 둔다
const OFF_MENU: { href: string; label: string }[] = [
  { href: "/lab/backtest", label: "실험장 · 백테스트" },
  { href: "/lab/super-signals", label: "실험장 · Super Signals" },
  { href: "/principles/verification", label: "원칙 · 확인 대기" },
  { href: "/principles/gate-history", label: "원칙 · 차단 이력" },
  { href: "/influencer", label: "인플루언서 (Serenity 로 이동)" },
  { href: "/influencer/serenity/backtest", label: "Serenity · 백테스트" },
  { href: "/influencer/serenity/methodology", label: "Serenity · 방법" },
  { href: "/biotech/docs", label: "바이오 · 안내서" },
  { href: "/docs/powderkeg-user-guide", label: "화약고 · 사용 안내서" },
];

/**
 * 「권고대로 숨기기」 확인 문구 · 권고 목록(화면 상수 = 서버 RECOMMENDED_HIDE · 시험이 대조)의 메뉴 이름을 모두 적는다.
 * 1120-01 단계 3 · 합친 옛 화면 5개가 더해져 7개 · 이름을 고정해 적으면 사용자가 모르는 화면이 함께 숨는다.
 */
function recommendedConfirmText(): string {
  const labels = new Map(GROUPS.flatMap((g) => g.tabs.map((t) => [t.href, t.label] as const)));
  const names = RECOMMENDED_HIDE_KEYS.map((k) => labels.get(k) ?? k);
  return `권고 목록 ${names.length}개(${names.join(" · ")})만 메뉴에서 숨깁니다. 다른 화면 설정은 그대로입니다. 계속할까요?`;
}

export default function MenuVisibilityPage() {
  const qc = useQueryClient();
  const [banner, setBanner] = useState<Banner>(null);
  const [busy, setBusy] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["menu-visibility", "page"],
    queryFn: () => api.menuVisibility.list(),
    retry: false,
  });

  useEffect(() => {
    if (banner?.kind !== "ok") return;
    const t = setTimeout(() => setBanner(null), 5000);
    return () => clearTimeout(t);
  }, [banner]);

  const onSession = useCallback((info: SessionInfo) => setIsAdmin(info.role === "admin"), []);

  const rows = new Map((data?.screens ?? []).map((s) => [s.key, s]));

  // 바꾼 값을 메뉴(공유 값)에도 곧바로 알린다
  function publish(next: MenuVisibilityResponse) {
    qc.setQueryData(["menu-visibility", "page"], next);
    const map = toMenuMap(next);
    if (map) {
      writeStored(map);
      qc.setQueryData(MENU_QUERY_KEY, map);
    }
  }

  async function toggle(key: string, label: string, visible: boolean) {
    const pageKey = ["menu-visibility", "page"];
    await qc.cancelQueries({ queryKey: pageKey });
    const before = qc.getQueryData<MenuVisibilityResponse>(pageKey);
    qc.setQueryData<MenuVisibilityResponse>(pageKey, (d) =>
      d ? { screens: d.screens.map((s) => (s.key === key ? { ...s, visible } : s)) } : d,
    );
    try {
      publish(await api.menuVisibility.update(key, visible));
      setBanner({ kind: "ok", text: `${label} · ${visible ? "메뉴에 보입니다" : "메뉴에서 숨겼습니다"}. 다음 화면 이동부터 바뀝니다.` });
    } catch (e) {
      qc.setQueryData(pageKey, before);
      setBanner({ kind: "error", text: `${label} 저장 실패 · 이전 설정으로 되돌렸습니다. (${editErrorMessage(e as Error)})` });
    }
  }

  async function applyRecommended() {
    if (!window.confirm(recommendedConfirmText())) return;
    setBusy(true);
    try {
      const r = await api.menuVisibility.applyRecommended();
      publish(r);
      setBanner({ kind: "ok", text: `권고 목록 ${r.applied}개를 숨겼습니다. 다음 화면 이동부터 바뀝니다.` });
    } catch (e) {
      setBanner({ kind: "error", text: `권고대로 숨기기 실패 · 바뀐 것이 없습니다. (${editErrorMessage(e as Error)})` });
    } finally {
      setBusy(false);
    }
  }

  async function showAll() {
    setBusy(true);
    try {
      publish(await api.menuVisibility.showAll());
      setBanner({ kind: "ok", text: "모든 화면을 메뉴에 보이게 했습니다. 다음 화면 이동부터 바뀝니다." });
    } catch (e) {
      setBanner({ kind: "error", text: `모두 보이기 실패 · 바뀐 것이 없습니다. (${editErrorMessage(e as Error)})` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">메뉴 보이기</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          메뉴에서 보이거나 숨길 화면을 고릅니다. 숨겨도 화면은 지워지지 않고, 주소와 알림 링크로 그대로 열리며, 자료 수집도 계속 됩니다.
        </p>
      </header>

      <AdminSessionBar scope="menu" onSessionChange={onSession} />

      {banner && (
        <div
          role={banner.kind === "ok" ? "status" : "alert"}
          className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${
            banner.kind === "ok" ? "border-primary/40 bg-primary/5 text-primary" : "border-warn/40 bg-warn/5 text-warn"
          }`}
        >
          <span>{banner.text}</span>
          <button className="min-h-[44px] px-2" onClick={() => setBanner(null)} aria-label="알림 닫기">
            ✕
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">메뉴 설정을 불러오는 중입니다…</p>}
      {error && (
        <p role="alert" className="rounded-lg border border-warn/40 px-4 py-3 text-sm">
          메뉴 설정을 불러오지 못했습니다 · 메뉴는 모두 보이는 상태로 표시됩니다. 새로 고침해 주세요.
        </p>
      )}

      {data && (
        <>
          {!isAdmin && (
            <p className="rounded-lg border border-border px-4 py-3 text-sm">관리자 로그인 뒤 바꿀 수 있습니다. 지금은 읽기만 됩니다.</p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={applyRecommended}
              disabled={busy || !isAdmin}
              className="min-h-[48px] rounded-lg bg-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
            >
              권고대로 숨기기
            </button>
            <button
              onClick={showAll}
              disabled={busy || !isAdmin}
              className="min-h-[48px] rounded-lg border border-border px-4 text-sm font-semibold disabled:opacity-60"
            >
              모두 보이기
            </button>
          </div>

          {GROUPS.filter((g) => g.tabs.length > 0).map((g) => (
            <section key={g.key} className="rounded-xl border border-border">
              <h2 className="border-b border-border px-4 py-3 text-lg font-semibold">{g.label}</h2>
              <ul>
                {g.tabs.map((t) => {
                  const row = rows.get(t.href);
                  const locked = row?.locked ?? isLocked(t.href);
                  const visible = row?.visible ?? true;
                  return (
                    <li key={t.href} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2 text-sm last:border-0">
                      <span className="min-w-0 flex-1 basis-40">
                        <span className="font-medium">{t.label}</span>
                        <span className="ml-2 text-xs text-muted-foreground">{t.href}</span>
                      </span>
                      <Link href={t.href} className="shrink-0 text-primary underline-offset-2 hover:underline">
                        열어 보기
                      </Link>
                      {locked ? (
                        <span className="shrink-0 rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground">숨길 수 없음</span>
                      ) : (
                        <label className="flex min-h-[44px] shrink-0 items-center gap-2">
                          <input
                            type="checkbox"
                            role="switch"
                            checked={visible}
                            disabled={!isAdmin || busy}
                            onChange={(e) => toggle(t.href, t.label, e.target.checked)}
                            className="h-5 w-5"
                            aria-label={`${t.label} 메뉴에 보이기`}
                          />
                          <span className="w-12">{visible ? "보임" : "숨김"}</span>
                        </label>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </>
      )}

      <section className="rounded-xl border border-border">
        <h2 className="border-b border-border px-4 py-3 text-lg font-semibold">원래 메뉴에 없음</h2>
        <p className="px-4 pt-3 text-sm text-muted-foreground">
          메뉴에 처음부터 없던 화면입니다. 바꿀 설정은 없고 주소로 열 수 있습니다. 종목 상세 화면(/stock/종목코드)도 메뉴에 없습니다.
        </p>
        <ul>
          {OFF_MENU.map((s) => (
            <li key={s.href} className="flex flex-wrap items-center gap-x-3 border-b border-border px-4 py-2 text-sm last:border-0">
              <span className="min-w-0 flex-1 basis-40">
                <span className="font-medium">{s.label}</span>
                <span className="ml-2 text-xs text-muted-foreground">{s.href}</span>
              </span>
              <Link href={s.href} className="flex min-h-[44px] shrink-0 items-center text-primary underline-offset-2 hover:underline">
                열어 보기
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
