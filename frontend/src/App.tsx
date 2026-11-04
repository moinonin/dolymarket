import React, { useEffect, useState } from 'react'
import {
  BarChart3,
  Briefcase,
  Gavel,
  LineChart,
  LogIn,
  LogOut,
  ShieldCheck,
  UserPlus,
} from 'lucide-react'
import { ToastProvider } from './context/toast'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { setToastHandler } from './api/client'
import { useToast } from './context/toast'
import MarketsPage from './pages/MarketsPage'
import EventDetailPage from './pages/EventDetailPage'
import PortfolioPage from './pages/PortfolioPage'
import ResolutionPage from './pages/ResolutionPage'

// Tiny hash router — path segments after '#'.
function useHashRoute(): [string[], (to: string) => void] {
  const [hash, setHash] = useState(window.location.hash.replace(/^#/, '') || '/markets')
  useEffect(() => {
    const onChange = () => setHash(window.location.hash.replace(/^#/, '') || '/markets')
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
  const section = route[0] || 'markets'

  let page: React.ReactNode
  if (section === 'event' && route[1]) {
    page = <EventDetailPage slug={route[1]} onNavigate={(to) => navigate(to)} />
  } else if (section === 'portfolio') {
    page = <PortfolioWrapper onNavigate={navigate} />
  } else if (section === 'resolution') {
    page = <ResolutionPage />
  } else {
    page = <MarketsPage onOpenEvent={(slug) => navigate(`event/${slug}`)} />
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
        Prediction Market Platform · off-chain CLOB · CTF settlement · UMA-style optimistic
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
  { key: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { key: 'resolution', label: 'Resolution', icon: Gavel },
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
  return (
    <nav className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/85 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-6">
        <button
          onClick={() => onNavigate('markets')}
          className="flex items-center gap-2 text-sm font-bold tracking-tight text-white transition hover:text-emerald-300"
        >
          <BarChart3 className="h-5 w-5 text-emerald-400" />
          Polymarket<span className="text-slate-500">/pred</span>
        </button>

        <div className="flex items-center gap-1">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                section === key
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
