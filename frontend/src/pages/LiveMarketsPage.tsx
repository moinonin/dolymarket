import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, KeyRound, RefreshCw, WifiOff } from 'lucide-react'
import { api, type LiveAuthStatus, type LiveMarket } from '../api/client'
import { Skeleton } from '../components/ui'

const REFRESH_MS = 20000
const PAGE_SIZE = 50

const STATUS_TABS = [
  { key: 'active', label: 'Live now' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'closed', label: 'All closed' },
]

export default function LiveMarketsPage({
  onOpenMarket,
}: {
  onOpenMarket: (marketId: string) => void
}) {
  const [markets, setMarkets] = useState<LiveMarket[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [status, setStatus] = useState('active')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [auth, setAuth] = useState<LiveAuthStatus | null>(null)

  const loadAuth = useCallback(async () => {
    try {
      setAuth(await api.getLiveAuth())
    } catch {
      setAuth(null)
    }
  }, [])

  useEffect(() => {
    void loadAuth()
    const iv = setInterval(() => void loadAuth(), 60000)
    return () => clearInterval(iv)
  }, [loadAuth])

  const load = useCallback(async () => {
    try {
      const res = await api.getLiveMarkets({ status, limit: PAGE_SIZE, offset })
      setMarkets(res.markets || [])
      setHasMore(Boolean(res.has_more))
      setUpdatedAt(Date.now())
      setError(null)
    } catch (err: any) {
      setError(err?.message || 'Could not reach the live feed')
    } finally {
      setLoading(false)
    }
  }, [status, offset])

  useEffect(() => {
    void load()
    const iv = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(iv)
  }, [load])

  const filtered = useMemo(() => {
    if (!markets) return []
    const q = search.trim().toLowerCase()
    if (!q) return markets
    return markets.filter(
      (m) =>
        m.question.toLowerCase().includes(q) ||
        (m.event_title || '').toLowerCase().includes(q) ||
        (m.category || '').toLowerCase().includes(q)
    )
  }, [markets, search])

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-400" />
            <h1 className="text-2xl font-bold text-white">Live markets</h1>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
              <span className="relative inline-flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
              </span>
              Live feed
            </span>
            {auth && (
              <span
                title={auth.upstream?.message || auth.scheme}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  auth.authenticated
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                    : auth.configured
                      ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                      : 'border-slate-700 bg-slate-800/60 text-slate-400'
                }`}
              >
                <KeyRound className="h-2.5 w-2.5" />
                {auth.authenticated
                  ? 'Auth ok'
                  : auth.configured
                    ? `Auth ${auth.upstream?.label || 'rejected'}`
                    : 'Public only'}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-400">
            Real-time market data from our live feed — read-only. Switch tabs for
            resolved markets and walk back through the feed history.
          </p>
          {auth && auth.configured && !auth.authenticated && (
            <p className="mt-2 text-xs text-amber-300/90">
              The live feed rejected the configured API credential ({auth.upstream?.label}).
              Public market data still works; account data (positions, trades, balances) stays
              unavailable until a valid key is configured.
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {updatedAt && (
            <span className="text-[11px] text-slate-500">
              updated {new Date(updatedAt).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </header>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search live markets…"
        className="mb-4 w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-emerald-500/50"
      />

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => {
                setStatus(t.key)
                setOffset(0)
              }}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                status === t.key
                  ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-slate-800 disabled:hover:text-slate-300"
          >
            ← Newer
          </button>
          <span className="text-[11px] text-slate-500">
            {offset === 0 ? 'latest' : `history ${offset}+`}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={!hasMore}
            className="rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-slate-800 disabled:hover:text-slate-300"
          >
            Older →
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-rose-800/60 bg-rose-950/40 p-4 text-sm text-rose-200">
          <WifiOff className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Live feed unavailable</p>
            <p className="mt-0.5 text-xs text-rose-300/80">{error}</p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
              <Skeleton className="h-8 w-full" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center">
          <p className="text-sm font-medium text-slate-300">
            {status === 'active' ? 'No live markets found' : 'No resolved markets on this page'}
          </p>
          <p className="mx-auto mt-1 max-w-md text-xs text-slate-500">
            {search
              ? 'Nothing matches that search in the live feed. Try a different term.'
              : status === 'active'
                ? 'The live feed has no active markets right now.'
                : 'Use “Older →” to walk further back through the feed history.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((m) => (
            <LiveMarketCard key={m.id} market={m} onOpen={() => onOpenMarket(m.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function LiveMarketCard({ market, onOpen }: { market: LiveMarket; onOpen: () => void }) {
  const first = market.tokens?.[0]
  const second = market.tokens?.[1]
  const yes = first?.price ?? null
  const no = second?.price ?? null
  const resolved = market.resolved || market.status === 'CLOSED'
  const winnerIndex = market.winning_outcome_index
  return (
    <button
      onClick={onOpen}
      className="group flex w-full flex-col rounded-2xl border border-slate-800 bg-slate-900/50 p-5 text-left transition hover:border-emerald-500/40 hover:bg-slate-900/80"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold leading-snug text-white group-hover:text-emerald-200">
          {market.question}
        </h2>
        {resolved ? (
          <span className="shrink-0 rounded-full border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
            Resolved
          </span>
        ) : (
          <span className="shrink-0 rounded-full border border-slate-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
            {market.status}
          </span>
        )}
      </div>
      {market.event_title && (
        <p className="mt-1 truncate text-xs text-slate-500">{market.event_title}</p>
      )}

      <div className="mt-4 flex items-end gap-4">
        <div className="flex-1">
          <div className="flex items-baseline justify-between text-[11px] text-slate-400">
            <span>{first?.symbol ?? 'Yes'}</span>
            <span className="font-mono text-base font-semibold text-emerald-400">
              {yes != null ? `${(yes * 100).toFixed(1)}%` : '—'}
            </span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            {yes != null && (
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${yes * 100}%` }} />
            )}
          </div>
        </div>
        {second && (
          <div className="flex-1">
            <div className="flex items-baseline justify-between text-[11px] text-slate-400">
              <span>{second.symbol}</span>
              <span className="font-mono text-base font-semibold text-rose-400">
                {no != null ? `${(no * 100).toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
              {no != null && (
                <div className="h-full rounded-full bg-rose-500" style={{ width: `${no * 100}%` }} />
              )}
            </div>
          </div>
        )}
      </div>

      {resolved && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-1.5 text-[11px]">
          {winnerIndex != null && market.outcomes?.[winnerIndex] ? (
            <span className="text-slate-300">
              Result:{' '}
              <span className="font-semibold text-emerald-300">
                {market.outcomes[winnerIndex]}
              </span>{' '}
              won
            </span>
          ) : (
            <span className="text-slate-500">Closed — no settled outcome reported</span>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span>vol ${fmtCompact(market.volume)}</span>
        <span>liq ${fmtCompact(market.liquidity)}</span>
        {market.best_bid != null && market.best_ask != null && (
          <span className="font-mono text-slate-400">
            {(market.best_bid * 100).toFixed(1)}¢ / {(market.best_ask * 100).toFixed(1)}¢
          </span>
        )}
        {market.category && <span className="uppercase tracking-wide">{market.category}</span>}
      </div>
    </button>
  )
}

function fmtCompact(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return value.toFixed(0)
}
