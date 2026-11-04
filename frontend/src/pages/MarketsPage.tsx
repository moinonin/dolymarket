import React, { useEffect, useState } from 'react'
import {
  Activity,
  BookOpen,
  CircleDollarSign,
  Gavel,
  Loader2,
  Search,
  TrendingUp,
} from 'lucide-react'
import { api, type Event, type Market, type OutcomeToken, type Ticker } from '../api/client'
import { ProbabilityBar, Skeleton, StatusPill } from '../components/ui'

const CATEGORIES = ['All', 'Politics', 'Crypto', 'Sports', 'Macro', 'Pop Culture', 'Tech']
const STATUS_TABS = [
  { key: '', label: 'All' },
  { key: 'ACTIVE', label: 'Active' },
  { key: 'ACTIVE_ENDING', label: 'Ending Soon' },
  { key: 'RESOLVED', label: 'Resolved' },
]
const SORTS = [
  { key: 'volume', label: 'Highest Volume' },
  { key: 'liquidity', label: 'Highest Liquidity' },
  { key: 'newest', label: 'Newest' },
  { key: 'ending_soon', label: 'Ending Soonest' },
]

interface TickerRow {
  token_id: string
  symbol: string
  price: number | null
}

export default function MarketsPage({ onOpenEvent }: { onOpenEvent: (slug: string) => void }) {
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState('All')
  const [statusTab, setStatusTab] = useState('')
  const [sort, setSort] = useState('volume')
  const [search, setSearch] = useState('')
  const [tickers, setTickers] = useState<Record<string, TickerRow>>({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        setError(null)
        const params: any = { sort_by: sort, limit: 50 }
        if (category !== 'All') params.category = category
        if (statusTab === 'ACTIVE' || statusTab === 'RESOLVED') params.status = statusTab
        if (search.trim()) params.search = search.trim()
        const res = await api.listEvents(params)
        if (cancelled) return
        setEvents(res.events)
        // Fetch top ticker per event's primary market token.
        const t: Record<string, TickerRow> = {}
        await Promise.all(
          res.events.slice(0, 12).map(async (ev) => {
            try {
              const detail = await api.getEventBySlug(ev.slug)
              const m = detail.markets?.[0]
              if (!m) return
              const tok = m.tokens[0]
              if (!tok) return
              const ticker = await api.getTicker(tok.token_id)
              t[ev.id] = {
                token_id: tok.token_id,
                symbol: tok.symbol,
                price: ticker.last_price ?? ticker.bbo.best_ask ?? ticker.bbo.best_bid,
              }
            } catch {
              /* ignore */
            }
          })
        )
        if (!cancelled) setTickers(t)
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Failed to load events')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [category, statusTab, sort, search])

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24 pt-8">
      {/* Hero */}
      <section className="mb-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white">
              Prediction markets for <span className="text-emerald-400">everything</span>
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Trade CLOB-driven probability on real-world outcomes. Robinhood-low fees at the
              extremes, transparent dynamic pricing, and 1:1 USDC settlement on resolution.
            </p>
          </div>
          <div className="flex items-center gap-6">
            <Stat icon={<TrendingUp className="h-4 w-4 text-emerald-400" />} label="Open Markets" value={`${events.filter((e) => e.status === 'ACTIVE').length}`} />
            <Stat icon={<BookOpen className="h-4 w-4 text-blue-400" />} label="Listed Events" value={`${events.length}`} />
          </div>
        </div>
      </section>

      {/* Controls */}
      <section className="mb-6 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search events, descriptions, tags…"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 py-2 pl-9 pr-3 text-sm text-slate-100 outline-none transition focus:border-emerald-500/60"
            />
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500/60"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key} className="bg-slate-900">
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-1.5">
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setStatusTab(t.key)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  statusTab === t.key
                    ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1.5">
            {CATEGORIES.map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  category === c
                    ? 'bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/40'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-200">{error}</div>
      )}

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-44 rounded-2xl border border-slate-800/70 p-5">
              <Skeleton className="mb-3 h-4 w-24" />
              <Skeleton className="mb-5 h-6 w-full" />
              <Skeleton className="mb-2 h-2 w-full" />
              <Skeleton className="h-2 w-2/3" />
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-slate-800 py-20 text-center">
          <Activity className="h-8 w-8 text-slate-600" />
          <p className="text-sm font-medium text-slate-300">No markets match your filters</p>
          <p className="max-w-sm text-xs text-slate-500">
            Try clearing the search box, switching category, or switching the status tab back
            to “All”. Market admins can create new events via the resolution portal.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {events.map((ev) => (
            <EventCard key={ev.id} event={ev} ticker={tickers[ev.id]} onOpen={onOpenEvent} />
          ))}
        </div>
      )}
    </div>
  )
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold text-white">{value}</div>
    </div>
  )
}

