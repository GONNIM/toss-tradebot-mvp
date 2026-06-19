"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const LEVEL_COLORS: Record<string, string> = {
  CRITICAL: "text-red-500",
  ERROR: "text-red-400",
  WARNING: "text-yellow-400",
  INFO: "text-cyan-400",
  DEBUG: "text-gray-400",
};

export default function LogsPage() {
  const [hours, setHours] = useState(24);
  const { data, isLoading } = useQuery({
    queryKey: ["logs", hours],
    queryFn: () => api.logs.list(100, hours),
  });

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">📜 감사 로그</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            최근 {hours}시간 로그.
          </p>
        </div>
        <select
          className="rounded-lg border border-border bg-card px-3 py-2 text-sm"
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
        >
          <option value={1}>1시간</option>
          <option value={6}>6시간</option>
          <option value={24}>24시간</option>
          <option value={72}>3일</option>
          <option value={168}>7일</option>
        </select>
      </header>

      {isLoading && <div className="text-muted-foreground">로딩 중...</div>}
      {data && data.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-6 text-muted-foreground">
          최근 {hours}시간 로그 없음.
        </div>
      )}
      {data && data.length > 0 && (
        <div className="rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 text-left">
              <tr>
                <th className="px-4 py-3">시각</th>
                <th className="px-4 py-3">레벨</th>
                <th className="px-4 py-3">카테고리</th>
                <th className="px-4 py-3">메시지</th>
              </tr>
            </thead>
            <tbody>
              {data.map((log) => (
                <tr key={log.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {new Date(log.created_at).toLocaleString("ko-KR")}
                  </td>
                  <td className={cn("px-4 py-3 font-bold", LEVEL_COLORS[log.level] || "")}>
                    {log.level}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{log.category}</td>
                  <td className="px-4 py-3 max-w-[600px] truncate">{log.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
