import React, { Suspense, lazy, useEffect, useState } from 'react'
import {
  Activity,
  BookOpen,
  Briefcase,
  Coins,
  Gavel,
  Home,
  LogIn,
  LogOut,
  Menu,
  ShieldCheck,
  Tag,
  TrendingUp,
  User,
  UserPlus,
  X,
} from 'lucide-react'
import { ToastProvider } from './context/toast'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { WalletProvider } from './context/WalletContext'
import { WalletButton } from './components/WalletButton'
import { setToastHandler } from './api/client'
import { useToast } from './context/toast'
const HomePage = lazy(() => import('./pages/HomePage'))
const MarketsPage = lazy(() => import('./pages/MarketsPage'))
const EventDetailPage = lazy(() => import('./pages/EventDetailPage'))
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'))
const ResolutionPage = lazy(() => import('./pages/ResolutionPage'))
const DesksPage = lazy(() => import('./pages/DesksPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const CopyActivityPage = lazy(() => import('./pages/CopyActivityPage'))
const DeskDetailPage = lazy(() => import('./pages/DeskDetailPage'))
const TagsPage = lazy(() => import('./pages/TagsPage'))
const UserTradesPage = lazy(() => import('./pages/UserTradesPage'))
const SettledPositionsPage = lazy(() => import('./pages/SettledPositionsPage'))
const MarketDetailPage = lazy(() => import('./pages/MarketDetailPage'))
const LiveMarketsPage = lazy(() => import('./pages/LiveMarketsPage'))
const LiveMarketDetailPage = lazy(() => import('./pages/LiveMarketDetailPage'))
const AgxStakingPage = lazy(() => import('./pages/AgxStakingPage'))
import { Footer } from './components/Footer'

// Tiny hash router — path segments after '#'.
function useHashRoute(): [string[], (to: string) => void] {
  const [hash, setHash] = useState(window.location.hash.replace(/^#/, ''))
  useEffect(() => {
    const onChange = () => setHash(window.location.hash.replace(/^#/, ''))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const navigate = (to: string) => {
    window.location.hash = to
  }
  return [hash.split('?')[0].split('/').filter(Boolean), navigate]
}

export default function App() {
  return (
    <ToastProvider>
      <ToastBridge />
      <WalletProvider>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </WalletProvider>
    </ToastProvider>
  )
}

function ToastBridge() {
  const { push } = useToast()
  useEffect(() => {
    setToastHandler((message, kind) => push(message, kind))
  }, [push])
  return null
}

function Shell() {
  const [route, navigate] = useHashRoute()
  const { user, openAuth, logout } = useAuth()
  const section = route[0] || 'home'

  const openEvent = (slug: string) => navigate(`event/${slug}`)

  let page: React.ReactNode
  if (section === 'home') {
    page = (
      <HomePage
        onOpenEvent={openEvent}
        onOpenAuth={openAuth}
        onBrowseMarkets={() => navigate('live')}
      />
    )
  } else if (section === 'desks' && route[1]) {
    page = (
      <DeskDetailPage
        deskId={route[1]}
        onBack={() => navigate(user ? 'desks' : 'home')}
      />
    )
  } else if (section === 'desks') {
    page = <DesksPage onOpenDesk={(id) => navigate(`desks/${id}`)} />
  } else if (section === 'tags') {
    page = <TagsPage />
  } else if (section === 'trades') {
    page = <UserTradesPage />
  } else if (section === 'settled') {
    page = <SettledPositionsPage />
  } else if (section === 'market' && route[1]) {
    page = <MarketDetailPage marketId={route[1]} onBack={() => navigate('live')} />
  } else if (section === 'live' && route[1] === 'market' && route[2]) {
    page = (
      <LiveMarketDetailPage marketId={route[2]} onBack={() => navigate('live')} />
    )
  } else if (section === 'live') {
    page = <LiveMarketsPage onOpenMarket={(id) => navigate(`live/market/${id}`)} />
  } else if (section === 'markets') {
    page = <MarketsPage onOpenEvent={openEvent} onOpenLive={() => navigate('live')} />
  } else if (section === 'event' && route[1]) {
    page = <EventDetailPage slug={route[1]} onNavigate={(to) => navigate(to)} />
  } else if (section === 'portfolio') {
    page = <PortfolioWrapper onNavigate={navigate} />
  } else if (section === 'agx') {
    page = <AgxStakingPage />
  } else if (section === 'resolution') {
    page = <ResolutionPage />
  } else if (section === 'activity') {
    page = <CopyActivityPage onOpenDesk={(id) => navigate(`desks/${id}`)} />
  } else if (section === 'admin') {
    page = user?.is_admin ? <AdminPage /> : <LiveMarketsPage onOpenMarket={(id) => navigate(`live/market/${id}`)} />
  } else {
    page = <LiveMarketsPage onOpenMarket={(id) => navigate(`live/market/${id}`)} />
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav
        section={section}
        onNavigate={navigate}
        user={user}
        onAuth={openAuth}
        onLogout={logout}
      />
      <SectionSubNav section={section} user={user} onNavigate={navigate} />
      <Suspense
        fallback={
          <div className="mx-auto max-w-6xl px-6 py-16 text-center text-xs text-slate-500">
            Loading view…
          </div>
        }
      >
        {page}
      </Suspense>
      <Footer onNavigate={navigate} />
    </div>
  )
}

function PortfolioWrapper({ onNavigate }: { onNavigate: (to: string) => void }) {
  return (
    <PortfolioPage
      onOpenEvent={(slug) => onNavigate(`event/${slug}`)}
      onNavigate={onNavigate}
    />
  )
}

const NAV_ITEMS = [
  { key: 'live', label: 'Live Markets', icon: Activity },
  { key: 'desks', label: 'Desks', icon: TrendingUp },
  { key: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { key: 'agx', label: 'AGX', icon: Coins },
  { key: 'resolution', label: 'Resolution', icon: Gavel },
]

const ANON_NAV_ITEMS = [
  { key: 'home', label: 'Home', icon: Home },
  { key: 'live', label: 'Live Markets', icon: Activity },
  { key: 'desks', label: 'Desks', icon: TrendingUp },
  { key: 'agx', label: 'AGX', icon: Coins },
]

function SectionSubNav({
  section,
  user,
  onNavigate,
}: {
  section: string
  user: { id: string; email: string; is_admin: boolean } | null
  onNavigate: (to: string) => void
}) {
  let tabs: { key: string; label: string }[] | null = null
  const normalized = section

  if (normalized === 'live' || normalized === 'markets' || normalized === 'tags') {
    tabs = [
      { key: 'live', label: 'Live Markets' },
      { key: 'markets', label: 'Community' },
      { key: 'tags', label: 'Tags' },
    ]
  } else if (user && (normalized === 'desks' || normalized === 'activity')) {
    tabs = [
      { key: 'desks', label: 'Pro Desks' },
      { key: 'activity', label: 'Copy Activity' },
    ]
  } else if (user && (normalized === 'portfolio' || normalized === 'trades' || normalized === 'settled')) {
    tabs = [
      { key: 'portfolio', label: 'Overview' },
      { key: 'trades', label: 'Trades' },
      { key: 'settled', label: 'Settled' },
    ]
  }

  if (!tabs) return null

  return (
    <div className="border-b border-border/60 bg-background/60">
      <div className="mx-auto flex w-full max-w-[1840px] items-center gap-1 px-4 py-1.5 sm:px-6 lg:px-8 2xl:px-12">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onNavigate(t.key)}
            className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition ${
              normalized === t.key
                ? 'bg-muted text-foreground'
                : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Nav({
  section,
  onNavigate,
  user,
  onAuth,
  onLogout,
}: {
  section: string
  onNavigate: (to: string) => void
  user: { id: string; email: string; is_admin: boolean } | null
  onAuth: (mode: 'login' | 'register') => void
  onLogout: () => void
}) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const items = user
    ? user.is_admin
      ? [...NAV_ITEMS, { key: 'admin', label: 'Admin', icon: ShieldCheck }]
      : NAV_ITEMS
    : ANON_NAV_ITEMS
  const activeSection =
    (user && section === 'home') || section === 'markets' || section === 'tags'
      ? 'live'
      : section === 'activity'
        ? 'desks'
        : section === 'trades' || section === 'settled'
          ? 'portfolio'
          : section

  function go(key: string) {
    onNavigate(key)
    setMobileOpen(false)
  }

  return (
    <nav className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1840px] items-center justify-between px-4 sm:px-6 lg:px-8 2xl:px-12">
        <button
          onClick={() => go(user ? 'live' : 'home')}
          className="flex shrink-0 items-center gap-2 text-sm font-bold tracking-tight text-foreground transition hover:text-accent"
        >
          <img
            src="/logo.png"
            alt=""
            width={24}
            height={24}
            className="h-6 w-6 shrink-0 object-contain"
          />
          <span>AlgoXen</span>
        </button>

        {/* Desktop nav */}
        <div className="mx-2 hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden md:flex">
          {items.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => go(key)}
              className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                activeSection === key
                  ? 'bg-muted text-foreground'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <WalletButton />
          <a
            href={import.meta.env.VITE_DOCS_URL || '/docs/'}
            target="_blank"
            rel="noopener noreferrer"
            title="Documentation"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] text-muted-foreground transition hover:border-accent/40 hover:text-accent"
          >
            <BookOpen className="h-3 w-3" /> <span className="hidden sm:inline">Docs</span>
          </a>
          {user ? (
            <>
              <div
                title={user.email || 'trader'}
                className="flex items-center gap-1 rounded-lg border border-border px-2 py-1.5 text-[11px] text-foreground bg-muted/40"
              >
                <User className="h-3.5 w-3.5 text-accent" />
                {user.is_admin && (
                  <span className="rounded bg-emerald-500/20 px-1 py-0.5 text-[9px] font-bold text-emerald-400">
                    ADMIN
                  </span>
                )}
              </div>
              <button
                onClick={onLogout}
                title="Sign out"
                className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] text-muted-foreground transition hover:border-destructive/40 hover:text-destructive"
              >
                <LogOut className="h-3 w-3" /> <span className="hidden sm:inline">Sign out</span>
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onAuth('login')}
                className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
              >
                <LogIn className="h-3 w-3" /> <span className="hidden sm:inline">Sign in</span>
              </button>
              <button
                onClick={() => onAuth('register')}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-slate-950 transition hover:bg-emerald-400"
              >
                <UserPlus className="h-3 w-3" /> <span className="hidden sm:inline">Register</span>
              </button>
            </>
          )}

          {/* Hamburger (mobile) */}
          <button
            onClick={() => setMobileOpen((v) => !v)}
            className="flex items-center justify-center rounded-lg border border-slate-800 p-2 text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300 md:hidden"
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Mobile dropdown */}
      {mobileOpen && (
        <div className="border-t border-slate-800/80 bg-slate-950/95 px-4 py-3 md:hidden">
          <div className="grid grid-cols-2 gap-1.5">
            {items.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => go(key)}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition ${
                  activeSection === key
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
          {user && (
            <div className="mt-3 flex items-center gap-2 border-t border-slate-800/60 pt-3 text-[11px] text-slate-400">
              <User className="h-3.5 w-3.5 text-accent" />
              <span className="truncate">{user.email || 'trader'}</span>
              {user.is_admin && (
                <span className="rounded bg-emerald-500/20 px-1 py-0.5 text-[9px] font-bold text-emerald-400">
                  ADMIN
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </nav>
  )
}
