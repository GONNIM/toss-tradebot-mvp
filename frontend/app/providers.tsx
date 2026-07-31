"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { initObservability } from "@/lib/observability";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1분
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  // Phase D 주 8 · 2026-07-31 · Sentry + PostHog 조건부 init (DSN/KEY 없으면 no-op).
  useEffect(() => {
    void initObservability();
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
