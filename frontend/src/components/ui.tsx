import React from 'react'
import type { Market, MarketStatus, EventStatus } from '../api/client'

export function statusTone(status: string): string {
  switch (status) {
    case 'ACTIVE':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
    case 'CLOSED':
    case 'IN_RESOLUTION':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/30'
    case 'RESOLVED':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/30'
    case 'DISPUTED':
      return 'bg-red-500/10 text-red-400 border-red-500/30'
    case 'SUSPENDED':
      return 'bg-slate-500/10 text-slate-400 border-slate-500/30'
    case 'FILLED':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/30'
    case 'OPEN':
    case 'PARTIALLY_FILLED':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
    case 'CANCELLED':
    case 'REJECTED':
      return 'bg-slate-500/10 text-slate-400 border-slate-500/30'
    case 'BUY':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
    case 'SELL':
      return 'bg-rose-500/10 text-rose-400 border-rose-500/30'
    default:
      return 'bg-slate-500/10 text-slate-400 border-slate-500/30'
  }
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = {
    ACTIVE: 'Active',
    CLOSED: 'Closed',
    RESOLVED: 'Resolved',
    IN_RESOLUTION: 'Resolving',
    DISPUTED: 'Disputed',
    SUSPENDED: 'Suspended',
    PARTIALLY_FILLED: 'Partially Filled',
    FILLED: 'Filled',
    OPEN: 'Open',
    CANCELLED: 'Cancelled',
    REJECTED: 'Rejected',
    GTC: "Good 'Til Cancelled",
    IOC: 'Immediate or Cancel',
    FOK: 'Fill or Kill',
  }
  return map[status] ?? status
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${statusTone(status)}`}
    >
      {['ACTIVE', 'OPEN', 'PARTIALLY_FILLED'].includes(status) && (
        <span className="relative inline-flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {statusLabel(status)}
    </span>
  )
}

export function ProbabilityBar({
  yes,
  no,
}: {
  yes: number | null
  no: number | null
}) {
  const p = yes == null ? null : Math.max(0, Math.min(1, yes))
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
      {p != null && (
        <>
          <div className="bg-emerald-500 transition-all" style={{ width: `${p * 100}%` }} />
          <div className="bg-rose-500 transition-all" style={{ width: `${(1 - p) * 100}%` }} />
        </>
      )}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-slate-800/70 ${className}`} />
}

export function FeePreview({
  shares,
  price,
  feeRate,
}: {
  shares: number | ''
  price: number | ''
  feeRate: number
}) {
  const c = Number(shares || 0)
  const p = Number(price || 0)
  const fee =
    c > 0 && p > 0 && p < 1 ? c * feeRate * p * (1 - p) : 0
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
      <span className="text-slate-400">
        Est. fee <span className="text-slate-600">· C × feeRate × p × (1−p)</span>
      </span>
      <span className="font-mono font-medium text-amber-400">
        ${fee ? fee.toFixed(4) : '0.0000'}
      </span>
    </div>
  )
}

export const CATEGORY_FEE_RATES: Record<string, number> = {
  Crypto: 0.02,
  Politics: 0.015,
  Sports: 0.025,
  Macro: 0.02,
  Tech: 0.02,
  'Pop Culture': 0.02,
}

export function feeRateForCategory(category: string): number {
  return CATEGORY_FEE_RATES[category] ?? 0.02
}
