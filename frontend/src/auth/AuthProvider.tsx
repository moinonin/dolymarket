import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, getStoredToken } from '../api/client'

interface AuthUser {
  id: string
  email: string
}

interface AuthContextValue {
  user: AuthUser | null
  openAuth: (mode: 'login' | 'register') => void
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  openAuth: () => {},
  logout: () => {},
  refreshUser: async () => {},
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authModal, setAuthModal] = useState<{ mode: 'login' | 'register' } | null>(null)

  const applyToken = useCallback(async () => {
    const token = getStoredToken()
    if (!token) {
      setUser(null)
      return
    }
    try {
      const bal = await api.getBalance()
      setUser((prev) =>
        prev ? { ...prev, id: bal.user_id } : { id: bal.user_id, email: '' }
      )
      try {
        const res = await fetch('/api/v1/collateral/balance', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setUser({ id: data.user_id, email: data.email ?? '' })
        }
      } catch {
        /* ignore */
      }
    } catch {
      setUser(null)
    }
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      const bal = await api.getBalance()
      setUser({ id: bal.user_id, email: user?.email || '' })
    } catch {
      setUser(null)
    }
  }, [user?.email])

  const userRef = { user, openAuth: (mode: 'login' | 'register') => setAuthModal({ mode }), logout: () => { api.logout(); setUser(null) }, refreshUser }

  return (
    <AuthContext.Provider value={userRef}>
      {children}
      {authModal && (
        <AuthModal
          mode={authModal.mode}
          onClose={() => setAuthModal(null)}
          onAuthed={async (u) => {
            setUser({ id: u.id, email: u.email })
            setAuthModal(null)
          }}
        />
      )}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export async function refreshAuthUser() {}

interface AuthModalProps {
  mode: 'login' | 'register'
  onClose: () => void
  onAuthed: (user: { id: string; email: string }) => void
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function AuthModal({ mode, onClose, onAuthed }: AuthModalProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = EMAIL_RE.test(email) && password.length >= 8

  async function submit() {
    if (!valid) return
    setSubmitting(true)
    setError(null)
    try {
      const res =
        mode === 'register'
          ? await api.register(email, password)
          : await api.login(email, password)
      onAuthed(res.user)
    } catch (err: any) {
      setError(err.message || 'Authentication failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-white">
          {mode === 'register' ? 'Create trader account' : 'Sign in'}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          {mode === 'register'
            ? 'Register to trade, deposit collateral and receive fill notifications.'
            : 'Welcome back. Enter your credentials to access your portfolio.'}
        </p>
        <div className="mt-5 space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-slate-400">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-400">
              Password <span className="text-slate-600">(min 8 chars)</span>
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && valid && submit()}
              placeholder="••••••••"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500"
            />
          </label>
        </div>
        {error && (
          <div className="mt-3 rounded-lg border border-red-800/60 bg-red-950/50 px-3 py-2 text-xs text-red-200">
            {error}
          </div>
        )}
        <button
          disabled={!valid || submitting}
          onClick={submit}
          className="mt-5 w-full rounded-lg bg-emerald-500 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? 'Please wait…' : mode === 'register' ? 'Create Account' : 'Sign In'}
        </button>
        {mode === 'register' && (
          <p className="mt-3 text-center text-xs text-slate-500">
            Demo trader preset: <span className="text-slate-300">trader@demo.io</span> /{' '}
            <span className="text-slate-300">trader-demo-1234</span>
          </p>
        )}
      </div>
    </div>
  )
}
