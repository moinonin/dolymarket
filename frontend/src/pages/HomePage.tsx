import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  BarChart3,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Coins,
  Fingerprint,
  Flame,
  Keyboard,
  Newspaper,
  Percent,
  Radio,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { api, type Event, type NewsCarouselItem, type Ticker } from '../api/client'
import { ProbabilityBar, Skeleton } from '../components/ui'
import { HeroVisual } from '../components/HeroVisual'

interface TickerRow {
  token_id: string
  symbol: string
  price: number | null
}

type FeedMode = 'TRENDING' | 'NEW' | 'ENDING_SOON' | 'ALL'

const HOME_CATEGORIES = [
  'Trending',
  'New',
  'Politics',
  'Sports',
  'Culture',
  'Crypto',
  'Climate',
  'Economics',
  'Companies',
  'Financials',
  'Tech & Science',
  'Health',
  'World',
] as const

const CATEGORY_ALIASES: Record<string, string[]> = {
  Politics: ['politics', 'election', 'president', 'congress', 'senate', 'white house', 'policy'],
  Sports: ['sports', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'ufc', 'tennis', 'golf', 'champion'],
  Culture: ['pop culture', 'culture', 'oscars', 'grammys', 'box office', 'music', 'film', 'tv'],
  Crypto: ['crypto', 'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'defi', 'etf'],
  Climate: ['climate', 'weather', 'temperature', 'hurricane', 'emissions', 'energy'],
  Economics: ['macro', 'economics', 'fed', 'fomc', 'cpi', 'inflation', 'gdp', 'jobs', 'rates', 'recession'],
  Companies: ['companies', 'ipo', 'anthropic', 'openai', 'apple', 'tesla', 'nvidia', 'earnings', 'merger'],
  Financials: ['financials', 's&p', 'nasdaq', 'treasury', 'yield', 'stocks', 'forex', 'gold'],
  'Tech & Science': ['tech', 'science', 'ai', 'space', 'spacex', 'chips', 'quantum', 'robotics'],
  Health: ['health', 'fda', 'biotech', 'pharma', 'vaccine', 'cdc', 'who'],
  World: ['world', 'geopolitics', 'europe', 'china', 'tariffs', 'trade', 'un', 'war'],
}

const CATEGORY_SUBTOPICS: Record<string, string[]> = {
  Politics: ['Elections', 'White House', 'Congress', 'Supreme Court', 'Foreign Policy', 'Approvals'],
  Sports: ['NBA', 'NFL', 'MLB', 'Soccer', 'UFC & Boxing', 'Championships', 'MVP & Awards'],
  Culture: ['Oscars & Film', 'Grammys & Music', 'Box Office', 'Streaming & TV', 'Social & Creators'],
  Crypto: ['Bitcoin', 'Ethereum', 'Solana', 'Spot ETFs', 'Stablecoins', 'Regulation'],
  Climate: ['Daily Temps', 'Hurricanes', 'Precipitation', 'Clean Energy', 'Emissions'],
  Economics: ['Fed Rates', 'Inflation & CPI', 'Jobs & NFP', 'GDP Growth', 'Recession', 'Tariffs'],
  Companies: ['IPOs', 'AI Labs', 'Earnings', 'M&A', 'Tech Giants', 'CEO Changes'],
  Financials: ['S&P 500', 'Nasdaq 100', 'Treasury Yields', 'Oil & Commodities', 'FX & Dollar'],
  'Tech & Science': ['AI & Models', 'Space & Rockets', 'Semiconductors', 'Robotics', 'Consumer Tech'],
  Health: ['FDA Approvals', 'Biotech', 'Public Health', 'Clinical Trials'],
  World: ['US-China', 'Europe & ECB', 'Middle East', 'Trade & Tariffs', 'Global Elections'],
}

const CATEGORY_WIKI_TOPIC: Record<string, string> = {
  Macro: 'Federal_Reserve',
  Economics: 'Federal_Reserve',
  Crypto: 'Bitcoin',
  Politics: 'United_States_Capitol',
  Sports: 'National_Basketball_Association',
  Tech: 'Artificial_intelligence',
  'Tech & Science': 'Artificial_intelligence',
  'Pop Culture': 'Academy_Awards',
  Culture: 'Academy_Awards',
  Climate: 'Climate_change',
  Companies: 'Initial_public_offering',
  Financials: 'Wall_Street',
  Health: 'World_Health_Organization',
  World: 'United_Nations',
}

function inferWikiTopic(event: Event): string {
  const hay = `${event.title} ${event.description || ''} ${(event.tags || []).join(' ')}`.toLowerCase()
  if (hay.includes('bitcoin') || hay.includes('btc')) return 'Bitcoin'
  if (hay.includes('ethereum') || hay.includes('eth')) return 'Ethereum'
  if (hay.includes('anthropic') || hay.includes('openai') || hay.includes('ai')) return 'Artificial_intelligence'
  if (hay.includes('fed') || hay.includes('rate') || hay.includes('fomc')) return 'Federal_Reserve'
  if (hay.includes('inflation') || hay.includes('cpi')) return 'Inflation'
  if (hay.includes('president') || hay.includes('election') || hay.includes('trump')) return 'White_House'
  if (hay.includes('nba') || hay.includes('basketball')) return 'National_Basketball_Association'
  if (hay.includes('nfl') || hay.includes('super bowl')) return 'National_Football_League'
  return CATEGORY_WIKI_TOPIC[event.category] || 'New_York_Stock_Exchange'
}

function eventCountdown(endDate: string | null): string | null {
  if (!endDate) return null
  const ms = new Date(endDate).getTime() - Date.now()
  if (Number.isNaN(ms) || ms <= 0) return null
  const d = Math.floor(ms / 86400000)
  if (d > 0) return `${d}d left`
  const h = Math.floor(ms / 3600000)
  if (h > 0) return `${h}h left`
  return `${Math.max(1, Math.floor(ms / 60000))}m left`
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
  const [corpusTags, setCorpusTags] = useState<string[]>([])
  const [tickers, setTickers] = useState<Record<string, TickerRow>>({})
  const [topicImages, setTopicImages] = useState<Record<string, string>>({})
  const [newsSlides, setNewsSlides] = useState<NewsCarouselItem[]>(() => {
    try {
      const raw = window.sessionStorage.getItem('algoxen_news_carousel_v1')
      if (!raw) return []
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  })
  const [activeCategory, setActiveCategory] = useState<string>('Trending')
  const [feedMode, setFeedMode] = useState<FeedMode>('TRENDING')
  const [selectedTag, setSelectedTag] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [subDropOpen, setSubDropOpen] = useState(true)
  const [topicsDropOpen, setTopicsDropOpen] = useState(true)
  const [statusDropOpen, setStatusDropOpen] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        setError(null)
        // Fire news carousel in parallel immediately — do not wait for tickers or Wikipedia
        void api
          .getNewsCarousel(12)
          .then((newsRes) => {
            if (!cancelled && Array.isArray(newsRes.items) && newsRes.items.length > 0) {
              setNewsSlides(newsRes.items)
              try {
                window.sessionStorage.setItem(
                  'algoxen_news_carousel_v1',
                  JSON.stringify(newsRes.items)
                )
              } catch {
                /* ignore storage quota */
              }
            }
          })
          .catch(() => {
            /* fallback to market + Wikimedia carousel */
          })

        const [res, tagRes, liveTagRes] = await Promise.all([
          api.listEvents({ sort_by: 'liquidity', limit: 100 }),
          api.listTags().catch(() => ({ tags: [] as string[] })),
          api.getLiveTags().catch(() => ({ tags: [] as string[] })),
        ])
        if (cancelled) return
        setEvents(res.events)
        const mergedTags = Array.from(
          new Set([...(tagRes.tags || []), ...(liveTagRes.tags || [])].map((t) => t.trim()).filter(Boolean))
        )
        setCorpusTags(mergedTags)
        // Render page & carousel immediately without waiting on 24 ticker + 12 wiki calls
        setLoading(false)

        const preview = res.events.filter((e) => e.status === 'ACTIVE').slice(0, 12)
        void (async () => {
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
        })()

        // Fetch free CORS-enabled topic thumbnails from Wikimedia REST API in background
        const topics = Array.from(new Set(res.events.slice(0, 12).map(inferWikiTopic)))
        void (async () => {
          const imgs: Record<string, string> = {}
          await Promise.all(
            topics.map(async (topic) => {
              try {
                const r = await fetch(
                  `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(topic)}`
                )
                if (!r.ok) return
                const data = await r.json()
                const src = data?.thumbnail?.source || data?.originalimage?.source
                if (typeof src === 'string') imgs[topic] = src
              } catch {
                /* image fallback handled in card */
              }
            })
          )
          if (!cancelled) setTopicImages(imgs)
        })()
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Could not load market data')
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  // Re-query cached backend news pool whenever user clicks a category tab or tag
  useEffect(() => {
    let cancelled = false
    const isDefault =
      (activeCategory === 'Trending' || activeCategory === 'New') && selectedTag === 'ALL'
    api
      .getNewsCarousel(12, {
        category: activeCategory,
        tag: selectedTag,
      })
      .then((newsRes) => {
        if (!cancelled && Array.isArray(newsRes.items)) {
          setNewsSlides(newsRes.items)
          if (isDefault && newsRes.items.length > 0) {
            try {
              window.sessionStorage.setItem(
                'algoxen_news_carousel_v1',
                JSON.stringify(newsRes.items)
              )
            } catch {
              /* ignore */
            }
          }
        }
      })
      .catch(() => {
        /* keep current slides */
      })
    return () => {
      cancelled = true
    }
  }, [activeCategory, selectedTag])

  // Rank tags across active events by total volume + event count (Kalshi-style trending topics)
  const trendingTags = useMemo(() => {
    const scores = new Map<string, number>()
    for (const ev of events) {
      if (ev.status !== 'ACTIVE') continue
      const weight = (ev.total_volume || 0) + 100
      const tags = ev.tags?.length ? ev.tags : [ev.category]
      for (const raw of tags) {
        const tag = raw?.trim()
        if (!tag) continue
        scores.set(tag, (scores.get(tag) || 0) + weight)
      }
    }
    for (const t of corpusTags) {
      const tag = t?.trim()
      if (tag && !scores.has(tag)) scores.set(tag, 1)
    }
    return Array.from(scores.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([tag]) => tag)
  }, [events, corpusTags])

  const eventMatchesCategory = (ev: Event, cat: string): boolean => {
    if (cat === 'Trending' || cat === 'New') return true
    const aliases = CATEGORY_ALIASES[cat] || [cat.toLowerCase()]
    const hay = `${ev.category} ${ev.title} ${ev.description || ''} ${(ev.tags || []).join(' ')}`.toLowerCase()
    return aliases.some((kw) => hay.includes(kw))
  }

  const categoryTopics = useMemo(() => {
    const counts = new Map<string, number>()
    for (const ev of events) {
      if (!eventMatchesCategory(ev, activeCategory)) {
        continue
      }
      for (const raw of ev.tags || []) {
        const t = raw?.trim()
        if (t) counts.set(t, (counts.get(t) || 0) + 1)
      }
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([tag, count]) => ({ tag, count }))
  }, [events, activeCategory])

  const filteredEvents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const now = Date.now()
    let list = events.filter((ev) => (feedMode === 'ALL' ? true : ev.status === 'ACTIVE'))

    if (activeCategory !== 'Trending' && activeCategory !== 'New') {
      list = list.filter((ev) => eventMatchesCategory(ev, activeCategory))
    }

    if (selectedTag !== 'ALL') {
      const target = selectedTag.toLowerCase()
      list = list.filter(
        (ev) =>
          ev.category.toLowerCase() === target ||
          ev.title.toLowerCase().includes(target) ||
          (ev.description || '').toLowerCase().includes(target) ||
          (ev.tags || []).some((t) => t.toLowerCase().includes(target))
      )
    }
    if (q) {
      list = list.filter(
        (ev) =>
          ev.title.toLowerCase().includes(q) ||
          ev.category.toLowerCase().includes(q) ||
          (ev.tags || []).some((t) => t.toLowerCase().includes(q))
      )
    }

    const sorted = [...list]
    if (feedMode === 'TRENDING') {
      sorted.sort((a, b) => (b.total_volume || 0) - (a.total_volume || 0))
    } else if (feedMode === 'NEW') {
      sorted.reverse()
    } else if (feedMode === 'ENDING_SOON') {
      sorted.sort((a, b) => {
        const ta = a.end_date ? new Date(a.end_date).getTime() - now : Number.MAX_SAFE_INTEGER
        const tb = b.end_date ? new Date(b.end_date).getTime() - now : Number.MAX_SAFE_INTEGER
        return (ta > 0 ? ta : Number.MAX_SAFE_INTEGER) - (tb > 0 ? tb : Number.MAX_SAFE_INTEGER)
      })
    }
    return sorted
  }, [events, activeCategory, feedMode, selectedTag, searchQuery])

  const preview = filteredEvents.slice(0, 12)
  const featured = preview[0] ?? events[0] ?? null
  const featuredTicker = featured ? tickers[featured.id] : undefined
  const featuredYesCents = featuredTicker?.price != null ? Math.round(featuredTicker.price * 100) : null
  const featuredNoCents = featuredYesCents != null ? 100 - featuredYesCents : null
  const openMarkets = events.filter((e) => e.status === 'ACTIVE').length
  const resolvedMarkets = events.filter((e) => e.status === 'RESOLVED').length
  const trackedVolume = events.reduce((acc, e) => acc + (e.total_volume || 0), 0)
  const isTrendingHome = activeCategory === 'Trending'
  const subtopics = CATEGORY_SUBTOPICS[activeCategory] || []

  const selectCategory = (cat: string) => {
    setActiveCategory(cat)
    setSelectedTag('ALL')
    if (cat === 'New') setFeedMode('NEW')
    else if (cat === 'Trending') setFeedMode('TRENDING')
  }

  return (
    <div className="mx-auto w-full max-w-[1840px] px-4 sm:px-6 lg:px-8 2xl:px-12 pb-24">
      {/* Kalshi-Style Top Category & Trending Tag Ribbon */}
      <section className="pt-6 pb-4">
        <div className="flex flex-col gap-3 border-b border-slate-800/80 pb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
              {HOME_CATEGORIES.map((cat) => {
                const active = activeCategory === cat
                return (
                  <button
                    key={cat}
                    onClick={() => selectCategory(cat)}
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                      active
                        ? 'bg-emerald-500 text-slate-950 shadow-sm'
                        : 'text-slate-400 hover:bg-slate-800/70 hover:text-slate-200'
                    }`}
                  >
                    {cat === 'Trending' && <Flame className="h-3.5 w-3.5" />}
                    {cat}
                  </button>
                )
              })}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search topics or markets…"
                  className="w-48 rounded-lg border border-slate-800 bg-slate-900/90 py-1.5 pl-8 pr-2.5 text-xs text-white placeholder-slate-500 outline-none focus:border-emerald-500/50 sm:w-64"
                />
              </div>
              <button
                onClick={onBrowseMarkets}
                className="rounded-lg border border-slate-800 px-3 py-1.5 text-xs font-medium text-emerald-400 transition hover:border-emerald-500/40 hover:text-emerald-300"
              >
                All Markets →
              </button>
              <button
                onClick={() => onOpenAuth('register')}
                className="rounded-lg bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-300 ring-1 ring-emerald-500/30 transition hover:bg-emerald-500/25"
              >
                Sign up
              </button>
            </div>
          </div>

          {isTrendingHome && trendingTags.length > 0 && (
            <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
              <button
                onClick={() => setSelectedTag('ALL')}
                className={`shrink-0 rounded-full px-3 py-1 text-[11px] font-medium transition ${
                  selectedTag === 'ALL'
                    ? 'bg-white text-slate-950 font-semibold'
                    : 'border border-slate-800 bg-slate-900/60 text-slate-400 hover:border-slate-700 hover:text-white'
                }`}
              >
                Top Stories
              </button>
              {trendingTags.map((tag) => (
                <button
                  key={tag}
                  onClick={() => setSelectedTag(selectedTag === tag ? 'ALL' : tag)}
                  className={`shrink-0 rounded-full px-3 py-1 text-[11px] font-medium transition ${
                    selectedTag === tag
                      ? 'bg-emerald-500 text-slate-950 font-semibold'
                      : 'border border-slate-800 bg-slate-900/60 text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300'
                  }`}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Auto-sliding Visual News & Market Image Strip (strictly matches active category/tag/search) */}
      {(!loading || newsSlides.length > 0) && (filteredEvents.length > 0 || events.length > 0 || newsSlides.length > 0) && (() => {
        const q = searchQuery.trim().toLowerCase()
        const matchingNews = q
          ? newsSlides.filter((n) =>
              `${n.category} ${n.news_title} ${n.caption} ${n.market_title} ${n.source}`
                .toLowerCase()
                .includes(q)
            )
          : newsSlides
        return (
          <NewsVisualMarquee
            events={(filteredEvents.length > 0 ? filteredEvents : events).slice(0, 8)}
            newsSlides={matchingNews}
            tickers={tickers}
            topicImages={topicImages}
            onOpen={onOpenEvent}
          />
        )
      })()}

      {isTrendingHome ? (
        <>
          {/* Trending Home: Featured Story + Two-line Chart + Fear & Greed Meter */}
          <section className="mb-8 grid grid-cols-1 items-stretch gap-5 lg:grid-cols-12">
            <div className="relative flex flex-col justify-between overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70 p-6 font-geist-mono lg:col-span-7">
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-36 w-full opacity-55 [mask-image:linear-gradient(to_bottom,transparent,black_45%)]">
                <HeroCanvas />
              </div>
              <div className="relative">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                    <Newspaper className="h-3 w-3" />
                    {featured ? `Lead Story · ${featured.category}` : 'Trending Brief'}
                  </span>
                  {featured && (
                    <span className="font-mono tabular-nums text-xs text-slate-400">
                      ${Math.round(featured.total_volume || 0).toLocaleString()} vol ·{' '}
                      {featuredYesCents != null ? `${featuredYesCents}% Yes` : 'Live'}
                    </span>
                  )}
                </div>

                {featured ? (
                  <>
                    <button
                      type="button"
                      onClick={() => onOpenEvent(featured.slug)}
                      className="mt-3 block text-left text-xl font-bold leading-snug text-white transition hover:text-emerald-300 sm:text-2xl"
                    >
                      {featured.title}
                    </button>
                    {featured.description && (
                      <p className="mt-1.5 line-clamp-2 max-w-2xl text-xs text-slate-400">
                        {featured.description}
                      </p>
                    )}
                    <div className="mt-5 flex flex-wrap items-center gap-2.5">
                      <button
                        type="button"
                        onClick={() => onOpenEvent(featured.slug)}
                        className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs font-bold text-emerald-300 transition hover:bg-emerald-500/25"
                      >
                        <span>Trade {featuredTicker?.symbol ?? 'Yes'}</span>
                        <span className="font-mono tabular-nums">
                          {featuredYesCents != null ? `${featuredYesCents}¢` : '—'}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => onOpenEvent(featured.slug)}
                        className="inline-flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/15 px-4 py-2 text-xs font-bold text-rose-300 transition hover:bg-rose-500/25"
                      >
                        <span>Trade No</span>
                        <span className="font-mono tabular-nums">
                          {featuredNoCents != null ? `${featuredNoCents}¢` : '—'}
                        </span>
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="mt-4">
                    <h1 className="text-2xl font-bold text-white">Live Market Intelligence</h1>
                    <p className="mt-1 text-xs text-slate-400">
                      Click any headline to open the underlying live order book.
                    </p>
                  </div>
                )}
              </div>

              <div className="relative mt-6 grid grid-cols-3 gap-3 border-t border-slate-800/70 pt-4">
                <HeroStat label="Active markets" value={loading ? null : `${openMarkets}`} />
                <HeroStat label="Settled" value={loading ? null : `${resolvedMarkets}`} />
                <HeroStat
                  label="Tracked vol"
                  value={loading ? null : `$${Math.round(trackedVolume).toLocaleString()}`}
                />
              </div>
            </div>

            <div className="lg:col-span-5">
              <HeroVisual
                onExplore={() => {
                  if (featured?.slug) {
                    onOpenEvent(featured.slug)
                  } else {
                    onBrowseMarkets()
                  }
                }}
              />
            </div>
          </section>

          {/* Trending News-Style Briefs (click opens prediction market) */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-300">
                <Newspaper className="h-4 w-4 text-emerald-400" />
                Trending Headlines &amp; Live Odds
              </h2>
              <span className="text-[11px] text-slate-500">Click any story to trade the market</span>
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
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 3xl:grid-cols-5">
                {Array.from({ length: 8 }).map((_, i) => (
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
                <p className="text-sm font-medium text-slate-300">No trending stories match</p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 3xl:grid-cols-5">
                {preview.map((ev) => (
                  <NewsMarketCard
                    key={ev.id}
                    event={ev}
                    ticker={tickers[ev.id]}
                    onOpen={onOpenEvent}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      ) : (
        /* Category / Tag View: Left Sidebar (Category + Subcategories & Topics Dropdowns) + Right Pure Markets & Charts */
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-[248px_1fr]">
          <aside className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 self-start lg:sticky lg:top-20">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Category
                </div>
                <h2 className="text-lg font-bold text-white">{activeCategory}</h2>
              </div>
              <button
                type="button"
                onClick={() => selectCategory('Trending')}
                className="rounded-lg border border-slate-800 px-2 py-1 text-[11px] text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300"
              >
                ← Trending
              </button>
            </div>

            {/* Subcategories dropdown */}
            <div className="border-b border-slate-800/80 pb-3">
              <button
                type="button"
                onClick={() => setSubDropOpen((v) => !v)}
                className="flex w-full items-center justify-between py-1 text-xs font-semibold uppercase tracking-wider text-slate-300"
              >
                <span>Subcategories</span>
                {subDropOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {subDropOpen && (
                <div className="mt-2 space-y-1">
                  <button
                    type="button"
                    onClick={() => setSelectedTag('ALL')}
                    className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition ${
                      selectedTag === 'ALL'
                        ? 'bg-emerald-500/15 font-semibold text-emerald-300'
                        : 'text-slate-400 hover:bg-slate-800/70 hover:text-white'
                    }`}
                  >
                    <span>All {activeCategory}</span>
                  </button>
                  {subtopics.map((sub) => (
                    <button
                      key={sub}
                      type="button"
                      onClick={() => setSelectedTag(selectedTag === sub ? 'ALL' : sub)}
                      className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition ${
                        selectedTag === sub
                          ? 'bg-emerald-500/15 font-semibold text-emerald-300'
                          : 'text-slate-400 hover:bg-slate-800/70 hover:text-white'
                      }`}
                    >
                      <span>{sub}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Related Topics dropdown */}
            {categoryTopics.length > 0 && (
              <div className="border-b border-slate-800/80 pb-3">
                <button
                  type="button"
                  onClick={() => setTopicsDropOpen((v) => !v)}
                  className="flex w-full items-center justify-between py-1 text-xs font-semibold uppercase tracking-wider text-slate-300"
                >
                  <span>Topics</span>
                  {topicsDropOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
                {topicsDropOpen && (
                  <div className="mt-2 space-y-1">
                    {categoryTopics.map(({ tag, count }) => (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => setSelectedTag(selectedTag === tag ? 'ALL' : tag)}
                        className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition ${
                          selectedTag === tag
                            ? 'bg-emerald-500/15 font-semibold text-emerald-300'
                            : 'text-slate-400 hover:bg-slate-800/70 hover:text-white'
                        }`}
                      >
                        <span className="truncate">{tag}</span>
                        <span className="font-mono text-[10px] text-slate-500">{count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Status / Sort dropdown */}
            <div>
              <button
                type="button"
                onClick={() => setStatusDropOpen((v) => !v)}
                className="flex w-full items-center justify-between py-1 text-xs font-semibold uppercase tracking-wider text-slate-300"
              >
                <span>Sort &amp; Status</span>
                {statusDropOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {statusDropOpen && (
                <div className="mt-2 space-y-1">
                  {(
                    [
                      { key: 'TRENDING', label: 'Highest Volume' },
                      { key: 'ENDING_SOON', label: 'Ending Soon' },
                      { key: 'NEW', label: 'Newest' },
                      { key: 'ALL', label: 'Include Resolved' },
                    ] as const
                  ).map(({ key, label }) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setFeedMode(key)}
                      className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition ${
                        feedMode === key
                          ? 'bg-slate-800 font-semibold text-white'
                          : 'text-slate-400 hover:bg-slate-800/60 hover:text-white'
                      }`}
                    >
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </aside>

          {/* Right side: Purely Charts & Markets */}
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
              <div className="relative flex flex-col justify-between overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/65 p-5 xl:col-span-7">
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 w-full opacity-40 [mask-image:linear-gradient(to_bottom,transparent,black_45%)]">
                  <HeroCanvas />
                </div>
                <div className="relative">
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                      <TrendingUp className="h-3 w-3" />
                      Top in {activeCategory}
                      {selectedTag !== 'ALL' ? ` · ${selectedTag}` : ''}
                    </span>
                    <span className="font-mono tabular-nums text-xs text-slate-400">
                      {filteredEvents.length} market{filteredEvents.length === 1 ? '' : 's'}
                    </span>
                  </div>

                  {preview[0] ? (
                    <>
                      <button
                        type="button"
                        onClick={() => onOpenEvent(preview[0].slug)}
                        className="mt-3 block text-left text-lg font-bold leading-snug text-white transition hover:text-emerald-300 sm:text-xl"
                      >
                        {preview[0].title}
                      </button>
                      {preview[0].description && (
                        <p className="mt-1 line-clamp-2 text-xs text-slate-400">
                          {preview[0].description}
                        </p>
                      )}
                      <div className="mt-4 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => onOpenEvent(preview[0].slug)}
                          className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-bold text-emerald-300 transition hover:bg-emerald-500/25"
                        >
                          <span>{tickers[preview[0].id]?.symbol ?? 'Yes'}</span>
                          <span className="font-mono tabular-nums">
                            {tickers[preview[0].id]?.price != null
                              ? `${Math.round(tickers[preview[0].id].price! * 100)}¢`
                              : 'Trade'}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => onOpenEvent(preview[0].slug)}
                          className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-bold text-rose-300 transition hover:bg-rose-500/25"
                        >
                          <span>No</span>
                          <span className="font-mono tabular-nums">
                            {tickers[preview[0].id]?.price != null
                              ? `${100 - Math.round(tickers[preview[0].id].price! * 100)}¢`
                              : 'Trade'}
                          </span>
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="mt-4">
                      <h3 className="text-base font-bold text-white">
                        {activeCategory} Markets
                      </h3>
                      <p className="mt-1 text-xs text-slate-400">
                        No open contracts match this filter yet. Try another topic or browse all markets.
                      </p>
                    </div>
                  )}
                </div>

                <div className="relative mt-5 grid grid-cols-3 gap-3 border-t border-slate-800/70 pt-3">
                  <HeroStat label="Matching" value={`${filteredEvents.length}`} />
                  <HeroStat
                    label={`${activeCategory} vol`}
                    value={`$${Math.round(
                      filteredEvents.reduce((acc, e) => acc + (e.total_volume || 0), 0)
                    ).toLocaleString()}`}
                  />
                  <HeroStat
                    label="Top topic"
                    value={categoryTopics[0]?.tag ?? activeCategory}
                  />
                </div>
              </div>
              <div className="xl:col-span-5">
                <HeroVisual
                  onExplore={() => {
                    if (preview[0]?.slug) onOpenEvent(preview[0].slug)
                    else onBrowseMarkets()
                  }}
                />
              </div>
            </div>

            {preview.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-800 py-14 text-center">
                <BarChart3 className="mx-auto mb-3 h-7 w-7 text-slate-600" />
                <p className="text-sm font-medium text-slate-300">
                  No markets in {activeCategory}
                  {selectedTag !== 'ALL' ? ` · ${selectedTag}` : ''}
                </p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
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
          </div>
        </section>
      )}

      {/* Features */}
      <section className="mt-20">
        <h2 className="text-center text-2xl font-semibold tracking-tight text-white">
          Built like a trading venue, not a survey
        </h2>
        <p className="mx-auto mt-2 max-w-2xl text-center text-sm text-slate-400">
          Back a view with real orders, watch the price move, and if you're
          right, your shares settle at exactly $1.00.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
      <section className="mt-20 grid gap-4 md:grid-cols-3">
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
              Connect your non-custodial Web3 wallet (MetaMask, Rabby, Coinbase),
              authenticate with biometric passkeys, or use email. Algorithmic
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
                Sign-In with Ethereum (SIWE) cryptographic challenge verification
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
    body: 'Sign in with your Web3 wallet (MetaMask, Rabby, Coinbase) or biometric passkeys. HMAC API keys for automated bots.',
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
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-lg font-semibold text-white">
        {value == null ? <Skeleton className="h-5 w-16" /> : value}
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

function HeroCanvas() {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const POINTS = 160
    const STEP_MS = 650
    const clamp = (x: number) => Math.min(0.85, Math.max(0.15, x))
    const next = (v: number) => clamp(v + (Math.random() - 0.5) * 0.07)

    let yes: number[] = []
    let v = 0.5
    for (let i = 0; i <= POINTS; i++) {
      v = next(v)
      yes.push(v)
    }

    let liveTokenId: string | null = null
    let liveMarketId: string | null = null
    let hasLiveSeries = false
    let cancelled = false

    ;(async () => {
      try {
        const lm = await api.getLiveMarkets({ status: 'active', limit: 5 })
        if (cancelled) return
        const pick = (lm.markets || []).find((m) => m.tokens?.[0]?.token_id)
        const tokId = pick?.tokens?.[0]?.token_id
        if (!pick || !tokId) return
        liveMarketId = pick.id
        liveTokenId = tokId
        const hist = await api.getLivePriceHistory(tokId, '1h')
        if (cancelled) return
        const pts = (hist.candles || [])
          .map((c: any) => Number(c.close ?? c.p ?? c.price))
          .filter((n) => Number.isFinite(n) && n > 0 && n < 1)
        if (pts.length >= 10) {
          const min = Math.min(...pts)
          const max = Math.max(...pts)
          if (max - min >= 0.005) {
            const tail = pts.slice(-(POINTS + 1))
            while (tail.length <= POINTS) {
              tail.unshift(tail[0])
            }
            yes = tail
            v = tail[tail.length - 1]
            hasLiveSeries = true
          }
        }
      } catch {
        /* keep fallback series */
      }
    })()

    const livePoll = window.setInterval(async () => {
      if (cancelled || !liveMarketId || !liveTokenId || !hasLiveSeries) return
      try {
        const res = await api.getLiveMarket(liveMarketId)
        const tok = res.tokens?.find((t) => t.token_id === liveTokenId)
        if (tok?.price != null && Number.isFinite(tok.price)) {
          v = clamp(tok.price)
          yes = [...yes.slice(1), v]
        }
      } catch {
        /* keep last */
      }
    }, 5000)

    const dpr = Math.min(2, window.devicePixelRatio || 1)
    const resize = () => {
      canvas.width = canvas.clientWidth * dpr
      canvas.height = canvas.clientHeight * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    let raf = 0
    let last = performance.now()
    let shift = 0

    const trace = (
      series: number[],
      step: number,
      frac: number,
      stroke: string,
      glow: string
    ) => {
      const h = canvas.clientHeight
      ctx.beginPath()
      series.forEach((p, i) => {
        const x = i * step - frac
        const y = h - p * h
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.strokeStyle = stroke
      ctx.lineWidth = 2
      ctx.lineJoin = 'round'
      ctx.shadowColor = glow
      ctx.shadowBlur = 14
      ctx.stroke()
    }

    const frame = (t: number) => {
      const dt = Math.min(100, t - last)
      last = t
      if (!reduced && !hasLiveSeries) {
        shift += dt / STEP_MS
        while (shift >= 1) {
          shift -= 1
          v = next(v)
          yes = [...yes.slice(1), v]
        }
      }
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      ctx.clearRect(0, 0, w, h)
      const step = w / POINTS
      trace(yes.map((p) => 1 - p), step, shift * step, '#f43f5e', 'rgba(244,63,94,0.5)')
      trace(yes, step, shift * step, '#10b981', 'rgba(16,185,129,0.7)')
      if (!reduced) raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    return () => {
      cancelled = true
      window.clearInterval(livePoll)
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return <canvas ref={ref} className="h-full w-full" aria-hidden="true" />
}

function NewsVisualMarquee({
  events,
  newsSlides = [],
  tickers,
  topicImages,
  onOpen,
}: {
  events: Event[]
  newsSlides?: NewsCarouselItem[]
  tickers: Record<string, TickerRow>
  topicImages: Record<string, string>
  onOpen: (slug: string) => void
}) {
  const [paused, setPaused] = useState(false)
  const [brokenImgs, setBrokenImgs] = useState<Record<string, boolean>>({})
  const trackRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<{ active: boolean; startX: number; startScroll: number; moved: boolean }>({
    active: false,
    startX: 0,
    startScroll: 0,
    moved: false,
  })
  const resumeTimerRef = useRef<number | null>(null)
  const fractionalPxRef = useRef(0)

  const slides = useMemo(() => {
    const evBySlug = new Map(events.map((e) => [e.slug, e]))
    if (newsSlides.length > 0) {
      return newsSlides.map((n) => {
        const matchedEv = evBySlug.get(n.market_slug)
        const fallbackImg = matchedEv ? topicImages[inferWikiTopic(matchedEv)] : undefined
        const t = tickers[n.event_id]
        const liveYes = t?.price != null ? Math.round(t.price * 100) : n.yes_pct
        return {
          key: n.id,
          slug: n.market_slug,
          category: n.category,
          source: n.source,
          headline: n.news_title,
          caption: n.caption,
          marketTitle: n.market_title,
          image: (!brokenImgs[n.id] && n.image_url) || fallbackImg || null,
          yesPct: liveYes,
          volume: n.volume,
        }
      })
    }
    return events.map((ev) => {
      const t = tickers[ev.id]
      return {
        key: ev.id,
        slug: ev.slug,
        category: ev.category,
        source: null as string | null,
        headline: ev.title,
        caption: ev.description || null,
        marketTitle: ev.title,
        image: topicImages[inferWikiTopic(ev)] || null,
        yesPct: t?.price != null ? Math.round(t.price * 100) : null,
        volume: ev.total_volume || 0,
      }
    })
  }, [events, newsSlides, tickers, topicImages, brokenImgs])

  const total = slides.length
  const loopedSlides = useMemo(
    () => (total > 1 ? [...slides, ...slides] : slides),
    [slides, total]
  )

  // Reset scroll cleanly when filtered slide list changes
  useEffect(() => {
    if (trackRef.current) {
      trackRef.current.scrollLeft = 0
      fractionalPxRef.current = 0
    }
  }, [total])

  // Continuous smooth left-sliding motion at a predictable constant speed (36 px/sec)
  useEffect(() => {
    if (paused || total <= 1) return
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return
    }
    let rafId = 0
    let lastTs = performance.now()
    const SPEED_PX_PER_SEC = 36

    const step = (now: number) => {
      const el = trackRef.current
      const dt = Math.min(0.05, Math.max(0, (now - lastTs) / 1000))
      lastTs = now
      if (el && !dragRef.current.active) {
        const half = el.scrollWidth / 2
        if (half > 0) {
          fractionalPxRef.current += SPEED_PX_PER_SEC * dt
          const whole = Math.floor(fractionalPxRef.current)
          if (whole >= 1) {
            fractionalPxRef.current -= whole
            let nextLeft = el.scrollLeft + whole
            if (nextLeft >= half) nextLeft -= half
            el.scrollLeft = nextLeft
          }
        }
      }
      rafId = window.requestAnimationFrame(step)
    }

    rafId = window.requestAnimationFrame(step)
    return () => window.cancelAnimationFrame(rafId)
  }, [paused, total])

  // Keep seamless wrap when user swipes manually on touchpad or mobile
  useEffect(() => {
    const el = trackRef.current
    if (!el || total <= 1) return
    const onScroll = () => {
      const half = el.scrollWidth / 2
      if (half <= 0) return
      if (el.scrollLeft >= half) {
        el.scrollLeft -= half
      } else if (el.scrollLeft <= 0) {
        el.scrollLeft += half
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [total])

  useEffect(() => {
    return () => {
      if (resumeTimerRef.current != null) window.clearTimeout(resumeTimerRef.current)
    }
  }, [])

  if (total === 0) return null

  const pauseTemporarily = (ms = 1400) => {
    setPaused(true)
    if (resumeTimerRef.current != null) window.clearTimeout(resumeTimerRef.current)
    resumeTimerRef.current = window.setTimeout(() => setPaused(false), ms)
  }

  const nudge = (dir: -1 | 1) => {
    const el = trackRef.current
    if (!el) return
    pauseTemporarily(1800)
    const stepPx = Math.max(280, Math.round(el.clientWidth * 0.45))
    el.scrollBy({ left: dir * stepPx, behavior: 'smooth' })
  }

  return (
    <section
      tabIndex={0}
      aria-label="News and active markets carousel"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => {
        dragRef.current.active = false
        setPaused(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowRight') nudge(1)
        else if (e.key === 'ArrowLeft') nudge(-1)
      }}
      className="relative mb-6 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/80 p-3 select-none focus:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500/50"
    >
      <div className="relative">
        {total > 1 && (
          <>
            <button
              type="button"
              aria-label="Slide left"
              onClick={(e) => {
                e.stopPropagation()
                nudge(-1)
              }}
              className="absolute left-2 top-1/2 z-20 -translate-y-1/2 rounded-full border border-slate-700/80 bg-slate-950/85 p-2 text-white shadow-lg backdrop-blur-sm transition hover:border-emerald-500/60 hover:bg-slate-900"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="Slide right"
              onClick={(e) => {
                e.stopPropagation()
                nudge(1)
              }}
              className="absolute right-2 top-1/2 z-20 -translate-y-1/2 rounded-full border border-slate-700/80 bg-slate-950/85 p-2 text-white shadow-lg backdrop-blur-sm transition hover:border-emerald-500/60 hover:bg-slate-900"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </>
        )}

        <div
          ref={trackRef}
          onWheel={(e) => {
            if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) pauseTemporarily(1200)
          }}
          onTouchStart={() => setPaused(true)}
          onTouchEnd={() => pauseTemporarily(1200)}
          onPointerDown={(e) => {
            if (e.pointerType !== 'mouse' || e.button !== 0 || !trackRef.current) return
            dragRef.current = {
              active: true,
              startX: e.clientX,
              startScroll: trackRef.current.scrollLeft,
              moved: false,
            }
          }}
          onPointerMove={(e) => {
            if (!dragRef.current.active || !trackRef.current) return
            const dx = e.clientX - dragRef.current.startX
            if (Math.abs(dx) > 6) dragRef.current.moved = true
            trackRef.current.scrollLeft = dragRef.current.startScroll - dx
          }}
          onPointerUp={() => {
            if (!dragRef.current.active) return
            const wasMoved = dragRef.current.moved
            dragRef.current.active = false
            if (wasMoved) {
              window.setTimeout(() => {
                dragRef.current.moved = false
              }, 150)
            }
          }}
          className="flex gap-3 overflow-x-auto overscroll-x-contain touch-pan-x [scrollbar-width:none] [&::-webkit-scrollbar]:hidden cursor-grab active:cursor-grabbing"
        >
        {loopedSlides.map((slide, idx) => (
          <button
            key={`${slide.key}-${idx}`}
            type="button"
            onClick={() => {
              if (dragRef.current.moved) return
              onOpen(slide.slug)
            }}
            className="group relative flex aspect-[16/10] min-h-[240px] w-[86%] shrink-0 flex-col justify-end overflow-hidden rounded-xl border border-slate-800 bg-slate-900 text-left transition hover:border-emerald-500/50 sm:min-h-[255px] sm:w-[48%] lg:min-h-[270px] lg:w-[32.2%] 2xl:w-[24.2%]"
          >
            {slide.image ? (
              <img
                src={slide.image}
                alt={slide.headline}
                loading="eager"
                decoding="async"
                draggable={false}
                onError={() => setBrokenImgs((b) => ({ ...b, [slide.key]: true }))}
                className="absolute inset-0 h-full w-full object-cover object-center opacity-100 transition duration-500 group-hover:scale-105"
              />
            ) : (
              <div className="absolute inset-0 bg-gradient-to-br from-emerald-950/80 via-slate-900 to-blue-950/80" />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/25 via-45% to-transparent" />

            <div className="relative z-10 p-4">
              <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider">
                <div className="flex items-center gap-1.5 truncate">
                  {slide.source && (
                    <span className="rounded bg-slate-900/90 px-2 py-0.5 text-slate-200 backdrop-blur-sm">
                      {slide.source}
                    </span>
                  )}
                  <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-300 backdrop-blur-sm">
                    {slide.category}
                  </span>
                </div>
                <span className="shrink-0 font-mono tabular-nums text-white">
                  {slide.yesPct != null ? `${slide.yesPct}% Yes` : 'Live'}
                </span>
              </div>
              <p className="line-clamp-2 text-sm font-bold leading-snug text-white group-hover:text-emerald-300">
                {slide.headline}
              </p>
              {slide.caption && slide.caption !== slide.headline && (
                <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-300/90">
                  {slide.caption}
                </p>
              )}
              <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-slate-800/80 pt-2 text-[11px]">
                <span className="truncate font-medium text-emerald-300">
                  Trade: {slide.marketTitle}
                </span>
                <span className="shrink-0 font-mono tabular-nums text-slate-400">
                  ${Math.round(slide.volume).toLocaleString()}
                </span>
              </div>
            </div>
          </button>
        ))}
        </div>
      </div>
    </section>
  )
}

function NewsMarketCard({
  event,
  ticker,
  onOpen,
}: {
  event: Event
  ticker?: TickerRow
  onOpen: (slug: string) => void
}) {
  const yesPct = ticker?.price != null ? Math.round(ticker.price * 100) : null
  const cd = eventCountdown(event.end_date)
  const primaryTag = event.tags?.[0] || event.category

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(event.slug)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(event.slug)
        }
      }}
      className="group flex cursor-pointer flex-col justify-between rounded-2xl border border-slate-800 bg-slate-900/65 p-5 text-left transition hover:border-emerald-500/40 hover:bg-slate-900"
    >
      <div>
        <div className="mb-2 flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider">
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <Newspaper className="h-3 w-3" />
            {event.category} · {primaryTag}
          </span>
          {cd && <span className="text-slate-500">{cd}</span>}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition group-hover:text-emerald-300">
          {event.title}
        </h3>
        {event.description && (
          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-slate-400">
            {event.description}
          </p>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-800/80 pt-3 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="font-mono tabular-nums font-semibold text-emerald-400">
            {yesPct != null ? `${yesPct}% odds` : 'Live market'}
          </span>
          <span className="text-slate-600">·</span>
          <span className="font-mono tabular-nums text-slate-400">
            ${Math.round(event.total_volume || 0).toLocaleString()} vol
          </span>
        </div>
        <span className="font-semibold text-slate-400 transition group-hover:text-emerald-300">
          Trade →
        </span>
      </div>
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
  const yesCents = ticker?.price != null ? Math.round(ticker.price * 100) : null
  const noCents = yesCents != null ? 100 - yesCents : null
  const cd = eventCountdown(event.end_date)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(event.slug)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(event.slug)
        }
      }}
      className="group flex cursor-pointer flex-col justify-between rounded-2xl border border-slate-800 bg-slate-900/65 p-5 text-left transition hover:border-emerald-500/40 hover:bg-slate-900"
    >
      <div>
        <div className="mb-2.5 flex items-center justify-between gap-2">
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
          <span className="font-mono tabular-nums text-sm font-bold text-emerald-400">
            {yesCents != null ? `${yesCents}%` : '—'}
          </span>
        </div>

        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition group-hover:text-emerald-300">
          {event.title}
        </h3>
      </div>

      <div className="mt-4 space-y-2.5">
        <ProbabilityBar
          yes={ticker?.price ?? null}
          no={ticker?.price != null ? 1 - ticker.price : null}
        />

        {/* Kalshi-style inline Yes / No quick-action pills */}
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpen(event.slug)
            }}
            className="flex items-center justify-between rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20"
          >
            <span>{ticker?.symbol ?? 'Yes'}</span>
            <span className="font-mono tabular-nums">
              {yesCents != null ? `${yesCents}¢` : '—'}
            </span>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpen(event.slug)
            }}
            className="flex items-center justify-between rounded-lg border border-rose-500/25 bg-rose-500/10 px-2.5 py-1.5 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20"
          >
            <span>No</span>
            <span className="font-mono tabular-nums">
              {noCents != null ? `${noCents}¢` : '—'}
            </span>
          </button>
        </div>

        <div className="flex items-center justify-between text-[10px] font-medium text-slate-500">
          <span className="font-mono tabular-nums">
            Vol ${Math.round(event.total_volume || 0).toLocaleString()}
          </span>
          {cd && <span className="text-amber-400/80">{cd}</span>}
        </div>
      </div>
    </div>
  )
}
