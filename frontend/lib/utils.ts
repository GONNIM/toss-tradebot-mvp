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
