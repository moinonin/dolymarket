import React, { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../context/toast'

interface TradeFeedItem {
  id: string
  price: number
  shares: number
  timestamp: string
}

export default function RecentTrades({
  tokenId,
  onChange,
}: {
  tokenId: string
  onChange?: (any: any) => void
}) {
  const [trades, setTrades] = useState<TradeFeedItem[] | null>(null)
  const { push } = useToast()

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await api.getPriceHistory(tokenId, '1m')
        if (cancelled) return
        // Derive a flat feed view from the candles.
        setTrades(
          res.candles
            .slice()
            .reverse()
            .slice(0, 30)
            .map((c, i) => ({
              id: `${c.timestamp}-${i}`,
              price: c.close,
              shares: c.volume,
              timestamp: new Date(c.timestamp * 1000).toISOString(),
            }))
        )
      } catch (err: any) {
        if (!cancelled) {
          setTrades([])
          push(err.message || 'Failed to load trade history', 'error')
        }
      }
    }
    load()
    const iv = setInterval(load, 8000)
    return () => {
      cancelled = true
      clearInterval(iv)
    }
  }, [tokenId])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
        <History className="h-4 w-4 text-blue-400" /> Recent Prints
      </h2>
      {trades == null ? (
        <p className="py-6 text-center text-xs text-slate-500">Loading prints…</p>
      ) : trades.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-800 py-10 text-center">
          <p className="text-xs font-medium text-slate-400">No trades yet</p>
          <p className="mt-1 text-[11px] text-slate-600">
            Matched fills stream here the moment print hits the tape.
          </p>
        </div>
      ) : (
        <div className="max-h-96 space-y-1 overflow-y-auto pr-1">
          {trades.map((t) => (
            <div
              key={t.id}
              className="grid grid-cols-3 items-center rounded-lg bg-slate-950/60 px-2.5 py-1.5 text-[11px]"
            >
              <span className="font-mono font-semibold text-white">
                ¢{(t.price * 100).toFixed(0)}
              </span>
              <span className="text-right font-mono text-slate-400">{t.shares.toFixed(1)} sh</span>
              <span className="text-right text-slate-600">
                {new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
