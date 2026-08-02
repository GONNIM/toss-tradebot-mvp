"use client";

// 15원칙 프레임 열람 · Phase L7 · 2026-08-02
// vendor/serenity-tracker/serenity-aleabitoreddit/references/methodology.md 원문

import Link from "next/link";
import { useEffect, useState } from "react";
import { serenityApi } from "@/lib/serenity/api";
import type { MethodologyResponse } from "@/lib/serenity/types";

export default function MethodologyPage() {
  const [data, setData] = useState<MethodologyResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    serenityApi
      .methodology()
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Link href="/influencer/serenity" className="text-xs text-sky-500 hover:underline">
        ← Serenity 랜딩
      </Link>

      <header>
        <h1 className="text-2xl font-bold">📚 Serenity Methodology · 15원칙</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          @aleabitoreddit references/methodology.md 원문 · vendor/serenity-tracker submodule
        </p>
      </header>

      {err && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-500">
          {err.includes("404")
            ? "methodology.md 없음 · submodule 미초기화 또는 배포 후 재실행 필요"
            : `에러: ${err}`}
        </div>
      )}

      {data && (
        <>
          <div className="text-[10px] text-muted-foreground">
            source: <code>{data.source}</code> · {data.bytes.toLocaleString()} bytes
          </div>
          <pre className="whitespace-pre-wrap rounded-lg border border-border bg-card p-4 text-xs leading-relaxed text-foreground">
{data.text}
          </pre>
        </>
      )}

      {!data && !err && (
        <div className="text-xs text-muted-foreground">로딩...</div>
      )}
    </div>
  );
}
