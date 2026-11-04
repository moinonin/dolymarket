import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeftRight,
  ChevronLeft,
  Layers,
  Loader2,
  Users,
} from 'lucide-react'
import {
  api,
  getStoredToken,
  type Candle,
  type Market,
  type Order,
  type OrderBookSnapshot,
  type OutcomeToken,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { StatusPill, feeRateForCategory } from '../components/ui'
import { useToast } from '../context/toast'
import OrderBookLadder from '../components/OrderBookLadder'
import TradeTicket from '../components/TradeTicket'
import RecentTrades from '../components/RecentTrades'

function levelList(raw: [string, number][]): { price: number; size: number }[] {
  return raw.map(([p, s]) => ({ price: Number(p), size: Number(s) }))
}

export default function EventDetailPage({
  slug,
  onNavigate,
}: {
  slug: string
  onNavigate: (to: string) => void
}) {
  const [event, setEvent] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [marketId, setMarketId] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        setError(null)
        const data = await api.getEventBySlug(slug)
        if (!cancelled) {
          setEvent(data)
          const active = (data.markets || []).find(
            (m: Market) => m.status === 'ACTIVE'
          ) || data.markets?.[0]
          if (active) setMarketId(active.id)
        }
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Failed to load event')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [slug, tick])

  const market = event?.markets?.find((m: Market) => m.id === marketId) || event?.markets?.[0]

  if (loading) {
    return (
      <div className="mx-auto flex max-w-7xl items-center justify-center gap-3 px-6 py-32 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading event…
      </div>
    )
  }
  if (error || !event) {
    return (
      <div className="mx-auto max-w-3xl px-6 pt-24 text-center">
        <p className="text-sm text-red-300">{error || 'Event not found'}</p>
        <button onClick={() => onNavigate('/markets')} className="mt-4 text-xs text-slate-400 underline">
          ← Back to markets
        </button>
      </div>
    )
  }

  const category = event.category || 'Crypto'
  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      <button
        onClick={() => onNavigate('/markets')}
        className="mb-5 flex items-center gap-1.5 text-xs text-slate-400 transition hover:text-slate-200"
      >
        <ChevronLeft className="h-3.5 w-3.5" /> All markets
      </button>

      {/* Header */}
      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
            {category}
          </span>
          <StatusPill status={event.status} />
          {market?.neg_risk && (
            <span className="rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-300">
              Negative Risk
            </span>
          )}
        </div>
        <h1 className="mt-2.5 text-2xl font-bold tracking-tight text-white">{event.title}</h1>
        {event.description && <p className="mt-1.5 max-w-3xl text-sm text-slate-400">{event.description}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-5 text-xs text-slate-500">
          <span>
            Event volume{' '}
            <span className="font-mono text-slate-300">
              ${(event.total_volume || 0).toLocaleString()}
            </span>
          </span>
          {event.end_date && (
            <span>
              Ends <span className="font-mono text-slate-300">{new Date(event.end_date).toLocaleDateString()}</span>
            </span>
          )}
          <span>
            Oracle criteria: <span className="text-slate-300">UMA optimistic oracle — bonded assert, 2h dispute window.</span>
          </span>
        </div>
      </header>

      {/* Multi-market switcher */}
      {event.markets && event.markets.length > 1 && (
        <div className="mb-5 flex flex-wrap gap-1.5">
          {event.markets.map((m: Market) => (
            <button
              key={m.id}
              onClick={() => setMarketId(m.id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                m.id === marketId
                  ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {m.question}
            </button>
          ))}
        </div>
      )}

      {market ? (
        <TradingPanel market={market} category={category} onMutated={() => setTick((t) => t + 1)} />
      ) : (
        <p className="text-sm text-slate-500">This event has no tradable markets.</p>
      )}
    </div>
  )
}

function TradingPanel({
  market,
  category,
  onMutated,
}: {
  market: Market
  category: string
  onMutated: () => void
}) {
  const { push } = useToast()
  const { user } = useAuth()
  const [token, setToken] = useState<OutcomeToken>(market.tokens[0])
  const [book, setBook] = useState<OrderBookSnapshot | null>(null)
  const [trades, setTrades] = useState<React.ReactNode | null>(null)
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => setToken(market.tokens[0]), [market.id])

  // Fetch + live-subscribe the order book for the selected token.
  useEffect(() => {
    let cancelled = false
    let ws: WebSocket | null = null

    async function load() {
      try {
        const snap = await api.getOrderBook(token.token_id, 25)
        if (!cancelled) setBook(snap)
        const ticker = await api.getTicker(token.token_id)
        if (!cancelled) setLastPrice(ticker.last_price ?? null)
      } catch (err: any) {
        push(err.message)
      }
    }
    load()

    const token2 = getStoredToken()
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/v4/prediction/ws/public`)
    wsRef.current = ws
    ws.onopen = () => {
      ws?.send(
        JSON.stringify({ action: 'subscribe', channel: 'pred.depth', token_id: token.token_id })
      )
      ws?.send(JSON.stringify({ action: 'subscribe', channel: 'pred.trades' }))
      ws?.send(JSON.stringify({ action: 'subscribe', channel: 'pred.bbo', token_id: token.token_id }))
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.channel === 'pred.depth' && msg.token_id === token.token_id) {
          setBook(msg as OrderBookSnapshot)
        } else if (msg.channel === 'pred.trades') {
          setLastPrice(msg.price)
        } else if (msg.channel === 'pred.bbo' && msg.token_id === token.token_id) {
          setLastPrice(msg.last_price)
        }
      } catch {
        /* ignore */
      }
    }
    ws.onerror = () => {
      /* silent — REST polling still works */
    }
    return () => {
      cancelled = true
      ws?.close()
    }
  }, [token.token_id])

  const bids = useMemo(() => levelList(book?.bids || []), [book])
  const asks = useMemo(() => levelList(book?.asks || []), [book])

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px_320px]">
      {/* Chart + book column */}
      <div className="space-y-6">
        <PriceChart token={token} lastPrice={lastPrice} />
        <OrderBookLadder
          bids={bids}
          asks={asks}
          tickSize={market.tick_size}
          tokenSymbol={token.symbol}
        />
      </div>

      {/* Trade ticket */}
      <div className="space-y-6">
        <TradeTicket
          market={market}
          token={token}
          onTokenChange={setToken}
          lastPrice={lastPrice}
          bids={bids}
          asks={asks}
          feeRate={feeRateForCategory(category)}
          onPlaced={onMutated}
        />
      </div>

      {/* Trades */}
      <RecentTrades
        tokenId={token.token_id}
        onChange={setTrades}
      />
    </div>
  )
}

function PriceChart({ token, lastPrice }: { token: OutcomeToken; lastPrice: number | null }) {
  const [resolution, setResolution] = useState('1m')
  const [candles, setCandles] = useState<Candle[] | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await api.getPriceHistory(token.token_id, resolution)
        if (!cancelled) setCandles(res.candles)
      } catch {
        if (!cancelled) setCandles([])
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token.token_id, resolution, lastPrice])

  const total = (candles || []).length
  const width = 600
  const height = 160
  const points =
    candles && candles.length > 1
      ? candles
          .map((c, i) => {
            const x = (i / (total - 1)) * width
            const y = height - (c.close - 0.01) / 0.98 * height
            return `${x.toFixed(1)},${y.toFixed(1)}`
          })
          .join(' ')
      : null

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500">
            {token.symbol} probability
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-bold text-emerald-400">
              {lastPrice != null ? `${(lastPrice * 100).toFixed(1)}¢` : '—'}
            </span>
            <span className="text-xs text-slate-500">
              implied {(lastPrice ?? 0) >= 0 ? `${((lastPrice ?? 0) * 100).toFixed(0)}%` : '—'} chance
            </span>
          </div>
        </div>
        <div className="flex gap-1">
          {['1m', '5m', '1h', '1d'].map((r) => (
            <button
              key={r}
              onClick={() => setResolution(r)}
              className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                resolution === r
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:bg-slate-800/60 hover:text-slate-300'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" preserveAspectRatio="none">
        {[0.25, 0.5, 0.75].map((g) => (
          <line
            key={g}
            x1={0}
            x2={width}
            y1={height - g * height}
            y2={height - g * height}
            stroke="#1e293b"
            strokeDasharray="4 6"
          />
        ))}
        {points ? (
          <polyline points={points} fill="none" stroke="#34d399" strokeWidth={2} />
        ) : (
          <text x="50%" y="50%" textAnchor="middle" fill="#475569" fontSize="12">
            {candles == null ? 'Loading price history…' : 'No trades yet — be the first to quote'}
          </text>
        )}
      </svg>
    </div>
  )
}
