/**
 * 공통 유틸리티.
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatUSD(n: number, digits = 2): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function formatPct(n: number, digits = 2): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export function formatMarketCap(usd: number | null): string {
  if (!usd) return "—";
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  return `$${(usd / 1000).toFixed(0)}K`;
}

export function riskBadgeClass(level: string): string {
  switch (level) {
    case "HIGH":
      return "bg-red-500/15 text-red-400 border-red-500/30";
    case "MED":
      return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
    case "LOW":
      return "bg-green-500/15 text-green-400 border-green-500/30";
    default:
      return "bg-gray-500/15 text-gray-400 border-gray-500/30";
  }
}

export function manipulationBadgeClass(score: number): string {
  if (score >= 4) return "bg-red-500/15 text-red-400 border-red-500/30";
  if (score === 3) return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  return "bg-green-500/15 text-green-400 border-green-500/30";
}

// ─── Sector Leaders ───────────────────────────────────────────

export function formatKRW(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || amount === 0) return "—";
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(2)}조`;
  if (amount >= 1e8) return `${(amount / 1e8).toFixed(1)}억`;
  if (amount >= 1e4) return `${(amount / 1e4).toFixed(0)}만`;
  return amount.toLocaleString();
}

export function formatMUSD(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  if (amount >= 1000) return `${(amount / 1000).toFixed(2)}억$`;
  return `${amount.toFixed(0)}백만$`;
}

export function confidenceBadgeClass(c: string): string {
  switch (c) {
    case "strong":
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
    case "medium":
      return "bg-cyan-500/15 text-cyan-400 border-cyan-500/30";
    case "weak":
    default:
      return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  }
}

export function confidenceStars(c: string): string {
  switch (c) {
    case "strong":
      return "★★★";
    case "medium":
      return "★★";
    case "weak":
    default:
      return "★";
  }
}

export function lagDescription(lag: number | null): string {
  if (lag === null) return "—";
  if (lag === 0) return "동행";
  if (lag > 0) return `수출 ${lag}M 선행`;
  return `주가 ${-lag}M 선행`;
}
