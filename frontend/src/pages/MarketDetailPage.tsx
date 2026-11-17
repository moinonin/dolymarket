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
  const [health, setHealth] = useState<{ ewi: number; regime_state: string } | null>(null)
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
          const [ob, fg] = await Promise.all([
            api.getOrderBook(first),
            api.getFearGreedLatest('microstructure').catch(() => null),
          ])
          if (!cancelled) {
            setBook(ob)
            setHealth(fg)
          }
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
    <div className="mx-auto w-full max-w-[1840px] px-4 sm:px-6 lg:px-8 2xl:px-12 pb-24 pt-8">
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
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-400">Status: {market.status}</span>
            {market.clarity && (
              <span
                title={market.clarity.flags?.join(' · ') || 'Unambiguous resolution criteria'}
                className={`rounded-full px-2.5 py-0.5 font-mono font-semibold ${
                  market.clarity.grade === 'HIGH'
                    ? 'border border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                    : market.clarity.grade === 'MEDIUM'
                      ? 'border border-amber-500/40 bg-amber-500/10 text-amber-300'
                      : 'border border-rose-500/40 bg-rose-500/10 text-rose-300'
                }`}
              >
                Oracle Clarity: {market.clarity.grade} ({market.clarity.score}/100)
              </span>
            )}
            {market.oracle_feed && (
              <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 font-mono text-blue-300">
                Feed: {market.oracle_feed}
              </span>
            )}
          </div>
          {market.resolution_criteria && (
            <p className="mt-2 text-xs text-slate-400">{market.resolution_criteria}</p>
          )}
          <section className="mt-6 grid gap-3 sm:grid-cols-2">
            {(market.tokens || []).map((t: any) => (
              <div key={t.token_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="text-xs text-slate-400">{t.symbol}</div>
                <div className="mt-1 font-mono text-lg font-semibold text-emerald-400">
                  {prices && prices[t.token_id] != null ? Number(prices[t.token_id]).toFixed(4) : '—'}
                </div>
              </div>
            ))}
          </section>
          {book && (() => {
            const bestAsk = book.asks?.[0]?.price != null ? Number(book.asks[0].price) : null
            const bestBid = book.bids?.[0]?.price != null ? Number(book.bids[0].price) : null
            const spreadCents =
              bestAsk != null && bestBid != null && bestAsk >= bestBid ? (bestAsk - bestBid) * 100 : null
            let remUsd = 100
            let filledSh = 0
            let spentUsd = 0
            for (const a of book.asks || []) {
              const px = Number(a.price)
              const sz = Number(a.size)
              if (px <= 0 || sz <= 0) continue
              const takeUsd = Math.min(remUsd, px * sz)
              spentUsd += takeUsd
              filledSh += takeUsd / px
              remUsd -= takeUsd
              if (remUsd <= 0) break
            }
            const vwap100 = filledSh > 0 ? spentUsd / filledSh : null
            const impactBps =
              vwap100 != null && bestAsk != null && bestAsk > 0
                ? ((vwap100 - bestAsk) / bestAsk) * 10000
                : null

            return (
              <section className="mt-6 space-y-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
                    <div className="text-slate-500">Bid-Ask Spread</div>
                    <div className="mt-1 font-mono text-sm font-semibold text-white">
                      {spreadCents != null ? `${spreadCents.toFixed(1)}¢` : '—'}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
                    <div className="text-slate-500">$100 Buy Slippage</div>
                    <div className="mt-1 font-mono text-sm font-semibold text-amber-300">
                      {impactBps != null ? `+${impactBps.toFixed(0)} bps${remUsd > 0 ? ' (partial)' : ''}` : '—'}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
                    <div className="text-slate-500">Toxicity Shield (EWI)</div>
                    <div
                      className={`mt-1 font-mono text-sm font-semibold ${
                        health?.ewi != null && health.ewi >= 0.75
                          ? 'text-rose-400'
                          : health?.ewi != null && health.ewi >= 0.45
                            ? 'text-amber-300'
                            : 'text-emerald-400'
                      }`}
                    >
                      {health ? `${health.regime_state} (${health.ewi.toFixed(2)})` : 'STABLE'}
                    </div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
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
                        <div key={i} className="flex justify-between font-mono text-emerald-300">
                          <span>{b.price}</span><span>{b.size}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </section>
            )
          })()}
        </>
      ) : null}
    </div>
  )
}