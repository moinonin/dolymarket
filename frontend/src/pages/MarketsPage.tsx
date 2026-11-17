import React, { useEffect, useState } from 'react'
import {
  Activity,
  CircleDollarSign,
  Gavel,
  Loader2,
  Plus,
  Search,
  TrendingUp,
} from 'lucide-react'
import { api, type Event, type Market, type OutcomeToken, type Ticker } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { ProbabilityBar, Skeleton, StatusPill } from '../components/ui'
import { useToast } from '../context/toast'

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

export default function MarketsPage({
  onOpenEvent,
  onOpenLive,
}: {
  onOpenEvent: (slug: string) => void
  onOpenLive?: () => void
}) {
  const { user, openAuth } = useAuth()
  const { push } = useToast()
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState('All')
  const [statusTab, setStatusTab] = useState('')
  const [sort, setSort] = useState('volume')
  const [search, setSearch] = useState('')
  const [tickers, setTickers] = useState<Record<string, TickerRow>>({})
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [cTitle, setCTitle] = useState('')
  const [cQuestion, setCQuestion] = useState('')
  const [cCategory, setCCategory] = useState('Crypto')
  const [cCriteria, setCCriteria] = useState('')
  const [cEndDate, setCEndDate] = useState('')
  const [cLiquidity, setCLiquidity] = useState('10')
  const [cFeed, setCFeed] = useState('')
  const [cRule, setCRule] = useState('>=')
  const [cThreshold, setCThreshold] = useState('')

  async function handleCreateCommunity(e: React.FormEvent) {
    e.preventDefault()
    if (!user) {
      openAuth('login')
      return
    }
    setCreating(true)
    try {
      const liq = Number(cLiquidity) || 0
      const thr = cThreshold.trim() !== '' ? Number(cThreshold) : undefined
      const res = await api.createCommunityMarket({
        title: cTitle.trim(),
        question: cQuestion.trim(),
        category: cCategory,
        resolution_criteria: cCriteria.trim(),
        outcomes: ['YES', 'NO'],
        ...(cEndDate ? { end_date: new Date(cEndDate).toISOString() } : {}),
        ...(liq > 0 ? { initial_liquidity_usdc: liq } : {}),
        ...(cFeed.trim() ? { oracle_feed: cFeed.trim(), oracle_comparator: cRule } : {}),
        ...(thr !== undefined && !Number.isNaN(thr) ? { oracle_threshold: thr } : {}),
      })
      push('Community market created!', 'info')
      setShowCreate(false)
      if (res.slug) {
        onOpenEvent(res.slug)
      }
    } catch (err: any) {
      push(err?.message || 'Could not create community market', 'error')
    } finally {
      setCreating(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        setError(null)
        const params: any = { sort_by: sort, limit: 50 }
        if (category !== 'All') params.category = category
        if (statusTab === 'ACTIVE_ENDING') {
          // "Ending Soon" is an ordering, not a status filter: the backend
          // sorts by end_date for sort_by=ending_soon.
          params.sort_by = 'ending_soon'
        } else if (statusTab === 'ACTIVE' || statusTab === 'RESOLVED') {
          params.status = statusTab
        }
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
    <div className="mx-auto w-full max-w-[1840px] px-4 sm:px-6 lg:px-8 2xl:px-12 pb-24 pt-8">
      {/* Hero */}
      <section className="mb-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white">
              Prediction markets for <span className="text-emerald-400">everything</span>
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Trade real-world outcomes on real order books. Fees shrink as prices
              approach certainty, and winning shares always settle 1:1 in USDC.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            <Stat icon={<TrendingUp className="h-3.5 w-3.5 text-emerald-400" />} label="Open" value={`${events.filter((e) => e.status === 'ACTIVE').length}`} />
            {onOpenLive && (
              <button
                onClick={onOpenLive}
                className="flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-xs font-semibold text-emerald-300 transition hover:border-emerald-500/60 hover:bg-emerald-500/15"
              >
                <Activity className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Live feed</span><span className="sm:hidden">Live</span> <span>→</span>
              </button>
            )}
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
          <button
            type="button"
            onClick={() => (user ? setShowCreate((v) => !v) : openAuth('login'))}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3.5 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-400"
          >
            <Plus className="h-3.5 w-3.5" />
            Create Community Market
          </button>
        </div>
        {showCreate && (
          <form
            onSubmit={handleCreateCommunity}
            className="grid gap-3 rounded-2xl border border-emerald-500/30 bg-slate-900/80 p-5 sm:grid-cols-2"
          >
            <input
              required
              minLength={5}
              value={cTitle}
              onChange={(e) => setCTitle(e.target.value)}
              placeholder="Event title (e.g. BTC >= $100k by Dec)"
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500"
            />
            <input
              required
              minLength={5}
              value={cQuestion}
              onChange={(e) => setCQuestion(e.target.value)}
              placeholder="Market question (e.g. Will BTC close >= $100,000?)"
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500"
            />
            <select
              value={cCategory}
              onChange={(e) => setCCategory(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500"
            >
              {CATEGORIES.filter((c) => c !== 'All').map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <input
              type="datetime-local"
              value={cEndDate}
              onChange={(e) => setCEndDate(e.target.value)}
              title="End date (UTC)"
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500"
            />
            <textarea
              required
              minLength={10}
              rows={2}
              value={cCriteria}
              onChange={(e) => setCCriteria(e.target.value)}
              placeholder="Resolution criteria (source, predicate, UTC deadline)..."
              className="sm:col-span-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-emerald-500"
            />
            <input
              type="number"
              min="0"
              step="any"
              value={cLiquidity}
              onChange={(e) => setCLiquidity(e.target.value)}
              placeholder="Initial LP USDC (>= 10 to activate)"
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500"
            />
            <div className="grid grid-cols-3 gap-2">
              <input
                value={cFeed}
                onChange={(e) => setCFeed(e.target.value)}
                placeholder="gate:BTC_USDT"
                className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500"
              />
              <select
                value={cRule}
                onChange={(e) => setCRule(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500"
              >
                <option value=">=">&gt;=</option>
                <option value=">">&gt;</option>
                <option value="<=">&lt;=</option>
                <option value="<">&lt;</option>
              </select>
              <input
                type="number"
                step="any"
                value={cThreshold}
                onChange={(e) => setCThreshold(e.target.value)}
                placeholder="Threshold"
                className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-xs text-white outline-none focus:border-emerald-500"
              />
            </div>
            <div className="sm:col-span-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={creating}
                className="rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
              >
                {creating ? 'Creating…' : 'Launch Market'}
              </button>
            </div>
          </form>
        )}
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
          <div className="flex flex-wrap gap-1.5">
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 3xl:grid-cols-5">
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 3xl:grid-cols-5">
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
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 sm:px-4 sm:py-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500 sm:text-[11px]">
        {icon}
        {label}
      </div>
      <div className="mt-0.5 font-mono text-lg font-semibold text-white sm:mt-1 sm:text-xl">{value}</div>
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
        <div className="flex items-center gap-1.5">
          <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
            {event.category}
          </span>
          {event.tier === 'COMMUNITY' && (
            <span className="rounded-md bg-purple-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-purple-300">
              Community
            </span>
          )}
        </div>
        {event.status === 'UNFUNDED' ? (
          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
            Unfunded
          </span>
        ) : (
          <StatusPill status={event.status} />
        )}
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