function countdown(endDate: string | null): string | null {
  if (!endDate) return null
  const ms = new Date(endDate).getTime() - Date.now()
  if (Number.isNaN(ms)) return null
  if (ms <= 0) return 'ended'
  const d = Math.floor(ms / 86400000)
  if (d > 0) return `${d}d left`
  const h = Math.floor(ms / 3600000)
  if (h > 0) return `${h}h left`
  const m = Math.floor(ms / 60000)
  return `${Math.max(1, m)}m left`
}

function EventCard({
  event,
  ticker,
  onOpen,
}: {
  event: Event
  ticker?: TickerRow
  onOpen: (slug: string) => void
}) {
  const cd = countdown(event.end_date)
  return (
    <button
      onClick={() => onOpen(event.slug)}
      className="group relative flex flex-col items-stretch rounded-2xl border border-slate-800 bg-slate-900/70 p-5 text-left transition-all hover:border-emerald-500/40 hover:bg-slate-900 hover:shadow-lg"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
          {event.category}
        </span>
        <StatusPill status={event.status} />
      </div>
      <h3 className="font-semibold leading-snug text-white group-hover:text-emerald-300 transition">
        {event.title}
      </h3>
      {event.description && (
        <p className="mt-1 line-clamp-2 text-xs text-slate-500">{event.description}</p>
      )}
      {event.markets && event.markets.length > 0 && (
        <div className="mt-4 space-y-2.5">
          {event.markets.slice(0, 1).map((m: Market) => {
            const tok = m.tokens[0]
            return (
              <div key={m.id} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3">
                <div className="mb-2 flex items-center justify-between text-[11px]">
                  <span className="truncate pr-2 text-slate-400">{m.question}</span>
                  {ticker?.price != null && (
                    <span className="shrink-0 font-mono font-semibold text-emerald-400">
                      ${(ticker.price * 100).toFixed(0)}¢
                    </span>
                  )}
                </div>
                <ProbabilityBar yes={ticker?.price ?? null} no={ticker?.price != null ? 1 - ticker.price : null} />
                <div className="mt-2 flex justify-between text-[10px] font-medium">
                  <span className="text-emerald-400">{tok?.symbol ?? 'YES'} {(ticker?.price ?? 0) >= 0 ? `${(100 * (ticker?.price ?? 0)).toFixed(0)}%` : '—'}</span>
                  <span className="text-rose-400">
                    {m.tokens[1]?.symbol ?? 'NO'}{' '}
                    {ticker?.price != null ? `${(100 * (1 - ticker.price)).toFixed(0)}%` : '—'}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
      <div className="mt-4 flex items-center justify-between text-[11px] text-slate-500">
        <span className="flex items-center gap-1">
          <CircleDollarSign className="h-3 w-3" />
          Vol ${event.total_volume?.toLocaleString?.() || '0'}
        </span>
        {cd && (
          <span className={cd === 'ended' ? 'text-slate-600' : 'text-amber-400/80'}>{cd}</span>
        )}
      </div>
    </button>
  )
}
