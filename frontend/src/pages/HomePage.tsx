import React, { useEffect, useState } from 'react'
import {
  Activity,
  BarChart3,
  Coins,
  Fingerprint,
  Keyboard,
  Percent,
  Radio,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { api, type Event, type Ticker } from '../api/client'
import { ProbabilityBar, Skeleton } from '../components/ui'

interface TickerRow {
  token_id: string
  symbol: string
  price: number | null
}

export default function HomePage({
  onOpenEvent,
  onOpenAuth,
  onBrowseMarkets,
}: {
  onOpenEvent: (slug: string) => void
  onOpenAuth: (mode: 'login' | 'register') => void
  onBrowseMarkets: () => void
}) {
  const [events, setEvents] = useState<Event[]>([])
  const [totalEvents, setTotalEvents] = useState(0)
  const [tickers, setTickers] = useState<Record<string, TickerRow>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        setError(null)
        const res = await api.listEvents({ sort_by: 'liquidity', limit: 100 })
        if (cancelled) return
        setEvents(res.events)
        setTotalEvents(res.total_count)

        const preview = res.events.slice(0, 6)
        const rows: Record<string, TickerRow> = {}
        await Promise.all(
          preview.map(async (ev) => {
            try {
              const detail = await api.getEventBySlug(ev.slug)
              const market = detail.markets?.[0]
              const token = market?.tokens?.[0]
              if (!token) return
              const ticker: Ticker = await api.getTicker(token.token_id)
              rows[ev.id] = {
                token_id: token.token_id,
                symbol: token.symbol,
                price: ticker.last_price ?? ticker.bbo.best_ask ?? ticker.bbo.best_bid,
              }
            } catch {
              /* a missing ticker must not break the page */
            }
          })
        )
        if (!cancelled) setTickers(rows)
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Could not load market data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const preview = events.slice(0, 6)
  const openMarkets = events.filter((e) => e.status === 'ACTIVE').length
  const trackedVolume = events.reduce((acc, e) => acc + (e.total_volume || 0), 0)

  return (
    <div className="mx-auto w-full max-w-7xl px-6 pb-24">
      {/* Hero */}
      <section className="relative overflow-hidden pt-16 pb-14">
        <div className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[46rem] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-[11px] font-medium text-emerald-300">
            <Sparkles className="h-3 w-3" />
            Trade the probability, not the narrative
          </span>
          <h1 className="mx-auto mt-5 max-w-3xl text-4xl font-bold leading-tight tracking-tight text-white sm:text-5xl">
            Prediction Markets with a{' '}
            <span className="text-emerald-400">Real Matching Engine</span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-slate-400">
            Back a view with real orders on a real order book. Prices move as the
            crowd trades, fees shrink as the outcome becomes certain, and winning
            shares redeem 1:1 in USDC.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <button
              onClick={() => onOpenAuth('register')}
              className="rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-400"
            >
              Create free account
            </button>
            <button
              onClick={onBrowseMarkets}
              className="rounded-xl border border-slate-700 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-emerald-500/40 hover:text-white"
            >
              Browse live markets
            </button>
          </div>

          <div className="mx-auto mt-10 grid max-w-2xl grid-cols-3 gap-3">
            <HeroStat
              label="Open markets"
              value={loading ? null : `${openMarkets}`}
            />
            <HeroStat
              label="Listed events"
              value={loading ? null : `${totalEvents}`}
            />
            <HeroStat
              label="Tracked volume"
              value={loading ? null : `$${Math.round(trackedVolume).toLocaleString()}`}
            />
          </div>
        </div>
      </section>

      {/* Live markets */}
      <section className="mt-6">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-xl font-semibold text-white">
              <Activity className="h-5 w-5 text-emerald-400" />
              Markets trading right now
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Live order books and prices streamed from the matching engine.
            </p>
          </div>
          <button
            onClick={onBrowseMarkets}
            className="text-xs font-medium text-emerald-400 transition hover:text-emerald-300"
          >
            View all →
          </button>
        </div>

        {error ? (
          <div className="rounded-2xl border border-red-800/60 bg-red-950/40 p-5 text-sm text-red-200">
            {error}
            <button
              onClick={() => window.location.reload()}
              className="ml-3 underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        ) : loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-2xl border border-slate-800/70 p-5">
                <Skeleton className="mb-3 h-3 w-20" />
                <Skeleton className="mb-5 h-5 w-full" />
                <Skeleton className="mb-2 h-2 w-full" />
                <Skeleton className="h-2 w-2/3" />
              </div>
            ))}
          </div>
        ) : preview.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-800 py-14 text-center">
            <BarChart3 className="mx-auto mb-3 h-7 w-7 text-slate-600" />
            <p className="text-sm font-medium text-slate-300">No markets listed yet</p>
            <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
              Markets appear here as soon as they are created in the resolution
              portal.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {preview.map((ev) => (
              <MarketPreviewCard
                key={ev.id}
                event={ev}
                ticker={tickers[ev.id]}
                onOpen={onOpenEvent}
              />
            ))}
          </div>
        )}
      </section>

      {/* Features */}
      <section className="mt-20">
        <h2 className="text-center text-2xl font-semibold tracking-tight text-white">
          Built like a trading venue, not a survey
        </h2>
        <p className="mx-auto mt-2 max-w-2xl text-center text-sm text-slate-400">
          Every layer of the stack is production-shaped: real matching, real
          settlement, real-time state and hardened access control.
        </p>
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 transition hover:border-emerald-500/30"
            >
              <f.icon className="h-5 w-5 text-emerald-400" />
              <h3 className="mt-3 text-sm font-semibold text-white">{f.title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                {f.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="mt-20 grid gap-3 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <div
            key={step.title}
            className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5"
          >
            <span className="font-mono text-xs font-bold text-emerald-400">
              STEP {i + 1}
            </span>
            <h3 className="mt-2 text-sm font-semibold text-white">{step.title}</h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              {step.body}
            </p>
          </div>
        ))}
      </section>

      {/* Security */}
      <section className="mt-20 overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900/60 to-emerald-950/30 p-8">
        <div className="grid items-center gap-8 lg:grid-cols-2">
          <div>
            <h2 className="flex items-center gap-2 text-xl font-semibold text-white">
              <ShieldCheck className="h-5 w-5 text-emerald-400" />
              Sign in the way you prefer
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              Email and password, a hardware-backed passkey, or a one-tap
              federated session with Google, Microsoft or Apple. Algorithmic
              traders can rotate an HMAC-signed API key and submit orders with
              idempotency keys.
            </p>
            <ul className="mt-4 space-y-2 text-xs text-slate-400">
              <li className="flex items-center gap-2">
                <Fingerprint className="h-3.5 w-3.5 text-emerald-400" />
                WebAuthn passkeys with sign-counter clone detection
              </li>
              <li className="flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                OAuth 2.0 authorization-code flow with one-time token exchange
              </li>
              <li className="flex items-center gap-2">
                <Radio className="h-3.5 w-3.5 text-emerald-400" />
                Rate-limited sign-in and order endpoints
              </li>
            </ul>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <MiniStat icon={<TrendingUp className="h-4 w-4 text-emerald-400" />} label="Fee model" value="C × r × p × (1−p)" />
            <MiniStat icon={<Coins className="h-4 w-4 text-emerald-400" />} label="Settlement" value="$1.00 / share" />
            <MiniStat icon={<Keyboard className="h-4 w-4 text-emerald-400" />} label="Hotkeys" value="B · S · ⏎ · Esc" />
            <MiniStat icon={<Percent className="h-4 w-4 text-emerald-400" />} label="Outcomes" value="Split & merge" />
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mt-20 text-center">
        <h2 className="text-2xl font-semibold tracking-tight text-white">
          Start trading probabilities in minutes
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-slate-400">
          Create an account, deposit USDC and take the first position on any
          live market.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => onOpenAuth('register')}
            className="rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-400"
          >
            Create free account
          </button>
          <button
            onClick={() => onOpenAuth('login')}
            className="rounded-xl border border-slate-700 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-emerald-500/40 hover:text-white"
          >
            I already have an account
          </button>
        </div>
      </section>
    </div>
  )
}

