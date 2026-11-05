import React, { useEffect, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  Briefcase,
  Gavel,
  Home,
  LineChart,
  LogIn,
  LogOut,
  ShieldCheck,
  Tag,
  TrendingUp,
  UserPlus,
} from 'lucide-react'
import { ToastProvider } from './context/toast'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { setToastHandler } from './api/client'
import { useToast } from './context/toast'
import HomePage from './pages/HomePage'
import MarketsPage from './pages/MarketsPage'
import EventDetailPage from './pages/EventDetailPage'
import PortfolioPage from './pages/PortfolioPage'
import ResolutionPage from './pages/ResolutionPage'
import DesksPage from './pages/DesksPage'
import DeskDetailPage from './pages/DeskDetailPage'
import TagsPage from './pages/TagsPage'
import UserTradesPage from './pages/UserTradesPage'
import SettledPositionsPage from './pages/SettledPositionsPage'
import MarketDetailPage from './pages/MarketDetailPage'

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
      <AuthProvider>
        <Shell />
      </AuthProvider>
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
    page = user ? (
      <MarketsPage onOpenEvent={openEvent} />
    ) : (
      <HomePage
        onOpenEvent={openEvent}
        onOpenAuth={openAuth}
        onBrowseMarkets={() => navigate('markets')}
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
    page = <MarketDetailPage marketId={route[1]} onBack={() => navigate('markets')} />
  } else if (section === 'event' && route[1]) {
    page = <EventDetailPage slug={route[1]} onNavigate={(to) => navigate(to)} />
  } else if (section === 'portfolio') {
    page = <PortfolioWrapper onNavigate={navigate} />
  } else if (section === 'resolution') {
    page = <ResolutionPage />
  } else {
    page = <MarketsPage onOpenEvent={openEvent} />
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Nav
        section={section}
        onNavigate={navigate}
        user={user}
        onAuth={openAuth}
        onLogout={logout}
      />
      {page}
      <footer className="border-t border-slate-900 py-6 text-center text-[11px] text-slate-600">
        Dolymarket · in-memory CLOB · CTF settlement · UMA-style optimistic
        oracle — simulation environment, not financial advice.
      </footer>
    </div>
  )
}

function PortfolioWrapper({ onNavigate }: { onNavigate: (to: string) => void }) {
  return <PortfolioPage onOpenEvent={(slug) => onNavigate(`event/${slug}`)} />
}

const NAV_ITEMS = [
  { key: 'markets', label: 'Markets', icon: LineChart },
  { key: 'desks', label: 'Desks', icon: TrendingUp },
  { key: 'tags', label: 'Tags', icon: Tag },
  { key: 'trades', label: 'Trades', icon: TrendingUp },
  { key: 'settled', label: 'Settled', icon: Briefcase },
  { key: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { key: 'resolution', label: 'Resolution', icon: Gavel },
]

const ANON_NAV_ITEMS = [
  { key: 'home', label: 'Home', icon: Home },
  { key: 'markets', label: 'Markets', icon: LineChart },
  { key: 'desks', label: 'Desks', icon: TrendingUp },
  { key: 'tags', label: 'Tags', icon: Tag },
]

function Nav({
  section,
  onNavigate,
  user,
  onAuth,
  onLogout,
}: {
  section: string
  onNavigate: (to: string) => void
  user: { id: string; email: string } | null
  onAuth: (mode: 'login' | 'register') => void
  onLogout: () => void
}) {
  const items = user ? NAV_ITEMS : ANON_NAV_ITEMS
  const activeSection = user && section === 'home' ? 'markets' : section
  return (
    <nav className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/85 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-6">
        <button
          onClick={() => onNavigate(user ? 'markets' : 'home')}
          className="flex shrink-0 items-center gap-2 text-sm font-bold tracking-tight text-white transition hover:text-emerald-300"
        >
          <BarChart3 className="h-5 w-5 text-emerald-400" />
          DolyMarket
        </button>

        <div className="mx-2 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
          {items.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
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

        <div className="flex items-center gap-2">
          <a
            href={import.meta.env.VITE_DOCS_URL || '/docs'}
            target="_blank"
            rel="noopener noreferrer"
            title="Documentation"
            className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-400 transition hover:border-emerald-500/40 hover:text-emerald-300"
          >
            <BookOpen className="h-3 w-3" /> Docs
          </a>
          {user ? (
            <>
              <span className="hidden items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1 text-[11px] text-slate-300 sm:flex">
                <ShieldCheck className="h-3 w-3 text-emerald-400" />
                {user.email || 'trader'}
              </span>
              <button
                onClick={onLogout}
                className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-400 transition hover:border-rose-500/40 hover:text-rose-300"
              >
                <LogOut className="h-3 w-3" /> Sign out
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onAuth('login')}
                className="flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-300"
              >
                <LogIn className="h-3 w-3" /> Sign in
              </button>
              <button
                onClick={() => onAuth('register')}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-slate-950 transition hover:bg-emerald-400"
              >
                <UserPlus className="h-3 w-3" /> Register
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}
