"use client";

// PrinciplesGate 차단 이력 (gate-design-v1 §3-1 · 세션 A · 2026-08-23)
// 최근 차단 로그 표 + 지난 24h 사유별 카운트

import { useEffect, useState } from "react";

interface BlockLog {
  id: number;
  created_at: string | null;
  ticker: string;
  source: string | null;
  reason: string;
  detail: string | null;
  run_id: number | null;
}

interface Payload {
  total_24h: number;
  block_24h: number;
  bypass_24h: number;
  by_reason_24h: Record<string, number>;
  recent: BlockLog[];
}

export default function GateHistoryPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/principles/gate/blocked-recent?limit=50")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j: Payload) => setData(j))
      .catch((e) => setErr(String(e)));
  }, []);

  if (err)
    return (
      <main style={{ padding: 20 }}>
        <h1>PrinciplesGate · 차단 이력</h1>
        <p style={{ color: "crimson" }}>로드 실패: {err}</p>
      </main>
    );
  if (!data)
    return (
      <main style={{ padding: 20 }}>
        <h1>PrinciplesGate · 차단 이력</h1>
        <p>로드 중...</p>
      </main>
    );

  return (
    <main style={{ padding: 20, maxWidth: 1100, margin: "0 auto" }}>
      <h1>PrinciplesGate · 차단 이력</h1>

      <section style={{ margin: "16px 0 24px" }}>
        <h2 style={{ fontSize: 18, marginBottom: 8 }}>지난 24시간 요약</h2>
        <p>
          총 이벤트: <strong>{data.total_24h}</strong> 건 (차단{" "}
          <strong>{data.block_24h}</strong> · 우회{" "}
          <strong style={{ color: "#c66" }}>{data.bypass_24h}</strong>)
        </p>
        <ul style={{ margin: "8px 0" }}>
          {Object.entries(data.by_reason_24h).map(([reason, cnt]) => (
            <li key={reason}>
              <code>{reason}</code>: {cnt}
            </li>
          ))}
          {Object.keys(data.by_reason_24h).length === 0 && (
            <li style={{ color: "#888" }}>지난 24h 차단 없음</li>
          )}
        </ul>
      </section>

      <section>
        <h2 style={{ fontSize: 18, marginBottom: 8 }}>최근 차단 (최대 50건)</h2>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13,
          }}
        >
          <thead style={{ background: "#f5f5f5" }}>
            <tr>
              <th style={cellStyle}>시각</th>
              <th style={cellStyle}>티커</th>
              <th style={cellStyle}>소스</th>
              <th style={cellStyle}>사유</th>
              <th style={cellStyle}>Run</th>
              <th style={{ ...cellStyle, textAlign: "left" }}>상세</th>
            </tr>
          </thead>
          <tbody>
            {data.recent.map((r) => (
              <tr key={r.id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={cellStyle}>{r.created_at?.slice(0, 19) ?? "-"}</td>
                <td style={cellStyle}>
                  <code>{r.ticker}</code>
                </td>
                <td style={cellStyle}>{r.source ?? "-"}</td>
                <td style={cellStyle}>
                  <code>{r.reason}</code>
                </td>
                <td style={cellStyle}>{r.run_id ?? "-"}</td>
                <td style={{ ...cellStyle, textAlign: "left", color: "#555" }}>
                  {r.detail ?? "-"}
                </td>
              </tr>
            ))}
            {data.recent.length === 0 && (
              <tr>
                <td colSpan={6} style={{ ...cellStyle, color: "#888" }}>
                  차단 이력 없음
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}

const cellStyle: React.CSSProperties = {
  padding: "6px 10px",
  textAlign: "center",
  borderBottom: "1px solid #ddd",
};