const FEATURES = [
  {
    icon: Zap,
    title: 'Instant matching',
    body: 'Limit and market orders match in milliseconds at price-time priority — exchange mechanics, not an AMM pool.',
  },
  {
    icon: Percent,
    title: 'Fees that fade near certainty',
    body: 'You pay the most at a coin flip and almost nothing at 99¢ — the fee follows your risk, not your size.',
  },
  {
    icon: Coins,
    title: 'Clean settlement',
    body: 'Winning shares redeem for exactly $1.00 in USDC. Split or merge outcome sets whenever you want.',
  },
  {
    icon: Radio,
    title: 'Live to the tick',
    body: 'Order book depth, trades and your fills stream in real time — no refreshing the page.',
  },
  {
    icon: BarChart3,
    title: 'Built for fast trading',
    body: 'Candlestick charts, depth ladders, keyboard shortcuts and one-tap order placement.',
  },
  {
    icon: ShieldCheck,
    title: 'Sign in without passwords',
    body: 'Passkeys or Google, Microsoft and Apple sign-in. API keys for bots, rate limits for everyone’s safety.',
  },
]

const STEPS = [
  {
    title: 'Fund your wallet',
    body: 'Deposit USDC in a couple of clicks. Funds are reserved per open order and released on cancel or fill.',
  },
  {
    title: 'Trade the book',
    body: 'Post limit or market orders with GTC, IOC or FOK. Post-only guarantees you never pay the taker fee.',
  },
  {
    title: 'Resolve and redeem',
    body: 'When the market resolves, winning tokens redeem 1:1 and the payout lands in your wallet.',
  },
]

function HeroStat({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-center">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-lg font-semibold text-white">
        {value == null ? <Skeleton className="mx-auto h-5 w-16" /> : value}
      </div>
    </div>
  )
}

function MiniStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold text-white">{value}</div>
    </div>
  )
}

function MarketPreviewCard({
  event,
  ticker,
  onOpen,
}: {
  event: Event
  ticker?: TickerRow
  onOpen: (slug: string) => void
}) {
  return (
    <button
      onClick={() => onOpen(event.slug)}
      className="group flex flex-col rounded-2xl border border-slate-800 bg-slate-900/60 p-5 text-left transition hover:border-emerald-500/40 hover:bg-slate-900"
    >
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
          {event.category}
        </span>
        {ticker?.price != null && (
          <span className="font-mono text-sm font-semibold text-emerald-400">
            {(ticker.price * 100).toFixed(0)}¢
          </span>
        )}
      </div>
      <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition group-hover:text-emerald-300">
        {event.title}
      </h3>
      <div className="mt-3">
        <ProbabilityBar
          yes={ticker?.price ?? null}
          no={ticker?.price != null ? 1 - ticker.price : null}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px] font-medium text-slate-500">
        <span className="text-emerald-400">
          {ticker?.symbol ?? 'YES'}{' '}
          {ticker?.price != null
            ? `${(ticker.price * 100).toFixed(0)}%`
            : '—'}
        </span>
        <span>Vol ${Math.round(event.total_volume || 0).toLocaleString()}</span>
      </div>
    </button>
  )
}
