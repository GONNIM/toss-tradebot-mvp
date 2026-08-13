"use client";

// Serenity Hunter · 알파 검증 + 발굴 페이지 (Phase L14 v6 · 2026-08-04)
// 기존 /influencer/serenity 는 유지 · 병존.
// 참조: docs/plans/serenity-hunter/plan-v6-20260804-094617.md

import { useEffect, useState } from "react";
import Link from "next/link";
import { hunterApi } from "@/lib/serenity-hunter/api";
import type {
  HealthResponse,
  HunterResponse,
  VerificationResponse,
} from "@/lib/serenity-hunter/types";
import { HealthWarningLine } from "./components/HealthWarningLine";
import { VerificationHero } from "./components/VerificationHero";
import { VerificationBucketTable } from "./components/VerificationBucketTable";
import { MidGateWarning } from "./components/MidGateWarning";
import { HunterTable } from "./components/HunterTable";
import { HunterEmptyGate } from "./components/HunterEmptyGate";

export default function SerenityHunterPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [verification, setVerification] = useState<VerificationResponse | null>(null);
  const [hunter, setHunter] = useState<HunterResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, v, hu] = await Promise.all([
          hunterApi.health(),
          hunterApi.verification(),
          hunterApi.hunter(),
        ]);
        if (!cancelled) {
          setHealth(h);
          setVerification(v);
          setHunter(hu);
        }
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) {
    return (
      <div className="space-y-4">
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          API 오류: {err}
        </div>
      </div>
    );
  }

  if (!verification) {
    return <div className="text-xs text-muted-foreground">로딩...</div>;
  }

  const gateOpen = verification.hero.gate_open;
  const deprecated = verification.hero.deprecation_triggered;
  const midWarn = verification.hero.mid_gate_excess_warning;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h1 className="text-2xl font-bold">🎯 Serenity Hunter · 알파 검증 + 발굴</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              첫 언급 급등 시나리오 발굴 실험대 · 인플루언서 1인 소스의 알파 존재 여부를 데이터로 검증.
            </p>
          </div>
          <Link
            href="/influencer/serenity"
            className="text-xs text-sky-500 hover:underline"
          >
            → 기존 Serenity Stock Tracker (seed 검증 종목)
          </Link>
        </div>
      </header>

      <HealthWarningLine health={health} />

      <VerificationHero hero={verification.hero} />

      <VerificationBucketTable
        buckets={verification.buckets}
        predictiveCheck={verification.confidence_predictive_check}
      />

      {midWarn && hunter && (
        <MidGateWarning
          valid={verification.hero.gate_events_have}
          needed={150}
        />
      )}

      {hunter && (gateOpen && !deprecated ? (
        <HunterTable rows={hunter.rows} />
      ) : (
        <HunterEmptyGate
          deprecated={deprecated}
          reasons={hunter.gate_close_reasons}
        />
      ))}
    </div>
  );
}
