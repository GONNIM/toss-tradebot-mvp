"use client";

// 1120-01 메뉴 보이기 값 읽기 (메뉴 · 숨김 안내 · 오늘 화면 · 설정 화면이 같은 값을 쓴다)
// - 화면 이동(주소 바뀜)마다 다시 읽는다 (AppNav 가 invalidate · 새로 마운트되는 화면도 다시 읽음).
// - 마지막 값을 localStorage 에 보관해 첫 그림에서 메뉴가 흔들리지 않게 한다. 깨졌거나 없으면 모두 보임.
// - 읽기 실패면 null (모두 보임) — 보관 값으로 계속 숨기지 않는다.

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { readStored, toMenuMap, writeStored } from "@/lib/menu-visibility";
import type { MenuState } from "@/lib/menu-visibility";

export const MENU_QUERY_KEY = ["menu-visibility"] as const;

export function useMenuVisibility(): { menu: MenuState; isError: boolean } {
  const [stored, setStored] = useState<MenuState>(null);
  useEffect(() => {
    setStored(readStored()); // 서버 그림과 어긋나지 않게 마운트 뒤에 읽는다
  }, []);

  const q = useQuery({
    queryKey: MENU_QUERY_KEY,
    queryFn: async () => {
      const map = toMenuMap(await api.menuVisibility.list());
      if (!map) throw new Error("메뉴 값 모양이 맞지 않습니다");
      writeStored(map);
      return map;
    },
    retry: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

  if (q.isError) return { menu: null, isError: true };
  return { menu: q.data ?? stored, isError: false };
}
