import React, { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { Skeleton } from '../components/ui'
import { useToast } from '../context/toast'

export default function MarketDetailPage({ marketId, onBack }: { marketId: string; onBack: () => void }) {
  const { push } = useToast()
  const [market, setMarket] = useState<any>(null)
  const [prices, setPrices] = useState<Record<string, number | null> | null>(null)
  const [book, setBook] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const m = await api.getMarket(marketId) as any
        if (cancelled) return
        setMarket(m)
        const tokens = (m.tokens || []).map((t: any) => t.token_id)
        if (tokens.length) {
          const bp = await api.getBulkPrices(tokens)
          if (!cancelled) setPrices(bp.prices || {})
        }
        const first = (m.tokens || [])[0]?.token_id
        if (first) {
          const ob = await api.getOrderBook(first)
          if (!cancelled) setBook(ob)
        }
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Could not load market')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [marketId])

  return (
    <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8">
      <button onClick={onBack} className="mb-4 text-xs text-slate-400 transition hover:text-slate-200">← Back</button>
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">{error}</div>
      ) : market ? (
        <>
          <h1 className="text-2xl font-bold text-white">{market.question}</h1>
          <p className="mt-1 text-sm text-slate-400">Status: {market.status}</p>
          <section className="mt-6 grid gap-3 sm:grid-cols-2">
            {(market.tokens || []).map((t: any) => (
              <div key={t.token_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="text-xs text-slate-400">{t.symbol}</div>
                <div className="mt-1 font-mono text-lg font-semibold text-cyan-400">
                  {prices && prices[t.token_id] != null ? Number(prices[t.token_id]).toFixed(4) : '—'}
                </div>
              </div>
            ))}
          </section>
          {book && (
            <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="text-sm font-semibold text-white">Order book (top)</h2>
              <div className="mt-3 grid grid-cols-2 gap-4 text-xs">
                <div>
                  <div className="mb-1 text-slate-500">Asks</div>
                  {(book.asks || []).slice(0, 5).map((a: any, i: number) => (
                    <div key={i} className="flex justify-between font-mono text-rose-300">
                      <span>{a.price}</span><span>{a.size}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div className="mb-1 text-slate-500">Bids</div>
                  {(book.bids || []).slice(0, 5).map((b: any, i: number) => (
                    <div key={i} className="flex justify-between font-mono text-cyan-300">
                      <span>{b.price}</span><span>{b.size}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}
        </>
      ) : null}
    </div>
  )
}