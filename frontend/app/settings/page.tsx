"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

function isCurrencyKey(key: string, description: string | null): boolean {
  const k = key.toLowerCase();
  if (/_krw$|_usd$|_won$|_seed|_size|amount|budget/.test(k)) return true;
  const d = description || "";
  return /KRW|USD|원|달러|시드|자금|매수|예산/.test(d);
}

function formatValue(value: string, key: string, description: string | null): string {
  if (!isCurrencyKey(key, description)) return value;
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString("ko-KR");
}

function currencyUnit(key: string, description: string | null): string {
  const k = key.toLowerCase();
  if (k.endsWith("_krw") || k.endsWith("_won")) return "원";
  if (k.endsWith("_usd")) return "USD";
  if (description && /KRW|원|시드|자금|매수|예산/.test(description)) return "원";
  if (description && /USD|달러/.test(description)) return "USD";
  return "";
}

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
        <div className="rounded-xl border border-border overflow-hidden bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/60 text-left text-foreground font-semibold">
              <tr>
                <th className="px-4 py-3">키</th>
                <th className="px-4 py-3 text-right">값</th>
                <th className="px-4 py-3">설명</th>
              </tr>
            </thead>
            <tbody>
              {data.map((s) => {
                const isCurrency = isCurrencyKey(s.key, s.description);
                const unit = isCurrency ? currencyUnit(s.key, s.description) : "";
                return (
                  <tr
                    key={s.key}
                    className="border-b border-border last:border-0 hover:bg-muted/30"
                  >
                    <td className="px-4 py-3 font-mono text-cyan-700 dark:text-cyan-300">
                      {s.key}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-foreground font-semibold whitespace-nowrap">
                      {formatValue(s.value, s.key, s.description)}
                      {unit && (
                        <span className="ml-1 text-xs text-muted-foreground font-sans">
                          {unit}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.description || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
