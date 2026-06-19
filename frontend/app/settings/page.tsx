"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.list(),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">⚙️ 운영 파라미터</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          정적 설정 (Phase J 후 동적 편집 활성).
        </p>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {data && (
        <div className="rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 text-left">
              <tr>
                <th className="px-4 py-3">키</th>
                <th className="px-4 py-3">값</th>
                <th className="px-4 py-3">설명</th>
              </tr>
            </thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.key} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-mono text-cyan-400">{s.key}</td>
                  <td className="px-4 py-3 font-mono">{s.value}</td>
                  <td className="px-4 py-3 text-muted-foreground">{s.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
