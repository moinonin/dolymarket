import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CheckCircle2, Eye, History, Loader2, RefreshCw, WifiOff } from 'lucide-react'
import { api, type Candle, type LiveMarket, type LiveTrade } from '../api/client'
import OrderBookLadder from '../components/OrderBookLadder'
import { Skeleton } from '../components/ui'

const REFRESH_MS = 15000

export default function LiveMarketDetailPage({
  marketId,
  onBack,
}: {
  marketId: string
  onBack: () => void
}) {
  const [market, setMarket] = useState<LiveMarket | null>(null)
  const [tokenId, setTokenId] = useState<string | null>(null)
  const [book, setBook] = useState<any>(null)
  const [trades, setTrades] = useState<LiveTrade[] | null>(null)
  const [candles, setCandles] = useState<Candle[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)

  const loadMarket = useCallback(async () => {
    try {
      const m = await api.getLiveMarket(marketId)
      setMarket(m)
      setTokenId((current) => current ?? m.tokens?.[0]?.token_id ?? null)
      setError(null)
      setUpdatedAt(Date.now())
    } catch (err: any) {
      setError(err?.message || 'Could not load the live market')
    } finally {
      setLoading(false)
    }
  }, [marketId])

  useEffect(() => {
    void loadMarket()
    const iv = setInterval(() => void loadMarket(), REFRESH_MS)
    return () => clearInterval(iv)
  }, [loadMarket])

  useEffect(() => {
    if (!tokenId) return
    let cancelled = false
    const load = async () => {
      try {
        const [ob, tr, cs] = await Promise.all([
          api.getLiveOrderBook(tokenId, 25),
          api.getLiveMarketTrades(marketId, 30),
          api.getLiveCandlesticks(tokenId, '1m', 120),
        ])
        if (cancelled) return
        setBook(ob)
        setTrades(tr.trades || [])
        setCandles(cs.candlesticks || [])
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Could not refresh live data')
      }
    }
    void load()
    const iv = setInterval(() => void load(), REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(iv)
    }
  }, [tokenId, marketId])

  const bids = useMemo(() => levelList(book?.bids || []), [book])
  const asks = useMemo(() => levelList(book?.asks || []), [book])
  const token = market?.tokens?.find((t) => t.token_id === tokenId) || market?.tokens?.[0]

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8">
        <Skeleton className="mb-4 h-4 w-24" />
        <Skeleton className="mb-3 h-7 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (error && !market) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8">
        <button onClick={onBack} className="mb-4 text-xs text-slate-400 transition hover:text-slate-200">
          ← Back
        </button>
        <div className="flex items-start gap-3 rounded-xl border border-rose-800/60 bg-rose-950/40 p-4 text-sm text-rose-200">
          <WifiOff className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Live upstream unavailable</p>
            <p className="mt-0.5 text-xs text-rose-300/80">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  if (!market) return null

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8">
      <button onClick={onBack} className="mb-4 text-xs text-slate-400 transition hover:text-slate-200">
        ← Back
      </button>

      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold leading-tight text-white">{market.question}</h1>
          {market.event_title && <p className="mt-1 text-sm text-slate-400">{market.event_title}</p>}
        </div>
        <div className="flex items-center gap-2">
          {updatedAt && (
            <span className="text-[11px] text-slate-500">
              updated {new Date(updatedAt).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => void loadMarket()}
            className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </header>

      <div className="mb-5 flex items-start gap-2 rounded-xl border border-amber-700/40 bg-amber-950/30 px-3.5 py-2.5 text-xs text-amber-200/90">
        <Eye className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Live DexBuilder market — prices, book and tape are upstream data. Placing orders on upstream
          markets requires a connected DexBuilder account.
        </span>
      </div>

      {(market.resolved || market.status === 'CLOSED') && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-emerald-700/40 bg-emerald-950/25 px-3.5 py-2.5 text-xs text-emerald-200/90">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {market.winning_outcome_index != null && market.outcomes?.[market.winning_outcome_index]
              ? `Resolved — ${market.outcomes[market.winning_outcome_index]} won (settled at 1.00 / 0.00).`
              : 'Closed — the upstream does not report a settled outcome for this market.'}
          </span>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          {error}
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        {market.tokens.map((t) => (
          <div
            key={t.token_id}
            className={`rounded-xl border p-4 ${
              t.token_id === tokenId
                ? 'border-emerald-500/50 bg-emerald-500/5'
                : 'border-slate-800 bg-slate-900/60'
            }`}
          >
            <div className="text-xs text-slate-400">{t.symbol}</div>
            <div className="mt-1 font-mono text-lg font-semibold text-emerald-400">
              {t.price != null ? `${(t.price * 100).toFixed(1)}%` : '—'}
            </div>
            {t.token_id && (
              <button
                onClick={() => setTokenId(t.token_id)}
                className="mt-2 text-[11px] text-slate-500 transition hover:text-emerald-300"
              >
                {t.token_id === tokenId ? 'viewing book' : 'view book'}
              </button>
            )}
          </div>
        ))}
      </section>

      <section className="mt-3 grid gap-3 sm:grid-cols-4">
        <Stat label="Best bid" value={market.best_bid != null ? `${(market.best_bid * 100).toFixed(2)}¢` : '—'} />
        <Stat label="Best ask" value={market.best_ask != null ? `${(market.best_ask * 100).toFixed(2)}¢` : '—'} />
        <Stat label="Last trade" value={market.last_trade_price != null ? `${(market.last_trade_price * 100).toFixed(2)}¢` : '—'} />
        <Stat label="Volume" value={`$${market.volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <LivePriceChart candles={candles} />
          {token && (
            <OrderBookLadder
              bids={bids}
              asks={asks}
              tickSize={market.tick_size}
              tokenSymbol={token.symbol}
            />
          )}
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
            <History className="h-4 w-4 text-blue-400" /> Trade tape
          </h2>
          {trades == null ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading prints…
            </div>
          ) : trades.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 py-10 text-center">
              <p className="text-xs font-medium text-slate-400">No prints yet</p>
              <p className="mt-1 text-[11px] text-slate-600">Upstream has no trades for this market.</p>
            </div>
          ) : (
            <div className="max-h-96 space-y-1 overflow-y-auto pr-1">
              {trades.map((t) => (
                <div
                  key={`${t.id}-${t.timestamp}`}
                  className="grid grid-cols-3 items-center rounded-lg bg-slate-950/60 px-2.5 py-1.5 text-[11px]"
                >
                  <span className={`font-mono font-semibold ${t.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {t.price != null ? `¢${(t.price * 100).toFixed(1)}` : '—'}
                  </span>
                  <span className="text-right font-mono text-slate-400">
                    {t.size != null ? `${t.size.toFixed(1)} sh` : '—'}
                  </span>
                  <span className="text-right text-slate-600">
                    {t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold text-white">{value}</div>
    </div>
  )
}

function LivePriceChart({ candles }: { candles: Candle[] | null }) {
  if (candles == null) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-semibold text-white">Price history</h2>
        <div className="mt-3 flex items-center justify-center gap-2 py-10 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading candles…
        </div>
      </div>
    )
  }
  const points = candles.filter((c) => c.close != null)
  if (points.length < 2) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-semibold text-white">Price history</h2>
        <div className="mt-3 rounded-xl border border-dashed border-slate-800 py-10 text-center text-xs text-slate-500">
          Not enough candles to draw a chart yet.
        </div>
      </div>
    )
  }
  const width = 640
  const height = 180
  const closes = points.map((c) => c.close as number)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const span = max - min || 1
  const step = width / (points.length - 1)
  const path = points
    .map((c, i) => {
      const x = i * step
      const y = height - ((c.close as number) - min) / span * height
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  const last = closes[closes.length - 1]

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Price history</h2>
        <span className="font-mono text-sm font-semibold text-emerald-400">
          {(last * 100).toFixed(2)}¢
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" preserveAspectRatio="none">
        <path d={path} fill="none" stroke="#10b981" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-2 flex justify-between text-[10px] text-slate-600">
        <span>{new Date(points[0].timestamp * 1000).toLocaleString()}</span>
        <span>{new Date(points[points.length - 1].timestamp * 1000).toLocaleString()}</span>
      </div>
    </div>
  )
}

function levelList(levels: [string, number][]): { price: number; size: number }[] {
  return levels
    .map(([price, size]) => ({ price: Number(price), size: Number(size) }))
    .filter((l) => Number.isFinite(l.price) && Number.isFinite(l.size))
}
