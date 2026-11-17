import React, { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { Skeleton } from '../components/ui'
import { useToast } from '../context/toast'

export default function MarketDetailPage({ marketId, onBack }: { marketId: string; onBack: () => void }) {
  const { user, openAuth } = useAuth()
  const { push } = useToast()
  const [market, setMarket] = useState<any>(null)
  const [prices, setPrices] = useState<Record<string, number | null> | null>(null)
  const [book, setBook] = useState<any>(null)
  const [ammPool, setAmmPool] = useState<any>(null)
  const [lpAmount, setLpAmount] = useState('10')
  const [ammShares, setAmmShares] = useState('10')
  const [ammSide, setAmmSide] = useState<'BUY' | 'SELL'>('BUY')
  const [ammOutcome, setAmmOutcome] = useState(0)
  const [ammQuote, setAmmQuote] = useState<any>(null)
  const [ammBusy, setAmmBusy] = useState(false)
  const [health, setHealth] = useState<{ ewi: number; regime_state: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const [m, pool] = await Promise.all([
      api.getMarket(marketId) as Promise<any>,
      api.getAmmPool(marketId).catch(() => null),
    ])
    setMarket(m)
    setAmmPool(pool)
  }, [marketId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const [m, pool] = await Promise.all([
          api.getMarket(marketId) as Promise<any>,
          api.getAmmPool(marketId).catch(() => null),
        ])
        if (cancelled) return
        setMarket(m)
        setAmmPool(pool)
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

          <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-white">Hybrid LMSR AMM &amp; LP Pool</h2>
              {ammPool && (
                <span className="font-mono text-xs text-emerald-300">
                  Pool: ${ammPool.pool_usdc.toFixed(2)} USDC · YES {(ammPool.yes_price * 100).toFixed(1)}¢ / NO {(ammPool.no_price * 100).toFixed(1)}¢
                </span>
              )}
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="text-xs font-medium text-slate-300">Provide / Fund Liquidity (USDC)</div>
                <div className="flex gap-2">
                  <input
                    type="number"
                    min="1"
                    step="any"
                    value={lpAmount}
                    onChange={(e) => setLpAmount(e.target.value)}
                    className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-emerald-500"
                  />
                  <button
                    type="button"
                    disabled={ammBusy}
                    onClick={async () => {
                      if (!user) return openAuth('login')
                      setAmmBusy(true)
                      try {
                        const amt = Number(lpAmount)
                        if (market.tier === 'COMMUNITY') {
                          await api.fundCommunityMarket(market.id, amt)
                        } else {
                          await api.depositAmmLiquidity(market.id, amt)
                        }
                        push('LP liquidity deposited.', 'info')
                        await reload()
                      } catch (err: any) {
                        push(err?.message || 'Deposit failed', 'error')
                      } finally {
                        setAmmBusy(false)
                      }
                    }}
                    className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
                  >
                    Deposit LP
                  </button>
                  {market.status === 'RESOLVED' && ammPool && (
                    <button
                      type="button"
                      disabled={ammBusy}
                      onClick={async () => {
                        if (!user) return openAuth('login')
                        setAmmBusy(true)
                        try {
                          const r = await api.redeemAmmLp(market.id)
                          push(`Redeemed LP shares for $${r.payout_usdc.toFixed(2)} USDC.`, 'info')
                          await reload()
                        } catch (err: any) {
                          push(err?.message || 'Redeem failed', 'error')
                        } finally {
                          setAmmBusy(false)
                        }
                      }}
                      className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/20 disabled:opacity-40"
                    >
                      Redeem LP
                    </button>
                  )}
                </div>
              </div>

              {ammPool && market.status === 'ACTIVE' && (
                <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="text-xs font-medium text-slate-300">Instant AMM Trade</div>
                  <div className="flex flex-wrap gap-2">
                    <select
                      value={ammSide}
                      onChange={(e) => setAmmSide(e.target.value as 'BUY' | 'SELL')}
                      className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                    <select
                      value={ammOutcome}
                      onChange={(e) => setAmmOutcome(Number(e.target.value))}
                      className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
                    >
                      {(market.tokens || []).slice(0, 2).map((t: any) => (
                        <option key={t.token_id} value={t.outcome_index}>{t.symbol}</option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min="1"
                      step="any"
                      value={ammShares}
                      onChange={(e) => setAmmShares(e.target.value)}
                      className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                    />
                    <button
                      type="button"
                      disabled={ammBusy}
                      onClick={async () => {
                        try {
                          const q = await api.quoteAmm(market.id, ammOutcome, ammSide, Number(ammShares))
                          setAmmQuote(q)
                        } catch (err: any) {
                          push(err?.message || 'Quote failed', 'error')
                        }
                      }}
                      className="rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
                    >
                      Quote
                    </button>
                    <button
                      type="button"
                      disabled={ammBusy}
                      onClick={async () => {
                        if (!user) return openAuth('login')
                        const tok = (market.tokens || []).find((t: any) => t.outcome_index === ammOutcome)
                        if (!tok) return
                        setAmmBusy(true)
                        try {
                          await api.tradeAmm(market.id, tok.token_id, ammSide, Number(ammShares))
                          push(`AMM ${ammSide} ${ammShares} ${tok.symbol} executed.`, 'info')
                          setAmmQuote(null)
                          await reload()
                        } catch (err: any) {
                          push(err?.message || 'AMM trade failed', 'error')
                        } finally {
                          setAmmBusy(false)
                        }
                      }}
                      className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
                    >
                      Execute
                    </button>
                  </div>
                  {ammQuote && (
                    <div className="font-mono text-[11px] text-slate-400">
                      Avg: {(ammQuote.avg_price * 100).toFixed(2)}¢ · Total: ${ammQuote.total_usdc.toFixed(2)} (fee ${ammQuote.fee_usdc.toFixed(2)})
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}