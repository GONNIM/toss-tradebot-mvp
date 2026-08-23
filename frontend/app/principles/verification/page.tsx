"use client";

// 실체 검증 확인 페이지 (gate-design-v1 §3-3 · 세션 B · 2026-08-23)
// PASS 종목 중 태깅 있는데 미확인 리스트 + 확인 버튼
// 확인 스코프 = (ticker, tags_hash) 이중키 · 태그 구성 동일 시 확인 유지

import { useEffect, useState } from "react";

interface Pending {
  ticker: string;
  name: string | null;
  tags: string[];
  tags_hash: string;
  per_ttm: number | null;
}

interface Payload {
  run_id: number | null;
  pending: Pending[];
}

const TAG_LABEL: Record<string, string> = {
  single_quarter_outlier: "단분기 이례 (직전 4Q 평균 대비 100% 편차)",
  ttm_concentration: "TTM 특정 분기 의존 (>50%)",
};

export default function VerificationPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => {
    fetch("/api/v1/principles/verification/pending")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j: Payload) => setData(j))
      .catch((e) => setErr(String(e)));
  };

  useEffect(load, []);

  async function confirm(p: Pending) {
    setBusy(p.ticker);
    try {
      const res = await fetch("/api/v1/principles/verification/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: p.ticker,
          tags: p.tags,
          confirmed_by: "web-ui",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      load();
    } catch (e) {
      alert(`확인 실패: ${e}`);
    } finally {
      setBusy(null);
    }
  }

  if (err)
    return (
      <main style={{ padding: 20 }}>
        <h1>실체 검증 · 확인 대기</h1>
        <p style={{ color: "crimson" }}>로드 실패: {err}</p>
      </main>
    );
  if (!data)
    return (
      <main style={{ padding: 20 }}>
        <h1>실체 검증 · 확인 대기</h1>
        <p>로드 중...</p>
      </main>
    );

  return (
    <main style={{ padding: 20, maxWidth: 1000, margin: "0 auto" }}>
      <h1>실체 검증 · 확인 대기</h1>
      <p style={{ color: "#666" }}>
        최신 run: {data.run_id ?? "N/A"} · 확인 대기 종목:{" "}
        <strong>{data.pending.length}</strong> 건
      </p>
      <p style={{ color: "#666", fontSize: 12 }}>
        스코프 = (ticker, tags_hash). 태그 구성이 다음 배치에서 변경되면 재확인 필요
        (구성 동일 시 확인 유지).
      </p>

      {data.pending.length === 0 ? (
        <p style={{ marginTop: 24 }}>✅ 모든 PASS 종목 확인 완료</p>
      ) : (
        <table
          style={{
            width: "100%",
            marginTop: 16,
            borderCollapse: "collapse",
            fontSize: 13,
          }}
        >
          <thead style={{ background: "#f5f5f5" }}>
            <tr>
              <th style={cell}>티커</th>
              <th style={cell}>종목명</th>
              <th style={cell}>PER</th>
              <th style={{ ...cell, textAlign: "left" }}>태그</th>
              <th style={cell}>확인</th>
            </tr>
          </thead>
          <tbody>
            {data.pending.map((p) => (
              <tr key={p.ticker + p.tags_hash} style={{ borderBottom: "1px solid #eee" }}>
                <td style={cell}>
                  <code>{p.ticker}</code>
                </td>
                <td style={cell}>{p.name ?? "-"}</td>
                <td style={cell}>{p.per_ttm?.toFixed(2) ?? "-"}</td>
                <td style={{ ...cell, textAlign: "left" }}>
                  {p.tags.map((t) => (
                    <div key={t} style={{ marginBottom: 4 }}>
                      ⚠ <code>{t}</code>
                      <br />
                      <small style={{ color: "#888" }}>{TAG_LABEL[t] || t}</small>
                    </div>
                  ))}
                </td>
                <td style={cell}>
                  <button
                    disabled={busy === p.ticker}
                    onClick={() => confirm(p)}
                    style={{
                      padding: "4px 12px",
                      background: "#4a90e2",
                      color: "white",
                      border: 0,
                      borderRadius: 4,
                      cursor: busy === p.ticker ? "wait" : "pointer",
                    }}
                  >
                    {busy === p.ticker ? "..." : "확인"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

const cell: React.CSSProperties = {
  padding: "8px 10px",
  textAlign: "center",
  borderBottom: "1px solid #ddd",
  verticalAlign: "top",
};
