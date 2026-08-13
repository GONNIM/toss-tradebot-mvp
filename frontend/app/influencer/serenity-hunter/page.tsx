"use client";

// Serenity Hunter · 알파 검증 + 발굴 페이지 (Phase L14+ 재구성 · 2026-08-05)
// 기존 /influencer/serenity 는 유지 · 병존.
// 참조: docs/plans/serenity-hunter/plan-v6-20260804-094617.md
//       사용자 지시서 (2026-08-05 · "오늘의 실행 카드")

import { useEffect, useState } from "react";
import Link from "next/link";
import { hunterApi } from "@/lib/serenity-hunter/api";
import type {
  ActionCardsResponse,
  HealthResponse,
  HunterResponse,
  VerificationResponse,
} from "@/lib/serenity-hunter/types";
import { ActionCardsSection } from "./components/ActionCardsSection";
import { DisclaimerBanner } from "./components/DisclaimerBanner";
import { HealthWarningLine } from "./components/HealthWarningLine";
import { HunterEmptyGate } from "./components/HunterEmptyGate";
import { HunterTable } from "./components/HunterTable";
import { MidGateWarning } from "./components/MidGateWarning";
import { VerificationBucketTable } from "./components/VerificationBucketTable";
import { VerificationHero } from "./components/VerificationHero";
import { WatchOnlyList } from "./components/WatchOnlyList";

export default function SerenityHunterPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [verification, setVerification] = useState<VerificationResponse | null>(null);
  const [hunter, setHunter] = useState<HunterResponse | null>(null);
  const [actionCards, setActionCards] = useState<ActionCardsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, v, hu, ac] = await Promise.all([
          hunterApi.health(),
          hunterApi.verification(),
          hunterApi.hunter(),
          hunterApi.actionCards(),
        ]);
        if (!cancelled) {
          setHealth(h);
          setVerification(v);
          setHunter(hu);
          setActionCards(ac);
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

  if (!actionCards) {
    return <div className="text-xs text-muted-foreground">로딩...</div>;
  }

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

      {/* 상시 고지 배너 · 지시서 §2 · 삭제 금지 */}
      <DisclaimerBanner />

      <HealthWarningLine health={health} />

      {/* 🎯 오늘의 실행 카드 · 지시서 §1 · 페이지 최상단 */}
      <ActionCardsSection data={actionCards} />

      {/* 👁 관찰 전용 · 지시서 §3 · 가격 없는 고언급 티커 · 접힘 */}
      <WatchOnlyList items={actionCards.watch_only} />

      {/* ── 기존 섹션 · 기본 접힘 (사용자 지시서 §3) ─────────── */}
      <details className="rounded border border-border/40 bg-background/40 px-3 py-2">
        <summary className="cursor-pointer text-sm font-semibold text-muted-foreground">
          🔬 알파 검증 상세 (Hero · Bucket · confidence)
        </summary>
        <div className="mt-3 space-y-4">
          {verification && (
            <>
              <VerificationHero hero={verification.hero} />
              <VerificationBucketTable
                buckets={verification.buckets}
                predictiveCheck={verification.confidence_predictive_check}
              />
            </>
          )}
        </div>
      </details>

      <details className="rounded border border-border/40 bg-background/40 px-3 py-2">
        <summary className="cursor-pointer text-sm font-semibold text-muted-foreground">
          🎯 Hunter 전체 리스트 (레거시 · 폐기 상태에선 소멸)
        </summary>
        <div className="mt-3 space-y-3">
          {verification?.hero.mid_gate_excess_warning && hunter && (
            <MidGateWarning
              valid={verification.hero.gate_events_have}
              needed={150}
            />
          )}
          {hunter && (verification?.hero.gate_open && !verification.hero.deprecation_triggered ? (
            <HunterTable rows={hunter.rows} />
          ) : (
            <HunterEmptyGate
              deprecated={verification?.hero.deprecation_triggered ?? false}
              reasons={hunter.gate_close_reasons}
            />
          ))}
        </div>
      </details>
    </div>
  );
}
