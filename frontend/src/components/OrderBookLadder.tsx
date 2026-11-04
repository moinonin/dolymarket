import React, { useMemo } from 'react'
import { statusTone } from './ui'

interface Level {
  price: number
  size: number
}

export default function OrderBookLadder({
  bids,
  asks,
  tickSize,
  tokenSymbol,
}: {
  bids: Level[]
  asks: Level[]
  tickSize: number
  tokenSymbol: string
}) {
  const maxSize = useMemo(
    () => Math.max(1, ...bids.map((l) => l.size), ...asks.map((l) => l.size)),
    [bids, asks]
  )
  const spread =
    asks.length && bids.length
      ? Math.max(0, asks[0].price - bids[0].price)
      : null

  const reversedAsks = [...asks].reverse()

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">
          Order Book <span className="font-normal text-slate-500">· {tokenSymbol}</span>
        </h2>
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <span>
            Spread{' '}
            <span className="font-mono text-amber-400">
              {spread != null ? `¢${(spread * 100).toFixed(1)}` : '—'}
            </span>
          </span>
          <span className="text-slate-700">·</span>
          <span>tick ¢{(tickSize * 100).toFixed(0)}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 pb-1.5 text-right text-[10px] uppercase tracking-wide text-slate-600">
        <span className="text-left">Price (¢)</span>
        <span>Size</span>
        <span>Cumulative</span>
      </div>

      {/* Asks (worst first at bottom) */}
      <div className="flex flex-col">
        {reversedAsks.map((l) => (
          <div key={`a${l.price}`} className="relative grid h-6 grid-cols-3 items-center px-1 text-xs">
            <div
              className="absolute inset-y-0 right-0 bg-rose-500/12"
              style={{ width: `${(l.size / maxSize) * 100}%` }}
            />
            <span className="relative font-mono text-rose-400">
              {(l.price * 100).toFixed(1)}¢
            </span>
            <span className="relative text-right font-mono text-slate-300">{l.size}</span>
            <span className="relative text-right font-mono text-slate-500">{l.size}</span>
          </div>
        ))}
        {asks.length === 0 && <EmptyKind label="No asks" />}

        <div className="my-2 flex items-center justify-center gap-2 border-y border-slate-800 py-1 text-[11px]">
          <span className="flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
          <span className="text-emerald-400">BID {(bids[0]?.price ?? 0) * 100}¢</span>
          <Arrow />
          <span className="text-rose-400">ASK {(asks[0]?.price ?? 0) * 100}¢</span>
        </div>

        {bids.map((l) => (
          <div key={`b${l.price}`} className="relative grid h-6 grid-cols-3 items-center px-1 text-xs">
            <div
              className="absolute inset-y-0 right-0 bg-emerald-500/12"
              style={{ width: `${(l.size / maxSize) * 100}%` }}
            />
            <span className="relative font-mono text-emerald-400">
              {(l.price * 100).toFixed(1)}¢
            </span>
            <span className="relative text-right font-mono text-slate-300">{l.size}</span>
            <span className="relative text-right font-mono text-slate-500">{l.size}</span>
          </div>
        ))}
        {bids.length === 0 && <EmptyKind label="No bids" />}
      </div>
    </div>
  )
}

function Arrow() {
  return <span className="text-slate-600">↔</span>
}

function EmptyKind({ label }: { label: string }) {
  return (
    <div className="py-1.5 text-center text-[11px] italic text-slate-600">{label}</div>
  )
}
