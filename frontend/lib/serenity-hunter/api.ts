// Serenity Hunter API fetcher · Phase L14 v6 · 2026-08-04
// 프록시: next.config.mjs rewrites · /api/v1/serenity/* → backend

import type {
  ActionCardsResponse,
  HealthResponse,
  HunterResponse,
  VerificationResponse,
} from "@/lib/serenity-hunter/types";

async function _get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

export const hunterApi = {
  health: () => _get<HealthResponse>("/api/v1/serenity/health"),
  verification: () => _get<VerificationResponse>("/api/v1/serenity/verification"),
  hunter: () => _get<HunterResponse>("/api/v1/serenity/hunter"),
  actionCards: () => _get<ActionCardsResponse>("/api/v1/serenity/action-cards"),
};
